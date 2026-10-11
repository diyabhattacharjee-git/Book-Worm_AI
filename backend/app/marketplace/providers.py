"""Listing provider adapters and the concurrent search coordinator.

Each provider runs in its own thread with its own DB session and a timeout; a
failure or timeout in one provider never discards results from another."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.text import normalize_title
from app.db.base import as_utc
from app.db.session import SessionLocal
from app.integrations import ebay
from app.integrations.http import ProviderError
from app.marketplace.types import NormalizedListing
from app.models.marketplace import (
    CachedExternalListing,
    MarketplaceListing,
    MarketplaceProvider,
)
from app.services.listings import search_community, seller_sales
from app.services.uploads import public_url

logger = logging.getLogger("bookworm.marketplace.providers")

PROVIDER_TIMEOUT_SECONDS = 12.0


@dataclass
class SearchRequest:
    title: str | None = None
    author: str | None = None
    isbn: str | None = None
    isbns: list[str] = field(default_factory=list)
    book_id: int | None = None
    max_price: float | None = None
    currency: str = "INR"
    min_condition: str | None = None
    location: str | None = None
    delivery: str = "any"
    include_external: bool = True

    @property
    def text(self) -> str:
        return " ".join(p for p in (self.title, self.author) if p) or (self.isbn or "")


@dataclass
class ProviderResult:
    provider: str
    label: str
    ok: bool
    listings: list[NormalizedListing] = field(default_factory=list)
    error: str | None = None
    skipped: str | None = None
    duration_ms: int = 0
    fetched_at: datetime | None = None


def community_to_normalized(lst: MarketplaceListing, sales: dict[int, int], now: datetime) -> NormalizedListing:
    ship_known = lst.delivery == "pickup" or lst.shipping_cost is not None
    return NormalizedListing(
        uid=f"community:{lst.id}", provider="community", provider_label="BookWorm community", is_external=False,
        is_sample=lst.is_sample, external_id=str(lst.id), title=lst.title, author=lst.author, isbn=lst.isbn,
        edition_text=lst.edition_text, published_year=lst.published_year, condition=lst.condition,
        condition_raw=lst.condition, price=float(lst.price_amount), currency=lst.currency,
        shipping_cost=0.0 if lst.delivery == "pickup" else (float(lst.shipping_cost) if lst.shipping_cost is not None else None),
        shipping_known=ship_known, delivery=lst.delivery,
        location=lst.location_city if lst.location_public else None, country="IN",
        seller_name=lst.seller.display_name, seller_id=lst.seller_id,
        seller_completed_sales=sales.get(lst.seller_id, 0),
        image_url=public_url(lst.images[0].path) if lst.images else (lst.book.cover_url if lst.book else None),
        image_count=len(lst.images), description=lst.description, url=f"/marketplace/listings/{lst.id}",
        status=lst.status, listed_at=as_utc(lst.updated_at), fetched_at=now, book_id=lst.book_id,
    )


def search_community_provider(db: Session, req: SearchRequest) -> list[NormalizedListing]:
    found: dict[int, MarketplaceListing] = {}
    for isbn in ([req.isbn] if req.isbn else []) + [i for i in req.isbns if i != req.isbn]:
        for lst in search_community(db, isbn=isbn, limit=100)[0]:
            found[lst.id] = lst
    if req.book_id:
        for lst in search_community(db, book_id=req.book_id, limit=100)[0]:
            found[lst.id] = lst
    if req.title:
        for lst in search_community(db, q=req.title, limit=100)[0]:
            found[lst.id] = lst
    now = datetime.now(timezone.utc)
    sales = seller_sales(db, list({lst.seller_id for lst in found.values()}))
    return [community_to_normalized(lst, sales, now) for lst in found.values()]


def _cache_external(db: Session, items: list[NormalizedListing]) -> None:
    for it in items:
        row = db.scalar(select(CachedExternalListing).where(CachedExternalListing.provider == it.provider,
                                                            CachedExternalListing.external_id == it.external_id))
        payload = it.model_dump(mode="json")
        if row:
            row.payload, row.fetched_at, row.price_amount, row.currency = payload, it.fetched_at, it.price, it.currency
        else:
            db.add(CachedExternalListing(provider=it.provider, external_id=it.external_id, isbn=it.isbn,
                                         normalized_title=normalize_title(it.title)[:300], price_amount=it.price,
                                         currency=it.currency, payload=payload, url=it.url, fetched_at=it.fetched_at))
    db.commit()


def search_ebay_provider(db: Session, req: SearchRequest) -> list[NormalizedListing]:
    items = ebay.search(req.text or req.isbn or "", isbn=req.isbn, limit=30,
                        max_price=req.max_price if req.currency == "USD" else None, currency=req.currency)
    try:
        _cache_external(db, items)
    except Exception:  # caching is best-effort
        db.rollback()
        logger.warning("could not cache eBay results", exc_info=True)
    return items


PROVIDERS = {
    "community": ("BookWorm community", search_community_provider),
    "ebay": ("eBay", search_ebay_provider),
}


def provider_enabled(key: str) -> tuple[bool, str | None]:
    if key == "community":
        return True, None
    if key == "ebay":
        if not get_settings().ebay_configured:
            return False, "Not connected"
        return True, None
    return False, "unknown provider"


def _run_provider(key: str, req: SearchRequest) -> list[NormalizedListing]:
    with SessionLocal() as db:
        return PROVIDERS[key][1](db, req)


def _record_status(key: str, ok: bool, error: str | None) -> None:
    try:
        with SessionLocal() as db:
            row = db.scalar(select(MarketplaceProvider).where(MarketplaceProvider.key == key))
            if row is None:
                return
            now = datetime.now(timezone.utc)
            if ok:
                row.last_success_at = now
            else:
                row.last_error, row.last_error_at = (error or "error")[:300], now
            db.commit()
    except Exception:
        logger.warning("could not record provider status", exc_info=True)


def search_all(req: SearchRequest) -> list[ProviderResult]:
    keys = [k for k in PROVIDERS if req.include_external or k == "community"]
    results: list[ProviderResult] = []
    runnable = []
    for key in PROVIDERS:
        label = PROVIDERS[key][0]
        if key not in keys:
            results.append(ProviderResult(key, label, ok=False, skipped="External sources were not requested"))
            continue
        enabled, why = provider_enabled(key)
        if not enabled:
            results.append(ProviderResult(key, label, ok=False, skipped=why))
            continue
        runnable.append(key)
    pool = ThreadPoolExecutor(max_workers=max(1, len(runnable)), thread_name_prefix="provider")
    deadline = time.perf_counter() + PROVIDER_TIMEOUT_SECONDS
    try:
        futures = {k: (pool.submit(_run_provider, k, req), time.perf_counter()) for k in runnable}
        for key, (fut, started) in futures.items():
            label = PROVIDERS[key][0]
            try:
                items = fut.result(timeout=max(0.1, deadline - time.perf_counter()))
                res = ProviderResult(key, label, ok=True, listings=items, fetched_at=datetime.now(timezone.utc))
                _record_status(key, True, None)
            except FutureTimeout:
                res = ProviderResult(key, label, ok=False, error="timed out")
                _record_status(key, False, "timed out")
            except ProviderError as exc:
                res = ProviderResult(key, label, ok=False, error=exc.message)
                _record_status(key, False, exc.message)
            except Exception as exc:
                logger.exception("provider crashed", extra={"data": {"provider": key}})
                res = ProviderResult(key, label, ok=False, error="unexpected error")
                _record_status(key, False, type(exc).__name__)
            res.duration_ms = int((time.perf_counter() - started) * 1000)
            results.append(res)
    finally:
        # Never block the request on a hung provider.
        pool.shutdown(wait=False, cancel_futures=True)
    order = list(PROVIDERS)
    return sorted(results, key=lambda r: order.index(r.provider))


def providers_status(db: Session) -> list[dict]:
    rows = {r.key: r for r in db.scalars(select(MarketplaceProvider))}
    out = []
    s = get_settings()
    for key, (label, _) in PROVIDERS.items():
        enabled, why = provider_enabled(key)
        row = rows.get(key)
        info = {"key": key, "name": label, "is_external": key != "community", "available": enabled,
                "reason": why, "last_success_at": row.last_success_at if row else None,
                "last_error": row.last_error if row else None, "last_error_at": row.last_error_at if row else None}
        if key == "ebay":
            info["environment"] = s.ebay_environment
            info["marketplace_id"] = s.ebay_marketplace_id
            info["note"] = ("Sandbox returns test data only." if s.ebay_environment == "sandbox" else
                            "Listings come from the configured eBay marketplace; shipping to India is not assumed.")
        out.append(info)
    return out
