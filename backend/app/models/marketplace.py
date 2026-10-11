"""Community marketplace and cached external listings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow
from app.models.book import Book
from app.models.user import User

# Ordered best -> worst. Index is used as an ordinal rank.
CONDITIONS = ("like_new", "very_good", "good", "acceptable", "poor")
CONDITION_LABELS = {
    "like_new": "Like New",
    "very_good": "Very Good",
    "good": "Good",
    "acceptable": "Acceptable",
    "poor": "Poor",
}
LISTING_STATUSES = ("active", "inactive", "sold", "removed")
DELIVERY_OPTIONS = ("pickup", "shipping", "both")


class MarketplaceProvider(Base):
    """Registry of listing sources (community + external adapters)."""

    __tablename__ = "marketplace_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_external: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketplaceListing(TimestampMixin, Base):
    __tablename__ = "marketplace_listings"
    __table_args__ = (
        CheckConstraint("price_amount > 0", name="price_positive"),
        CheckConstraint("shipping_cost IS NULL OR shipping_cost >= 0", name="shipping_nonneg"),
        Index("ix_listing_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"), index=True)
    edition_id: Mapped[int | None] = mapped_column(ForeignKey("book_editions.id", ondelete="SET NULL"))

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(300), index=True, nullable=False)
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    isbn: Mapped[str | None] = mapped_column(String(13), index=True)
    edition_text: Mapped[str | None] = mapped_column(String(100))
    published_year: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    condition: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    shipping_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    delivery: Mapped[str] = mapped_column(String(10), default="pickup", nullable=False)
    location_city: Mapped[str | None] = mapped_column(String(80), index=True)
    location_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_inquiries: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="active", index=True, nullable=False)
    moderation_note: Mapped[str | None] = mapped_column(String(300))
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    seller: Mapped[User] = relationship(lazy="joined")
    book: Mapped[Book | None] = relationship(lazy="joined")
    images: Mapped[list[ListingImage]] = relationship(
        back_populates="listing", cascade="all, delete-orphan", order_by="ListingImage.position", lazy="selectin"
    )


class ListingImage(Base):
    __tablename__ = "listing_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_listings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    path: Mapped[str] = mapped_column(String(255), nullable=False)  # relative to UPLOAD_DIR
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    listing: Mapped[MarketplaceListing] = relationship(back_populates="images")


class ListingFavorite(Base):
    __tablename__ = "listing_favorites"
    __table_args__ = (UniqueConstraint("user_id", "listing_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_listings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    listing: Mapped[MarketplaceListing] = relationship(lazy="joined")


class ListingInquiry(TimestampMixin, Base):
    """A buyer's message to a seller. The seller's reply is only visible to that
    buyer, which is how contact details are shared without being public."""

    __tablename__ = "listing_inquiries"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_listings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    seller_reply: Mapped[str | None] = mapped_column(Text)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), default="open", nullable=False)  # open|answered|closed

    listing: Mapped[MarketplaceListing] = relationship(lazy="joined")
    buyer: Mapped[User] = relationship(lazy="joined")


class ListingReport(Base):
    __tablename__ = "listing_reports"
    __table_args__ = (UniqueConstraint("reporter_id", "listing_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_listings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    listing: Mapped[MarketplaceListing] = relationship(lazy="joined")


class CachedExternalListing(Base):
    """Normalized snapshot of an external (e.g. eBay) listing, kept with its
    provenance so price comparables can cite source + retrieval time."""

    __tablename__ = "cached_external_listings"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    isbn: Mapped[str | None] = mapped_column(String(13), index=True)
    normalized_title: Mapped[str] = mapped_column(String(300), index=True, nullable=False)
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
