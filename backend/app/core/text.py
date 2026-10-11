"""Text normalisation and identifier helpers shared across modules."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_ARTICLES = re.compile(r"^(the|a|an)\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _ascii_lower(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def normalize_title(title: str) -> str:
    """Lowercase, strip accents, punctuation, a leading article and any subtitle."""
    t = _ascii_lower(title)
    head = t.split(":")[0]
    if len(head.strip()) >= 4:
        t = head
    t = _NON_ALNUM.sub(" ", t).strip()
    t = _ARTICLES.sub("", t)
    return re.sub(r"\s+", " ", t)


def normalize_name(name: str) -> str:
    n = _ascii_lower(name)
    return re.sub(r"\s+", " ", _NON_ALNUM.sub(" ", n)).strip()


def slugify(text: str) -> str:
    return normalize_name(text).replace(" ", "-")[:140] or "item"


def similarity(a: str, b: str) -> float:
    """Fuzzy title similarity in [0, 1] (max of sequence ratio and token Jaccard)."""
    a, b = normalize_title(a), normalize_title(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    seq = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    jacc = len(ta & tb) / len(ta | tb)
    return max(seq, jacc)


def clean_isbn(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"[^0-9Xx]", "", raw).upper()
    return s or None


def is_valid_isbn10(s: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dX]", s):
        return False
    total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s))
    return total % 11 == 0


def is_valid_isbn13(s: str) -> bool:
    if not re.fullmatch(r"\d{13}", s):
        return False
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s[:12]))
    return (10 - total % 10) % 10 == int(s[12])


def isbn10_to_13(s: str) -> str:
    core = "978" + s[:9]
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core))
    return core + str((10 - total % 10) % 10)


def to_isbn13(raw: str | None) -> str | None:
    """Return a valid ISBN-13 (converting ISBN-10 when needed), else None."""
    s = clean_isbn(raw)
    if not s:
        return None
    if len(s) == 13 and is_valid_isbn13(s):
        return s
    if len(s) == 10 and is_valid_isbn10(s):
        return isbn10_to_13(s)
    return None


ISBN_PATTERN = re.compile(r"(?<![\d])(97[89][\d-]{10,14}|\d{9}[\dXx])(?![\d])")


def find_isbn(text: str) -> str | None:
    for m in ISBN_PATTERN.finditer(text or ""):
        isbn = to_isbn13(m.group(1))
        if isbn:
            return isbn
    return None


def strip_control(text: str | None, max_len: int | None = None) -> str | None:
    """Remove control characters from untrusted text and optionally truncate."""
    if text is None:
        return None
    t = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C").strip()
    return t[:max_len] if max_len else t
