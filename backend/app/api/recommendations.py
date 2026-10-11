from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import not_found
from app.core.ratelimit import rate_limit
from app.db.session import get_db
from app.models.book import Book
from app.models.social import (
    RecommendationEvaluationRun,
    RecommendationEvent,
    Review,
    UserBookInteraction,
)
from app.models.user import User
from app.recommender import service as rec_service
from app.recommender.evaluation import evaluate
from app.repositories.books import get_books, summaries
from app.security.deps import get_current_user, get_current_user_optional, require_admin
from app.services.users import record_interaction

router = APIRouter(tags=["recommendations"])

MODE_LABELS = {
    "personalized": "Personalised from your ratings, shelf and feedback",
    "cold_start": "Starter picks: based on your stated preferences (if any) and what is popular. "
                  "They become personalised as you rate, save or shelve books.",
}

HOW_IT_WORKS = [
    "Ratings: 4-5 stars pull similar books up; 1-2 stars push them down.",
    "Bookshelf: finished and currently-reading books count as strong positive signals; abandoned books as mild negatives.",
    "Save / Interested add a positive signal; Not interested and Dismiss add negative signals and hide that book.",
    f"Older activity fades: a signal loses half its weight every {get_settings().rec_recency_half_life_days:g} days.",
    "Your onboarding preferences (genres, authors, length, themes) add a separate preference score.",
    "Similar readers' activity (collaborative filtering) is used only once enough readers overlap.",
]


@router.get("/recommendations")
def get_recommendations(limit: int = Query(12, ge=1, le=40), genre: str | None = Query(None, max_length=120),
                        user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    result = rec_service.recommend_for_user(db, user, k=limit, genre=genre)
    books = {b.id: b for b in get_books(db, [i.book_id for i in result.items])}
    sums = {s.id: s for s in summaries(db, list(books.values()))}
    s = get_settings()
    rec = rec_service.get_recommender(db)
    return {
        "mode": result.mode,
        "mode_label": MODE_LABELS[result.mode],
        "signals_used": result.signals_used,
        "collaborative_status": result.cf_status,
        "notes": result.notes,
        "weights": {"content": s.rec_weight_content, "collaborative": s.rec_weight_collaborative,
                    "popularity": s.rec_weight_popularity, "preference": s.rec_weight_preference,
                    "diversity_lambda": s.rec_diversity_lambda},
        "content_backend": rec.content.backend,
        "fitted_at": rec_service.fitted_at(),
        "how_it_works": HOW_IT_WORKS,
        "items": [{
            "book": sums[i.book_id].model_dump(),
            "score": i.score,
            "strategy": i.strategy,
            "contributions": i.contributions,
            "reasons": [{"signal": r.signal, "text": r.text, "evidence": r.evidence} for r in i.reasons],
        } for i in result.items if i.book_id in sums],
    }


class FeedbackIn(BaseModel):
    book_id: int
    action: Literal["save", "dismiss", "interested", "not_interested", "rate", "opened"]
    rating: int | None = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def _rating_needed(self):
        if self.action == "rate" and self.rating is None:
            raise ValueError("rating is required when action is 'rate'")
        return self


@router.post("/recommendations/feedback", status_code=200)
def feedback(body: FeedbackIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(Book, body.book_id):
        raise not_found("Book")
    if body.action == "rate":
        review = db.scalar(select(Review).where(Review.user_id == user.id, Review.book_id == body.book_id))
        if review:
            review.rating = body.rating
        else:
            db.add(Review(user_id=user.id, book_id=body.book_id, rating=body.rating))
        event = "rated"
    elif body.action == "opened":
        event = "opened"
    else:
        record_interaction(db, user.id, body.book_id, body.action)
        event = {"save": "saved", "dismiss": "dismissed", "interested": "saved", "not_interested": "dismissed"}[body.action]
    db.add(RecommendationEvent(user_id=user.id, book_id=body.book_id, event=event, strategy="feedback"))
    db.commit()
    return {"detail": "Thanks, your recommendations will update.", "action": body.action}


@router.post("/recommendations/recompute", dependencies=[Depends(rate_limit("recompute", 10, 60))])
def recompute(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Refit the recommender now (it also refits automatically when data changes)."""
    rec_service.get_recommender(db, force=True)
    return {"detail": "Recommendation model refitted.", "fitted_at": rec_service.fitted_at()}


class EvaluateIn(BaseModel):
    k: int = Field(default=10, ge=1, le=50)
    include_demo: bool = False


@router.post("/recommendations/evaluate")
def run_evaluation(body: EvaluateIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    result = evaluate(db, k=body.k, include_demo=body.include_demo)
    run = RecommendationEvaluationRun(created_by=admin.id, status=result["status"], k=body.k,
                                      include_demo=body.include_demo, n_users=result["eligible_users"],
                                      results=result.get("results", {}), notes=result.get("data_warning"))
    db.add(run)
    db.commit()
    return {**result, "run_id": run.id, "created_at": run.created_at}


@router.get("/recommendations/metrics")
@router.get("/admin/recommendation-metrics", include_in_schema=False)
def metrics(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    runs = db.scalars(select(RecommendationEvaluationRun).order_by(RecommendationEvaluationRun.created_at.desc()).limit(20))
    usage = dict(db.execute(select(RecommendationEvent.event, func.count(RecommendationEvent.id))
                            .group_by(RecommendationEvent.event)).all())
    by_strategy = dict(db.execute(select(RecommendationEvent.strategy, func.count(RecommendationEvent.id))
                                  .where(RecommendationEvent.event == "shown")
                                  .group_by(RecommendationEvent.strategy)).all())
    shown = usage.get("shown", 0)
    acted = usage.get("saved", 0) + usage.get("rated", 0) + usage.get("opened", 0)
    real_users = db.scalar(select(func.count(func.distinct(UserBookInteraction.user_id)))
                           .join(User, User.id == UserBookInteraction.user_id).where(User.is_demo.is_(False)))
    rec = rec_service.get_recommender(db)
    return {
        "usage": {"events": usage, "shown_by_strategy": by_strategy,
                  "engagement_rate": round(acted / shown, 4) if shown >= 50 else None,
                  "engagement_note": None if shown >= 50 else "Shown when at least 50 recommendations have been served."},
        "model": {"content_backend": rec.content.backend, "collaborative": rec.cf.status(),
                  "fitted_at": rec_service.fitted_at(), "real_users_with_activity": real_users},
        "runs": [{"id": r.id, "status": r.status, "k": r.k, "include_demo": r.include_demo, "n_users": r.n_users,
                  "results": r.results, "notes": r.notes, "created_at": r.created_at} for r in runs],
    }


@router.get("/recommendations/explain-settings")
def explain_settings():
    return {"how_it_works": HOW_IT_WORKS}


