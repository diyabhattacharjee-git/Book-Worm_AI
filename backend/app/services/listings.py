"""Community listing persistence, linking to the catalogue and serialisation."""

from __future__ import annotations

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.text import normalize_title, strip_control, to_isbn13
from app.models.marketplace import (
    CONDITION_LABELS,
    CONDITIONS,
    ListingFavorite,
    ListingInquiry,
    MarketplaceListing,
)
from app.models.user import User
from app.repositories.books import find_by_title
from app.schemas.marketplace import ListingImageOut, ListingOut, SellerMini
from app.services.catalogue import find_book_by_isbn
from app.services.uploads import public_url

LISTING_SORTS = ("recent", "price_asc", "price_desc", "condition", "relevance")


def link_to_catalogue(db: Session, listing: MarketplaceListing) -> None:
    """Attach the catalogue book: exact ISBN first, otherwise a strong title+author match.
    Never links on a weak title match, so different works aren't merged."""
    if listing.isbn:
        book = find_book_by_isbn(db, listing.isbn)
        if book:
            listing.book_id = book.id
            listing.edition_id = next((e.id for e in book.editions if e.isbn13 == listing.isbn), None)
            return
    matches = find_by_title(db, listing.title, listing.author, limit=1)
    if matches and matches[0][1] >= 0.9:
        listing.book_id = matches[0][0].id
        listing.edition_id = None  # edition unknown without an ISBN
    else:
        listing.book_id = None
        listing.edition_id = None


def apply_fields(listing: MarketplaceListing, data: dict) -> None:
    for k, v in data.items():
        if k in ("description",):
            v = strip_control(v, 3000)
        setattr(listing, k, v)
    listing.normalized_title = normalize_title(listing.title)
    if listing.delivery == "pickup":
        listing.shipping_cost = None


def seller_sales(db: Session, seller_ids: list[int]) -> dict[int, int]:
    if not seller_ids:
        return {}
    rows = db.execute(select(MarketplaceListing.seller_id, func.count(MarketplaceListing.id))
                      .where(MarketplaceListing.seller_id.in_(seller_ids), MarketplaceListing.status == "sold")
                      .group_by(MarketplaceListing.seller_id)).all()
    return {sid: int(c) for sid, c in rows}


def listing_out(db: Session, listing: MarketplaceListing, viewer: User | None, *, sales: dict[int, int] | None = None,
                favorites: set[int] | None = None) -> ListingOut:
    is_owner = bool(viewer and viewer.id == listing.seller_id)
    is_admin = bool(viewer and viewer.is_admin)
    sales = sales if sales is not None else seller_sales(db, [listing.seller_id])
    price = float(listing.price_amount)
    ship_known = listing.delivery == "pickup" or listing.shipping_cost is not None
    ship = 0.0 if listing.delivery == "pickup" else (float(listing.shipping_cost) if listing.shipping_cost is not None else None)
    out = ListingOut(
        id=listing.id, book_id=listing.book_id, title=listing.title, author=listing.author, isbn=listing.isbn,
        edition_text=listing.edition_text, published_year=listing.published_year, description=listing.description,
        condition=listing.condition, condition_label=CONDITION_LABELS.get(listing.condition, listing.condition),
        price_amount=price, currency=listing.currency, shipping_cost=ship, shipping_known=ship_known,
        total_known_cost=price + (ship or 0.0), total_cost_complete=ship_known, delivery=listing.delivery,
        location_city=listing.location_city if (listing.location_public or is_owner or is_admin) else None,
        allow_inquiries=listing.allow_inquiries, status=listing.status, is_sample=listing.is_sample,
        images=[ListingImageOut(id=i.id, url=public_url(i.path)) for i in listing.images],
        cover_url=listing.book.cover_url if listing.book else None,
        seller=SellerMini(id=listing.seller.id, display_name=listing.seller.display_name,
                          member_since=listing.seller.created_at, completed_sales=sales.get(listing.seller_id, 0),
                          is_demo=listing.seller.is_demo),
        created_at=listing.created_at, updated_at=listing.updated_at, sold_at=listing.sold_at,
        is_mine=is_owner, is_favorite=bool(favorites and listing.id in favorites),
    )
    if is_owner or is_admin:
        out.view_count = listing.view_count
        out.inquiry_count = db.scalar(select(func.count(ListingInquiry.id)).where(ListingInquiry.listing_id == listing.id))
        out.favorite_count = db.scalar(select(func.count(ListingFavorite.id)).where(ListingFavorite.listing_id == listing.id))
        out.location_public = listing.location_public
        out.moderation_note = listing.moderation_note
    return out


def listings_out(db: Session, listings: list[MarketplaceListing], viewer: User | None) -> list[ListingOut]:
    sales = seller_sales(db, list({lst.seller_id for lst in listings}))
    favs: set[int] = set()
    if viewer and listings:
        favs = set(db.scalars(select(ListingFavorite.listing_id).where(
            ListingFavorite.user_id == viewer.id, ListingFavorite.listing_id.in_([lst.id for lst in listings]))))
    return [listing_out(db, lst, viewer, sales=sales, favorites=favs) for lst in listings]


def search_community(db: Session, *, q: str | None = None, isbn: str | None = None, book_id: int | None = None,
                     condition: str | None = None, min_condition: str | None = None, max_price: float | None = None,
                     currency: str | None = None, location: str | None = None, delivery: str | None = None,
                     seller_id: int | None = None, statuses: tuple[str, ...] = ("active",), sort: str = "recent",
                     limit: int | None = None, offset: int = 0) -> tuple[list[MarketplaceListing], int]:
    stmt = select(MarketplaceListing).where(MarketplaceListing.status.in_(statuses))
    isbn13 = to_isbn13(isbn) if isbn else (to_isbn13(q) if q else None)
    if isbn13:
        stmt = stmt.where(MarketplaceListing.isbn == isbn13)
    elif q:
        nq = normalize_title(q)
        toks = [t for t in nq.split() if len(t) > 1][:6]
        conds = [MarketplaceListing.normalized_title.ilike(f"%{nq}%")]
        if toks:
            conds.append(and_(*[or_(MarketplaceListing.normalized_title.ilike(f"%{t}%"),
                                    MarketplaceListing.author.ilike(f"%{t}%")) for t in toks]))
        stmt = stmt.where(or_(*conds))
    if book_id:
        stmt = stmt.where(MarketplaceListing.book_id == book_id)
    if condition:
        stmt = stmt.where(MarketplaceListing.condition == condition)
    if min_condition and min_condition in CONDITIONS:
        ok = CONDITIONS[: CONDITIONS.index(min_condition) + 1]
        stmt = stmt.where(MarketplaceListing.condition.in_(ok))
    if max_price:
        stmt = stmt.where(MarketplaceListing.price_amount <= max_price)
    if currency:
        stmt = stmt.where(MarketplaceListing.currency == currency)
    if location:
        stmt = stmt.where(MarketplaceListing.location_city.ilike(f"%{location.strip()}%"),
                          MarketplaceListing.location_public.is_(True))
    if delivery == "shipping":
        stmt = stmt.where(MarketplaceListing.delivery.in_(("shipping", "both")))
    elif delivery == "pickup":
        stmt = stmt.where(MarketplaceListing.delivery.in_(("pickup", "both")))
    if seller_id:
        stmt = stmt.where(MarketplaceListing.seller_id == seller_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = {
        "recent": (MarketplaceListing.created_at.desc(),),
        "price_asc": (MarketplaceListing.price_amount.asc(),),
        "price_desc": (MarketplaceListing.price_amount.desc(),),
        "condition": (MarketplaceListing.condition.asc(), MarketplaceListing.price_amount.asc()),
        "relevance": (MarketplaceListing.created_at.desc(),),
    }.get(sort, (MarketplaceListing.created_at.desc(),))
    if sort == "condition":
        rank = case({c: i for i, c in enumerate(CONDITIONS)}, value=MarketplaceListing.condition, else_=99)
        order = (rank.asc(), MarketplaceListing.price_amount.asc())
    stmt = stmt.order_by(*order).offset(offset)
    if limit:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).unique()), total

