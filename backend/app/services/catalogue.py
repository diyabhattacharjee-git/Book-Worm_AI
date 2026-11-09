"""Catalogue persistence: turn provider metadata into Book / BookEdition rows."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.text import (
    normalize_name,
    normalize_title,
    similarity,
    slugify,
    strip_control,
    to_isbn13,
)
from app.integrations.http import ProviderError
from app.integrations.metadata import BookMetadata, gb_by_isbn, gb_search, ol_by_isbn, ol_search
from app.models.book import Author, Book, BookEdition, Genre
from app.repositories.books import find_by_title

logger = logging.getLogger("bookworm.catalogue")

TITLE_MATCH = 0.8
LOCAL_TITLE_MATCH = 0.9
# A star average from a handful of people says more about them than the book.
MIN_EXTERNAL_RATINGS = 5

FORMAT_ALIASES = {"paperback": "paperback", "mass market paperback": "paperback", "trade paperback": "paperback",
                  "hardcover": "hardcover", "hardback": "hardcover", "ebook": "ebook", "e-book": "ebook",
                  "kindle": "ebook", "audio cd": "audiobook", "audiobook": "audiobook"}


def normalize_format(raw: str | None) -> str | None:
    if not raw:
        return None
    return FORMAT_ALIASES.get(raw.strip().lower())


def get_or_create_author(db: Session, name: str) -> Author:
    name = name.strip()[:200]
    author = db.scalar(select(Author).where(Author.name == name))
    if author is None:
        author = Author(name=name)
        db.add(author)
        db.flush()
    return author


def get_or_create_genre(db: Session, name: str, kind: str = "genre") -> Genre:
    slug = slugify(name)
    genre = db.scalar(select(Genre).where(Genre.slug == slug))
    if genre is None:
        genre = Genre(name=name.strip()[:120], slug=slug, kind=kind)
        db.add(genre)
        db.flush()
    elif kind == "genre" and genre.kind != "genre":
        genre.kind = "genre"
    return genre


def find_book_by_isbn(db: Session, isbn: str | None) -> Book | None:
    isbn13 = to_isbn13(isbn)
    if not isbn13:
        return None
    ed = db.scalar(select(BookEdition).where(BookEdition.isbn13 == isbn13))
    return ed.book if ed else None


def upsert_book(
    db: Session,
    meta: BookMetadata,
    *,
    genres: list[str] | None = None,
    is_sample: bool = False,
    edition_format: str | None = None,
) -> Book:
    """Create or enrich a Book from metadata. Existing non-empty fields are kept
    so curated data is never overwritten by a less complete provider record."""
    book: Book | None = None
    for isbn in meta.isbns:
        book = find_book_by_isbn(db, isbn)
        if book:
            break
    if book is None and meta.work_key:
        book = db.scalar(select(Book).where(Book.openlibrary_work_key == meta.work_key))
    if book is None and meta.source == "google_books" and meta.source_id:
        book = db.scalar(select(Book).where(Book.google_volume_id == meta.source_id))
    if book is None:
        book = Book(title=meta.title.strip()[:300], normalized_title=normalize_title(meta.title), source=meta.source,
                    is_sample=is_sample)
        db.add(book)

    def fill(attr: str, value):
        if value not in (None, "", []) and getattr(book, attr) in (None, ""):
            setattr(book, attr, value)

    fill("subtitle", strip_control(meta.subtitle, 300))
    fill("description", strip_control(meta.description, 6000))
    fill("language", meta.language)
    fill("first_published_year", meta.published_year)
    fill("page_count", meta.page_count if meta.page_count and 0 < meta.page_count < 10000 else None)
    fill("publisher", strip_control(meta.publisher, 200))
    fill("cover_url", meta.cover_url)
    if meta.rating_avg and (meta.rating_count or 0) >= MIN_EXTERNAL_RATINGS and book.external_rating_avg is None:
        book.external_rating_avg = float(meta.rating_avg)
        book.external_rating_count = int(meta.rating_count)
        book.external_rating_source = meta.source
    if meta.work_key and not book.openlibrary_work_key:
        if not db.scalar(select(Book.id).where(Book.openlibrary_work_key == meta.work_key)):
            book.openlibrary_work_key = meta.work_key
    if meta.source == "google_books" and meta.source_id and not book.google_volume_id:
        if not db.scalar(select(Book.id).where(Book.google_volume_id == meta.source_id)):
            book.google_volume_id = meta.source_id
    book.metadata_fetched_at = datetime.now(timezone.utc)

    if not book.authors:
        seen: set[str] = set()
        for name in meta.authors:
            key = normalize_name(name)
            if key and key not in seen:
                seen.add(key)
                book.authors.append(get_or_create_author(db, name))

    existing = {g.slug for g in book.genres}
    for g in genres or []:
        genre = get_or_create_genre(db, g, "genre")
        if genre.slug not in existing:
            book.genres.append(genre)
            existing.add(genre.slug)
    for s in meta.subjects[:8]:
        if len(s) <= 40 and not any(ch.isdigit() for ch in s):
            genre = get_or_create_genre(db, s.strip().title(), "subject")
            if genre.slug not in existing:
                book.genres.append(genre)
                existing.add(genre.slug)

    db.flush()
    known = {e.isbn13 for e in book.editions}
    for isbn in meta.isbns[:3]:
        if isbn in known:
            continue
        if db.scalar(select(BookEdition.id).where(BookEdition.isbn13 == isbn)):
            continue
        book.editions.append(BookEdition(
            isbn13=isbn,
            format=normalize_format(edition_format or meta.format),
            publisher=strip_control(meta.publisher, 200),
            published_year=meta.published_year,
            page_count=meta.page_count,
            language=meta.language,
        ))
        known.add(isbn)
    db.flush()
    return book


def import_by_isbn(db: Session, isbn: str, prefer: str | None = None) -> tuple[Book | None, list[str]]:
    """Local lookup first, then Google Books and Open Library (`prefer="open_library"` swaps them)."""
    isbn13 = to_isbn13(isbn)
    if not isbn13:
        return None, ["Invalid ISBN"]
    existing = find_book_by_isbn(db, isbn13)
    if existing:
        return existing, []
    errors: list[str] = []
    providers = [(gb_by_isbn, "Google Books"), (ol_by_isbn, "Open Library")]
    if prefer == "open_library":
        providers.reverse()
    for fetch, label in providers:
        try:
            meta = fetch(isbn13, db)
        except ProviderError as exc:
            errors.append(f"{label}: {exc.message}")
            continue
        if meta and meta.authors:
            book = upsert_book(db, meta)
            db.commit()
            return book, errors
    return None, errors or ["No metadata found for this ISBN"]


def _same_book(meta: BookMetadata, title: str, author: str | None) -> bool:
    if not meta.authors or similarity(title, meta.title) < TITLE_MATCH:
        return False
    if not author or not author.strip():
        return True
    wanted = normalize_name(author).split()
    names = normalize_name(" ".join(meta.authors)).split()
    return bool(wanted) and wanted[-1] in names


def find_or_add_by_title(db: Session, title: str, author: str | None = None) -> Book | None:
    """The real book with this title: from the catalogue, or else fetched from Google Books /
    Open Library and added. Returns None when no provider knows it, so nothing can be invented."""
    matches = find_by_title(db, title, author, limit=1)
    if matches and matches[0][1] >= LOCAL_TITLE_MATCH:
        return matches[0][0]
    google_query = f'intitle:"{title}"' + (f' inauthor:"{author}"' if author else "")
    open_library_query = f"{title} {author or ''}".strip()
    for search, query in ((gb_search, google_query), (ol_search, open_library_query)):
        try:
            candidates = search(query, db, 5)
        except ProviderError:
            continue
        meta = next((m for m in candidates if _same_book(m, title, author)), None)
        if meta:
            book = upsert_book(db, meta)
            db.commit()
            return book
    return None
