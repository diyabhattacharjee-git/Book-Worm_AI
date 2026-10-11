"""Item-item collaborative filtering on the (user x book) signal matrix.

Similarity between two books is the cosine of their user-signal columns, shrunk
towards zero when few users interacted with both:
    sim'(i, j) = cos(i, j) * n_ij / (n_ij + shrinkage)
A user's score for candidate c is the similarity-weighted average of their own
signals:  score(c) = sum_i sim'(c, i) * r_ui / sum_i |sim'(c, i)|

The model reports itself as *unreliable* (and the hybrid gives it zero weight)
when fewer than `min_users` users have at least `min_user_interactions` signals.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from sklearn.preprocessing import normalize

from app.recommender.signals import Signals


@dataclass
class CFScore:
    score: float
    top_item: int | None
    support: int  # number of the user's items that contributed


class ItemCF:
    def __init__(self, signals: Signals, shrinkage: float = 10.0, min_users: int = 5, min_user_interactions: int = 3):
        self.signals = signals
        self.shrinkage = shrinkage
        self.min_users = min_users
        self.min_user_interactions = min_user_interactions
        self.item_index: dict[int, int] = {}
        self.items: list[int] = []
        self.sim: np.ndarray | None = None
        self.active_users = 0
        self.n_users_with_signals = 0

    def fit(self) -> "ItemCF":
        users = [u for u, items in self.signals.values.items() if items]
        self.n_users_with_signals = len(users)
        self.active_users = sum(1 for u in users if len(self.signals.values[u]) >= self.min_user_interactions)
        items = sorted({b for u in users for b in self.signals.values[u]})
        self.items = items
        self.item_index = {b: i for i, b in enumerate(items)}
        if not users or not items:
            self.sim = None
            return self
        rows, cols, vals = [], [], []
        for ui, u in enumerate(users):
            for b, v in self.signals.values[u].items():
                rows.append(ui)
                cols.append(self.item_index[b])
                vals.append(v)
        r = sparse.csr_matrix((vals, (rows, cols)), shape=(len(users), len(items)), dtype=np.float32)
        binary = (r != 0).astype(np.float32)
        cooc = (binary.T @ binary).toarray()
        cols_norm = normalize(r.T.tocsr(), axis=1)
        cos = (cols_norm @ cols_norm.T).toarray()
        sim = cos * (cooc / (cooc + self.shrinkage))
        np.fill_diagonal(sim, 0.0)
        self.sim = sim.astype(np.float32)
        return self

    @property
    def reliable(self) -> bool:
        return self.sim is not None and self.active_users >= self.min_users

    def status(self) -> dict:
        return {
            "reliable": self.reliable,
            "users_with_enough_data": self.active_users,
            "required_users": self.min_users,
            "items_in_matrix": len(self.items),
        }

    def score_user(self, user_items: dict[int, float], candidates: list[int]) -> dict[int, CFScore]:
        out: dict[int, CFScore] = {}
        if self.sim is None or len(user_items) < self.min_user_interactions:
            return out
        known = [(self.item_index[b], b, v) for b, v in user_items.items() if b in self.item_index]
        if not known:
            return out
        idx = np.array([k[0] for k in known])
        vals = np.array([k[2] for k in known], dtype=np.float32)
        for c in candidates:
            ci = self.item_index.get(c)
            if ci is None:
                continue
            s = self.sim[ci, idx]
            denom = float(np.abs(s).sum())
            if denom < 1e-6:
                continue
            contrib = s * vals
            score = float(contrib.sum() / denom)
            top = int(np.argmax(contrib))
            out[c] = CFScore(score=score, top_item=known[top][1] if contrib[top] > 0 else None,
                             support=int((np.abs(s) > 1e-6).sum()))
        return out
