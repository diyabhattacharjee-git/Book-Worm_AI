"""Hybrid recommender: content + collaborative + popularity + stated preferences.

final(c) = sum_s w_s * norm_s(c) / sum_{s available} w_s

* Each signal is min-max normalised over the candidate pool. A signal that is
  unavailable for this user (no history, CF unreliable, no preferences) or has
  no variance is dropped and the remaining weights are renormalised.
* Diversity: Maximal Marginal Relevance re-ranking
      mmr(c) = lambda * final(c) - (1 - lambda) * max_{s in selected} contentsim(c, s)
  plus a cap of two books per author in one list.
* Every recommendation carries evidence-based reasons built only from the
  signals that actually contributed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.recommender.collaborative import ItemCF
from app.recommender.content import ContentModel
from app.recommender.popularity import PopularityInfo, fit_popularity
from app.recommender.signals import Signals

SHORT_MAX, MEDIUM_MAX = 250, 450


@dataclass
class BookLite:
    id: int
    title: str
    authors: list[str]
    genres: set[str]  # lowercase genre + subject names
    language: str | None
    pages: int | None
    external_rating: tuple[float | None, int | None] = (None, None)
    text: str = ""


@dataclass
class Preferences:
    genres: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    length: str | None = None

    @property
    def empty(self) -> bool:
        return not (self.genres or self.authors or self.languages or self.themes or self.topics
                    or (self.length and self.length != "any"))

    def as_text(self) -> str:
        return " ".join(self.genres * 2 + self.themes + self.topics + self.authors)


@dataclass
class RecConfig:
    w_content: float = 0.40
    w_collaborative: float = 0.25
    w_popularity: float = 0.15
    w_preference: float = 0.20
    diversity_lambda: float = 0.80
    max_per_author: int = 2
    pool_size: int = 150

    @classmethod
    def only(cls, signal: str) -> "RecConfig":
        w = {"content": 0.0, "collaborative": 0.0, "popularity": 0.0, "preference": 0.0}
        w[signal] = 1.0
        return cls(w_content=w["content"], w_collaborative=w["collaborative"], w_popularity=w["popularity"],
                   w_preference=w["preference"], diversity_lambda=1.0)


@dataclass
class Reason:
    signal: str
    text: str
    evidence: dict = field(default_factory=dict)


@dataclass
class Recommendation:
    book_id: int
    score: float
    contributions: dict[str, float]
    reasons: list[Reason]
    strategy: str  # dominant signal


@dataclass
class RecResult:
    items: list[Recommendation]
    mode: str  # personalized | cold_start
    signals_used: list[str]
    cf_status: dict
    notes: list[str]


def length_bucket(pages: int | None) -> str | None:
    if not pages:
        return None
    return "short" if pages <= SHORT_MAX else "medium" if pages <= MEDIUM_MAX else "long"


def _minmax(d: dict[int, float]) -> dict[int, float] | None:
    if not d:
        return None
    lo, hi = min(d.values()), max(d.values())
    if hi - lo < 1e-9:
        return None
    return {k: (v - lo) / (hi - lo) for k, v in d.items()}


class HybridRecommender:
    def __init__(self, content: ContentModel, signals: Signals, books: dict[int, BookLite], config: RecConfig,
                 prior_m: int = 5, cf_min_users: int = 5, cf_min_user_interactions: int = 3):
        self.content = content
        self.signals = signals
        self.books = books
        self.config = config
        self.cf = ItemCF(signals, min_users=cf_min_users, min_user_interactions=cf_min_user_interactions).fit()
        self.popularity: dict[int, PopularityInfo] = fit_popularity(
            signals, list(books), {b.id: b.external_rating for b in books.values()}, prior_m=prior_m
        )

    # ------------------------------------------------------------- signals
    def _content_scores(self, positives: dict[int, float], negatives: dict[int, float], prefs: Preferences,
                        texts: list[str], cands: list[int]) -> tuple[dict[int, float], dict[int, tuple[int, float]]]:
        if self.content.matrix.shape[0] == 0:
            return {}, {}
        dim = self.content.matrix.shape[1]
        profile = np.zeros(dim, dtype=np.float32)
        used = False
        for b, w in {**positives, **negatives}.items():
            v = self.content.vector(b)
            if v is not None:
                profile += w * v
                used = True
        pref_text = prefs.as_text()
        if pref_text.strip():
            profile += 0.8 * self.content.encode_text(pref_text).astype(np.float32)
            used = True
        if texts:
            profile += 0.3 * self.content.encode_text(" ".join(texts)).astype(np.float32)
            used = True
        if not used or not np.any(profile):
            return {}, {}
        profile /= np.linalg.norm(profile) or 1.0
        idx = [self.content.index[c] for c in cands if c in self.content.index]
        ids = [c for c in cands if c in self.content.index]
        sims = self.content.matrix[idx] @ profile
        scores = {c: float(s) for c, s in zip(ids, sims)}
        nearest: dict[int, tuple[int, float]] = {}
        pos_ids = [b for b in positives if b in self.content.index]
        if pos_ids:
            pm = self.content.matrix[[self.content.index[b] for b in pos_ids]]
            weights = np.array([positives[b] for b in pos_ids], dtype=np.float32)
            pair = self.content.matrix[idx] @ pm.T  # (cands x positives)
            weighted = pair * weights
            for row, c in enumerate(ids):
                j = int(np.argmax(weighted[row]))
                nearest[c] = (pos_ids[j], float(pair[row, j]))
        return scores, nearest

    def _preference_scores(self, prefs: Preferences, cands: list[int]) -> tuple[dict[int, float], dict[int, dict]]:
        scores: dict[int, float] = {}
        evidence: dict[int, dict] = {}
        fav_g = {g.lower() for g in prefs.genres}
        fav_a = {a.lower() for a in prefs.authors}
        langs = {lang.lower() for lang in prefs.languages}
        terms = [t.lower() for t in prefs.themes + prefs.topics]
        for c in cands:
            b = self.books[c]
            s, ev = 0.0, {}
            g = sorted(fav_g & b.genres)
            if g:
                s += 0.4 * min(2, len(g))
                ev["genres"] = g
            a = [name for name in b.authors if name.lower() in fav_a]
            if a:
                s += 0.5
                ev["authors"] = a
            if langs and b.language:
                if b.language.lower() in langs:
                    s += 0.1
                else:
                    s -= 0.3
                    ev["language_mismatch"] = b.language
            if prefs.length and prefs.length != "any":
                bucket = length_bucket(b.pages)
                if bucket == prefs.length:
                    s += 0.25
                    ev["length"] = {"pages": b.pages, "preference": prefs.length}
                elif bucket is not None:
                    s -= 0.1
            hits = [t for t in terms if t and t in b.text][:3]
            if hits:
                s += 0.15 * len(hits)
                ev["themes"] = hits
            scores[c] = s
            if ev:
                evidence[c] = ev
        return scores, evidence

    # ------------------------------------------------------------- main API
    def recommend(self, user_id: int | None, prefs: Preferences | None = None, k: int = 12,
                  exclude: set[int] | None = None, texts: list[str] | None = None,
                  restrict_to: set[int] | None = None) -> RecResult:
        prefs = prefs or Preferences()
        exclude = set(exclude or set())
        texts = texts or []
        user_items = self.signals.user_items(user_id) if user_id is not None else {}
        positives = {b: v for b, v in user_items.items() if v >= 0.5}
        negatives = {b: v for b, v in user_items.items() if v < 0}
        exclude |= set(user_items)  # never recommend what the user already acted on
        cands = [b for b in self.books if b not in exclude and (restrict_to is None or b in restrict_to)]
        notes: list[str] = []
        if not cands:
            return RecResult([], "cold_start", [], self.cf.status(), ["No unseen books left in the catalogue."])

        # Pre-filter to a candidate pool using popularity + content for speed on large catalogues.
        raw: dict[str, dict[int, float]] = {}
        content_raw, nearest = self._content_scores(positives, negatives, prefs, texts, cands)
        if content_raw:
            raw["content"] = content_raw
        cf_scores = self.cf.score_user(user_items, cands) if self.cf.reliable else {}
        if cf_scores:
            raw["collaborative"] = {c: s.score for c, s in cf_scores.items()}
        elif user_items and not self.cf.reliable:
            notes.append("Picks from readers with similar taste will appear as more readers rate books.")
        raw["popularity"] = {c: self.popularity[c].score for c in cands if c in self.popularity}
        pref_ev: dict[int, dict] = {}
        if not prefs.empty:
            pref_raw, pref_ev = self._preference_scores(prefs, cands)
            raw["preference"] = pref_raw

        weights = {"content": self.config.w_content, "collaborative": self.config.w_collaborative,
                   "popularity": self.config.w_popularity, "preference": self.config.w_preference}
        normed: dict[str, dict[int, float]] = {}
        for s, d in raw.items():
            n = _minmax(d)
            if n is not None and weights[s] > 0:
                normed[s] = n
        total_w = sum(weights[s] for s in normed)
        final: dict[int, float] = {}
        contribs: dict[int, dict[str, float]] = {}
        for c in cands:
            parts = {s: weights[s] * normed[s].get(c, 0.0) / total_w for s in normed} if total_w else {}
            contribs[c] = parts
            final[c] = sum(parts.values())

        pool = sorted(cands, key=lambda c: final[c], reverse=True)[: self.config.pool_size]
        selected = self._mmr(pool, final, k)
        mode = "personalized" if positives else "cold_start"
        items = [self._explain(c, final[c], contribs[c], nearest, cf_scores, pref_ev, mode) for c in selected]
        return RecResult(items, mode, sorted(normed), self.cf.status(), notes)

    def _mmr(self, pool: list[int], final: dict[int, float], k: int) -> list[int]:
        lam = self.config.diversity_lambda
        selected: list[int] = []
        author_count: dict[str, int] = {}
        remaining = list(pool)
        while remaining and len(selected) < k:
            best, best_val = None, -1e9
            for c in remaining:
                if any(author_count.get(a, 0) >= self.config.max_per_author for a in self.books[c].authors):
                    continue
                redundancy = max((self.content.item_similarity(c, s) for s in selected), default=0.0)
                val = lam * final[c] - (1 - lam) * redundancy
                if val > best_val:
                    best, best_val = c, val
            if best is None:
                break
            selected.append(best)
            remaining.remove(best)
            for a in self.books[best].authors:
                author_count[a] = author_count.get(a, 0) + 1
        return selected

    def _explain(self, c: int, score: float, parts: dict[str, float], nearest, cf_scores, pref_ev, mode) -> Recommendation:
        reasons: list[Reason] = []
        ordered = sorted(parts.items(), key=lambda kv: kv[1], reverse=True)
        for signal, value in ordered:
            if value <= 0.02 or len(reasons) >= 2:
                continue
            if signal == "content" and c in nearest and nearest[c][1] > 0.05:
                ref, sim = nearest[c]
                reasons.append(Reason("content", f"Shares themes and subjects with “{self.books[ref].title}” from your reading activity.",
                                      {"similar_to_book_id": ref, "similarity": round(sim, 3)}))
            elif signal == "content":
                reasons.append(Reason("content", "Its description and subjects match your stated interests and recent searches.", {}))
            elif signal == "collaborative" and c in cf_scores and cf_scores[c].top_item:
                ref = cf_scores[c].top_item
                reasons.append(Reason("collaborative", f"Readers who liked “{self.books[ref].title}” also responded well to this book.",
                                      {"because_of_book_id": ref, "overlapping_items": cf_scores[c].support}))
            elif signal == "preference" and c in pref_ev:
                ev = pref_ev[c]
                bits = []
                if ev.get("authors"):
                    bits.append(f"is by {', '.join(ev['authors'])}, an author you follow")
                if ev.get("genres"):
                    bits.append(f"matches your favourite genres ({', '.join(g.title() for g in ev['genres'])})")
                if ev.get("length"):
                    bits.append(f"is a {ev['length']['preference']} read ({ev['length']['pages']} pages)")
                if ev.get("themes"):
                    bits.append(f"mentions {', '.join(ev['themes'])}")
                if bits:
                    reasons.append(Reason("preference", "This book " + " and ".join(bits[:2]) + ".", ev))
            elif signal == "popularity":
                p = self.popularity.get(c)
                if p and p.n_ratings >= 3:
                    reasons.append(Reason("popularity", f"Well rated by BookWorm readers ({p.mean_rating}★ from {p.n_ratings} ratings).",
                                          {"mean_rating": p.mean_rating, "n_ratings": p.n_ratings}))
                elif p and p.used_external:
                    ext = self.books[c].external_rating
                    reasons.append(Reason("popularity", f"Well regarded on an external catalogue ({ext[0]}★ from {ext[1]} ratings).",
                                          {"external_rating": ext[0], "external_count": ext[1]}))
                else:
                    reasons.append(Reason("popularity", "Popular with readers in this catalogue.", {}))
        if not reasons:
            reasons.append(Reason("popularity", "A general catalogue pick while we learn your taste.", {}))
        strategy = ordered[0][0] if ordered and ordered[0][1] > 0 else "popularity"
        return Recommendation(c, round(score, 4), {k: round(v, 4) for k, v in parts.items()}, reasons, strategy)
