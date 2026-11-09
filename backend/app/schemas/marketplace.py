from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.text import to_isbn13

Condition = Literal["like_new", "very_good", "good", "acceptable", "poor"]
Delivery = Literal["pickup", "shipping", "both"]
SUPPORTED_CURRENCIES = ("INR", "USD", "EUR", "GBP")
MIN_PRICE = Decimal("1")
MAX_PRICE = Decimal("1000000")
MAX_SHIPPING = Decimal("100000")
MIN_DESCRIPTION = 10
_HAS_TEXT = re.compile(r"[^\W_]")
_SINGLE_LINE_FIELDS = ("title", "author", "edition_text", "location_city")
_NOT_NULLABLE = ("title", "author", "description", "condition", "price_amount", "currency", "delivery")


def validate_isbn(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    isbn = to_isbn13(v)
    if not isbn:
        raise ValueError("ISBN is not valid (check the digits)")
    return isbn


def validate_currency(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.upper()
    if v not in SUPPORTED_CURRENCIES:
        raise ValueError(f"currency must be one of {', '.join(SUPPORTED_CURRENCIES)}")
    return v


def _collapse_spaces(v):
    return " ".join(v.split()) if isinstance(v, str) else v


def _trim(v):
    return v.strip() if isinstance(v, str) else v


def _empty_to_none(v: str | None) -> str | None:
    return v or None


def _must_have_text(v: str | None) -> str | None:
    if v is not None and not _HAS_TEXT.search(v):
        raise ValueError("Enter real text, not just symbols")
    return v


def validate_year(v: int | None) -> int | None:
    if v is not None and v > datetime.now(timezone.utc).year + 1:
        raise ValueError("Publication year can't be in the future")
    return v


class ListingBase(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(min_length=1, max_length=200)
    isbn: str | None = Field(default=None, max_length=20)
    edition_text: str | None = Field(default=None, max_length=100)
    published_year: int | None = Field(default=None, ge=1450)
    description: str = Field(min_length=MIN_DESCRIPTION, max_length=3000)
    condition: Condition
    price_amount: Decimal = Field(ge=MIN_PRICE, le=MAX_PRICE, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    shipping_cost: Decimal | None = Field(default=None, ge=0, le=MAX_SHIPPING, decimal_places=2)
    delivery: Delivery = "pickup"
    location_city: str | None = Field(default=None, max_length=80)
    location_public: bool = True
    allow_inquiries: bool = True
    book_id: int | None = None

    _isbn = field_validator("isbn")(validate_isbn)
    _currency = field_validator("currency")(validate_currency)
    _year = field_validator("published_year")(validate_year)
    _spaces = field_validator(*_SINGLE_LINE_FIELDS, mode="before")(_collapse_spaces)
    _description = field_validator("description", mode="before")(_trim)
    _text = field_validator("title", "author", "location_city", "description")(_must_have_text)
    _blank_optional = field_validator("edition_text", "location_city")(_empty_to_none)

    @model_validator(mode="after")
    def _shipping(self):
        if self.delivery == "pickup" and self.shipping_cost:
            raise ValueError("Shipping cost only applies when shipping is offered")
        return self


class ListingCreate(ListingBase):
    pass


class ListingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    author: str | None = Field(default=None, min_length=1, max_length=200)
    isbn: str | None = Field(default=None, max_length=20)
    edition_text: str | None = Field(default=None, max_length=100)
    published_year: int | None = Field(default=None, ge=1450)
    description: str | None = Field(default=None, min_length=MIN_DESCRIPTION, max_length=3000)
    condition: Condition | None = None
    price_amount: Decimal | None = Field(default=None, ge=MIN_PRICE, le=MAX_PRICE, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    shipping_cost: Decimal | None = Field(default=None, ge=0, le=MAX_SHIPPING, decimal_places=2)
    delivery: Delivery | None = None
    location_city: str | None = Field(default=None, max_length=80)
    location_public: bool | None = None
    allow_inquiries: bool | None = None
    status: Literal["active", "inactive"] | None = None
    book_id: int | None = None

    _isbn = field_validator("isbn")(validate_isbn)
    _currency = field_validator("currency")(validate_currency)
    _year = field_validator("published_year")(validate_year)
    _spaces = field_validator(*_SINGLE_LINE_FIELDS, mode="before")(_collapse_spaces)
    _description = field_validator("description", mode="before")(_trim)
    _text = field_validator("title", "author", "location_city", "description")(_must_have_text)
    _blank_optional = field_validator("edition_text", "location_city")(_empty_to_none)

    @model_validator(mode="after")
    def _required_stay_set(self):
        for name in _NOT_NULLABLE:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name.replace('_', ' ').capitalize()} can't be empty")
        return self


class ListingImageOut(BaseModel):
    id: int
    url: str


class SellerMini(BaseModel):
    id: int
    display_name: str
    member_since: datetime
    completed_sales: int
    is_demo: bool


class ListingOut(BaseModel):
    id: int
    book_id: int | None
    title: str
    author: str
    isbn: str | None
    edition_text: str | None
    published_year: int | None
    description: str | None
    condition: str
    condition_label: str
    price_amount: float
    currency: str
    shipping_cost: float | None
    shipping_known: bool
    total_known_cost: float
    total_cost_complete: bool
    delivery: str
    location_city: str | None
    allow_inquiries: bool
    status: str
    is_sample: bool
    images: list[ListingImageOut]
    cover_url: str | None
    seller: SellerMini
    created_at: datetime
    updated_at: datetime
    sold_at: datetime | None
    is_mine: bool = False
    is_favorite: bool = False
    # Owner-only fields
    view_count: int | None = None
    inquiry_count: int | None = None
    favorite_count: int | None = None
    location_public: bool | None = None
    moderation_note: str | None = None


class InquiryIn(BaseModel):
    message: str = Field(min_length=5, max_length=1500)


class InquiryReplyIn(BaseModel):
    reply: str = Field(min_length=1, max_length=1500)
    close: bool = False


class EstimateIn(BaseModel):
    isbn: str | None = Field(default=None, max_length=20)
    title: str | None = Field(default=None, max_length=300)
    author: str | None = Field(default=None, max_length=200)
    condition: Condition | Literal["new"] | None = "good"
    asking_price: float | None = Field(default=None, gt=0, le=1_000_000)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    new_price_reference: float | None = Field(default=None, gt=0, le=1_000_000,
                                              description="Optional new-copy price you have seen (used only as a labelled fallback)")
    exclude_listing_id: int | None = None

    @model_validator(mode="after")
    def _need_identity(self):
        if not (self.isbn or self.title):
            raise ValueError("Provide an ISBN or a title")
        self.currency = self.currency.upper()
        return self


class UsedSearchIn(BaseModel):
    query: str | None = Field(default=None, max_length=500, description="Free text, e.g. 'good copy of Atomic Habits under 250 rupees'")
    title: str | None = Field(default=None, max_length=300)
    author: str | None = Field(default=None, max_length=200)
    isbn: str | None = Field(default=None, max_length=20)
    edition: str | None = Field(default=None, max_length=100)
    max_price: float | None = Field(default=None, gt=0, le=1_000_000)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    min_condition: Condition | None = None
    location: str | None = Field(default=None, max_length=80)
    delivery: Literal["pickup", "shipping", "any"] = "any"
    include_external: bool = True

    @model_validator(mode="after")
    def _need_something(self):
        if not any([self.query, self.title, self.isbn]):
            raise ValueError("Describe the book you want (query, title or ISBN)")
        self.currency = self.currency.upper()
        return self


class CompareListingsIn(BaseModel):
    listing_ids: list[int] = Field(min_length=2, max_length=10)
