"""eBay Browse API adapter (optional).

Requires EBAY_CLIENT_ID / EBAY_CLIENT_SECRET from a free eBay developer account.
Uses the client-credentials OAuth flow and `item_summary/search`. Results are
asking prices from the configured marketplace (default EBAY_US); nothing here
implies a listing ships to India unless eBay returns shipping info saying so.
"""

from __future__ import annotations

import base64
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.text import strip_control, to_isbn13
from app.integrations.http import (
    USER_AGENT,
    ProviderError,
    breaker_remaining,
    cache_get,
    cache_put,
    open_breaker,
)
from app.marketplace.types import NormalizedListing

_HOSTS = {"sandbox": "https://api.sandbox.ebay.com", "production": "https://api.ebay.com"}
BOOKS_CATEGORY_ID = "267"
BACKOFF_SECONDS = 0.6
RATE_LIMIT_COOLDOWN_SECONDS = 900

# eBay condition IDs used for books
_CONDITION_IDS = {"1000": "new", "1500": "new", "2750": "like_new", "3000": "unknown", "4000": "very_good",
                  "5000": "good", "6000": "acceptable", "7000": "poor"}
_CONDITION_TEXT = {"brand new": "new", "new": "new", "like new": "like_new", "very good": "very_good",
                   "good": "good", "acceptable": "acceptable", "used": "unknown", "pre-owned": "unknown"}

_token_lock = threading.Lock()
_token: dict = {"value": None, "expires": 0.0}


def _host() -> str:
    return _HOSTS[get_settings().ebay_environment]


def _get_token() -> str:
    s = get_settings()
    with _token_lock:
        if _token["value"] and time.time() < _token["expires"] - 60:
            return _token["value"]
        creds = base64.b64encode(f"{s.ebay_client_id}:{s.ebay_client_secret}".encode()).decode()
        try:
            resp = httpx.post(
                f"{_host()}/identity/v1/oauth2/token",
                headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded",
                         "User-Agent": USER_AGENT},
                data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
                timeout=s.external_http_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ProviderError("ebay", "could not reach eBay authentication service") from exc
        if resp.status_code != 200:
            raise ProviderError("ebay", f"authentication failed (HTTP {resp.status_code}); check credentials")
        data = resp.json()
        _token["value"] = data["access_token"]
        _token["expires"] = time.time() + int(data.get("expires_in", 7200))
        return _token["value"]


def _money(obj: dict | None) -> tuple[float | None, str | None]:
    if not obj:
        return None, None
    try:
        return float(obj.get("value")), (obj.get("currency") or "").upper() or None
    except (TypeError, ValueError):
        return None, None


def _condition(item: dict) -> str:
    cid = str(item.get("conditionId") or "")
    if cid in _CONDITION_IDS:
        return _CONDITION_IDS[cid]
    return _CONDITION_TEXT.get((item.get("condition") or "").strip().lower(), "unknown")


def normalize_item(item: dict, fetched_at: datetime) -> NormalizedListing | None:
    """Map an eBay item summary to NormalizedListing. Returns None if unusable."""
    item_id = item.get("itemId")
    url = item.get("itemWebUrl")
    if not item_id or not url or not url.startswith("https://"):
        return None
    price, currency = _money(item.get("price"))
    shipping_cost: float | None = None
    shipping_known = False
    for opt in item.get("shippingOptions") or []:
        cost, cur = _money(opt.get("shippingCost"))
        if cost is not None and (cur is None or cur == currency):
            shipping_cost = cost if shipping_cost is None else min(shipping_cost, cost)
            shipping_known = True
    loc = item.get("itemLocation") or {}
    seller = item.get("seller") or {}
    feedback = seller.get("feedbackPercentage")
    gtins = [to_isbn13(g) for g in item.get("gtin", []) or []] if isinstance(item.get("gtin"), list) else []
    image = (item.get("image") or {}).get("imageUrl")
    listed = item.get("itemCreationDate")
    try:
        listed_at = datetime.fromisoformat(listed.replace("Z", "+00:00")) if listed else None
    except ValueError:
        listed_at = None
    return NormalizedListing(
        uid=f"ebay:{item_id}",
        provider="ebay",
        provider_label="eBay",
        is_external=True,
        external_id=str(item_id),
        title=strip_control(item.get("title"), 300) or "Untitled listing",
        isbn=next((g for g in gtins if g), None),
        condition=_condition(item),
        condition_raw=item.get("condition"),
        price=price,
        currency=currency,
        shipping_cost=shipping_cost,
        shipping_known=shipping_known,
        delivery="shipping",
        location=", ".join(p for p in (loc.get("city"), loc.get("stateOrProvince")) if p) or None,
        country=loc.get("country"),
        seller_name=seller.get("username"),
        seller_feedback_pct=float(feedback) if feedback else None,
        seller_completed_sales=seller.get("feedbackScore"),
        image_url=image if image and image.startswith("https://") else None,
        image_count=1 if image else 0,
        description=strip_control(item.get("shortDescription"), 500),
        url=url,
        listed_at=listed_at,
        fetched_at=fetched_at,
    )


def _invalidate_token() -> None:
    with _token_lock:
        _token["value"], _token["expires"] = None, 0.0


def _browse(params: dict) -> dict:
    """One Browse API search. Retries once for an expired token or a transient server error."""
    s = get_settings()
    for attempt in range(2):
        retry = attempt == 0
        try:
            resp = httpx.get(
                f"{_host()}/buy/browse/v1/item_summary/search",
                params=params,
                headers={"Authorization": f"Bearer {_get_token()}", "X-EBAY-C-MARKETPLACE-ID": s.ebay_marketplace_id,
                         "User-Agent": USER_AGENT},
                timeout=s.external_http_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("ebay", "request timed out") from exc
        except httpx.HTTPError as exc:
            if retry:
                time.sleep(BACKOFF_SECONDS)
                continue
            raise ProviderError("ebay", "unreachable") from exc
        if resp.status_code == 401 and retry:
            _invalidate_token()
            continue
        if resp.status_code >= 500 and retry:
            time.sleep(BACKOFF_SECONDS)
            continue
        if resp.status_code == 429:
            raise ProviderError("ebay", "rate limit reached", retry_after=RATE_LIMIT_COOLDOWN_SECONDS)
        if resp.status_code in (401, 403):
            raise ProviderError("ebay", "access denied for Browse API; check application keyset permissions")
        if resp.status_code != 200:
            raise ProviderError("ebay", f"search failed (HTTP {resp.status_code})")
        return resp.json()
    raise ProviderError("ebay", "unavailable")


def _cached_search(params: dict, db: Session | None) -> tuple[list[dict], datetime]:
    """Search through the shared cache and breaker so repeat lookups cost no eBay calls."""
    s = get_settings()
    key = f"ebay:{s.ebay_environment}:{s.ebay_marketplace_id}:{urlencode(sorted(params.items()))}"
    ttl = timedelta(minutes=s.ebay_cache_ttl_minutes)

    def unpack(row: dict) -> tuple[list[dict], datetime]:
        return row["items"], datetime.fromisoformat(row["fetched_at"])

    cached = cache_get(db, key)
    if cached is not None:
        return unpack(cached)
    try:
        remaining = breaker_remaining("ebay", db)
        if remaining:
            raise ProviderError("ebay", "temporarily paused to stay within its free limit", retry_after=remaining)
        fetched_at = datetime.now(timezone.utc)
        items = _browse(params).get("itemSummaries", []) or []
    except ProviderError as exc:
        if exc.retry_after and not breaker_remaining("ebay", db):
            open_breaker("ebay", exc.retry_after, exc.message, db)
        stale = cache_get(db, key, allow_stale=True)
        if stale is not None:
            return unpack(stale)
        raise
    cache_put(db, key, "ebay", {"items": items, "fetched_at": fetched_at.isoformat()}, ttl)
    return items, fetched_at


def search(query: str, isbn: str | None = None, limit: int = 25, max_price: float | None = None,
           currency: str | None = None, db: Session | None = None) -> list[NormalizedListing]:
    s = get_settings()
    if not s.ebay_configured:
        raise ProviderError("ebay", "not configured")
    base: dict = {"category_ids": BOOKS_CATEGORY_ID, "limit": str(min(limit, 50))}
    filters = ["buyingOptions:{FIXED_PRICE}"]
    if max_price and currency:
        filters.append(f"price:[..{max_price:.2f}],priceCurrency:{currency}")
    base["filter"] = ",".join(filters)
    # An ISBN is exact, and combining it with free text would make eBay require both.
    items, fetched_at, matched_isbn = [], datetime.now(timezone.utc), None
    if isbn:
        items, fetched_at = _cached_search({**base, "gtin": isbn}, db)
        matched_isbn = isbn if items else None
    if not items and query.strip():
        items, fetched_at = _cached_search({**base, "q": query[:100]}, db)
    out = []
    for item in items:
        n = normalize_item(item, fetched_at)
        if n:
            if matched_isbn and not n.isbn:
                n.isbn = matched_isbn
            out.append(n)
    return out
