"""Offline evaluation with a per-user temporal hold-out.

Methodology (also shown in the admin dashboard):
1. Relevant items = books a user rated >= 4 or marked as read.
2. Eligible users have >= MIN_POSITIVES relevant items.
3. For each eligible user, the most recent 20% of relevant items (at least 1)
   are hidden. Every event for those (user, book) pairs is removed from training.
4. Models are fitted on the remaining events only, then asked for top-K among
   books the user has not interacted with in training.
5. Metrics: Precision@K, Recall@K, NDCG@K (binary relevance), catalogue
   coverage, intra-list diversity (1 - mean pairwise content cosine) and
   popularity concentration (share of recommended slots taken by the top-10%
   most-interacted books in training).

Assumptions / limits: implicit relevance from a small catalogue, no position
bias correction, asking a model to rank only unseen books. With demo data the
numbers describe synthetic taste profiles, not real readers.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.recommender.content import get_content_model
from app.recommender.hybrid import HybridRecommender, RecConfig
from app.recommender.service import config_from_settings, load_book_lites
from app.recommender.signals import Event, aggregate, load_events

MIN_POSITIVES = 5
MIN_ELIGIBLE_USERS = 5
HOLDOUT_FRACTION = 0.2


def _is_relevant(e: Event) -> bool:
    return (e.kind == "rating" and (e.rating or 0) >= 4) or e.kind == "shelf_read"


def split_events(events: list[Event]) -> tuple[list[Event], dict[int, set[int]]]:
    by_user: dict[int, dict[int, Event]] = defaultdict(dict)
    for e in events:
        if _is_relevant(e) and e.ts is not None:
            prev = by_user[e.user_id].get(e.book_id)
            if prev is None or e.ts > prev.ts:
                by_user[e.user_id][e.book_id] = e
    held: dict[int, set[int]] = {}
    for u, items in by_user.items():
        if len(items) < MIN_POSITIVES:
            continue
        ordered = sorted(items.values(), key=lambda e: e.ts)
        n_hold = max(1, int(round(len(ordered) * HOLDOUT_FRACTION)))
        held[u] = {e.book_id for e in ordered[-n_hold:]}
    train = [e for e in events if not (e.user_id in held and e.book_id in held[e.user_id])]
    return train, held


def _ndcg(recs: list[int], relevant: set[int], k: int) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, b in enumerate(recs[:k]) if b in relevant)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return dcg / ideal if ideal else 0.0


CONFIGS = {
    "hybrid": None,  # current settings
    "content_only": RecConfig.only("content"),
    "collaborative_only": RecConfig.only("collaborative"),
    "popularity_only": RecConfig.only("popularity"),
}


def evaluate(db: Session, k: int = 10, include_demo: bool = False) -> dict:
    s = get_settings()
    events = load_events(db, include_demo=include_demo)
    train, held = split_events(events)
    n_users = len(held)
    base = {
        "k": k, "include_demo": include_demo, "eligible_users": n_users,
        "methodology": __doc__.split("Methodology (also shown in the admin dashboard):")[1].strip(),
        "requirements": f"Needs at least {MIN_ELIGIBLE_USERS} users with {MIN_POSITIVES}+ books rated 4-5 stars or marked as read.",
    }
    if n_users < MIN_ELIGIBLE_USERS:
        return {**base, "status": "insufficient_data",
                "message": "Not enough evaluation data. " + base["requirements"], "results": {}}

    content = get_content_model(db)
    books = load_book_lites(db)
    signals = aggregate(train, s.rec_recency_half_life_days)
    train_counts: dict[int, int] = defaultdict(int)
    for e in train:
        if e.value > 0:
            train_counts[e.book_id] += 1
    ranked_pop = sorted(books, key=lambda b: train_counts.get(b, 0), reverse=True)
    top_decile = set(ranked_pop[: max(1, len(ranked_pop) // 10)])

    results = {}
    for name, cfg in CONFIGS.items():
        cfg = cfg or config_from_settings()
        model = HybridRecommender(content, signals, books, cfg, prior_m=s.rec_bayes_prior_count,
                                  cf_min_users=s.rec_cf_min_users,
                                  cf_min_user_interactions=s.rec_cf_min_user_interactions)
        if name == "collaborative_only" and not model.cf.reliable:
            results[name] = {"status": "unavailable", "message": "Collaborative filtering has too little data to fit."}
            continue
        p, r, n, div = [], [], [], []
        cold_p: list[float] = []
        recommended: set[int] = set()
        slots = pop_slots = 0
        for u, relevant in held.items():
            res = model.recommend(u, None, k=k)
            recs = [i.book_id for i in res.items]
            hits = len(set(recs) & relevant)
            p.append(hits / k)
            r.append(hits / len(relevant))
            n.append(_ndcg(recs, relevant, k))
            if len(signals.user_items(u)) < 3:
                cold_p.append(hits / k)
            recommended |= set(recs)
            slots += len(recs)
            pop_slots += sum(1 for b in recs if b in top_decile)
            if len(recs) > 1:
                sims = [content.item_similarity(a, b) for i, a in enumerate(recs) for b in recs[i + 1:]]
                div.append(1 - float(np.mean(sims)))
        results[name] = {
            "status": "ok",
            f"precision_at_{k}": round(float(np.mean(p)), 4),
            f"recall_at_{k}": round(float(np.mean(r)), 4),
            f"ndcg_at_{k}": round(float(np.mean(n)), 4),
            "catalogue_coverage": round(len(recommended) / max(1, len(books)), 4),
            "intra_list_diversity": round(float(np.mean(div)), 4) if div else None,
            "popularity_concentration": round(pop_slots / slots, 4) if slots else None,
            "cold_start_precision": round(float(np.mean(cold_p)), 4) if len(cold_p) >= 3 else None,
            "cold_start_users": len(cold_p),
            "cf_reliable": model.cf.reliable,
        }
    return {**base, "status": "ok", "results": results,
            "data_warning": ("Includes synthetic demo users: metrics describe generated taste profiles, "
                             "not real-world performance.") if include_demo else None}
