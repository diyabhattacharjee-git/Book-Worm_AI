from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RatingSummary(BaseModel):
    app_average: float | None
    app_count: int
    app_demo_count: int = 0
    external_average: float | None
    external_count: int | None
    external_source: str | None


class BookSummary(BaseModel):
    id: int
    title: str
    subtitle: str | None
    authors: list[str]
    cover_url: str | None
    genres: list[str]
    first_published_year: int | None
    page_count: int | None
    language: str | None
    ratings: RatingSummary
    is_sample: bool
    used_listing_count: int = 0
    lowest_used_price: float | None = None
    lowest_used_currency: str | None = None


class EditionOut(BaseModel):
    id: int | None
    isbn13: str | None
    isbn10: str | None = None
    format: str | None
    edition_label: str | None = None
    publisher: str | None
    published_year: int | None
    page_count: int | None
    language: str | None
    source: str = "catalogue"
    source_url: str | None = None


class ExternalLink(BaseModel):
    label: str
    url: str


class BookDetail(BookSummary):
    description: str | None
    publisher: str | None
    series: str | None
    subjects: list[str]
    isbn13: str | None
    editions: list[EditionOut]
    source: str
    metadata_fetched_at: datetime | None
    external_links: list[ExternalLink]
    difficulty_signal: str | None


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    body: str | None = Field(default=None, max_length=5000)

    @field_validator("body")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class ReviewUpdateIn(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    body: str | None = Field(default=None, max_length=5000)


class ReviewOut(BaseModel):
    id: int
    book_id: int
    user_id: int
    user_display_name: str
    rating: int
    body: str | None
    helpful_count: int
    status: str
    created_at: datetime
    updated_at: datetime
    is_mine: bool = False
    voted_helpful: bool = False


ReportReason = Literal["spam", "offensive", "off_topic", "spoilers", "fraud", "misleading", "other"]


class ReportIn(BaseModel):
    reason: ReportReason
    details: str | None = Field(default=None, max_length=500)


class InteractionIn(BaseModel):
    type: Literal["interested", "not_interested", "save", "view"]


class CompareIn(BaseModel):
    book_ids: list[int] = Field(min_length=2, max_length=4)
    goal: str | None = Field(default=None, max_length=200)


class ImportIsbnIn(BaseModel):
    isbn: str = Field(min_length=10, max_length=17)


class ExternalSearchResult(BaseModel):
    title: str
    authors: list[str]
    published_year: int | None
    isbns: list[str]
    cover_url: str | None
    source: str
    info_url: str | None
    in_catalogue_book_id: int | None


class OfferOut(BaseModel):
    source: str
    title: str
    format: str | None
    price: float | None
    currency: str | None
    availability: str | None
    url: str | None
    retrieved_at: datetime
    note: str | None = None


class OffersResponse(BaseModel):
    book_id: int
    offers: list[OfferOut]
    used_summary: dict
    metadata_links: list[ExternalLink]
    provider_notes: list[str]


class BookshelfIn(BaseModel):
    book_id: int
    status: Literal["want_to_read", "reading", "read", "abandoned"] = "want_to_read"


class BookshelfUpdateIn(BaseModel):
    status: Literal["want_to_read", "reading", "read", "abandoned"] | None = None
    pages_read: int | None = Field(default=None, ge=0, le=20000)
    started_on: date | None = None
    finished_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
