"""Popularity prior with Bayesian smoothing.

bayes(b) = (m * C + sum_ratings_b) / (m + n_b)
  C = global mean app rating, m = REC_BAYES_PRIOR_COUNT (default 5).
A book with a single 5-star rating therefore scores close to the global mean,
not at the top. When a book has no app ratings, an external provider rating is
used with the same shrinkage (its count capped at m) and a 0.8 discount, because
it is a different population of readers.

activity(b) = log1p(positive interactions) / log1p(max positive interactions)
popularity(b) = 0.6 * (bayes(b) - 1) / 4 + 0.4 * activity(b)
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from app.recommender.signals import Signals


@dataclass
class PopularityInfo:
    score: float
    n_ratings: int
    mean_rating: float | None
    bayes_rating: float
    activity: int
    used_external: bool


def fit_popularity(
    signals: Signals,
    book_ids: list[int],
    external: dict[int, tuple[float | None, int | None]],
    prior_m: int = 5,
) -> dict[int, PopularityInfo]:
    sums: dict[int, float] = defaultdict(float)
    counts: dict[int, int] = defaultdict(int)
    activity: dict[int, int] = defaultdict(int)
    for e in signals.events:
        if e.kind == "rating" and e.rating is not None:
            sums[e.book_id] += e.rating
            counts[e.book_id] += 1
        if e.value > 0:
            activity[e.book_id] += 1
    total_n = sum(counts.values())
    global_mean = (sum(sums.values()) / total_n) if total_n else 3.5
    max_act = max(activity.values(), default=0)
    out: dict[int, PopularityInfo] = {}
    for b in book_ids:
        n = counts.get(b, 0)
        used_ext = False
        if n:
            bayes = (prior_m * global_mean + sums[b]) / (prior_m + n)
        else:
            ext_avg, ext_n = external.get(b, (None, None))
            if ext_avg and ext_n:
                k = min(int(ext_n), prior_m)
                bayes = global_mean + 0.8 * ((prior_m * global_mean + ext_avg * k) / (prior_m + k) - global_mean)
                used_ext = True
            else:
                bayes = global_mean
        act = activity.get(b, 0)
        act_norm = math.log1p(act) / math.log1p(max_act) if max_act else 0.0
        score = 0.6 * (bayes - 1) / 4 + 0.4 * act_norm
        out[b] = PopularityInfo(
            score=score, n_ratings=n, mean_rating=round(sums[b] / n, 2) if n else None,
            bayes_rating=round(bayes, 3), activity=act, used_external=used_ext,
        )
    return out
