"""Fetch real metadata for the development catalogue and write seed_books.json.

Run once with internet access:  python -m app.db.build_seed_catalogue
The generated JSON is committed so the app can be seeded fully offline.
Every field records which provider it came from.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.db.seed_source import SEED_BOOKS
from app.integrations.http import ProviderError
from app.integrations.metadata import gb_by_isbn, ol_by_isbn, ol_search

OUT = Path(__file__).with_name("seed_books.json")


def _first(*vals):
    for v in vals:
        if v not in (None, "", []):
            return v
    return None


def build() -> None:
    records = []
    for isbn, title, author, genres in SEED_BOOKS:
        ol = gb = ol_doc = None
        errors = []
        try:
            ol = ol_by_isbn(isbn)
        except ProviderError as exc:
            errors.append(f"open_library: {exc.message}")
        try:
            docs = ol_search(f"isbn:{isbn}", limit=1)
            ol_doc = docs[0] if docs else None
        except ProviderError as exc:
            errors.append(f"open_library_search: {exc.message}")
        try:
            gb = gb_by_isbn(isbn)
        except ProviderError as exc:
            errors.append(f"google_books: {exc.message}")
        time.sleep(0.4)  # be polite to free APIs

        desc_src = "google_books" if gb and gb.description else ("open_library" if ol and ol.description else None)
        pages_src = "open_library" if ol and ol.page_count else ("google_books" if gb and gb.page_count else None)
        rec = {
            "isbn13": isbn,
            "title": title,
            "authors": [author],
            "genres": genres,
            "description": _first(gb.description if gb else None, ol.description if ol else None),
            "description_source": desc_src,
            "page_count": _first(ol.page_count if ol else None, gb.page_count if gb else None),
            "page_count_source": pages_src,
            "first_published_year": _first(ol_doc.published_year if ol_doc else None),
            "edition_year": _first(ol.published_year if ol else None, gb.published_year if gb else None),
            "publisher": _first(ol.publisher if ol else None, gb.publisher if gb else None),
            "language": _first(gb.language if gb else None, ol.language if ol else None),
            "format": ol.format if ol else None,
            "subjects": (ol.subjects if ol else [])[:8] or (gb.subjects if gb else []),
            "openlibrary_work_key": _first(ol.work_key if ol else None, ol_doc.work_key if ol_doc else None),
            "google_volume_id": gb.source_id if gb else None,
            "cover_url": f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg",
            "external_rating_avg": ol_doc.rating_avg if ol_doc and ol_doc.rating_count else None,
            "external_rating_count": ol_doc.rating_count if ol_doc else None,
            "external_rating_source": "open_library" if ol_doc and ol_doc.rating_count else None,
            "fetch_errors": errors,
        }
        found = "ok" if (ol or gb) else "NOT FOUND"
        print(f"{found:9} {title[:50]:50} pages={rec['page_count']} year={rec['first_published_year']}", flush=True)
        records.append(rec)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Development catalogue. Metadata fetched from Open Library and Google Books; "
                "genres are curated tags. Flagged as sample data in the app.",
        "books": records,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(records)} records to {OUT}")


if __name__ == "__main__":
    sys.exit(build())
