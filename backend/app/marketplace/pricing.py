"""Price intelligence agent: a fair asking-price range from comparable listings.

Method (docs/MARKETPLACE_INTELLIGENCE.md):
1. Comparables = validated listings with a price in the target currency. Other
   currencies are excluded unless FX_RATES_JSON explicitly provides a rate.
2. Tiers: exact edition (ISBN) > same work > approximate title match. The
   narrowest tier with >= MIN_COMPARABLES listings is used.
3. Prices are condition-normalised to a "Good" equivalent with documented
   heuristic factors, weighted by recency (half-life 60 days) and source
   reliability (sample data weighs 0.5), then the weighted 25th/50th/75th
   percentiles are taken and scaled back to the requested condition.
4. Fewer comparables: if a new-copy reference price is supplied, a rule-based
   band (CONDITION_NEW_RATIO) is returned with low confidence and clearly labelled.
5. Otherwise: "Insufficient data to estimate reliably".

The estimate describes *asking* prices, not completed sales.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import numpy as np

from app.core.config import get_settings
from app.marketplace.types import NormalizedListing

MIN_COMPARABLES = 3
CONDITION_FACTOR = {"new": 1.30, "like_new": 1.15, "very_good": 1.05, "good": 1.00, "acceptable": 0.85, "poor": 0.65}
# Rule-based fallback: share of a new-copy price typically asked for a used copy (heuristic, low confidence).
CONDITION_NEW_RATIO = {"new": (0.85, 1.0), "like_new": (0.55, 0.75), "very_good": (0.45, 0.65), "good": (0.35, 0.55),
                       "acceptable": (0.25, 0.40), "poor": (0.10, 0.25)}
TIER_BASE = {"exact": 0.50, "same_work": 0.40, "approximate": 0.25}
RECENCY_HALF_LIFE_DAYS = 60


@dataclass
class PriceEstimate:
    status: str  # ok | rule_based | insufficient_data
    currency: str
    condition: str
    low: float | None = None
    median: float | None = None
    high: float | None = None
    n_comparables: int = 0
    tier: str | None = None
    confidence: str | None = None  # low | medium | high
    confidence_score: float | None = None
    sources: dict[str, int] = field(default_factory=dict)
    comparables: list[dict] = field(default_factory=list)
    excluded_other_currency: int = 0
    limitations: list[str] = field(default_factory=list)
    explanation: str = ""
    method: str = "deterministic"

    def to_dict(self) -> dict:
        return asdict(self)


def _wquantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w) - 0.5 * w
    cum /= w.sum()
    return float(np.interp(q, cum, v))


def _convert(price: float, cur: str, target: str) -> float | None:
    if cur == target:
        return price
    rate = get_settings().fx_rates.get(f"{cur}_{target}")
    return price * rate if rate else None


def confidence_from(tier: str, n: int, dispersion: float, sample_share: float) -> tuple[str, float]:
    """score = tier base + 0.35 * min(n, 10)/10 + dispersion bonus (0.15 if IQR/median < 0.35,
    0.05 if < 0.6) - 0.2 * share of sample data.  high >= 0.75, medium >= 0.5, else low."""
    score = TIER_BASE.get(tier, 0.2) + 0.35 * min(n, 10) / 10
    score += 0.15 if dispersion < 0.35 else 0.05 if dispersion < 0.6 else 0.0
    score -= 0.2 * sample_share
    score = max(0.0, min(1.0, score))
    level = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
    return level, round(score, 3)


def estimate_price(listings: list[NormalizedListing], currency: str, condition: str = "good",
                   new_price_reference: float | None = None, now: datetime | None = None,
                   exclude_uid: str | None = None) -> PriceEstimate:
    now = now or datetime.now(timezone.utc)
    condition = condition if condition in CONDITION_FACTOR else "good"
    s = get_settings()
    est = PriceEstimate(status="insufficient_data", currency=currency, condition=condition)
    est.limitations.append("Based on current asking prices, not completed sales.")
    pool: dict[str, list[tuple[NormalizedListing, float]]] = {"exact": [], "same_work": [], "approximate": []}
    for it in listings:
        if it.uid == exclude_uid or it.price is None or it.match not in pool:
            continue
        if it.is_sample and not s.include_sample_listings_in_estimates:
            continue
        if it.condition == "unknown":
            continue
        price = _convert(it.price, (it.currency or "").upper(), currency)
        if price is None:
            est.excluded_other_currency += 1
            continue
        pool[it.match].append((it, price))
    if est.excluded_other_currency:
        est.limitations.append(f"{est.excluded_other_currency} listing(s) in other currencies were excluded "
                               "(no configured exchange rate).")

    chosen_tier, chosen = None, []
    cumulative: list[tuple[NormalizedListing, float]] = []
    for tier in ("exact", "same_work", "approximate"):
        cumulative = cumulative + pool[tier]
        if len(cumulative) >= MIN_COMPARABLES:
            chosen_tier, chosen = tier, list(cumulative)
            break

    if chosen_tier:
        vals, weights = [], []
        for it, price in chosen:
            age_days = max(0.0, (now - (it.listed_at or it.fetched_at)).total_seconds() / 86400)
            w = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS) * (0.5 if it.is_sample else 1.0)
            vals.append(price / CONDITION_FACTOR.get(it.condition, 1.0))
            weights.append(max(w, 0.05))
            est.sources[it.provider_label] = est.sources.get(it.provider_label, 0) + 1
            est.comparables.append({"uid": it.uid, "title": it.title, "price": it.price, "currency": it.currency,
                                    "condition": it.condition, "match": it.match, "provider": it.provider_label,
                                    "is_sample": it.is_sample, "url": it.url})
        v, w = np.array(vals), np.array(weights)
        factor = CONDITION_FACTOR[condition]
        p25, p50, p75 = (_wquantile(v, w, q) * factor for q in (0.25, 0.5, 0.75))
        if len(v) < 5:  # small samples: widen the band by 10% each side
            p25, p75 = min(p25, float(v.min()) * factor) * 0.9, max(p75, float(v.max()) * factor) * 1.1
        dispersion = (p75 - p25) / p50 if p50 else 1.0
        sample_share = sum(1 for it, _ in chosen if it.is_sample) / len(chosen)
        est.confidence, est.confidence_score = confidence_from(chosen_tier, len(chosen), dispersion, sample_share)
        est.status, est.tier, est.n_comparables = "ok", chosen_tier, len(chosen)
        est.low, est.median, est.high = round(p25), round(p50), round(p75)
        tier_txt = {"exact": "the same edition (ISBN match)", "same_work": "the same book (edition may differ)",
                    "approximate": "listings that match by title only"}[chosen_tier]
        est.explanation = (f"Typical asking price for a {condition.replace('_', ' ')} copy, from {len(chosen)} "
                           f"comparable listing(s) of {tier_txt}, adjusted for condition and recency.")
        if chosen_tier != "exact":
            est.limitations.append("Comparables may include different editions, which can be priced differently.")
        if sample_share > 0:
            est.limitations.append("Includes sample (demo) listings: not real market data.")
        if len(chosen) < 5:
            est.limitations.append("Few comparable listings: treat the range as rough.")
        return est

    n_any = sum(len(v) for v in pool.values())
    if new_price_reference:
        lo_r, hi_r = CONDITION_NEW_RATIO[condition]
        est.status, est.tier, est.n_comparables = "rule_based", "new_price_rule", n_any
        est.low, est.high = round(new_price_reference * lo_r), round(new_price_reference * hi_r)
        est.median = round((est.low + est.high) / 2)
        est.confidence, est.confidence_score = "low", None
        est.explanation = (f"Only {n_any} comparable listing(s) found, so this is a rule-of-thumb band: "
                           f"{int(lo_r * 100)}-{int(hi_r * 100)}% of the new-copy price you provided "
                           f"({currency} {new_price_reference:g}) for a {condition.replace('_', ' ')} copy.")
        est.limitations.append("A rough guide based on the new-copy price, not on real listings.")
        return est

    est.n_comparables = n_any
    est.explanation = (f"Insufficient data to estimate reliably: found {n_any} usable comparable listing(s); "
                       f"at least {MIN_COMPARABLES} are needed. Providing a new-copy price enables a rough rule-based band.")
    return est


def interpret_price(price: float | None, est: PriceEstimate) -> dict:
    if price is None or est.status == "insufficient_data" or est.low is None or est.high is None:
        return {"verdict": "unknown", "text": "Can't judge this price without enough comparable data."}
    if price < est.low * 0.85:
        return {"verdict": "well_below", "text": "Well below the typical asking range. Could be a great deal, "
                "but check the condition and photos carefully before paying."}
    if price < est.low:
        return {"verdict": "below", "text": "Below the typical asking range: good value if the copy is as described."}
    if price <= est.high:
        return {"verdict": "within", "text": "Within the typical asking range."}
    if price <= est.high * 1.25:
        return {"verdict": "above", "text": "Above the typical asking range; you may be able to find it cheaper or negotiate."}
    return {"verdict": "well_above", "text": "Well above the typical asking range."}
