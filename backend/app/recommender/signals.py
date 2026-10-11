"""Turn raw user activity into weighted (user, book) preference signals.

Signal values (documented in docs/RECOMMENDER.md):
* explicit rating r in 1..5  ->  1.5 * (r - 3) / 2         (range -1.5 .. +1.5)
* implicit interaction       ->  INTERACTION_WEIGHTS[type]  (e.g. save=+1.0, dismiss=-0.7)
* onboarding "enjoyed" book  ->  +1.2 (no timestamp decay)

Each event decays with age: value * 0.5 ** (age_days / half_life_days), so recent
explicit feedback outweighs stale or weak signals. Per (user, book) the decayed
values are summed and clipped to [-2, 3].
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import as_utc
from app.models.social import Review, UserBookInteraction
from app.models.user import User, UserProfile

RATING_SCALE = 1.5
ENJOYED_WEIGHT = 1.2
CLIP_MIN, CLIP_MAX = -2.0, 3.0


@dataclass
class Event:
    user_id: int
    book_id: int
    kind: str  # rating | <interaction type> | enjoyed
    value: float
    ts: datetime | None
    rating: int | None = None


@dataclass
class Signals:
    """Aggregated preference matrix in sparse dict form plus raw events."""

    values: dict[int, dict[int, float]] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)

    def user_items(self, user_id: int) -> dict[int, float]:
        return self.values.get(user_id, {})

    def positives(self, user_id: int, threshold: float = 0.5) -> dict[int, float]:
        return {b: v for b, v in self.user_items(user_id).items() if v >= threshold}

    def negatives(self, user_id: int) -> dict[int, float]:
        return {b: v for b, v in self.user_items(user_id).items() if v < 0}


def event_value(e: Event, now: datetime, half_life_days: float) -> float:
    if e.ts is None or half_life_days <= 0:
        return e.value
    age_days = max(0.0, (now - e.ts).total_seconds() / 86400)
    return e.value * 0.5 ** (age_days / half_life_days)


def aggregate(events: list[Event], half_life_days: float, now: datetime | None = None) -> Signals:
    now = now or datetime.now(timezone.utc)
    vals: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for e in events:
        vals[e.user_id][e.book_id] += event_value(e, now, half_life_days)
    clipped = {
        u: {b: max(CLIP_MIN, min(CLIP_MAX, v)) for b, v in items.items() if abs(v) > 1e-6}
        for u, items in vals.items()
    }
    return Signals(values=clipped, events=events)


def load_events(db: Session, include_demo: bool = True, user_ids: list[int] | None = None) -> list[Event]:
    demo_filter = [] if include_demo else [User.is_demo.is_(False)]
    uid_filter_r = [Review.user_id.in_(user_ids)] if user_ids is not None else []
    uid_filter_i = [UserBookInteraction.user_id.in_(user_ids)] if user_ids is not None else []
    events: list[Event] = []
    for uid, bid, rating, ts in db.execute(
        select(Review.user_id, Review.book_id, Review.rating, Review.updated_at)
        .join(User, User.id == Review.user_id).where(*demo_filter, *uid_filter_r)
    ):
        events.append(Event(uid, bid, "rating", RATING_SCALE * (rating - 3) / 2, as_utc(ts), rating=rating))
    for uid, bid, typ, w, ts in db.execute(
        select(UserBookInteraction.user_id, UserBookInteraction.book_id, UserBookInteraction.type,
               UserBookInteraction.weight, UserBookInteraction.created_at)
        .join(User, User.id == UserBookInteraction.user_id).where(*demo_filter, *uid_filter_i)
    ):
        events.append(Event(uid, bid, typ, float(w), as_utc(ts)))
    prof_q = select(UserProfile.user_id, UserProfile.enjoyed_book_ids).join(User, User.id == UserProfile.user_id)
    prof_q = prof_q.where(*demo_filter)
    if user_ids is not None:
        prof_q = prof_q.where(UserProfile.user_id.in_(user_ids))
    for uid, enjoyed in db.execute(prof_q):
        for bid in enjoyed or []:
            if isinstance(bid, int):
                events.append(Event(uid, bid, "enjoyed", ENJOYED_WEIGHT, None))
    return events
