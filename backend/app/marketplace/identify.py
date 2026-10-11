"""Book identification agent (deterministic).

Confidence (documented in docs/MARKETPLACE_INTELLIGENCE.md):
* ISBN found in catalogue                       -> 1.00
* ISBN resolved via Open Library/Google Books   -> 0.95 (imported into catalogue)
* Title (+author) fuzzy match in catalogue      -> match score s (0..1), accepted if s >= 0.80
* Title match from Open Library search only     -> 0.85 * s
Ambiguity is flagged when the runner-up is a *different* work within 0.05 of
the best score; both are returned so the user can pick.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sqlalchemy.orm import Session

from app.core.text import normalize_title, similarity, to_isbn13
from app.integrations.http import ProviderError
from app.integrations.metadata import ol_search
from app.models.book import Book
from app.repositories.books import find_by_title
from app.services.catalogue import find_book_by_isbn, import_by_isbn

ACCEPT = 0.80


@dataclass
class IdentifiedBook:
    found: bool
    confidence: float
    method: str
    book_id: int | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    isbns: list[str] = field(default_factory=list)  # known edition ISBNs of this work
    requested_isbn: str | None = None
    language: str | None = None
    cover_url: str | None = None
    ambiguous: bool = False
    candidates: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _from_book(book: Book, confidence: float, method: str, requested_isbn: str | None = None) -> IdentifiedBook:
    return IdentifiedBook(found=True, confidence=round(confidence, 3), method=method, book_id=book.id,
                          title=book.title, authors=book.author_names,
                          isbns=[e.isbn13 for e in book.editions if e.isbn13], requested_isbn=requested_isbn,
                          language=book.language, cover_url=book.cover_url)


def identify(db: Session, *, isbn: str | None, title: str | None, author: str | None,
             allow_network: bool = True) -> IdentifiedBook:
    notes: list[str] = []
    isbn13 = to_isbn13(isbn) if isbn else None
    if isbn and not isbn13:
        notes.append("The ISBN provided is not valid, so it was ignored.")
    if isbn13:
        book = find_book_by_isbn(db, isbn13)
        if book:
            return _from_book(book, 1.0, "isbn_catalogue", isbn13)
        if allow_network:
            book, errors = import_by_isbn(db, isbn13)
            if book:
                ib = _from_book(book, 0.95, "isbn_metadata_provider", isbn13)
                ib.notes.append("Book metadata was fetched by ISBN and added to the catalogue.")
                return ib
            notes.extend(errors)
        if not title:
            return IdentifiedBook(found=False, confidence=0.0, method="isbn_unresolved", requested_isbn=isbn13,
                                  isbns=[isbn13], notes=notes + ["Searching listings by ISBN only."])

    if title:
        matches = find_by_title(db, title, author, limit=5)
        if matches and matches[0][1] >= ACCEPT:
            best, score = matches[0]
            ib = _from_book(best, score, "title_catalogue", isbn13)
            rivals = [(b, s) for b, s in matches[1:] if s >= score - 0.05
                      and normalize_title(b.title) != normalize_title(best.title)]
            if rivals:
                ib.ambiguous = True
                ib.candidates = [{"book_id": b.id, "title": b.title, "authors": b.author_names, "score": s}
                                 for b, s in [(best, score), *rivals]]
                ib.notes.append("Several catalogue books match this title; showing results for the closest one.")
            if not author and score < 0.95:
                ib.notes.append("Matched on title only; add the author for a more certain match.")
            ib.notes = notes + ib.notes
            return ib
        if allow_network:
            try:
                metas = ol_search(f"{title} {author or ''}".strip(), db, limit=5)
            except ProviderError as exc:
                metas = []
                notes.append(f"Open Library: {exc.message}")
            scored = sorted(((m, similarity(title, m.title)) for m in metas), key=lambda x: x[1], reverse=True)
            if scored and scored[0][1] >= ACCEPT:
                m, s = scored[0]
                ib = IdentifiedBook(found=True, confidence=round(0.85 * s, 3), method="title_open_library",
                                    title=m.title, authors=m.authors, isbns=m.isbns[:10], requested_isbn=isbn13,
                                    language=m.language, cover_url=m.cover_url)
                distinct = {(normalize_title(x.title), tuple(x.authors[:1])) for x, sc in scored if sc >= s - 0.05}
                if len(distinct) > 1:
                    ib.ambiguous = True
                    ib.candidates = [{"title": x.title, "authors": x.authors, "score": round(sc, 3)}
                                     for x, sc in scored if sc >= s - 0.05][:4]
                ib.notes = notes + ["Identified from Open Library; this book isn't in the local catalogue yet."]
                return ib
        return IdentifiedBook(found=False, confidence=0.0, method="unidentified", title=title,
                              authors=[author] if author else [], requested_isbn=isbn13,
                              notes=notes + ["Couldn't confidently identify this book; listings are matched by title text only."])
    return IdentifiedBook(found=False, confidence=0.0, method="no_input", notes=notes)
