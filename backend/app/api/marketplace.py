from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import forbidden, not_found
from app.core.ratelimit import rate_limit
from app.core.text import normalize_title, strip_control
from app.db.session import get_db
from app.models.book import Book
from app.models.marketplace import (
    ListingFavorite,
    ListingImage,
    ListingInquiry,
    ListingReport,
    MarketplaceListing,
)
from app.models.user import User
from app.schemas.books import ReportIn
from app.schemas.common import Page
from app.schemas.marketplace import (
    Condition,
    InquiryIn,
    InquiryReplyIn,
    ListingCreate,
    ListingOut,
    ListingUpdate,
)
from app.security.deps import get_current_user, get_current_user_optional
from app.services import uploads
from app.services.listings import (
    LISTING_SORTS,
    apply_fields,
    link_to_catalogue,
    listing_out,
    listings_out,
    search_community,
)
from app.services.users import public_seller

router = APIRouter(prefix="/marketplace", tags=["marketplace"])

DISCLAIMER = ("BookWorm does not process payments, hold funds or guarantee transactions, and does not verify every "
              "seller or book. Meet in a safe place or use a trusted delivery method, and inspect the book before paying.")


def _get_listing(db: Session, listing_id: int) -> MarketplaceListing:
    listing = db.get(MarketplaceListing, listing_id)
    if not listing:
        raise not_found("Listing")
    return listing


def _owned(db: Session, listing_id: int, user: User) -> MarketplaceListing:
    listing = _get_listing(db, listing_id)
    if listing.seller_id != user.id:
        # Ownership is enforced here, on the server, for every mutating route.
        raise forbidden("You can only manage your own listings")
    return listing


@router.get("/listings", response_model=Page[ListingOut])
def browse_listings(
    q: str | None = Query(None, max_length=200), isbn: str | None = Query(None, max_length=20),
    book_id: int | None = None, condition: Condition | None = None, min_condition: Condition | None = None,
    max_price: float | None = Query(None, gt=0), currency: str | None = Query(None, min_length=3, max_length=3),
    location: str | None = Query(None, max_length=80),
    delivery: Literal["pickup", "shipping", "any"] = "any", sort: str = "recent",
    page: int = Query(1, ge=1, le=1000), page_size: int = Query(20, ge=1, le=60),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if sort not in LISTING_SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of {', '.join(LISTING_SORTS)}")
    items, total = search_community(
        db, q=q, isbn=isbn, book_id=book_id, condition=condition, min_condition=min_condition, max_price=max_price,
        currency=currency.upper() if currency else None, location=location, delivery=delivery, sort=sort,
        limit=page_size, offset=(page - 1) * page_size,
    )
    return Page(items=listings_out(db, items, user), total=total, page=page, page_size=page_size)


@router.post("/listings", response_model=ListingOut, status_code=201,
             dependencies=[Depends(rate_limit("create_listing", 30, 3600))])
def create_listing(body: ListingCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.book_id and not db.get(Book, body.book_id):
        raise HTTPException(status_code=422, detail="Selected catalogue book does not exist")
    duplicate = db.scalar(select(MarketplaceListing.id).where(
        MarketplaceListing.seller_id == user.id, MarketplaceListing.status == "active",
        MarketplaceListing.normalized_title == normalize_title(body.title),
        MarketplaceListing.condition == body.condition, MarketplaceListing.price_amount == body.price_amount,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail=f"You already have an identical active listing (#{duplicate})")
    data = body.model_dump()
    explicit_book = data.pop("book_id")
    listing = MarketplaceListing(seller_id=user.id, status="active", normalized_title="")
    apply_fields(listing, data)
    if explicit_book:
        listing.book_id = explicit_book
    else:
        link_to_catalogue(db, listing)
    if not listing.location_city and user.profile and user.profile.location_city:
        listing.location_city = user.profile.location_city
    db.add(listing)
    user.is_seller = True
    db.commit()
    db.refresh(listing)
    return listing_out(db, listing, user)


@router.get("/listings/{listing_id}", response_model=dict)
def get_listing(listing_id: int, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    listing = _get_listing(db, listing_id)
    is_owner = bool(user and user.id == listing.seller_id)
    if listing.status == "removed" and not (is_owner or (user and user.is_admin)):
        raise not_found("Listing")
    if not is_owner:
        listing.view_count += 1
        db.commit()
    fav = set()
    if user:
        fav = set(db.scalars(select(ListingFavorite.listing_id).where(ListingFavorite.user_id == user.id,
                                                                      ListingFavorite.listing_id == listing.id)))
    my_inquiries = []
    if user and not is_owner:
        my_inquiries = [_inquiry_out(i, user) for i in db.scalars(select(ListingInquiry).where(
            ListingInquiry.listing_id == listing.id, ListingInquiry.buyer_id == user.id)
            .order_by(ListingInquiry.created_at.desc()))]
    return {"listing": listing_out(db, listing, user, favorites=fav).model_dump(), "my_inquiries": my_inquiries,
            "disclaimer": DISCLAIMER}


@router.get("/listings/{listing_id}/same-book", response_model=list[ListingOut])
def same_book_listings(listing_id: int, user: User | None = Depends(get_current_user_optional),
                       db: Session = Depends(get_db)):
    """Other active listings of the same book, for side-by-side comparison."""
    listing = _get_listing(db, listing_id)
    if listing.isbn:
        items, _ = search_community(db, isbn=listing.isbn, sort="price_asc", limit=20)
    elif listing.book_id:
        items, _ = search_community(db, book_id=listing.book_id, sort="price_asc", limit=20)
    else:
        items = []
    return listings_out(db, [i for i in items if i.id != listing.id], user)


@router.patch("/listings/{listing_id}", response_model=ListingOut)
def update_listing(listing_id: int, body: ListingUpdate, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    listing = _owned(db, listing_id, user)
    if listing.status in ("removed", "sold"):
        raise HTTPException(status_code=409, detail=f"A {listing.status} listing can't be edited")
    data = body.model_dump(exclude_unset=True)
    explicit_book = data.pop("book_id", None)
    merged_delivery = data.get("delivery", listing.delivery)
    if merged_delivery == "pickup" and data.get("shipping_cost"):
        raise HTTPException(status_code=422, detail="Shipping cost only applies when shipping is offered")
    identity_changed = any(k in data for k in ("title", "author", "isbn"))
    apply_fields(listing, data)
    if explicit_book:
        if not db.get(Book, explicit_book):
            raise HTTPException(status_code=422, detail="Selected catalogue book does not exist")
        listing.book_id = explicit_book
    elif identity_changed:
        link_to_catalogue(db, listing)
    db.commit()
    return listing_out(db, listing, user)


@router.delete("/listings/{listing_id}", status_code=204)
def delete_listing(listing_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    listing = _owned(db, listing_id, user)
    paths = [i.path for i in listing.images]
    db.delete(listing)
    db.commit()
    for p in paths:
        uploads.delete_upload(p)


@router.post("/listings/{listing_id}/mark-sold", response_model=ListingOut)
def mark_sold(listing_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    listing = _owned(db, listing_id, user)
    if listing.status == "removed":
        raise HTTPException(status_code=409, detail="This listing was removed by a moderator")
    listing.status = "sold"
    listing.sold_at = datetime.now(timezone.utc)
    db.commit()
    return listing_out(db, listing, user)


@router.post("/listings/{listing_id}/deactivate", response_model=ListingOut)
def deactivate(listing_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    listing = _owned(db, listing_id, user)
    if listing.status != "active":
        raise HTTPException(status_code=409, detail="Only active listings can be deactivated")
    listing.status = "inactive"
    db.commit()
    return listing_out(db, listing, user)


@router.post("/listings/{listing_id}/reactivate", response_model=ListingOut)
def reactivate(listing_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    listing = _owned(db, listing_id, user)
    if listing.status == "removed":
        raise HTTPException(status_code=403, detail="Listings removed by a moderator can't be reactivated")
    if listing.status == "active":
        return listing_out(db, listing, user)
    listing.status = "active"
    listing.sold_at = None
    db.commit()
    return listing_out(db, listing, user)


@router.post("/listings/{listing_id}/images", response_model=ListingOut, status_code=201,
             dependencies=[Depends(rate_limit("upload", 60, 3600))])
async def upload_listing_image(listing_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    listing = _owned(db, listing_id, user)
    limit = get_settings().max_images_per_listing
    if len(listing.images) >= limit:
        raise HTTPException(status_code=409, detail=f"A listing can have at most {limit} photos")
    data = await uploads.read_limited(file)
    path = uploads.save_image(data, "listings")
    listing.images.append(ListingImage(path=path, position=len(listing.images)))
    db.commit()
    db.refresh(listing)
    return listing_out(db, listing, user)


@router.delete("/listings/{listing_id}/images/{image_id}", response_model=ListingOut)
def delete_listing_image(listing_id: int, image_id: int, user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    listing = _owned(db, listing_id, user)
    img = next((i for i in listing.images if i.id == image_id), None)
    if not img:
        raise not_found("Image")
    path = img.path
    listing.images.remove(img)
    db.commit()
    uploads.delete_upload(path)
    db.refresh(listing)
    return listing_out(db, listing, user)


# ------------------------------------------------------------- favourites
@router.post("/listings/{listing_id}/favorite", status_code=204)
def favorite(listing_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    listing = _get_listing(db, listing_id)
    if listing.status == "removed":
        raise not_found("Listing")
    if not db.scalar(select(ListingFavorite.id).where(ListingFavorite.user_id == user.id,
                                                      ListingFavorite.listing_id == listing_id)):
        db.add(ListingFavorite(user_id=user.id, listing_id=listing_id))
        db.commit()


@router.delete("/listings/{listing_id}/favorite", status_code=204)
def unfavorite(listing_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(delete(ListingFavorite).where(ListingFavorite.user_id == user.id, ListingFavorite.listing_id == listing_id))
    db.commit()


@router.get("/favorites", response_model=list[ListingOut])
def my_favorites(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    favs = db.scalars(select(ListingFavorite).where(ListingFavorite.user_id == user.id)
                      .order_by(ListingFavorite.created_at.desc())).unique()
    listings = [f.listing for f in favs if f.listing.status != "removed"]
    return listings_out(db, listings, user)


# --------------------------------------------------------------- inquiries
def _inquiry_out(i: ListingInquiry, viewer: User) -> dict:
    return {
        "id": i.id, "listing_id": i.listing_id, "listing_title": i.listing.title, "listing_status": i.listing.status,
        "buyer": {"id": i.buyer.id, "display_name": i.buyer.display_name},
        "seller": {"id": i.listing.seller.id, "display_name": i.listing.seller.display_name},
        "message": i.message, "seller_reply": i.seller_reply, "replied_at": i.replied_at, "status": i.status,
        "created_at": i.created_at, "role": "seller" if viewer.id == i.listing.seller_id else "buyer",
    }


@router.post("/listings/{listing_id}/inquiries", status_code=201,
             dependencies=[Depends(rate_limit("inquiry", 20, 3600))])
def send_inquiry(listing_id: int, body: InquiryIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    listing = _get_listing(db, listing_id)
    if listing.seller_id == user.id:
        raise HTTPException(status_code=400, detail="You can't send an inquiry about your own listing")
    if listing.status != "active":
        raise HTTPException(status_code=409, detail="This listing is no longer active")
    seller_allows = listing.seller.profile.allow_inquiries if listing.seller.profile else True
    if not listing.allow_inquiries or not seller_allows:
        raise HTTPException(status_code=403, detail="The seller isn't accepting messages for this listing")
    open_count = db.scalar(select(func.count(ListingInquiry.id)).where(
        ListingInquiry.listing_id == listing_id, ListingInquiry.buyer_id == user.id, ListingInquiry.status == "open"))
    if open_count and open_count >= 3:
        raise HTTPException(status_code=429, detail="Please wait for the seller to reply before sending more messages")
    inquiry = ListingInquiry(listing_id=listing_id, buyer_id=user.id, message=strip_control(body.message, 1500))
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    return _inquiry_out(inquiry, user)


@router.get("/inquiries")
def my_inquiries(role: Literal["buyer", "seller"] = "buyer", user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    q = select(ListingInquiry).join(MarketplaceListing, MarketplaceListing.id == ListingInquiry.listing_id)
    q = q.where(ListingInquiry.buyer_id == user.id) if role == "buyer" else q.where(MarketplaceListing.seller_id == user.id)
    return [_inquiry_out(i, user) for i in db.scalars(q.order_by(ListingInquiry.created_at.desc())).unique()]


@router.post("/inquiries/{inquiry_id}/reply")
def reply_inquiry(inquiry_id: int, body: InquiryReplyIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    inquiry = db.get(ListingInquiry, inquiry_id)
    if not inquiry:
        raise not_found("Inquiry")
    if inquiry.listing.seller_id != user.id:
        raise forbidden("Only the seller can reply to this inquiry")
    # The reply (which may include contact details the seller chooses to share) is visible only to this buyer.
    inquiry.seller_reply = strip_control(body.reply, 1500)
    inquiry.replied_at = datetime.now(timezone.utc)
    inquiry.status = "closed" if body.close else "answered"
    db.commit()
    return _inquiry_out(inquiry, user)


# ----------------------------------------------------------------- reports
@router.post("/listings/{listing_id}/report", status_code=201, dependencies=[Depends(rate_limit("report", 20, 3600))])
def report_listing(listing_id: int, body: ReportIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    listing = _get_listing(db, listing_id)
    if listing.seller_id == user.id:
        raise HTTPException(status_code=400, detail="You can't report your own listing")
    if db.scalar(select(ListingReport.id).where(ListingReport.listing_id == listing_id, ListingReport.reporter_id == user.id)):
        raise HTTPException(status_code=409, detail="You have already reported this listing")
    db.add(ListingReport(listing_id=listing_id, reporter_id=user.id, reason=body.reason,
                         details=strip_control(body.details, 500)))
    db.commit()
    return {"detail": "Thanks. A moderator will review this listing."}


# ------------------------------------------------------- sellers & dashboard
@router.get("/sellers/{seller_id}")
def seller_profile(seller_id: int, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    seller = db.get(User, seller_id)
    if not seller or not seller.is_active:
        raise not_found("Seller")
    items, _ = search_community(db, seller_id=seller_id, sort="recent", limit=60)
    return {"seller": public_seller(db, seller).model_dump(), "listings": [i.model_dump() for i in listings_out(db, items, user)]}


@router.get("/seller-dashboard")
def seller_dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items, _ = search_community(db, seller_id=user.id, statuses=("active", "inactive", "sold", "removed"), sort="recent")
    listings = listings_out(db, items, user)
    counts: dict[str, int] = {}
    for lst in listings:
        counts[lst.status] = counts.get(lst.status, 0) + 1
    inquiries = db.scalars(select(ListingInquiry).join(MarketplaceListing).where(MarketplaceListing.seller_id == user.id)
                           .order_by(ListingInquiry.created_at.desc()).limit(50)).unique()
    inq = [_inquiry_out(i, user) for i in inquiries]
    return {
        "listings": [lst.model_dump() for lst in listings],
        "counts": counts,
        "total_views": sum(lst.view_count or 0 for lst in listings),
        "open_inquiries": sum(1 for i in inq if i["status"] == "open"),
        "inquiries": inq,
        "disclaimer": DISCLAIMER,
    }
