"""eBay integration endpoints: account-deletion webhook, seller market check and seller tools.

Marketplace Account Deletion: eBay requires every application with a production
keyset to accept these notifications or claim an exemption. BookWorm caches eBay
listings (with the seller's username) for price comparables, so it accepts them:

* GET  ?challenge_code=...  -> {"challengeResponse": sha256(code + token + endpoint)}
* POST notification         -> 204, and that seller's cached listings are deleted.

Configure EBAY_VERIFICATION_TOKEN and EBAY_DELETION_ENDPOINT (the exact public URL
registered in the eBay developer portal). See docs/DEPLOYMENT.md.
"""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import forbidden, not_found
from app.core.logging import log_event
from app.core.ratelimit import rate_limit
from app.db.session import get_db
from app.integrations import ebay as browse
from app.integrations import ebay_seller as seller
from app.integrations.http import ProviderError
from app.marketplace.identify import identify
from app.marketplace.pricing import estimate_price
from app.marketplace.validate import validate_and_dedupe
from app.models.ebay import EbayPublication
from app.models.marketplace import CachedExternalListing, MarketplaceListing
from app.models.user import User
from app.schemas.marketplace import Condition
from app.security.deps import get_current_user, get_current_user_optional
from app.security.tokens import create_purpose_token, decode_purpose_token

logger = logging.getLogger("bookworm.ebay")

router = APIRouter(prefix="/ebay", tags=["ebay"], include_in_schema=False)

CONNECT_PURPOSE = "ebay_connect"
CONNECT_MINUTES = 10
MARKET_CHECK_ITEMS = 8


def challenge_response(code: str, token: str, endpoint: str) -> str:
    return hashlib.sha256((code + token + endpoint).encode("utf-8")).hexdigest()


@router.get("/account-deletion")
def deletion_challenge(challenge_code: str = ""):
    s = get_settings()
    if not s.ebay_deletion_configured:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    if not challenge_code:
        return JSONResponse(status_code=400, content={"detail": "challenge_code is required"})
    return {"challengeResponse": challenge_response(challenge_code, s.ebay_verification_token,
                                                     s.ebay_deletion_endpoint)}


@router.post("/account-deletion", status_code=204)
async def deletion_notification(request: Request, db: Session = Depends(get_db)):
    if not get_settings().ebay_deletion_configured:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    try:
        body = await request.json()
        data = (body.get("notification") or {}).get("data") or {}
    except (ValueError, AttributeError):
        data = {}
    names = {str(v) for v in (data.get("username"), data.get("userId")) if v}
    removed = 0
    if names:
        rows = db.execute(select(CachedExternalListing.id, CachedExternalListing.payload)
                          .where(CachedExternalListing.provider == "ebay")).all()
        ids = [i for i, p in rows if isinstance(p, dict) and p.get("seller_name") in names]
        if ids:
            removed = db.execute(delete(CachedExternalListing).where(CachedExternalListing.id.in_(ids))).rowcount
            db.commit()
    # Acknowledge every notification (eBay re-sends unacknowledged ones); log no personal data.
    log_event(logger, "ebay account deletion processed", removed_listings=removed)
    return Response(status_code=204)


# ------------------------------------------------------------- seller status
def _seller_error(exc: seller.EbaySellerError) -> HTTPException:
    if exc.field:
        return HTTPException(status_code=exc.status, detail={"message": exc.message, "field": exc.field})
    return HTTPException(status_code=exc.status, detail=exc.message)


def _require_seller_tools() -> None:
    if not get_settings().ebay_seller_configured:
        raise HTTPException(status_code=404, detail="Not found")


def _publication_out(pub: EbayPublication) -> dict:
    return {"listing_id": pub.listing_id, "status": pub.status, "url": pub.url, "price_amount": float(pub.price_amount) if pub.price_amount else None,
            "currency": pub.currency, "last_error": pub.last_error, "published_at": pub.published_at}


@router.get("/status")
def status(user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    """Which eBay features this site can offer, so the seller area only shows what really works."""
    s = get_settings()
    account = seller.get_account(db, user.id) if user and s.ebay_seller_configured else None
    publications: list[dict] = []
    if account:
        publications = [_publication_out(p) for p in db.scalars(select(EbayPublication).where(EbayPublication.user_id == account.user_id))]
    return {
        "market_check": s.ebay_configured,
        "seller_tools": s.ebay_seller_configured,
        "connected": account is not None,
        "test_environment": s.ebay_environment == "sandbox",
        "marketplace": s.ebay_marketplace_id,
        "currency": seller.MARKETPLACE_CURRENCY.get(s.ebay_marketplace_id, "USD"),
        "publications": publications,
    }


# -------------------------------------------------------------- market check
@router.get("/market-check", dependencies=[Depends(rate_limit("ebay_market_check", 20, 60))])
def market_check(title: str = Query(..., min_length=1, max_length=300), author: str | None = Query(None, max_length=200),
                 isbn: str | None = Query(None, max_length=20), condition: Condition = "good",
                 _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What this book is listed for on eBay right now. Runs only when a seller asks for it, and is cached."""
    s = get_settings()
    if not s.ebay_configured:
        raise HTTPException(status_code=404, detail="Not found")
    book = identify(db, isbn=isbn, title=title, author=author, allow_network=False)
    try:
        found = browse.search(" ".join(p for p in (book.title or title, author) if p), isbn=book.requested_isbn, limit=30, db=db)
    except ProviderError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(status_code=503, detail="eBay prices aren't available right now. Please try again later.", headers=headers)
    kept, _excluded = validate_and_dedupe(found, book)
    currency = seller.MARKETPLACE_CURRENCY.get(s.ebay_marketplace_id, "USD")
    estimate = estimate_price(kept, currency, condition)
    priced = sorted((k for k in kept if k.price is not None and k.currency == currency), key=lambda k: k.price)
    return {
        "currency": currency,
        "test_environment": s.ebay_environment == "sandbox",
        "total_found": len(kept),
        "estimate": estimate.to_dict(),
        "lowest": priced[0].price if priced else None,
        "items": [{"title": k.title, "price": k.price, "currency": k.currency, "condition": k.condition,
                   "shipping_cost": k.shipping_cost, "shipping_known": k.shipping_known, "url": k.url, "image_url": k.image_url,
                   "location": k.location, "country": k.country} for k in priced[:MARKET_CHECK_ITEMS]],
    }


# -------------------------------------------------------------- connect flow
def _return_url(result: str) -> str:
    s = get_settings()
    base = s.public_base_url.rstrip("/") or ("" if s.is_production else (s.cors_origins or [""])[0].rstrip("/"))
    return f"{base}/seller?tab=ebay&ebay={result}"


@router.get("/connect", dependencies=[Depends(_require_seller_tools)])
def connect(user: User = Depends(get_current_user)):
    state = create_purpose_token(str(user.id), CONNECT_PURPOSE, get_settings(), minutes=CONNECT_MINUTES)
    return {"url": seller.consent_url(state)}


@router.get("/callback", dependencies=[Depends(_require_seller_tools)])
def callback(code: str | None = None, state: str | None = None, user: User | None = Depends(get_current_user_optional),
             db: Session = Depends(get_db)):
    """eBay sends the seller back here. The signed state must belong to the person who started the flow."""
    payload = decode_purpose_token(state or "", CONNECT_PURPOSE, get_settings())
    if not code or not payload or user is None or payload.get("sub") != str(user.id):
        return RedirectResponse(_return_url("denied"), status_code=303)
    try:
        seller.connect_account(db, user, code)
    except seller.EbaySellerError:
        return RedirectResponse(_return_url("failed"), status_code=303)
    return RedirectResponse(_return_url("connected"), status_code=303)


def _live_count(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count(EbayPublication.id)).where(EbayPublication.user_id == user_id,
                                                                  EbayPublication.status == "published")) or 0


@router.delete("/account", status_code=204, dependencies=[Depends(_require_seller_tools)])
def disconnect(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = seller.get_account(db, user.id)
    if account is None:
        return Response(status_code=204)
    live = _live_count(db, user.id)
    if live:
        raise HTTPException(status_code=409, detail=f"End your {live} live eBay listing{'' if live == 1 else 's'} first, so nothing is left for sale without a connection.")
    db.delete(account)
    db.commit()
    seller.forget_access_token(user.id)
    return Response(status_code=204)


# ------------------------------------------------------------------ publish
def _connected(db: Session, user: User):
    account = seller.get_account(db, user.id)
    if account is None:
        raise HTTPException(status_code=409, detail="Connect your eBay account first.")
    return account


@router.get("/seller/setup", dependencies=[Depends(_require_seller_tools), Depends(rate_limit("ebay_setup", 20, 60))])
def setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        data = seller.seller_setup(_connected(db, user))
    except seller.EbaySellerError as exc:
        raise _seller_error(exc)
    return {"fulfillment_policies": data.fulfillment_policies, "payment_policies": data.payment_policies,
            "return_policies": data.return_policies, "locations": data.locations, "ready": data.ready,
            "message": data.policies_message, "help_url": seller.POLICIES_HELP_URL}


class LocationIn(BaseModel):
    city: str = Field(min_length=2, max_length=60)
    state: str = Field(min_length=2, max_length=60)
    postal_code: str = Field(min_length=3, max_length=12, pattern=r"^[A-Za-z0-9 -]+$")
    country: str = Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")

    @field_validator("city", "state", "postal_code", mode="before")
    @classmethod
    def _trim(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("country")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


@router.post("/seller/location", status_code=201, dependencies=[Depends(_require_seller_tools), Depends(rate_limit("ebay_write", 30, 3600))])
def add_location(body: LocationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        key = seller.create_location(_connected(db, user), user.id, city=body.city, state=body.state,
                                     postal_code=body.postal_code, country=body.country)
    except seller.EbaySellerError as exc:
        raise _seller_error(exc)
    return {"key": key, "name": f"{body.city}, {body.country}"}


POLICY_ID = r"^[A-Za-z0-9_-]{1,64}$"


class PublishIn(BaseModel):
    price: Decimal = Field(ge=Decimal("0.99"), le=Decimal("100000"), decimal_places=2)
    fulfillment_policy_id: str = Field(pattern=POLICY_ID)
    payment_policy_id: str = Field(pattern=POLICY_ID)
    return_policy_id: str = Field(pattern=POLICY_ID)
    merchant_location_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,36}$")
    language: Literal["English", "Hindi", "Bengali", "Tamil", "Spanish", "French", "German"] = "English"


def _owned_listing(db: Session, listing_id: int, user: User) -> MarketplaceListing:
    listing = db.get(MarketplaceListing, listing_id)
    if not listing:
        raise not_found("Listing")
    if listing.seller_id != user.id:
        raise forbidden("You can only manage your own listings")
    return listing


@router.post("/listings/{listing_id}/publish", dependencies=[Depends(_require_seller_tools), Depends(rate_limit("ebay_write", 30, 3600))])
def publish_listing(listing_id: int, body: PublishIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    listing = _owned_listing(db, listing_id, user)
    try:
        pub = seller.publish(db, user, listing, seller.PublishRequest(
            price=body.price, fulfillment_policy_id=body.fulfillment_policy_id, payment_policy_id=body.payment_policy_id,
            return_policy_id=body.return_policy_id, merchant_location_key=body.merchant_location_key, language=body.language))
    except seller.EbaySellerError as exc:
        raise _seller_error(exc)
    return _publication_out(pub)


@router.post("/listings/{listing_id}/end", dependencies=[Depends(_require_seller_tools), Depends(rate_limit("ebay_write", 30, 3600))])
def end_listing(listing_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    listing = _owned_listing(db, listing_id, user)
    pub = seller.get_publication(db, listing.id)
    if pub is None or pub.status != "published":
        raise HTTPException(status_code=409, detail="This listing isn't live on eBay.")
    try:
        return _publication_out(seller.end(db, pub))
    except seller.EbaySellerError as exc:
        raise _seller_error(exc)
