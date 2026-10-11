"""Natural-language book search.

1. A deterministic parser pulls structured constraints out of the sentence
   (length, language, "similar to <title>", skill level, budget-ish wording).
2. Candidates are filtered by those constraints, then scored:
       final = 0.60 * semantic + 0.25 * lexical + 0.15 * quality (+0.10 level match)
   semantic = cosine(query, book) using the active content backend (TF-IDF or
   sentence embeddings), lexical = keyword relevance, quality = Bayesian rating.
3. Refinements ("shorter", "more technical", "cheaper copies") modify the
   previous parsed query, so follow-ups work without retyping.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

import numpy as np
from sqlalchemy.orm import Session

from app.models.book import Book
from app.recommender.content import get_content_model
from app.recommender.service import get_recommender
from app.repositories.books import (
    difficulty_signal,
    find_by_title,
    get_books,
    relevance,
    summaries,
    used_stats,
)

LANG_WORDS = {"hindi": "hi", "english": "en", "bengali": "bn", "bangla": "bn", "tamil": "ta", "spanish": "es",
              "french": "fr", "german": "de", "japanese": "ja", "marathi": "mr", "telugu": "te"}

FILLER = re.compile(
    r"\b(i\s+want|i'?d\s+like|i\s+need|looking\s+for|suggest|recommend|find|show\s+me|give\s+me|can\s+you|please|"
    r"something|some|a\s+book|books?|novels?|to\s+read|that\s+i\s+can|me)\b", re.I)


@dataclass
class ParsedQuery:
    text: str
    semantic_text: str
    pages_max: int | None = None
    pages_min: int | None = None
    language: str | None = None
    level: str | None = None  # beginner | advanced
    similar_to_book_id: int | None = None
    similar_to_title: str | None = None
    used_only: bool = False
    sort_by_price: bool = False
    notes: list[str] = field(default_factory=list)

    def describe(self) -> list[str]:
        out = []
        if self.similar_to_title:
            out.append(f"similar to “{self.similar_to_title}”")
        if self.pages_max:
            out.append(f"≤ {self.pages_max} pages")
        if self.pages_min:
            out.append(f"≥ {self.pages_min} pages")
        if self.language:
            out.append(f"language: {self.language}")
        if self.level:
            out.append(f"level: {self.level}")
        if self.used_only:
            out.append("has used copies" + (", cheapest first" if self.sort_by_price else ""))
        return out


def parse_query(db: Session, text: str) -> ParsedQuery:
    t = text.strip()
    low = t.lower()
    pq = ParsedQuery(text=t, semantic_text=t)
    if re.search(r"\b(weekend|short|quick|light read|one sitting|under\s+200\s+pages)\b", low):
        pq.pages_max = 250
    m = re.search(r"(?:under|less than|fewer than|below|max(?:imum)?)\s+(\d{2,4})\s+pages", low)
    if m:
        pq.pages_max = int(m.group(1))
    m = re.search(r"(?:over|more than|at least)\s+(\d{2,4})\s+pages", low)
    if m:
        pq.pages_min = int(m.group(1))
    if re.search(r"\b(long|epic|doorstopper)\b", low) and not pq.pages_max:
        pq.pages_min = pq.pages_min or 450
    for word, code in LANG_WORDS.items():
        if re.search(rf"\b(in|written in)\s+{word}\b", low):
            pq.language = code
    if re.search(r"\b(beginner|beginners|newbie|introduct\w*|first book|from scratch|no experience|easy)\b", low):
        pq.level = "beginner"
    elif re.search(r"\b(advanced|in-depth|deep dive|expert|rigorous)\b", low):
        pq.level = "advanced"
    if re.search(r"\b(used|second[- ]hand|cheap|affordable|budget)\b", low):
        pq.used_only = True
        pq.sort_by_price = bool(re.search(r"\b(cheap|cheapest|affordable|budget)\b", low))
    m = re.search(r"(?:similar to|like|books like|in the style of)\s+[\"“']?(.+?)[\"”']?\s*(?:[.?!]|$|\bbut\b)", t, re.I)
    if m:
        cand = m.group(1).strip()
        matches = find_by_title(db, cand, limit=1)
        if matches and matches[0][1] >= 0.75:
            book = matches[0][0]
            pq.similar_to_book_id, pq.similar_to_title = book.id, book.title
        elif len(cand) > 2:
            pq.notes.append(f"“{cand}” isn't in the catalogue, so it was treated as keywords.")
    sem = FILLER.sub(" ", t)
    pq.semantic_text = re.sub(r"\s+", " ", sem).strip() or t
    return pq


def apply_refinement(prev: dict, refinement: str) -> ParsedQuery:
    pq = ParsedQuery(**{k: v for k, v in prev.items() if k in ParsedQuery.__dataclass_fields__})
    low = refinement.lower()
    applied = []
    if re.search(r"\b(shorter|less long|quicker)\b", low):
        pq.pages_max = int((pq.pages_max or 400) * 0.75)
        pq.pages_min = None
        applied.append(f"≤ {pq.pages_max} pages")
    if re.search(r"\b(longer|more depth)\b", low):
        pq.pages_min = max(pq.pages_max or 300, 300)
        pq.pages_max = None
        applied.append(f"≥ {pq.pages_min} pages")
    if re.search(r"\b(more technical|more advanced|harder|deeper)\b", low):
        pq.level = "advanced"
        pq.semantic_text += " technical advanced in-depth"
        applied.append("more technical")
    if re.search(r"\b(less technical|simpler|easier|beginner)\b", low):
        pq.level = "beginner"
        applied.append("simpler")
    if re.search(r"\b(cheaper|less expensive|budget|used)\b", low):
        pq.used_only = True
        pq.sort_by_price = True
        applied.append("cheaper used copies first")
    leftover = re.sub(r"\b(shorter|longer|more|less|technical|advanced|simpler|easier|cheaper|expensive|copies|books?|"
                      r"something|please|show|me|only|and|a|bit)\b", " ", low).strip()
    if len(leftover) > 3:
        pq.semantic_text += " " + leftover
        applied.append(f"also about “{leftover}”")
    pq.text = f"{pq.text} → {refinement}"
    pq.notes = [f"Refined: {', '.join(applied) or 'no recognised refinement; kept previous filters'}"]
    return pq


def run_search(db: Session, pq: ParsedQuery, limit: int = 12) -> dict:
    model = get_content_model(db)
    rec = get_recommender(db)
    qvec = model.encode_text(pq.semantic_text)
    if pq.similar_to_book_id is not None:
        bvec = model.vector(pq.similar_to_book_id)
        if bvec is not None:
            qvec = 0.7 * bvec + 0.3 * qvec
            qvec = qvec / (np.linalg.norm(qvec) or 1.0)
    sims = model.similarities(qvec) if model.matrix.shape[0] else np.array([])
    books = {b.id: b for b in get_books(db, model.book_ids)}
    used = used_stats(db, list(books)) if pq.used_only else {}
    scored = []
    for i, bid in enumerate(model.book_ids):
        b: Book | None = books.get(bid)
        if b is None or bid == pq.similar_to_book_id:
            continue
        if pq.pages_max and (b.page_count is None or b.page_count > pq.pages_max):
            continue
        if pq.pages_min and (b.page_count is None or b.page_count < pq.pages_min):
            continue
        if pq.language and b.language and b.language != pq.language:
            continue
        if pq.used_only and bid not in used:
            continue
        sem = float(sims[i]) if len(sims) else 0.0
        lex = min(1.0, relevance(b, pq.semantic_text) / 6.0)
        pop = rec.popularity.get(bid)
        quality = (pop.bayes_rating - 1) / 4 if pop else 0.5
        level_bonus, level_ev = 0.0, None
        sig = difficulty_signal(b)
        if pq.level == "beginner" and sig and any(w in sig.lower() for w in ("beginner", "introduction", "no prior")):
            level_bonus, level_ev = 0.10, sig
        if pq.level == "advanced" and sig and any(w in sig.lower() for w in ("advanced", "graduate", "rigorous")):
            level_bonus, level_ev = 0.10, sig
        score = 0.60 * sem + 0.25 * lex + 0.15 * quality + level_bonus
        if sem < 0.02 and lex == 0 and pq.similar_to_book_id is None:
            continue
        why = []
        if pq.similar_to_title:
            why.append(f"close in themes to “{pq.similar_to_title}”")
        q_terms = {w for w in re.findall(r"[a-z]{4,}", pq.semantic_text.lower())}
        genre_hits = [g.name for g in b.genres if any(w in g.name.lower() for w in q_terms)][:3]
        if genre_hits:
            why.append("matches " + ", ".join(genre_hits))
        if pq.pages_max and b.page_count:
            why.append(f"{b.page_count} pages")
        if level_ev:
            why.append(level_ev.lower())
        if pq.used_only and bid in used:
            why.append(f"used from {used[bid][2]} {used[bid][1]:.0f}")
        scored.append((score, b, why, round(sem, 3)))
    if pq.sort_by_price:
        scored.sort(key=lambda x: (used.get(x[1].id, (0, 1e12, None))[1], -x[0]))
    else:
        scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]
    sums = summaries(db, [b for _, b, _, _ in top])
    results = [{"book": s.model_dump(), "score": round(sc, 4), "semantic_similarity": sem, "why": why}
               for s, (sc, _, why, sem) in zip(sums, top)]
    return {
        "query": asdict(pq),
        "interpreted_as": pq.describe(),
        "results": results,
        "search_backend": f"semantic ({model.backend}) + keyword + rating",
        "notes": pq.notes + ([] if results else ["No catalogue books matched. Try fewer constraints or import a book by ISBN."]),
    }
