"""Seed data: real records only.

* Catalogue: 70 real books whose metadata (description, page count, publisher,
  year, subjects, cover, Open Library rating) was fetched from Open Library /
  Google Books into seed_books.json. Genre tags are curated labels.
* Marketplace provider registry.

No users, ratings, reviews or listings are created: those come only from real
people using the app.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.metadata import BookMetadata
from app.models.marketplace import MarketplaceProvider
from app.services.catalogue import find_book_by_isbn, upsert_book

SEED_FILE = Path(__file__).with_name("seed_books.json")

# Open Library's work-level first_publish_year is wrong for a few works (merged
# pre-release editions). These well-established years are curated overrides.
YEAR_OVERRIDES = {
    "9780743273565": 1925,  # The Great Gatsby
    "9780316769488": 1951,  # The Catcher in the Rye
    "9780804139298": 2014,  # Zero to One
    "9781501110368": 2016,  # It Ends with Us
    "9781612680194": 1997,  # Rich Dad Poor Dad
    "9780735211292": 2018,  # Atomic Habits
    "9781416562603": 2008,  # The White Tiger
}

PROVIDERS = [
    ("community", "BookWorm community", False),
    ("ebay", "eBay", True),
]

def seed_providers(db: Session) -> None:
    for key, name, external in PROVIDERS:
        if not db.scalar(select(MarketplaceProvider).where(MarketplaceProvider.key == key)):
            db.add(MarketplaceProvider(key=key, name=name, is_external=external, enabled=True))
    db.commit()


def seed_catalogue(db: Session) -> int:
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    created = 0
    for rec in data["books"]:
        if find_book_by_isbn(db, rec["isbn13"]):
            continue
        meta = BookMetadata(
            title=rec["title"],
            source="open_library",
            authors=rec["authors"],
            description=rec.get("description"),
            language=rec.get("language"),
            published_year=YEAR_OVERRIDES.get(rec["isbn13"], rec.get("first_published_year") or rec.get("edition_year")),
            page_count=rec.get("page_count"),
            publisher=rec.get("publisher"),
            isbns=[rec["isbn13"]],
            cover_url=rec.get("cover_url"),
            subjects=rec.get("subjects") or [],
            rating_avg=rec.get("external_rating_avg"),
            rating_count=rec.get("external_rating_count"),
            work_key=rec.get("openlibrary_work_key"),
            format=rec.get("format"),
        )
        book = upsert_book(db, meta, genres=rec["genres"], is_sample=False)
        book.source = "open_library"
        if rec.get("external_rating_source"):
            book.external_rating_source = rec["external_rating_source"]
        if book.editions and rec.get("edition_year"):
            book.editions[0].published_year = rec["edition_year"]
        created += 1
    db.commit()
    return created


def run_seed(db: Session) -> dict:
    seed_providers(db)
    return {"books_created": seed_catalogue(db)}
