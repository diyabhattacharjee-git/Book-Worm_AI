"""Listing quality agent: a transparent 0-100 score from observable signals.

Points (docs/MARKETPLACE_INTELLIGENCE.md):
  completeness   30  (author 5, ISBN 10, edition/year 5, description >= 30 chars 10)
  condition      15  (stated condition)
  photos         15  (seller photos; 8 if only a stock/catalogue image)
  identification 15  (exact 15, same work 12, approximate 7)
  freshness      10  (<=30 days 10, <=90 7, <=180 4, older 0, unknown 5)
  seller history 10  (see below; never treated as proof of trustworthiness)
  shipping known  5
Flags are phrased neutrally: they describe missing or unusual information and
never accuse a seller of anything.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from app.marketplace.pricing import CONDITION_FACTOR, PriceEstimate
from app.marketplace.types import NormalizedListing


@dataclass
class QualityReport:
    uid: str
    score: int
    breakdown: dict[str, int]
    flags: list[str] = field(default_factory=list)
    level: str = "fair"  # good | fair | limited

    def to_dict(self) -> dict:
        return asdict(self)


def _freshness_points(it: NormalizedListing, now: datetime) -> int:
    if not it.listed_at:
        return 5
    days = (now - it.listed_at).days
    return 10 if days <= 30 else 7 if days <= 90 else 4 if days <= 180 else 0


def _seller_points(it: NormalizedListing) -> tuple[int, str | None]:
    if it.provider == "community":
        n = it.seller_completed_sales or 0
        return (10, None) if n >= 3 else (6, None) if n >= 1 else (3, "Seller has no completed sales on BookWorm yet")
    if it.seller_feedback_pct is not None:
        fb, cnt = it.seller_feedback_pct, it.seller_completed_sales or 0
        if fb >= 98 and cnt >= 50:
            return 10, None
        if fb >= 95:
            return 6, None
        return 3, f"Seller feedback is {fb:g}% on {it.provider_label}"
    return 3, None


def assess(it: NormalizedListing, est: PriceEstimate | None, now: datetime | None = None) -> QualityReport:
    now = now or datetime.now(timezone.utc)
    b: dict[str, int] = {}
    flags: list[str] = []
    b["completeness"] = (5 if it.author else 0) + (10 if it.isbn else 0) + (5 if (it.edition_text or it.published_year) else 0) \
        + (10 if it.description and len(it.description.strip()) >= 30 else 0)
    b["condition"] = 15 if it.condition != "unknown" else 0
    if it.condition == "unknown":
        flags.append("Condition not stated")
    if it.provider == "community":
        b["photos"] = 15 if it.image_count > 0 else 0
        if it.image_count == 0:
            flags.append("No photos of the actual copy")
    else:
        b["photos"] = 8 if it.image_url else 0
        if not it.image_url:
            flags.append("No photos")
    b["identification"] = {"exact": 15, "same_work": 12, "approximate": 7}.get(it.match, 0)
    b["freshness"] = _freshness_points(it, now)
    b["seller_history"], seller_flag = _seller_points(it)
    if seller_flag:
        flags.append(seller_flag)
    b["shipping_known"] = 5 if it.shipping_known else 0
    if b["completeness"] <= 10 and not it.description:
        flags.append("Listing details are sparse")
    if est and est.status == "ok" and est.median and it.price:
        good_equiv = it.price / CONDITION_FACTOR.get(it.condition, 1.0)
        if good_equiv < 0.5 * est.median:
            flags.append("Price is far below comparable listings: confirm condition and details before paying")
    if it.probable_duplicate_of:
        flags.append("Possible duplicate listing")
    score = int(sum(b.values()))
    level = "good" if score >= 70 else "fair" if score >= 45 else "limited"
    return QualityReport(uid=it.uid, score=score, breakdown=b, flags=flags, level=level)
