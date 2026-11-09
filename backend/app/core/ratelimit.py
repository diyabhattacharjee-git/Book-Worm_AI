"""Small in-memory sliding-window rate limiter.

Good enough for a single-process deployment. With several workers each process
keeps its own counters (documented limitation in docs/SECURITY.md)."""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


PRUNE_EVERY_CHECKS = 2000
MAX_WINDOW_SECONDS = 86400


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._checks = 0
        self.enabled = True

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            self._checks += 1
            if self._checks % PRUNE_EVERY_CHECKS == 0:
                for stale in [k for k, hits in self._hits.items() if not hits or now - hits[-1] > MAX_WINDOW_SECONDS]:
                    del self._hits[stale]
            q = self._hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                retry = int(window_seconds - (now - q[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please slow down and try again shortly.",
                    headers={"Retry-After": str(retry)},
                )
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    # On Vercel every request arrives from the platform's proxy, which sets this header itself.
    if os.environ.get("VERCEL"):
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit: int, window_seconds: int):
    """FastAPI dependency factory: limit requests per client IP for a named bucket."""

    def _dep(request: Request) -> None:
        limiter.check(f"{name}:{client_ip(request)}", limit, window_seconds)

    return _dep
