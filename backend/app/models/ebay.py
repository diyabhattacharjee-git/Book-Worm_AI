"""A seller's connected eBay account and the listings they published through it."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class EbayAccount(TimestampMixin, Base):
    __tablename__ = "ebay_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    environment: Mapped[str] = mapped_column(String(12), nullable=False)
    # Encrypted with a key derived from APP_SECRET_KEY; the short-lived access token is never stored.
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EbayPublication(TimestampMixin, Base):
    """Where one community listing stands on eBay."""

    __tablename__ = "ebay_publications"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("marketplace_listings.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    offer_id: Mapped[str | None] = mapped_column(String(40))
    ebay_listing_id: Mapped[str | None] = mapped_column(String(40))
    url: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12), default="draft", index=True, nullable=False)  # draft|published|ended
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    last_error: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
