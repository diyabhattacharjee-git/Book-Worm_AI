"""Listing validation, book matching and de-duplication agent (deterministic).

Match classes relative to the identified book:
* exact       - listing ISBN is one of the identified edition ISBNs
* same_work   - linked to the same catalogue work, edition unknown or different
* approximate - title (and author, when known) match strongly but no ISBN/link
* unmatched   - excluded as probably a different book (kept in `excluded`)
Listings are never dropped just for missing optional fields; issues are recorded.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.core.text import normalize_name, normalize_title, similarity
from app.marketplace.identify import IdentifiedBook
from app.marketplace.types import NormalizedListing

NOT_THE_BOOK = re.compile(
    r"\b(summary|summaries|study guide|workbook|analysis of|notes on|lot of|bundle|set of|collection|box set|"
    r"cliffs?notes|sparknotes|audiobook|audio cd|dvd|poster|bookmark|journal|planner|keychain|t-shirt)\b", re.I)
STALE_EXTERNAL_HOURS = 24
STALE_COMMUNITY_DAYS = 120


def _title_contains(identified_title: str, listing_title: str) -> bool:
    want = set(normalize_title(identified_title).split())
    have = set(normalize_title(listing_title).split()) | set(re.findall(r"[a-z0-9]+", listing_title.lower()))
    return bool(want) and want <= have


def classify_match(item: NormalizedListing, book: IdentifiedBook) -> tuple[str, float, str | None]:
    if NOT_THE_BOOK.search(item.title or ""):
        return "unmatched", 0.0, "Looks like a companion item (summary, workbook, bundle or merchandise), not the book itself."
    isbns = set(book.isbns) | ({book.requested_isbn} if book.requested_isbn else set())
    if item.isbn and isbns and item.isbn in isbns:
        return "exact", 1.0, None
    if book.book_id and item.book_id == book.book_id:
        if item.isbn:
            return "same_work", 0.85, "Different ISBN from the identified edition: may be a different edition or printing."
        return "same_work", 0.8, "Edition not stated by the seller."
    if not book.title:
        return "unmatched", 0.0, "No book identity to compare against."
    sim = similarity(book.title, item.title)
    contains = _title_contains(book.title, item.title)
    author_ok = True
    if book.authors:
        last_names = {normalize_name(a).split()[-1] for a in book.authors if normalize_name(a)}
        hay = normalize_name(f"{item.title} {item.author or ''}")
        author_ok = any(ln in hay.split() for ln in last_names) if (item.author or item.is_external) else True
        if item.is_external and not author_ok and contains:
            author_ok = True  # external titles often omit the author; title containment is required instead
    if (sim >= 0.85 or contains) and author_ok:
        conf = 0.7 if item.isbn is None else 0.6
        note = "Matched by title" + (" and author" if book.authors and item.author else "") + "; edition unknown."
        if item.isbn:
            note = "ISBN differs from known editions; matched by title. Could be a translation or another edition."
        return "approximate", conf, note
    return "unmatched", round(sim, 2), "Title doesn't match the requested book closely enough."


def validate_and_dedupe(items: list[NormalizedListing], book: IdentifiedBook, now: datetime | None = None
                        ) -> tuple[list[NormalizedListing], list[dict]]:
    now = now or datetime.now(timezone.utc)
    kept: list[NormalizedListing] = []
    excluded: list[dict] = []
    seen_uids: set[str] = set()
    for it in items:
        if it.uid in seen_uids:
            excluded.append({"uid": it.uid, "title": it.title, "provider": it.provider, "reason": "Exact duplicate result"})
            continue
        seen_uids.add(it.uid)
        if it.status != "active":
            excluded.append({"uid": it.uid, "title": it.title, "provider": it.provider, "reason": f"Listing is {it.status}"})
            continue
        issues: list[str] = []
        if it.price is None or it.price <= 0:
            issues.append("Price missing or invalid")
        if not it.currency:
            issues.append("Currency missing")
        if it.condition == "unknown":
            issues.append("Condition not specified")
        if it.image_count == 0 and not it.image_url:
            issues.append("No photos")
        elif it.provider == "community" and it.image_count == 0:
            issues.append("No photos of the actual copy (catalogue cover shown)")
        if not it.shipping_known:
            issues.append("Shipping cost unknown: total cost incomplete")
        if not it.isbn and not it.edition_text:
            issues.append("Edition not stated")
        if it.is_external and (now - it.fetched_at).total_seconds() > STALE_EXTERNAL_HOURS * 3600:
            issues.append("External data may be stale")
        if it.listed_at and not it.is_external and (now - it.listed_at).days > STALE_COMMUNITY_DAYS:
            issues.append(f"Not updated for {(now - it.listed_at).days} days")
        if it.is_external and it.country and it.country != "IN":
            issues.append(f"Item located in {it.country}; shipping to India not confirmed")
        if it.is_sample:
            issues.append("Sample data (not a real listing)")
        match, conf, note = classify_match(it, book)
        if match == "unmatched":
            excluded.append({"uid": it.uid, "title": it.title, "provider": it.provider, "reason": note or "Different book"})
            continue
        if note:
            issues.append(note)
        it.match, it.match_confidence, it.validation_issues = match, conf, issues
        kept.append(it)

    # Probable duplicates: same seller, same title, same price & condition (kept, but flagged).
    sig: dict[tuple, str] = {}
    for it in kept:
        key = (it.provider if not it.is_external else "ext", (it.seller_name or "").lower(),
               normalize_title(it.title), it.price, it.condition)
        if key in sig:
            it.probable_duplicate_of = sig[key]
            it.validation_issues.append("Probable duplicate of another listing from the same seller")
        else:
            sig[key] = it.uid
    return kept, excluded
