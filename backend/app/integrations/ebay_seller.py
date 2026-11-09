"""eBay seller tools: connect an account (OAuth) and publish listings (Sell Inventory API).

Needs the same free developer keys as the Browse adapter plus EBAY_RUNAME. The
flow is the one eBay documents:

    consent URL -> /api/ebay/callback -> code exchanged for tokens
    PUT inventory_item -> POST offer -> POST offer/{id}/publish

Each seller uses their own eBay account, business policies and listing allowance;
BookWorm stores only their encrypted refresh token.
"""

from __future__ import annotations

import base64
import hashlib
import html
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_secret_key, get_settings
from app.core.text import strip_control
from app.integrations.http import USER_AGENT
from app.models.ebay import EbayAccount, EbayPublication
from app.models.marketplace import MarketplaceListing
from app.models.user import User
from app.services.uploads import public_url

logger = logging.getLogger("bookworm.ebay.seller")

SCOPES = " ".join((
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
))
_API_HOSTS = {"sandbox": "https://api.sandbox.ebay.com", "production": "https://api.ebay.com"}
_AUTH_HOSTS = {"sandbox": "https://auth.sandbox.ebay.com", "production": "https://auth.ebay.com"}
_SITE_HOSTS = {"EBAY_US": "www.ebay.com", "EBAY_GB": "www.ebay.co.uk", "EBAY_CA": "www.ebay.ca", "EBAY_AU": "www.ebay.com.au",
               "EBAY_DE": "www.ebay.de", "EBAY_FR": "www.ebay.fr", "EBAY_IT": "www.ebay.it", "EBAY_ES": "www.ebay.es"}
MARKETPLACE_CURRENCY = {"EBAY_US": "USD", "EBAY_GB": "GBP", "EBAY_CA": "CAD", "EBAY_AU": "AUD",
                        "EBAY_DE": "EUR", "EBAY_FR": "EUR", "EBAY_IT": "EUR", "EBAY_ES": "EUR"}
_CONTENT_LANGUAGE = {"EBAY_US": "en-US", "EBAY_GB": "en-GB", "EBAY_CA": "en-CA", "EBAY_AU": "en-AU",
                     "EBAY_DE": "de-DE", "EBAY_FR": "fr-FR", "EBAY_IT": "it-IT", "EBAY_ES": "es-ES"}
BOOKS_LEAF_CATEGORY = "261186"
TITLE_LIMIT = 80
# "poor" has no equivalent: eBay's book conditions stop at Acceptable.
CONDITIONS = {"like_new": "LIKE_NEW", "very_good": "USED_VERY_GOOD", "good": "USED_GOOD", "acceptable": "USED_ACCEPTABLE"}
OFFER_EXISTS_ERROR = 25002
TOKEN_SAFETY_SECONDS = 60
POLICIES_HELP_URL = "https://www.bizpolicy.ebay.com/businesspolicy/manage"


class EbaySellerError(Exception):
    """A problem to show the seller as-is. `status` is the HTTP code our API responds with."""

    def __init__(self, message: str, status: int = 502, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.field = field


# -------------------------------------------------------------------- crypto
def _fernet() -> Fernet:
    digest = hashlib.sha256(get_secret_key(get_settings()).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def _decrypt(text: str) -> str:
    return _fernet().decrypt(text.encode()).decode()


# ------------------------------------------------------------------- OAuth
def _api_host() -> str:
    return _API_HOSTS[get_settings().ebay_environment]


def consent_url(state: str) -> str:
    s = get_settings()
    query = urlencode({"client_id": s.ebay_client_id, "redirect_uri": s.ebay_runame, "response_type": "code",
                       "scope": SCOPES, "state": state})
    return f"{_AUTH_HOSTS[s.ebay_environment]}/oauth2/authorize?{query}"


def _token_request(data: dict) -> dict:
    s = get_settings()
    creds = base64.b64encode(f"{s.ebay_client_id}:{s.ebay_client_secret}".encode()).decode()
    try:
        resp = httpx.post(f"{_api_host()}/identity/v1/oauth2/token", data=data, timeout=s.external_http_timeout_seconds,
                          headers={"Authorization": f"Basic {creds}", "User-Agent": USER_AGENT,
                                   "Content-Type": "application/x-www-form-urlencoded"})
    except httpx.HTTPError as exc:
        raise EbaySellerError("Couldn't reach eBay. Please try again.") from exc
    if resp.status_code != 200:
        logger.warning("ebay token request failed", extra={"data": {"status": resp.status_code}})
        raise EbaySellerError("eBay didn't accept the connection. Please connect your account again.", 409)
    return resp.json()


_access_lock = threading.Lock()
_access_tokens: dict[int, tuple[str, float]] = {}


def connect_account(db: Session, user: User, code: str) -> EbayAccount:
    tokens = _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": get_settings().ebay_runame})
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise EbaySellerError("eBay didn't return a usable authorisation. Please try again.")
    account = db.scalar(select(EbayAccount).where(EbayAccount.user_id == user.id))
    if account is None:
        account = EbayAccount(user_id=user.id, environment=get_settings().ebay_environment, refresh_token_encrypted="")
        db.add(account)
    account.environment = get_settings().ebay_environment
    account.refresh_token_encrypted = _encrypt(refresh)
    lifetime = tokens.get("refresh_token_expires_in")
    account.refresh_token_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(lifetime))) if lifetime else None
    db.commit()
    with _access_lock:
        _access_tokens[user.id] = (tokens["access_token"], time.time() + int(tokens.get("expires_in", 7200)))
    return account


def get_account(db: Session, user_id: int) -> EbayAccount | None:
    return db.scalar(select(EbayAccount).where(EbayAccount.user_id == user_id))


def _access_token(account: EbayAccount) -> str:
    with _access_lock:
        cached = _access_tokens.get(account.user_id)
    if cached and time.time() < cached[1] - TOKEN_SAFETY_SECONDS:
        return cached[0]
    try:
        refresh = _decrypt(account.refresh_token_encrypted)
    except InvalidToken as exc:  # APP_SECRET_KEY was rotated
        raise EbaySellerError("Your eBay connection has expired. Please connect your account again.", 409) from exc
    tokens = _token_request({"grant_type": "refresh_token", "refresh_token": refresh, "scope": SCOPES})
    token, expires = tokens["access_token"], time.time() + int(tokens.get("expires_in", 7200))
    with _access_lock:
        _access_tokens[account.user_id] = (token, expires)
    return token


def forget_access_token(user_id: int) -> None:
    with _access_lock:
        _access_tokens.pop(user_id, None)


# ------------------------------------------------------------------ requests
def _error_details(resp: httpx.Response) -> tuple[str | None, int | None, list[dict]]:
    try:
        errors = resp.json().get("errors") or []
    except (ValueError, AttributeError):
        return None, None, []
    if not errors:
        return None, None, []
    first = errors[0]
    text = first.get("longMessage") or first.get("message")
    return (strip_control(text, 400) if text else None), first.get("errorId"), first.get("parameters") or []


def _call(account: EbayAccount, method: str, path: str, *, body: dict | None = None, params: dict | None = None,
          content_language: bool = False, ok: tuple[int, ...] = (200, 201, 204)) -> httpx.Response:
    """Call the seller's eBay account. Only idempotent requests are retried."""
    s = get_settings()
    retriable = method in ("GET", "PUT")
    for attempt in range(2):
        headers = {"Authorization": f"Bearer {_access_token(account)}", "Accept": "application/json", "User-Agent": USER_AGENT,
                   "X-EBAY-C-MARKETPLACE-ID": s.ebay_marketplace_id}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if content_language:
            headers["Content-Language"] = _CONTENT_LANGUAGE.get(s.ebay_marketplace_id, "en-US")
        try:
            resp = httpx.request(method, f"{_api_host()}{path}", json=body, params=params, headers=headers,
                                 timeout=max(s.external_http_timeout_seconds, 15.0))
        except httpx.HTTPError as exc:
            if retriable and attempt == 0:
                time.sleep(0.6)
                continue
            raise EbaySellerError("Couldn't reach eBay. Please try again.") from exc
        if resp.status_code == 401 and attempt == 0:
            forget_access_token(account.user_id)
            continue
        if resp.status_code >= 500 and retriable and attempt == 0:
            time.sleep(0.6)
            continue
        if resp.status_code in ok:
            return resp
        if resp.status_code == 401:
            raise EbaySellerError("Your eBay connection has expired. Please connect your account again.", 409)
        if resp.status_code == 429:
            raise EbaySellerError("eBay is limiting requests right now. Please try again in a few minutes.", 429)
        return resp
    raise EbaySellerError("Couldn't reach eBay. Please try again.")


def _fail(resp: httpx.Response, fallback: str) -> EbaySellerError:
    message, error_id, _ = _error_details(resp)
    logger.warning("ebay seller call failed", extra={"data": {"status": resp.status_code, "error_id": error_id}})
    return EbaySellerError(message or fallback, 502 if resp.status_code >= 500 else 422)


# --------------------------------------------------------------------- setup
@dataclass
class SellerSetup:
    fulfillment_policies: list[dict]
    payment_policies: list[dict]
    return_policies: list[dict]
    locations: list[dict]
    policies_message: str | None = None

    @property
    def ready(self) -> bool:
        return bool(self.fulfillment_policies and self.payment_policies and self.return_policies and self.locations)


def _policies(account: EbayAccount, kind: str, list_key: str, id_key: str) -> tuple[list[dict], bool]:
    resp = _call(account, "GET", f"/sell/account/v1/{kind}", params={"marketplace_id": get_settings().ebay_marketplace_id})
    if resp.status_code != 200:
        return [], False
    return [{"id": str(p[id_key]), "name": strip_control(p.get("name"), 100) or str(p[id_key])}
            for p in resp.json().get(list_key, []) if p.get(id_key)], True


def seller_setup(account: EbayAccount) -> SellerSetup:
    fulfillment, ok1 = _policies(account, "fulfillment_policy", "fulfillmentPolicies", "fulfillmentPolicyId")
    payment, ok2 = _policies(account, "payment_policy", "paymentPolicies", "paymentPolicyId")
    returns, ok3 = _policies(account, "return_policy", "returnPolicies", "returnPolicyId")
    resp = _call(account, "GET", "/sell/inventory/v1/location", params={"limit": "25"})
    locations = []
    if resp.status_code == 200:
        for loc in resp.json().get("locations", []):
            address = (loc.get("location") or {}).get("address") or {}
            label = ", ".join(p for p in (loc.get("name"), address.get("city"), address.get("country")) if p)
            locations.append({"key": loc.get("merchantLocationKey"), "name": strip_control(label, 120) or loc.get("merchantLocationKey")})
    message = None
    if not (ok1 and ok2 and ok3):
        message = "eBay couldn't share your selling policies. Turn on Business Policies in your eBay account, then try again."
    elif not (fulfillment and payment and returns):
        message = "Create at least one shipping, payment and return policy in your eBay account, then try again."
    return SellerSetup(fulfillment, payment, returns, locations, message)


def create_location(account: EbayAccount, user_id: int, *, city: str, state: str, postal_code: str, country: str) -> str:
    key = f"bookworm-{user_id}"
    resp = _call(account, "POST", f"/sell/inventory/v1/location/{key}", body={
        "name": "BookWorm shipping location", "merchantLocationStatus": "ENABLED", "merchantLocationTypes": ["WAREHOUSE"],
        "location": {"address": {"city": city, "stateOrProvince": state, "postalCode": postal_code, "country": country}},
    })
    if resp.status_code not in (200, 201, 204):
        raise _fail(resp, "eBay couldn't save that location. Please check the address.")
    return key


# ------------------------------------------------------------------ publish
def _photo_urls(listing: MarketplaceListing) -> list[str]:
    s = get_settings()
    base = (s.public_base_url or next((o for o in s.cors_origins if o.startswith("https://")), "")).rstrip("/")
    urls = []
    for image in listing.images:
        url = public_url(image.path) or ""
        if url.startswith("/") and base:
            url = f"{base}{url}"
        if url.startswith("https://"):
            urls.append(url)
    if not urls and listing.book and (listing.book.cover_url or "").startswith("https://"):
        urls.append(listing.book.cover_url)
    return urls[:12]


def _inventory_item(listing: MarketplaceListing, language: str, photos: list[str]) -> dict:
    description = listing.description or listing.title
    title = listing.title[:TITLE_LIMIT]
    product: dict = {"title": title, "description": html.escape(description), "imageUrls": photos,
                     "aspects": {"Book Title": [title[:65]], "Author": [listing.author[:65]], "Language": [language]}}
    if listing.isbn:
        product["isbn"] = [listing.isbn]
    if listing.published_year:
        product["aspects"]["Publication Year"] = [str(listing.published_year)]
    if listing.edition_text:
        product["aspects"]["Edition"] = [listing.edition_text[:65]]
    return {"product": product, "condition": CONDITIONS[listing.condition],
            "conditionDescription": strip_control(description, 1000),
            "availability": {"shipToLocationAvailability": {"quantity": 1}}}


@dataclass
class PublishRequest:
    price: Decimal
    fulfillment_policy_id: str
    payment_policy_id: str
    return_policy_id: str
    merchant_location_key: str
    language: str = "English"


def _offer(listing: MarketplaceListing, sku: str, req: PublishRequest, currency: str) -> dict:
    s = get_settings()
    return {
        "sku": sku, "marketplaceId": s.ebay_marketplace_id, "format": "FIXED_PRICE", "availableQuantity": 1,
        "categoryId": BOOKS_LEAF_CATEGORY, "listingDescription": html.escape(listing.description or listing.title),
        "merchantLocationKey": req.merchant_location_key,
        "listingPolicies": {"fulfillmentPolicyId": req.fulfillment_policy_id, "paymentPolicyId": req.payment_policy_id,
                            "returnPolicyId": req.return_policy_id},
        "pricingSummary": {"price": {"value": f"{req.price:.2f}", "currency": currency}},
    }


def listing_url(ebay_listing_id: str) -> str:
    s = get_settings()
    host = "www.sandbox.ebay.com" if s.ebay_environment == "sandbox" else _SITE_HOSTS.get(s.ebay_marketplace_id, "www.ebay.com")
    return f"https://{host}/itm/{ebay_listing_id}"


def get_publication(db: Session, listing_id: int) -> EbayPublication | None:
    return db.scalar(select(EbayPublication).where(EbayPublication.listing_id == listing_id))


def publish(db: Session, user: User, listing: MarketplaceListing, req: PublishRequest) -> EbayPublication:
    """Create or update the eBay listing. Each step is saved, so a retry resumes rather than duplicates."""
    if listing.status != "active":
        raise EbaySellerError("Only active listings can be published to eBay.", 409)
    if listing.condition not in CONDITIONS:
        raise EbaySellerError("eBay doesn't accept books in Poor condition.", 422, "condition")
    if not listing.description:
        raise EbaySellerError("Add a description of your copy first.", 422, "description")
    photos = _photo_urls(listing)
    if not photos:
        raise EbaySellerError("eBay needs at least one photo it can load. Add a photo to this listing first.", 422, "photos")
    account = get_account(db, user.id)
    if account is None:
        raise EbaySellerError("Connect your eBay account first.", 409)
    currency = MARKETPLACE_CURRENCY.get(get_settings().ebay_marketplace_id, "USD")

    pub = get_publication(db, listing.id)
    if pub is None:
        pub = EbayPublication(listing_id=listing.id, user_id=user.id, sku=f"bookworm-{listing.id}")
        db.add(pub)
    try:
        resp = _call(account, "PUT", f"/sell/inventory/v1/inventory_item/{pub.sku}",
                     body=_inventory_item(listing, req.language, photos), content_language=True)
        if resp.status_code not in (200, 201, 204):
            raise _fail(resp, "eBay rejected the book details.")

        offer = _offer(listing, pub.sku, req, currency)
        if pub.offer_id:
            resp = _call(account, "PUT", f"/sell/inventory/v1/offer/{pub.offer_id}", body=offer, content_language=True)
            if resp.status_code not in (200, 201, 204):
                raise _fail(resp, "eBay rejected the updated offer.")
        else:
            resp = _call(account, "POST", "/sell/inventory/v1/offer", body=offer, content_language=True)
            if resp.status_code in (200, 201):
                pub.offer_id = str(resp.json()["offerId"])
            else:
                _, error_id, params = _error_details(resp)
                existing = next((p.get("value") for p in params if p.get("name") == "offerId"), None)
                if error_id != OFFER_EXISTS_ERROR or not existing:
                    raise _fail(resp, "eBay rejected the offer.")
                pub.offer_id = str(existing)
            db.commit()

        if pub.status != "published":
            resp = _call(account, "POST", f"/sell/inventory/v1/offer/{pub.offer_id}/publish")
            if resp.status_code != 200:
                raise _fail(resp, "eBay couldn't publish this listing.")
            pub.ebay_listing_id = str(resp.json()["listingId"])
            pub.url = listing_url(pub.ebay_listing_id)
            pub.status = "published"
            pub.published_at = datetime.now(timezone.utc)
    except EbaySellerError as exc:
        pub.last_error = exc.message[:500]
        db.commit()
        raise
    pub.price_amount, pub.currency, pub.last_error = req.price, currency, None
    db.commit()
    return pub


def end(db: Session, pub: EbayPublication) -> EbayPublication:
    account = get_account(db, pub.user_id)
    if account is None:
        raise EbaySellerError("Connect your eBay account first.", 409)
    resp = _call(account, "POST", f"/sell/inventory/v1/offer/{pub.offer_id}/withdraw")
    if resp.status_code != 200:
        error = _fail(resp, "eBay couldn't end this listing.")
        pub.last_error = error.message[:500]
        db.commit()
        raise error
    pub.status, pub.last_error = "ended", None
    db.commit()
    return pub


def end_if_live(db: Session, listing: MarketplaceListing) -> None:
    """A copy sold or hidden here must not stay for sale on eBay. Failures are recorded, never fatal."""
    if not get_settings().ebay_seller_configured:
        return
    pub = get_publication(db, listing.id)
    if pub is None or pub.status != "published":
        return
    try:
        end(db, pub)
    except EbaySellerError:
        logger.warning("could not end eBay listing automatically", extra={"data": {"listing_id": listing.id}})
