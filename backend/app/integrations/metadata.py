"""Book metadata providers: Open Library (no key) and Google Books (key optional).

Both are used for *metadata*. Google Books `saleInfo` is surfaced separately as
an offer source only when the API actually returns a price (usually ebooks)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.text import to_isbn13
from app.integrations.http import ProviderError, get_json

OL_BASE = "https://openlibrary.org"
GB_BASE = "https://www.googleapis.com/books/v1"
OL_COVER = "https://covers.openlibrary.org/b"


@dataclass
class BookMetadata:
    title: str
    source: str
    source_id: str | None = None
    subtitle: str | None = None
    authors: list[str] = field(default_factory=list)
    description: str | None = None
    language: str | None = None
    published_year: int | None = None
    page_count: int | None = None
    publisher: str | None = None
    isbns: list[str] = field(default_factory=list)
    cover_url: str | None = None
    subjects: list[str] = field(default_factory=list)
    rating_avg: float | None = None
    rating_count: int | None = None
    info_url: str | None = None
    work_key: str | None = None
    format: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


_LANG_3_TO_2 = {"eng": "en", "hin": "hi", "spa": "es", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de",
                "jpn": "ja", "ben": "bn", "tam": "ta", "tel": "te", "mar": "mr", "ita": "it", "por": "pt"}


def _year(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"(1[5-9]\d\d|20\d\d)", str(text))
    return int(m.group(1)) if m else None


def _ttl() -> timedelta:
    return timedelta(hours=get_settings().metadata_cache_ttl_hours)


# ---------------------------------------------------------------- Open Library
def _ol_doc_to_meta(doc: dict) -> BookMetadata:
    isbns = [i for i in (to_isbn13(x) for x in (doc.get("isbn") or [])[:40]) if i]
    isbns = list(dict.fromkeys(isbns))
    cover = f"{OL_COVER}/id/{doc['cover_i']}-L.jpg" if doc.get("cover_i") else None
    langs = doc.get("language") or []
    return BookMetadata(
        title=doc.get("title") or "Untitled",
        subtitle=doc.get("subtitle"),
        source="open_library",
        source_id=doc.get("key"),
        work_key=doc.get("key"),
        authors=(doc.get("author_name") or [])[:5],
        published_year=doc.get("first_publish_year"),
        page_count=doc.get("number_of_pages_median"),
        publisher=(doc.get("publisher") or [None])[0],
        isbns=isbns[:10],
        cover_url=cover,
        subjects=[s for s in (doc.get("subject") or [])[:12] if len(s) < 60],
        language=_LANG_3_TO_2.get(langs[0], langs[0]) if langs else None,
        rating_avg=round(doc["ratings_average"], 2) if doc.get("ratings_average") else None,
        rating_count=doc.get("ratings_count"),
        info_url=f"{OL_BASE}{doc['key']}" if doc.get("key") else None,
    )


def ol_search(query: str, db: Session | None = None, limit: int = 10) -> list[BookMetadata]:
    if not get_settings().enable_open_library:
        return []
    fields = ("key,title,subtitle,author_name,first_publish_year,isbn,number_of_pages_median,subject,"
              "language,publisher,cover_i,ratings_average,ratings_count")
    data = get_json(
        "open_library",
        f"{OL_BASE}/search.json",
        params={"q": query, "limit": limit, "fields": fields},
        db=db,
        cache_key=f"ol:search:{query.lower()}:{limit}",
        ttl=_ttl(),
    )
    return [_ol_doc_to_meta(d) for d in (data or {}).get("docs", [])]


def ol_work_details(work_key: str, db: Session | None = None) -> dict:
    data = get_json("open_library", f"{OL_BASE}{work_key}.json", db=db, cache_key=f"ol:work:{work_key}", ttl=_ttl())
    if not data:
        return {}
    desc = data.get("description")
    if isinstance(desc, dict):
        desc = desc.get("value")
    return {"description": desc, "subjects": (data.get("subjects") or [])[:15]}


def ol_by_isbn(isbn13: str, db: Session | None = None) -> BookMetadata | None:
    if not get_settings().enable_open_library:
        return None
    ed = get_json("open_library", f"{OL_BASE}/isbn/{isbn13}.json", db=db, cache_key=f"ol:isbn:{isbn13}", ttl=_ttl())
    if not ed:
        return None
    works = ed.get("works") or []
    work_key = works[0]["key"] if works else None
    details = ol_work_details(work_key, db) if work_key else {}
    langs = [lang.get("key", "").split("/")[-1] for lang in ed.get("languages") or []]
    authors: list[str] = []
    if work_key:
        search = get_json(
            "open_library", f"{OL_BASE}/search.json", params={"q": f"isbn:{isbn13}", "fields": "author_name,key"},
            db=db, cache_key=f"ol:isbn-authors:{isbn13}", ttl=_ttl(),
        ) or {}
        docs = search.get("docs") or []
        authors = (docs[0].get("author_name") or []) if docs else []
    return BookMetadata(
        title=ed.get("title") or "Untitled",
        subtitle=ed.get("subtitle"),
        source="open_library",
        source_id=ed.get("key"),
        work_key=work_key,
        authors=authors[:5],
        description=details.get("description"),
        subjects=[s for s in details.get("subjects", []) if len(s) < 60],
        language=_LANG_3_TO_2.get(langs[0], langs[0]) if langs else None,
        published_year=_year(ed.get("publish_date")),
        page_count=ed.get("number_of_pages"),
        publisher=(ed.get("publishers") or [None])[0],
        isbns=[isbn13],
        cover_url=f"{OL_COVER}/isbn/{isbn13}-L.jpg",
        info_url=f"{OL_BASE}{ed['key']}" if ed.get("key") else None,
        format=(ed.get("physical_format") or "").lower() or None,
    )


def ol_editions(work_key: str, db: Session | None = None, limit: int = 30) -> list[dict]:
    data = get_json(
        "open_library", f"{OL_BASE}{work_key}/editions.json", params={"limit": limit},
        db=db, cache_key=f"ol:editions:{work_key}:{limit}", ttl=_ttl(),
    )
    out = []
    for e in (data or {}).get("entries", []):
        isbn = next((to_isbn13(i) for i in (e.get("isbn_13") or []) + (e.get("isbn_10") or []) if to_isbn13(i)), None)
        langs = [lang.get("key", "").split("/")[-1] for lang in e.get("languages") or []]
        out.append({
            "title": e.get("title"),
            "isbn13": isbn,
            "publisher": (e.get("publishers") or [None])[0],
            "published_year": _year(e.get("publish_date")),
            "page_count": e.get("number_of_pages"),
            "format": (e.get("physical_format") or "").lower() or None,
            "language": _LANG_3_TO_2.get(langs[0], langs[0]) if langs else None,
            "source_url": f"{OL_BASE}{e['key']}" if e.get("key") else None,
        })
    return out


# ---------------------------------------------------------------- Google Books
def _gb_params(extra: dict) -> dict:
    s = get_settings()
    params = {"country": s.google_books_country, **extra}
    if s.google_books_api_key:
        params["key"] = s.google_books_api_key
    return params


def _gb_item_to_meta(item: dict) -> BookMetadata:
    info = item.get("volumeInfo", {})
    isbns = [to_isbn13(i.get("identifier")) for i in info.get("industryIdentifiers", [])]
    images = info.get("imageLinks") or {}
    cover = images.get("thumbnail") or images.get("smallThumbnail")
    if cover:
        cover = cover.replace("http://", "https://")
    return BookMetadata(
        title=info.get("title") or "Untitled",
        subtitle=info.get("subtitle"),
        source="google_books",
        source_id=item.get("id"),
        authors=(info.get("authors") or [])[:5],
        description=info.get("description"),
        language=info.get("language"),
        published_year=_year(info.get("publishedDate")),
        page_count=info.get("pageCount") or None,
        publisher=info.get("publisher"),
        isbns=[i for i in isbns if i],
        cover_url=cover,
        subjects=info.get("categories") or [],
        rating_avg=info.get("averageRating"),
        rating_count=info.get("ratingsCount"),
        info_url=info.get("infoLink") or info.get("canonicalVolumeLink"),
    )


def gb_search(query: str, db: Session | None = None, limit: int = 10) -> list[BookMetadata]:
    if not get_settings().enable_google_books:
        return []
    data = get_json(
        "google_books", f"{GB_BASE}/volumes", params=_gb_params({"q": query, "maxResults": min(limit, 40)}),
        db=db, cache_key=f"gb:search:{query.lower()}:{limit}", ttl=_ttl(),
    )
    return [_gb_item_to_meta(i) for i in (data or {}).get("items", [])]


def gb_raw_by_isbn(isbn13: str, db: Session | None = None) -> list[dict]:
    if not get_settings().enable_google_books:
        return []
    data = get_json(
        "google_books", f"{GB_BASE}/volumes", params=_gb_params({"q": f"isbn:{isbn13}"}),
        db=db, cache_key=f"gb:isbn:{isbn13}:{get_settings().google_books_country}", ttl=timedelta(hours=12),
    )
    return (data or {}).get("items", [])


def gb_by_isbn(isbn13: str, db: Session | None = None) -> BookMetadata | None:
    items = gb_raw_by_isbn(isbn13, db)
    return _gb_item_to_meta(items[0]) if items else None


def search_metadata(query: str, db: Session | None = None, limit: int = 10) -> tuple[list[BookMetadata], list[str]]:
    """Query every enabled provider; one failing provider never hides the other."""
    results: list[BookMetadata] = []
    errors: list[str] = []
    for fn, name in ((ol_search, "Open Library"), (gb_search, "Google Books")):
        try:
            results.extend(fn(query, db, limit))
        except ProviderError as exc:
            errors.append(f"{name}: {exc.message}")
    return results, errors
