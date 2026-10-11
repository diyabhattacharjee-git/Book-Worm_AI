"""Common schema every listing source is normalised into."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.marketplace import CONDITIONS

ConditionKey = Literal["new", "like_new", "very_good", "good", "acceptable", "poor", "unknown"]

# Ordinal rank: higher is better. "unknown" is deliberately 0 so it never meets
# a minimum-condition preference.
CONDITION_RANK: dict[str, int] = {"new": 6, "like_new": 5, "very_good": 4, "good": 3, "acceptable": 2, "poor": 1, "unknown": 0}
assert set(CONDITIONS) <= set(CONDITION_RANK)


class NormalizedListing(BaseModel):
    uid: str  # "<provider>:<id>" - stable across the pipeline
    provider: str  # community | ebay
    provider_label: str
    is_external: bool
    is_sample: bool = False
    external_id: str
    title: str
    author: str | None = None
    isbn: str | None = None
    edition_text: str | None = None
    published_year: int | None = None
    condition: ConditionKey = "unknown"
    condition_raw: str | None = None
    price: float | None = None
    currency: str | None = None
    shipping_cost: float | None = None  # None = unknown, 0 = free / pickup
    shipping_known: bool = False
    delivery: str | None = None
    location: str | None = None
    country: str | None = None
    seller_name: str | None = None
    seller_id: int | None = None
    seller_feedback_pct: float | None = None
    seller_completed_sales: int | None = None
    image_url: str | None = None
    image_count: int = 0
    description: str | None = None
    url: str | None = None  # external URL (provider-returned) or internal route
    status: str = "active"
    listed_at: datetime | None = None
    fetched_at: datetime
    book_id: int | None = None

    # Filled in by later pipeline stages
    match: Literal["exact", "same_work", "approximate", "unmatched"] = "unmatched"
    match_confidence: float = 0.0
    validation_issues: list[str] = Field(default_factory=list)
    probable_duplicate_of: str | None = None

    @property
    def total_known_cost(self) -> float | None:
        if self.price is None:
            return None
        return self.price + (self.shipping_cost or 0.0)

    @property
    def total_cost_complete(self) -> bool:
        return self.price is not None and self.shipping_known
