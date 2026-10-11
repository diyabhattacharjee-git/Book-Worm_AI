from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import forbidden, not_found
from app.core.ratelimit import rate_limit
from app.core.text import strip_control
from app.db.session import get_db
from app.integrations.http import ProviderError
from app.integrations.metadata import ol_editions, search_metadata
from app.models.book import Book
from app.models.social import Review, ReviewHelpfulVote, ReviewReport, SearchQuery
from app.models.user import User
from app.recommender.service import similar_books
from app.repositories.books import (
    SORTS,
    BookFilters,
    facet_options,
    get_books,
    search_books,
    summaries,
)
from app.schemas.books import (
    BookDetail,
    BookSummary,
    CompareIn,
    EditionOut,
    ExternalSearchResult,
    ImportIsbnIn,
    InteractionIn,
    OffersResponse,
    ReportIn,
    ReviewIn,
    ReviewOut,
    ReviewUpdateIn,
)
from app.schemas.common import Page
from app.security.deps import get_current_user, get_current_user_optional
from app.services.books import book_detail, compare_books, new_offers
from app.services.catalogue import find_book_by_isbn, import_by_isbn
from app.services.nl_search import apply_refinement, parse_query, run_search
from app.services.users import record_interaction

router = APIRouter(tags=["books"])


def _get_book(db: Session, book_id: int) -> Book:
    book = db.get(Book, book_id)
    if not book:
        raise not_found("Book")
    return book


def _filters(q, genre, author, language, year_min, year_max, min_rating, pages_min, pages_max, fmt, availability):
    return BookFilters(q=(q or "").strip()[:200] or None, genre=genre, author=author, language=language,
                       year_min=year_min, year_max=year_max, min_rating=min_rating, pages_min=pages_min,
                       pages_max=pages_max, format=fmt, availability=availability)


@router.get("/books", response_model=Page[BookSummary])
@router.get("/books/search", response_model=Page[BookSummary], include_in_schema=False)
def list_books(
    q: str | None = Query(None, max_length=200, description="Title, author, ISBN, genre, publisher or keywords"),
    genre: str | None = Query(None, max_length=140),
    author: str | None = Query(None, max_length=200),
    language: str | None = Query(None, max_length=12),
    year_min: int | None = Query(None, ge=0, le=2100),
    year_max: int | None = Query(None, ge=0, le=2100),
    min_rating: float | None = Query(None, ge=0, le=5),
    pages_min: int | None = Query(None, ge=1),
    pages_max: int | None = Query(None, ge=1),
    format: Literal["paperback", "hardcover", "ebook", "audiobook"] | None = None,
    availability: Literal["used"] | None = None,
    sort: str = Query("relevance"),
    page: int = Query(1, ge=1, le=1000),
    page_size: int = Query(24, ge=1, le=60),
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if sort not in SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of {', '.join(SORTS)}")
    f = _filters(q, genre, author, language, year_min, year_max, min_rating, pages_min, pages_max, format, availability)
    items, total = search_books(db, f, sort, page, page_size)
    if user and f.q and page == 1:
        db.add(SearchQuery(user_id=user.id, query=f.q))
        db.commit()
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/books/facets")
def facets(db: Session = Depends(get_db)):
    return facet_options(db)


class NLSearchIn(BaseModel):
    query: str | None = Field(default=None, max_length=300)
    refinement: str | None = Field(default=None, max_length=200)
    previous: dict | None = None
    limit: int = Field(default=12, ge=1, le=30)


@router.post("/books/nl-search", dependencies=[Depends(rate_limit("nl_search", 60, 60))])
def nl_search(body: NLSearchIn, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    if body.refinement and body.previous:
        pq = apply_refinement(body.previous, body.refinement)
    elif body.query and body.query.strip():
        pq = parse_query(db, body.query)
    else:
        raise HTTPException(status_code=422, detail="Enter a query, or a refinement with the previous query")
    if user and body.query:
        db.add(SearchQuery(user_id=user.id, query=body.query.strip()[:300]))
        db.commit()
    return run_search(db, pq, body.limit)


@router.get("/books/external-search", response_model=dict)
def external_search(q: str = Query(..., min_length=2, max_length=200), db: Session = Depends(get_db),
                    _: None = Depends(rate_limit("external_search", 30, 60))):
    """Search Open Library / Google Books for books not yet in the catalogue."""
    results, errors = search_metadata(q.strip(), db, limit=10)
    out = []
    seen = set()
    for m in results:
        key = (m.title.lower(), tuple(a.lower() for a in m.authors[:1]))
        if key in seen:
            continue
        seen.add(key)
        local = next((find_book_by_isbn(db, i) for i in m.isbns if find_book_by_isbn(db, i)), None)
        out.append(ExternalSearchResult(title=m.title, authors=m.authors, published_year=m.published_year,
                                        isbns=m.isbns[:3], cover_url=m.cover_url, source=m.source,
                                        info_url=m.info_url, in_catalogue_book_id=local.id if local else None))
    return {"results": [r.model_dump() for r in out[:15]], "errors": errors}


@router.post("/books/import", response_model=BookDetail, status_code=201,
             dependencies=[Depends(rate_limit("import", 20, 3600))])
def import_book(body: ImportIsbnIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    book, errors = import_by_isbn(db, body.isbn)
    if not book:
        raise HTTPException(status_code=404, detail="; ".join(errors))
    return book_detail(db, book)


@router.post("/books/compare")
def compare(body: CompareIn, db: Session = Depends(get_db)):
    books = get_books(db, list(dict.fromkeys(body.book_ids)))
    if len(books) < 2:
        raise HTTPException(status_code=422, detail="Choose at least two existing books to compare")
    return compare_books(db, books, body.goal)


@router.get("/books/{book_id}", response_model=BookDetail)
def get_book(book_id: int, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    book = _get_book(db, book_id)
    if user:
        record_interaction(db, user.id, book.id, "view")
        db.commit()
    return book_detail(db, book)


@router.get("/books/{book_id}/similar", response_model=list[dict])
def get_similar(book_id: int, limit: int = Query(8, ge=1, le=20), db: Session = Depends(get_db)):
    _get_book(db, book_id)
    sims = similar_books(db, book_id, limit)
    books = {b.id: b for b in get_books(db, [s[0] for s in sims])}
    sums = {s.id: s for s in summaries(db, list(books.values()))}
    return [{"book": sums[bid].model_dump(), "similarity": round(score, 3), "reason": why}
            for bid, score, why in sims if bid in sums]


@router.get("/books/{book_id}/editions", response_model=dict)
def get_editions(book_id: int, include_external: bool = False, db: Session = Depends(get_db)):
    book = _get_book(db, book_id)
    local = [EditionOut(id=e.id, isbn13=e.isbn13, isbn10=e.isbn10, format=e.format, edition_label=e.edition_label,
                        publisher=e.publisher, published_year=e.published_year, page_count=e.page_count,
                        language=e.language) for e in book.editions]
    external: list[EditionOut] = []
    error = None
    if include_external and book.openlibrary_work_key:
        try:
            known = {e.isbn13 for e in local}
            for e in ol_editions(book.openlibrary_work_key, db):
                if e["isbn13"] and e["isbn13"] in known:
                    continue
                external.append(EditionOut(id=None, isbn13=e["isbn13"], format=e["format"], publisher=e["publisher"],
                                           published_year=e["published_year"], page_count=e["page_count"],
                                           language=e["language"], source="open_library", source_url=e["source_url"]))
        except ProviderError as exc:
            error = f"Open Library: {exc.message}"
    return {"catalogue": [e.model_dump() for e in local], "external": [e.model_dump() for e in external],
            "error": error}


@router.get("/books/{book_id}/offers", response_model=OffersResponse)
def get_offers(book_id: int, db: Session = Depends(get_db), _: None = Depends(rate_limit("offers", 30, 60))):
    return new_offers(db, _get_book(db, book_id))


@router.post("/books/{book_id}/interactions", status_code=204)
def add_interaction(book_id: int, body: InteractionIn, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    _get_book(db, book_id)
    record_interaction(db, user.id, book_id, body.type)
    db.commit()


# ------------------------------------------------------------------- reviews
def _review_out(r: Review, me: User | None, voted: set[int]) -> ReviewOut:
    return ReviewOut(id=r.id, book_id=r.book_id, user_id=r.user_id, user_display_name=r.user.display_name,
                     rating=r.rating, body=r.body, helpful_count=r.helpful_count, status=r.status,
                     created_at=r.created_at, updated_at=r.updated_at, is_mine=bool(me and me.id == r.user_id),
                     voted_helpful=r.id in voted)


@router.get("/books/{book_id}/reviews", response_model=dict)
def list_reviews(book_id: int, sort: Literal["helpful", "recent", "rating_high", "rating_low"] = "helpful",
                 page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=50),
                 user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    _get_book(db, book_id)
    base = select(Review).where(Review.book_id == book_id, Review.status == "visible")
    order = {"helpful": (Review.helpful_count.desc(), Review.updated_at.desc()),
             "recent": (Review.updated_at.desc(),),
             "rating_high": (Review.rating.desc(), Review.updated_at.desc()),
             "rating_low": (Review.rating.asc(), Review.updated_at.desc())}[sort]
    # Rating-only entries are counted in the aggregate but not listed as written reviews.
    written = base.where(Review.body.is_not(None))
    total = db.scalar(select(func.count()).select_from(written.subquery()))
    rows = list(db.scalars(written.order_by(*order).offset((page - 1) * page_size).limit(page_size)).unique())
    voted = set()
    mine = None
    if user:
        voted = set(db.scalars(select(ReviewHelpfulVote.review_id).where(
            ReviewHelpfulVote.user_id == user.id, ReviewHelpfulVote.review_id.in_([r.id for r in rows]))))
        m = db.scalar(select(Review).where(Review.book_id == book_id, Review.user_id == user.id))
        mine = _review_out(m, user, set()).model_dump() if m else None
    dist = dict(db.execute(select(Review.rating, func.count(Review.id)).where(
        Review.book_id == book_id, Review.status == "visible").group_by(Review.rating)).all())
    return {"items": [_review_out(r, user, voted).model_dump() for r in rows], "total": total, "page": page,
            "page_size": page_size, "my_review": mine,
            "distribution": {str(i): dist.get(i, 0) for i in range(1, 6)}}


@router.post("/books/{book_id}/reviews", response_model=ReviewOut, status_code=201,
             dependencies=[Depends(rate_limit("review", 30, 3600))])
def upsert_review(book_id: int, body: ReviewIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create the user's rating/review, or update it if one exists (one per user per book)."""
    _get_book(db, book_id)
    review = db.scalar(select(Review).where(Review.book_id == book_id, Review.user_id == user.id))
    text = strip_control(body.body, 5000)
    if review:
        review.rating, review.body = body.rating, text
    else:
        review = Review(book_id=book_id, user_id=user.id, rating=body.rating, body=text)
        db.add(review)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You have already rated this book")
    db.refresh(review)
    return _review_out(review, user, set())


def _own_review(db: Session, review_id: int, user: User) -> Review:
    review = db.get(Review, review_id)
    if not review:
        raise not_found("Review")
    if review.user_id != user.id:
        raise forbidden("You can only change your own review")
    return review


@router.patch("/reviews/{review_id}", response_model=ReviewOut)
def update_review(review_id: int, body: ReviewUpdateIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    review = _own_review(db, review_id, user)
    data = body.model_dump(exclude_unset=True)
    if "rating" in data and data["rating"] is not None:
        review.rating = data["rating"]
    if "body" in data:
        review.body = strip_control(data["body"], 5000) or None
    db.commit()
    return _review_out(review, user, set())


@router.delete("/reviews/{review_id}", status_code=204)
def delete_review(review_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_own_review(db, review_id, user))
    db.commit()


@router.post("/reviews/{review_id}/helpful", response_model=dict)
def vote_helpful(review_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    review = db.get(Review, review_id)
    if not review or review.status != "visible":
        raise not_found("Review")
    if review.user_id == user.id:
        raise HTTPException(status_code=400, detail="You can't vote on your own review")
    if not db.scalar(select(ReviewHelpfulVote.id).where(ReviewHelpfulVote.review_id == review_id,
                                                        ReviewHelpfulVote.user_id == user.id)):
        db.add(ReviewHelpfulVote(review_id=review_id, user_id=user.id))
        review.helpful_count += 1
        db.commit()
    return {"helpful_count": review.helpful_count, "voted": True}


@router.delete("/reviews/{review_id}/helpful", response_model=dict)
def unvote_helpful(review_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    review = db.get(Review, review_id)
    if not review:
        raise not_found("Review")
    n = db.execute(delete(ReviewHelpfulVote).where(ReviewHelpfulVote.review_id == review_id,
                                                   ReviewHelpfulVote.user_id == user.id)).rowcount
    if n:
        review.helpful_count = max(0, review.helpful_count - 1)
    db.commit()
    return {"helpful_count": review.helpful_count, "voted": False}


@router.post("/reviews/{review_id}/report", status_code=201, dependencies=[Depends(rate_limit("report", 20, 3600))])
def report_review(review_id: int, body: ReportIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    review = db.get(Review, review_id)
    if not review:
        raise not_found("Review")
    if review.user_id == user.id:
        raise HTTPException(status_code=400, detail="You can't report your own review")
    if db.scalar(select(ReviewReport.id).where(ReviewReport.review_id == review_id, ReviewReport.reporter_id == user.id)):
        raise HTTPException(status_code=409, detail="You have already reported this review")
    db.add(ReviewReport(review_id=review_id, reporter_id=user.id, reason=body.reason,
                        details=strip_control(body.details, 500)))
    db.commit()
    return {"detail": "Thanks. A moderator will review this report."}
