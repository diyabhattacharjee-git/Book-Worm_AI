"""Glue between the database and the hybrid recommender (kept out of API routes)."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.book import Book
from app.models.reading import BookshelfEntry
from app.models.social import (
    RecommendationEvent,
    Review,
    SearchQuery,
    UserBookInteraction,
)
from app.models.user import User, UserProfile
from app.recommender.content import book_document, get_content_model
from app.recommender.hybrid import (
    BookLite,
    HybridRecommender,
    Preferences,
    RecConfig,
    RecResult,
)
from app.recommender.signals import aggregate, load_events


def config_from_settings() -> RecConfig:
    s = get_settings()
    return RecConfig(w_content=s.rec_weight_content, w_collaborative=s.rec_weight_collaborative,
                     w_popularity=s.rec_weight_popularity, w_preference=s.rec_weight_preference,
                     diversity_lambda=s.rec_diversity_lambda)


def load_book_lites(db: Session) -> dict[int, BookLite]:
    out = {}
    for b in db.scalars(select(Book)).unique():
        out[b.id] = BookLite(
            id=b.id, title=b.title, authors=b.author_names,
            genres={g.name.lower() for g in b.genres}, language=b.language, pages=b.page_count,
            external_rating=(b.external_rating_avg, b.external_rating_count),
            text=book_document(b).lower(),
        )
    return out


def prefs_from_profile(profile: UserProfile | None) -> Preferences:
    if profile is None:
        return Preferences()
    return Preferences(
        genres=list(profile.favorite_genres or []), authors=list(profile.favorite_authors or []),
        languages=list(profile.preferred_languages or []), themes=list(profile.favorite_themes or []),
        topics=list(profile.topics_to_explore or []), length=profile.preferred_length,
    )


_cache: dict = {"sig": None, "rec": None}
_lock = threading.Lock()


def _data_signature(db: Session) -> tuple:
    return (
        db.scalar(select(func.count(Review.id))), db.scalar(select(func.max(Review.updated_at))),
        db.scalar(select(func.count(UserBookInteraction.id))), db.scalar(select(func.max(UserBookInteraction.id))),
        db.scalar(select(func.max(UserProfile.updated_at))),
        db.scalar(select(func.count(Book.id))), db.scalar(select(func.max(Book.updated_at))),
    )


def get_recommender(db: Session, force: bool = False) -> HybridRecommender:
    """Fit (or reuse) the hybrid model. It is refitted automatically whenever
    ratings, interactions, preferences or the catalogue change, or on demand."""
    sig = _data_signature(db)
    with _lock:
        if force or _cache["rec"] is None or _cache["sig"] != sig:
            s = get_settings()
            signals = aggregate(load_events(db, include_demo=True), s.rec_recency_half_life_days)
            _cache["rec"] = HybridRecommender(
                get_content_model(db), signals, load_book_lites(db), config_from_settings(),
                prior_m=s.rec_bayes_prior_count, cf_min_users=s.rec_cf_min_users,
                cf_min_user_interactions=s.rec_cf_min_user_interactions,
            )
            _cache["sig"] = sig
            _cache["fitted_at"] = datetime.now(timezone.utc)
        return _cache["rec"]


def fitted_at() -> datetime | None:
    return _cache.get("fitted_at")


def reset_cache() -> None:
    with _lock:
        _cache["rec"] = None
        _cache["sig"] = None


def user_exclusions(db: Session, user_id: int) -> set[int]:
    shelf = set(db.scalars(select(BookshelfEntry.book_id).where(BookshelfEntry.user_id == user_id)))
    negative = set(db.scalars(select(UserBookInteraction.book_id).where(
        UserBookInteraction.user_id == user_id,
        UserBookInteraction.type.in_(("dismiss", "not_interested")),
    )))
    rated = set(db.scalars(select(Review.book_id).where(Review.user_id == user_id)))
    return shelf | negative | rated


def recent_searches(db: Session, user_id: int, limit: int = 8) -> list[str]:
    return list(db.scalars(select(SearchQuery.query).where(SearchQuery.user_id == user_id)
                           .order_by(SearchQuery.created_at.desc()).limit(limit)))


def recommend_for_user(db: Session, user: User | None, k: int = 12, genre: str | None = None,
                       log: bool = True) -> RecResult:
    rec = get_recommender(db)
    if user is None:
        result = rec.recommend(None, None, k=k, restrict_to=_genre_restrict(rec, genre))
    else:
        prefs = prefs_from_profile(user.profile)
        exclude = user_exclusions(db, user.id) | set((user.profile.enjoyed_book_ids if user.profile else []) or [])
        result = rec.recommend(user.id, prefs, k=k, exclude=exclude, texts=recent_searches(db, user.id),
                               restrict_to=_genre_restrict(rec, genre))
        if log and result.items:
            for item in result.items:
                db.add(RecommendationEvent(user_id=user.id, book_id=item.book_id, event="shown",
                                           strategy=item.strategy, score=item.score))
            db.commit()
    return result


def _genre_restrict(rec: HybridRecommender, genre: str | None) -> set[int] | None:
    if not genre:
        return None
    g = genre.lower().replace("-", " ")
    return {b.id for b in rec.books.values() if g in {x.replace("-", " ") for x in b.genres}}


def similar_books(db: Session, book_id: int, k: int = 8) -> list[tuple[int, float, str]]:
    """Content-based neighbours of one book (works for brand-new books too)."""
    model = get_content_model(db)
    v = model.vector(book_id)
    if v is None:
        return []
    sims = model.similarities(v)
    order = sims.argsort()[::-1]
    rec = get_recommender(db)
    out = []
    this_authors = set(rec.books[book_id].authors) if book_id in rec.books else set()
    for i in order:
        bid = model.book_ids[i]
        if bid == book_id or sims[i] <= 0.01:
            continue
        other = rec.books.get(bid)
        shared = sorted((rec.books[book_id].genres & other.genres)) if other and book_id in rec.books else []
        if other and this_authors & set(other.authors):
            reason = f"Also by {', '.join(sorted(this_authors & set(other.authors)))}"
        elif shared:
            reason = "Shared subjects: " + ", ".join(s.title() for s in shared[:3])
        else:
            reason = "Similar description and themes"
        out.append((bid, float(sims[i]), reason))
        if len(out) >= k:
            break
    return out
