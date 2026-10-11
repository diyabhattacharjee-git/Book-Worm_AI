"""Book detail, comparison and new-copy offers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations import ebay
from app.integrations.http import ProviderError
from app.integrations.metadata import gb_raw_by_isbn
from app.models.book import Book
from app.recommender.service import get_recommender
from app.repositories.books import (
    difficulty_signal,
    rating_stats,
    to_summary,
    used_stats,
)
from app.schemas.books import (
    BookDetail,
    EditionOut,
    ExternalLink,
    OfferOut,
    OffersResponse,
)

NA = "Not available"


def external_links(book: Book) -> list[ExternalLink]:
    links = []
    if book.openlibrary_work_key:
        links.append(ExternalLink(label="Open Library", url=f"https://openlibrary.org{book.openlibrary_work_key}"))
    isbn = book.primary_isbn
    if book.google_volume_id:
        links.append(ExternalLink(label="Google Books", url=f"https://books.google.com/books?id={book.google_volume_id}"))
    elif isbn:
        links.append(ExternalLink(label="Google Books", url=f"https://books.google.com/books?vid=ISBN{isbn}"))
    if isbn:
        links.append(ExternalLink(label="WorldCat (libraries)", url=f"https://search.worldcat.org/isbn/{isbn}"))
    return links


def book_detail(db: Session, book: Book) -> BookDetail:
    summary = to_summary(book, rating_stats(db, [book.id]).get(book.id, (None, 0, 0)), used_stats(db, [book.id]).get(book.id))
    return BookDetail(
        **summary.model_dump(),
        description=book.description,
        publisher=book.publisher,
        series=book.series,
        subjects=[g.name for g in book.genres if g.kind == "subject"][:12],
        isbn13=book.primary_isbn,
        editions=[EditionOut(id=e.id, isbn13=e.isbn13, isbn10=e.isbn10, format=e.format, edition_label=e.edition_label,
                             publisher=e.publisher, published_year=e.published_year, page_count=e.page_count,
                             language=e.language) for e in book.editions],
        source=book.source,
        metadata_fetched_at=book.metadata_fetched_at,
        external_links=external_links(book),
        difficulty_signal=difficulty_signal(book),
    )


# ------------------------------------------------------------------ comparison
def compare_books(db: Session, books: list[Book], goal: str | None) -> dict:
    ids = [b.id for b in books]
    rs, us = rating_stats(db, ids), used_stats(db, ids)
    rec = get_recommender(db)
    rows = []
    for b in books:
        avg, cnt, n_demo = rs.get(b.id, (None, 0, 0))
        used = us.get(b.id)
        pop = rec.popularity.get(b.id)
        rows.append({
            "book_id": b.id,
            "title": b.title,
            "authors": ", ".join(b.author_names) or NA,
            "genres": ", ".join(g.name for g in b.genres if g.kind == "genre") or NA,
            "themes": ", ".join(g.name for g in b.genres if g.kind == "subject")[:160] or NA,
            "description": (b.description[:280] + "…") if b.description and len(b.description) > 280 else (b.description or NA),
            "page_count": b.page_count if b.page_count else NA,
            "first_published_year": b.first_published_year or NA,
            "language": b.language or NA,
            "app_rating": (f"{avg}★ ({cnt} ratings" + (f", {n_demo} from demo accounts" if n_demo else "") + ")")
            if cnt else "No BookWorm ratings yet",
            "external_rating": (f"{b.external_rating_avg}★ ({b.external_rating_count} on {b.external_rating_source})"
                                if b.external_rating_avg else NA),
            "difficulty": difficulty_signal(b) or NA,
            "formats": ", ".join(sorted({e.format for e in b.editions if e.format})) or NA,
            "used_copies": f"{used[0]} active from {used[2]} {used[1]:.0f}" if used else "No active community listings",
            "cover_url": b.cover_url,
            "_bayes": pop.bayes_rating if pop else None,
        })
    advice = _comparison_advice(rows, goal)
    for r in rows:
        r.pop("_bayes", None)
    return {
        "fields": [
            ("authors", "Author(s)"), ("genres", "Genres"), ("themes", "Subjects / themes"),
            ("description", "Description"), ("page_count", "Pages"), ("first_published_year", "First published"),
            ("language", "Language"), ("app_rating", "BookWorm rating"), ("external_rating", "External rating"),
            ("difficulty", "Difficulty signal"), ("formats", "Known formats"), ("used_copies", "Used copies here"),
        ],
        "rows": rows,
        "advice": advice,
        "generated_by": "deterministic",
    }


def _comparison_advice(rows: list[dict], goal: str | None) -> list[dict]:
    advice = []
    g = (goal or "").lower()
    if any(w in g for w in ("beginner", "start", "new to", "first", "easy", "introduct")):
        beg = [r for r in rows if isinstance(r["difficulty"], str) and any(
            w in r["difficulty"].lower() for w in ("beginner", "introduction", "no prior"))]
        if beg:
            advice.append({"pick_book_id": beg[0]["book_id"], "text": f"For a beginner, “{beg[0]['title']}” is the safer start.",
                           "evidence": beg[0]["difficulty"]})
        else:
            advice.append({"pick_book_id": None, "text": "None of these descriptions explicitly say they target beginners, so I can't rank them on difficulty.",
                           "evidence": "No beginner/introductory wording found in the descriptions."})
    if any(w in g for w in ("short", "quick", "weekend", "fast", "time")):
        with_pages = [r for r in rows if isinstance(r["page_count"], int)]
        if with_pages:
            s = min(with_pages, key=lambda r: r["page_count"])
            advice.append({"pick_book_id": s["book_id"], "text": f"“{s['title']}” is the shortest at {s['page_count']} pages.",
                           "evidence": "Page counts from catalogue metadata (books without a page count were excluded)."})
    if any(w in g for w in ("rated", "best", "quality", "popular", "good")) or not advice:
        rated = [r for r in rows if r["_bayes"] is not None]
        counted = [r for r in rated if "No BookWorm" not in r["app_rating"]]
        if counted:
            best = max(counted, key=lambda r: r["_bayes"])
            advice.append({"pick_book_id": best["book_id"],
                           "text": f"“{best['title']}” has the strongest BookWorm rating after smoothing for sample size.",
                           "evidence": f"Bayesian-smoothed rating {best['_bayes']:.2f} (see docs/RECOMMENDER.md)."})
    if not advice:
        advice.append({"pick_book_id": None, "text": "There isn't enough rating or metadata evidence to prefer one book; compare the descriptions above.",
                       "evidence": None})
    return advice


# ---------------------------------------------------------------------- offers
def new_offers(db: Session, book: Book) -> OffersResponse:
    """New-copy offers from configured sources. Google Books / Open Library are
    metadata sources; Google's saleInfo only yields a price when Google itself
    sells the (usually e-book) edition in GOOGLE_BOOKS_COUNTRY."""
    offers: list[OfferOut] = []
    notes: list[str] = []
    s = get_settings()
    isbn = book.primary_isbn
    if isbn and s.enable_google_books:
        try:
            for item in gb_raw_by_isbn(isbn, db):
                sale = item.get("saleInfo") or {}
                price = sale.get("retailPrice") or sale.get("listPrice")
                if sale.get("saleability") == "FOR_SALE" and price and sale.get("buyLink", "").startswith("https://"):
                    offers.append(OfferOut(
                        source="Google Play Books", title=item.get("volumeInfo", {}).get("title", book.title),
                        format="ebook" if sale.get("isEbook") else None, price=float(price.get("amount")),
                        currency=price.get("currencyCode"), availability="For sale (as reported by Google)",
                        url=sale["buyLink"], retrieved_at=datetime.now(timezone.utc),
                        note=f"Price for country {sale.get('country', s.google_books_country)}",
                    ))
            if not offers:
                notes.append(f"Google Books returned no priced offer for this ISBN in {s.google_books_country}.")
        except ProviderError as exc:
            notes.append(f"Google Books unavailable: {exc.message}.")
    elif not isbn:
        notes.append("No ISBN on file, so price sources can't be queried precisely.")
    if s.ebay_configured:
        try:
            for item in ebay.search(book.title, isbn=isbn, limit=10):
                if item.condition == "new" and item.price is not None:
                    offers.append(OfferOut(
                        source="eBay", title=item.title, format=None, price=item.price, currency=item.currency,
                        availability="Listed (availability not verified)", url=item.url, retrieved_at=item.fetched_at,
                        note=("Shipping to India not confirmed" if item.country != "IN" else None),
                    ))
        except ProviderError as exc:
            notes.append(f"eBay unavailable: {exc.message}.")
    used = used_stats(db, [book.id]).get(book.id)
    return OffersResponse(
        book_id=book.id,
        offers=offers,
        used_summary={"active_listings": used[0], "lowest_price": used[1], "currency": used[2]} if used else
        {"active_listings": 0, "lowest_price": None, "currency": None},
        metadata_links=external_links(book),
        provider_notes=notes,
    )
