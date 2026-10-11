"""Content representation of books: TF-IDF (default) or sentence embeddings.

The model is *fitted* on the current catalogue (TfidfVectorizer.fit_transform)
and cached until the catalogue changes. Sentence-transformer embeddings are used
only when EMBEDDINGS_BACKEND=sentence-transformers and the optional package and
model are available locally; otherwise TF-IDF is used and the status endpoint
reports which backend is active.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.book import Book

logger = logging.getLogger("bookworm.recommender.content")

# Light query expansion so short natural-language queries hit catalogue vocabulary.
SYNONYMS = {
    "ml": "machine learning", "ai": "artificial intelligence machine learning", "dl": "deep learning",
    "coding": "programming software", "code": "programming software", "developer": "programming software",
    "finance": "personal finance money investing", "money": "personal finance money",
    "invest": "investing finance", "habits": "habit productivity self-help", "thriller": "thriller suspense mystery",
    "scary": "horror", "spooky": "horror", "romantic": "romance love", "space": "science fiction space astronaut",
    "scifi": "science fiction", "sci-fi": "science fiction", "motivational": "inspirational self-help",
    "inspiring": "inspirational", "startup": "entrepreneurship startup business", "data": "data science",
    "python": "python programming", "twist": "twist suspense psychological thriller",
    "mind": "psychology", "history": "history", "india": "indian", "indian": "indian",
}


def book_document(book: Book) -> str:
    subjects = [g.name for g in book.genres if g.kind != "genre"]
    curated = [g.name for g in book.genres if g.kind == "genre"]
    parts = [
        book.title, book.subtitle or "",
        " ".join(book.author_names),
        " ".join(subjects),
        # Curated genre tags are repeated so they carry more weight than long descriptions.
        " ".join(curated * 3),
        (book.description or "")[:2500],
    ]
    return " \n".join(p for p in parts if p)


def expand_query(text: str) -> str:
    words = re.findall(r"[a-z0-9\-]+", text.lower())
    extra = [SYNONYMS[w] for w in words if w in SYNONYMS]
    return text + " " + " ".join(extra)


@dataclass
class ContentModel:
    book_ids: list[int]
    index: dict[int, int]
    matrix: np.ndarray  # L2-normalised rows
    backend: str
    vectorizer: TfidfVectorizer | None = None
    encoder: object | None = None

    def vector(self, book_id: int) -> np.ndarray | None:
        i = self.index.get(book_id)
        return None if i is None else self.matrix[i]

    def encode_text(self, text: str) -> np.ndarray:
        if self.backend == "sentence-transformers" and self.encoder is not None:
            v = self.encoder.encode([text], normalize_embeddings=True)[0]  # type: ignore[attr-defined]
            return np.asarray(v, dtype=np.float32)
        v = self.vectorizer.transform([expand_query(text)]).toarray()[0]  # type: ignore[union-attr]
        n = np.linalg.norm(v)
        return v / n if n else v

    def similarities(self, vec: np.ndarray) -> np.ndarray:
        return self.matrix @ vec

    def item_similarity(self, a: int, b: int) -> float:
        va, vb = self.vector(a), self.vector(b)
        if va is None or vb is None:
            return 0.0
        return float(va @ vb)


def _try_sentence_transformer(docs: list[str]):
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError:
        logger.info("sentence-transformers not installed; using TF-IDF")
        return None, None
    try:
        model = SentenceTransformer(get_settings().embeddings_model)
        emb = model.encode(docs, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
        return model, np.asarray(emb, dtype=np.float32)
    except Exception:  # model download/load failures fall back to TF-IDF
        logger.warning("could not load sentence-transformer model; using TF-IDF", exc_info=True)
        return None, None


def fit_content_model(books: list[Book]) -> ContentModel:
    docs = [book_document(b) for b in books]
    ids = [b.id for b in books]
    index = {bid: i for i, bid in enumerate(ids)}
    if get_settings().embeddings_backend == "sentence-transformers" and docs:
        encoder, emb = _try_sentence_transformer(docs)
        if encoder is not None:
            return ContentModel(ids, index, emb, "sentence-transformers", encoder=encoder)
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1, max_df=0.6, sublinear_tf=True,
                          max_features=40000)
    if not docs:
        return ContentModel([], {}, np.zeros((0, 1), dtype=np.float32), "tfidf", vectorizer=vec.fit(["empty"]))
    m = vec.fit_transform(docs)
    m = normalize(m).toarray().astype(np.float32)
    return ContentModel(ids, index, m, "tfidf", vectorizer=vec)


_cache: dict = {"sig": None, "model": None}
_lock = threading.Lock()


def get_content_model(db: Session) -> ContentModel:
    """Cached model, refitted whenever the catalogue changes."""
    sig = tuple(db.execute(select(func.count(Book.id), func.max(Book.updated_at))).one())
    with _lock:
        if _cache["sig"] != sig or _cache["model"] is None:
            books = list(db.scalars(select(Book).order_by(Book.id)).unique())
            _cache["model"] = fit_content_model(books)
            _cache["sig"] = sig
            logger.info("content model fitted", extra={"data": {"books": len(books), "backend": _cache["model"].backend}})
        return _cache["model"]


def reset_cache() -> None:
    with _lock:
        _cache["sig"] = None
        _cache["model"] = None
