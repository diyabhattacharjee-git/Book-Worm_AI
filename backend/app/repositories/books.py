"""Catalogue queries: search, filters, aggregate ratings and serialisation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.text import normalize_title, to_isbn13
from app.models.book import Author, Book, BookEdition, Genre, book_authors, book_genres
from app.models.marketplace import MarketplaceListing
from app.models.social import Review, UserBookInteraction
from app.models.user import User
from app.schemas.books import BookSummary, RatingSummary

SORTS = ("relevance", "title", "year_desc", "year_asc", "rating", "popularity", "price")


@dataclass
class BookFilters:
    q: str | None = None
    genre: str | None = None  # slug
    author: str | None = None
    language: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    min_rating: float | None = None
    pages_min: int | None = None
    pages_max: int | None = None
    format: str | None = None
    availability: str | None = None  # used
    exclude_ids: set[int] = field(default_factory=set)


def rating_stats(db: Session, book_ids: list[int]) -> dict[int, tuple[float | None, int, int]]:
    """(average, count, how many of those come from synthetic demo accounts)."""
    if not book_ids:
        return {}
    demo = func.sum(case((User.is_demo.is_(True), 1), else_=0))
    rows = db.execute(
        select(Review.book_id, func.avg(Review.rating), func.count(Review.id), demo)
        .join(User, User.id == Review.user_id)
        .where(Review.book_id.in_(book_ids), Review.status == "visible")
        .group_by(Review.book_id)
    ).all()
    out: dict[int, tuple[float | None, int, int]] = {bid: (None, 0, 0) for bid in book_ids}
    for bid, avg, cnt, n_demo in rows:
        out[bid] = (round(float(avg), 2), int(cnt), int(n_demo or 0))
    return out


def used_stats(db: Session, book_ids: list[int]) -> dict[int, tuple[int, float | None, str | None]]:
    """Active community listing count and lowest asking price (per book, INR-first)."""
    if not book_ids:
        return {}
    rows = db.execute(
        select(MarketplaceListing.book_id, MarketplaceListing.currency,
               func.count(MarketplaceListing.id), func.min(MarketplaceListing.price_amount))
        .where(MarketplaceListing.book_id.in_(book_ids), MarketplaceListing.status == "active")
        .group_by(MarketplaceListing.book_id, MarketplaceListing.currency)
    ).all()
    out: dict[int, tuple[int, float | None, str | None]] = {}
    for bid, cur, cnt, low in rows:
        prev = out.get(bid)
        if prev is None or (cur == "INR" and prev[2] != "INR"):
            out[bid] = (int(cnt) + (prev[0] if prev else 0), float(low), cur)
        else:
            out[bid] = (prev[0] + int(cnt), prev[1], prev[2])
    return out


def popularity_counts(db: Session, book_ids: list[int] | None = None) -> dict[int, int]:
    q = select(UserBookInteraction.book_id, func.count(UserBookInteraction.id)).group_by(UserBookInteraction.book_id)
    if book_ids is not None:
        q = q.where(UserBookInteraction.book_id.in_(book_ids))
    return {bid: int(c) for bid, c in db.execute(q).all()}


def to_summary(book: Book, ratings: tuple[float | None, int, int], used: tuple[int, float | None, str | None] | None = None) -> BookSummary:
    used = used or (0, None, None)
    return BookSummary(
        id=book.id,
        title=book.title,
        subtitle=book.subtitle,
        authors=book.author_names,
        cover_url=book.cover_url,
        genres=[g.name for g in book.genres if g.kind == "genre"][:6],
        first_published_year=book.first_published_year,
        page_count=book.page_count,
        language=book.language,
        ratings=RatingSummary(
            app_average=ratings[0], app_count=ratings[1], app_demo_count=ratings[2],
            external_average=book.external_rating_avg, external_count=book.external_rating_count,
            external_source=book.external_rating_source,
        ),
        is_sample=book.is_sample,
        used_listing_count=used[0],
        lowest_used_price=used[1],
        lowest_used_currency=used[2],
    )


def summaries(db: Session, books: list[Book]) -> list[BookSummary]:
    ids = [b.id for b in books]
    rs, us = rating_stats(db, ids), used_stats(db, ids)
    return [to_summary(b, rs.get(b.id, (None, 0, 0)), us.get(b.id)) for b in books]


_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "by", "with", "book", "books"}


def _tokens(q: str) -> list[str]:
    return [t for t in _TOKEN.findall(q.lower()) if t not in _STOP and len(t) > 1][:8]


def _apply_filters(stmt: Select, f: BookFilters) -> Select:
    if f.genre:
        stmt = stmt.where(Book.id.in_(
            select(book_genres.c.book_id).join(Genre, Genre.id == book_genres.c.genre_id).where(Genre.slug == f.genre)
        ))
    if f.author:
        stmt = stmt.where(Book.id.in_(
            select(book_authors.c.book_id).join(Author, Author.id == book_authors.c.author_id)
            .where(Author.name.ilike(f"%{f.author.strip()}%"))
        ))
    if f.language:
        stmt = stmt.where(Book.language == f.language)
    if f.year_min:
        stmt = stmt.where(Book.first_published_year >= f.year_min)
    if f.year_max:
        stmt = stmt.where(Book.first_published_year <= f.year_max)
    if f.pages_min:
        stmt = stmt.where(Book.page_count >= f.pages_min)
    if f.pages_max:
        stmt = stmt.where(Book.page_count <= f.pages_max)
    if f.format:
        stmt = stmt.where(Book.id.in_(select(BookEdition.book_id).where(BookEdition.format == f.format)))
    if f.availability == "used":
        stmt = stmt.where(Book.id.in_(
            select(MarketplaceListing.book_id).where(MarketplaceListing.status == "active")
        ))
    if f.exclude_ids:
        stmt = stmt.where(Book.id.notin_(f.exclude_ids))
    return stmt


def _text_condition(q: str):
    isbn = to_isbn13(q)
    if isbn:
        return Book.id.in_(select(BookEdition.book_id).where(BookEdition.isbn13 == isbn)), isbn
    toks = _tokens(q)
    if not toks:
        return None, None
    conds = []
    for t in toks:
        like = f"%{t}%"
        conds.append(or_(
            Book.normalized_title.ilike(like),
            Book.subtitle.ilike(like),
            Book.publisher.ilike(like),
            Book.series.ilike(like),
            Book.description.ilike(like),
            Book.id.in_(select(book_authors.c.book_id).join(Author).where(Author.name.ilike(like))),
            Book.id.in_(select(book_genres.c.book_id).join(Genre).where(Genre.name.ilike(like))),
        ))
    return or_(*conds), None


def relevance(book: Book, q: str) -> float:
    """Transparent lexical relevance: title > author > genre > description hits."""
    toks = _tokens(q)
    if not toks:
        return 0.0
    title = normalize_title(book.title) + " " + (book.subtitle or "").lower()
    authors = " ".join(book.author_names).lower()
    genres = " ".join(g.name.lower() for g in book.genres)
    desc = (book.description or "").lower()
    score = 0.0
    nq = normalize_title(q)
    if nq and nq == normalize_title(book.title):
        score += 10
    elif nq and nq in title:
        score += 5
    for t in toks:
        if re.search(rf"\b{re.escape(t)}", title):
            score += 3
        if t in authors:
            score += 2.5
        if t in genres:
            score += 1.5
        if t in desc:
            score += 0.5
    return score / len(toks)


def search_books(
    db: Session, f: BookFilters, sort: str = "relevance", page: int = 1, page_size: int = 24
) -> tuple[list[BookSummary], int]:
    stmt = _apply_filters(select(Book), f)
    if f.q:
        cond, _isbn = _text_condition(f.q)
        if cond is not None:
            stmt = stmt.where(cond)
    books = list(db.scalars(stmt.limit(3000)).unique())
    ids = [b.id for b in books]
    rs = rating_stats(db, ids)
    us = used_stats(db, ids)

    if f.min_rating:
        def eff(b: Book) -> float:
            avg, cnt, _ = rs.get(b.id, (None, 0, 0))
            return avg if cnt else (b.external_rating_avg or 0.0)
        books = [b for b in books if eff(b) >= f.min_rating]

    pop = popularity_counts(db, ids) if sort in ("popularity", "relevance") else {}
    if sort == "title":
        books.sort(key=lambda b: normalize_title(b.title))
    elif sort == "year_desc":
        books.sort(key=lambda b: b.first_published_year or -9999, reverse=True)
    elif sort == "year_asc":
        books.sort(key=lambda b: b.first_published_year or 9999)
    elif sort == "rating":
        def rkey(b: Book):
            avg, cnt, _ = rs.get(b.id, (None, 0, 0))
            return (avg or 0, cnt, b.external_rating_avg or 0)
        books.sort(key=rkey, reverse=True)
    elif sort == "popularity":
        books.sort(key=lambda b: (pop.get(b.id, 0), b.external_rating_count or 0), reverse=True)
    elif sort == "price":
        # Only books with an actual active listing have a price; others go last.
        books.sort(key=lambda b: (us.get(b.id, (0, None, None))[1] is None, us.get(b.id, (0, math.inf, None))[1] or math.inf))
    else:
        if f.q:
            books.sort(key=lambda b: (relevance(b, f.q or ""), math.log1p(pop.get(b.id, 0))), reverse=True)
        else:
            books.sort(key=lambda b: (pop.get(b.id, 0), b.external_rating_count or 0), reverse=True)

    total = len(books)
    start = (page - 1) * page_size
    page_books = books[start:start + page_size]
    return [to_summary(b, rs.get(b.id, (None, 0, 0)), us.get(b.id)) for b in page_books], total


def facet_options(db: Session) -> dict:
    genres = db.execute(
        select(Genre.name, Genre.slug, func.count(book_genres.c.book_id))
        .join(book_genres, book_genres.c.genre_id == Genre.id)
        .where(Genre.kind == "genre").group_by(Genre.id).order_by(func.count(book_genres.c.book_id).desc())
    ).all()
    languages = db.execute(
        select(Book.language, func.count(Book.id)).where(Book.language.is_not(None)).group_by(Book.language)
    ).all()
    formats = db.scalars(select(BookEdition.format).where(BookEdition.format.is_not(None)).distinct()).all()
    years = db.execute(select(func.min(Book.first_published_year), func.max(Book.first_published_year))).one()
    return {
        "genres": [{"name": n, "slug": s, "count": c} for n, s, c in genres],
        "languages": [{"code": code, "count": c} for code, c in languages],
        "formats": sorted(formats),
        "year_range": [years[0], years[1]],
        "sorts": list(SORTS),
    }


def difficulty_signal(book: Book) -> str | None:
    """Evidence-based hint only: reports what the description says, never guesses."""
    if book.difficulty:
        return f"Listed difficulty: {book.difficulty}"
    d = (book.description or "").lower()
    for phrase in ("for beginners", "beginner", "no prior experience", "introduction to", "gentle introduction"):
        if phrase in d:
            return f"Description mentions '{phrase}'"
    for phrase in ("advanced", "graduate", "rigorous", "comprehensive reference"):
        if phrase in d:
            return f"Description mentions '{phrase}'"
    return None


def get_books(db: Session, ids: list[int]) -> list[Book]:
    if not ids:
        return []
    found = {b.id: b for b in db.scalars(select(Book).where(Book.id.in_(ids))).unique()}
    return [found[i] for i in ids if i in found]


def find_by_title(db: Session, title: str, author: str | None = None, limit: int = 5) -> list[tuple[Book, float]]:
    """Fuzzy title (+author) match against the catalogue, best first."""
    from app.core.text import similarity

    nt = normalize_title(title)
    if not nt:
        return []
    first = nt.split()[0]
    cands = list(db.scalars(select(Book).where(or_(
        Book.normalized_title.ilike(f"%{nt}%"),
        and_(Book.normalized_title.ilike(f"%{first}%")),
    )).limit(200)).unique())
    scored = []
    for b in cands:
        s = similarity(title, b.title)
        if author:
            names = " ".join(b.author_names).lower()
            last = author.strip().split()[-1].lower() if author.strip() else ""
            s = s * 0.8 + (0.2 if last and last in names else 0.0)
        scored.append((b, round(s, 3)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]
