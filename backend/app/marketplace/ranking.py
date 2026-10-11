"""Deal ranking agent.

deal = 0.30 value + 0.20 condition + 0.20 quality + 0.15 edition match
       + 0.10 delivery fit + 0.05 freshness
* value: price advantage vs. the condition-adjusted typical price,
  clip((typical - total) / typical, -0.5, 0.35) mapped to 0..1. Without a price
  estimate, cheaper listings in the result set score higher (rank-based).
* Price competitiveness is kept separate from listing quality: listings flagged
  as unusually cheap get their value component capped at 0.6, and listings with
  quality < 40 are multiplied by 0.8, so a suspiciously cheap, incomplete
  listing is not automatically ranked first.
Constraints: budget (total known cost), minimum condition, delivery/location.
Listings that miss one constraint slightly are returned as "near matches".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.marketplace.pricing import CONDITION_FACTOR, PriceEstimate, interpret_price
from app.marketplace.quality import QualityReport
from app.marketplace.types import CONDITION_RANK, NormalizedListing

WEIGHTS = {"value": 0.30, "condition": 0.20, "quality": 0.20, "match": 0.15, "delivery": 0.10, "freshness": 0.05}
CONDITION_LABEL = {"new": "New", "like_new": "Like New", "very_good": "Very Good", "good": "Good",
                   "acceptable": "Acceptable", "poor": "Poor", "unknown": "Unknown"}


@dataclass
class Constraints:
    max_price: float | None = None
    currency: str = "INR"
    min_condition: str | None = None
    location: str | None = None
    delivery: str = "any"


@dataclass
class RankedDeal:
    uid: str
    score: float
    group: str  # match | near_match | other
    components: dict[str, float]
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)
    price_verdict: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _money(cur: str | None, v: float | None) -> str:
    if v is None:
        return "unknown"
    sym = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(cur or "", f"{cur} ")
    if cur == "INR" or float(v).is_integer():
        return f"{sym}{v:,.0f}"
    return f"{sym}{v:,.2f}"


def _constraint_check(it: NormalizedListing, c: Constraints) -> tuple[list[str], list[str], bool]:
    """Returns (unmet hard, unmet soft, delivery_fit)."""
    hard, soft = [], []
    total = it.total_known_cost
    if it.price is None:
        hard.append("No price")
    if c.max_price is not None and total is not None:
        if (it.currency or c.currency) != c.currency:
            soft.append(f"Priced in {it.currency}, budget in {c.currency}")
        elif total > c.max_price:
            (soft if total <= c.max_price * 1.15 else hard).append(
                f"Over budget by {_money(it.currency, total - c.max_price)}")
        elif not it.shipping_known and it.delivery != "pickup":
            soft.append("Shipping unknown: may exceed budget")
    if c.min_condition:
        need, have = CONDITION_RANK[c.min_condition], CONDITION_RANK.get(it.condition, 0)
        if have < need:
            (soft if have == need - 1 else hard).append(
                f"Condition {CONDITION_LABEL[it.condition]} is below your minimum ({CONDITION_LABEL[c.min_condition]})")
    fit = True
    if c.delivery == "pickup":
        if it.is_external or it.delivery == "shipping":
            hard.append("Pickup not available")
            fit = False
        elif c.location and (not it.location or c.location.lower() not in it.location.lower()):
            soft.append(f"Not listed in {c.location}")
            fit = False
    elif c.delivery == "shipping" and it.delivery == "pickup":
        hard.append("Seller offers pickup only")
        fit = False
    elif c.location and not it.is_external and it.location and c.location.lower() not in it.location.lower():
        fit = it.delivery in ("shipping", "both")
    return hard, soft, fit


def rank(listings: list[NormalizedListing], quality: dict[str, QualityReport], est: PriceEstimate | None,
         verdicts: dict[str, dict], c: Constraints) -> list[RankedDeal]:
    priced = sorted([it.total_known_cost for it in listings if it.total_known_cost is not None])
    out: list[RankedDeal] = []
    for it in listings:
        q = quality[it.uid]
        hard, soft, fit = _constraint_check(it, c)
        comp: dict[str, float] = {}
        typical = None
        if est and est.status in ("ok", "rule_based") and est.median and it.currency == est.currency:
            typical = est.median * CONDITION_FACTOR.get(it.condition, 1.0) / CONDITION_FACTOR.get(est.condition, 1.0)
        if typical and it.total_known_cost is not None:
            adv = max(-0.5, min(0.35, (typical - it.total_known_cost) / typical))
            comp["value"] = (adv + 0.5) / 0.85
        elif it.total_known_cost is not None and priced:
            idx = priced.index(it.total_known_cost)
            comp["value"] = 1 - idx / max(1, len(priced) - 1) if len(priced) > 1 else 0.5
        else:
            comp["value"] = 0.0
        if any("far below" in f for f in q.flags):
            comp["value"] = min(comp["value"], 0.6)
        comp["condition"] = CONDITION_RANK.get(it.condition, 0) / 6
        comp["quality"] = q.score / 100
        comp["match"] = {"exact": 1.0, "same_work": 0.8, "approximate": 0.5}.get(it.match, 0.0)
        comp["delivery"] = 1.0 if fit else 0.4
        comp["freshness"] = q.breakdown.get("freshness", 5) / 10
        score = sum(WEIGHTS[k] * v for k, v in comp.items())
        if q.score < 40:
            score *= 0.8
        group = "other" if hard else "near_match" if soft else "match"
        reasons: list[str] = []
        verdict = verdicts.get(it.uid)
        if typical and it.price is not None:
            # Compare like with like: the item price against typical item prices (shipping is reported separately).
            diff = round(typical - it.price)
            if diff >= 1:
                reasons.append(f"Asking price {_money(it.currency, diff)} below typical for this condition "
                               f"(~{_money(it.currency, typical)})")
            elif diff <= -1:
                reasons.append(f"Asking price {_money(it.currency, -diff)} above typical for this condition "
                               f"(~{_money(it.currency, typical)})")
            else:
                reasons.append(f"Asking price in line with typical for this condition (~{_money(it.currency, typical)})")
        if it.condition != "unknown":
            meets = f" (meets your {CONDITION_LABEL[c.min_condition]} minimum)" if c.min_condition and CONDITION_RANK[it.condition] >= CONDITION_RANK[c.min_condition] else ""
            reasons.append(f"{CONDITION_LABEL[it.condition]} condition{meets}")
        if it.match == "exact":
            reasons.append("Exact edition match (ISBN)")
        elif it.match == "same_work":
            reasons.append("Same book; edition not confirmed")
        else:
            reasons.append("Matched by title only")
        if it.total_cost_complete and it.total_known_cost is not None:
            ship = "pickup" if it.delivery == "pickup" else (
                "free shipping" if (it.shipping_cost or 0) == 0 else f"incl. {_money(it.currency, it.shipping_cost)} shipping")
            reasons.append(f"Total known cost {_money(it.currency, it.total_known_cost)} ({ship})")
        if c.location and it.location and c.location.lower() in it.location.lower():
            reasons.append(f"Located in {it.location}")
        out.append(RankedDeal(uid=it.uid, score=round(score, 4), group=group, components={k: round(v, 3) for k, v in comp.items()},
                              reasons=reasons, cautions=list(q.flags), unmet=hard + soft, price_verdict=verdict))
    group_order = {"match": 0, "near_match": 1, "other": 2}
    out.sort(key=lambda d: (group_order[d.group], -d.score))
    return out


def verdicts_for(listings: list[NormalizedListing], estimator) -> dict[str, dict]:
    """Leave-one-out price verdict for each listing (its own price is not a comparable)."""
    out = {}
    for it in listings:
        est = estimator(it)
        out[it.uid] = {**interpret_price(it.price, est), "range_low": est.low, "range_high": est.high,
                       "currency": est.currency, "n_comparables": est.n_comparables, "status": est.status}
    return out
