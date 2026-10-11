"""Shared HTTP helpers: timeouts, a DB-backed response cache, and provider errors."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import as_utc
from app.models.book import ExternalCache

logger = logging.getLogger("bookworm.http")

USER_AGENT = "BookWorm/0.1 (open-source student project; local development)"


class ProviderError(Exception):
    """Raised when an external provider fails; carries a user-safe message."""

    def __init__(self, provider: str, message: str):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message


def client(timeout: float | None = None) -> httpx.Client:
    t = timeout or get_settings().external_http_timeout_seconds
    return httpx.Client(
        timeout=httpx.Timeout(t, connect=min(t, 5.0)),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        max_redirects=3,
    )


def cache_get(db: Session | None, key: str) -> Any | None:
    if db is None:
        return None
    row = db.get(ExternalCache, key)
    if row and as_utc(row.expires_at) > datetime.now(timezone.utc):
        return json.loads(row.payload)
    return None


def cache_put(db: Session | None, key: str, provider: str, payload: Any, ttl: timedelta) -> None:
    if db is None:
        return
    now = datetime.now(timezone.utc)
    row = db.get(ExternalCache, key)
    data = json.dumps(payload)
    if row:
        row.payload, row.fetched_at, row.expires_at = data, now, now + ttl
    else:
        db.add(ExternalCache(key=key[:300], provider=provider, payload=data, fetched_at=now, expires_at=now + ttl))
    try:
        db.commit()
    except Exception:  # cache failures must never break a request
        db.rollback()


def get_json(
    provider: str,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    db: Session | None = None,
    cache_key: str | None = None,
    ttl: timedelta | None = None,
    retries: int = 1,
) -> Any:
    """GET JSON with timeout, one retry on transient errors (idempotent GET only),
    and an optional DB-backed cache."""
    if cache_key:
        cached = cache_get(db, cache_key)
        if cached is not None:
            return cached
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with client() as c:
                resp = c.get(url, params=params, headers=headers)
            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                raise ProviderError(provider, "rate limited by provider")
            if resp.status_code >= 500 and attempt < retries:
                continue
            resp.raise_for_status()
            data = resp.json()
            if cache_key and ttl:
                cache_put(db, cache_key, provider, data, ttl)
            return data
        except ProviderError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt < retries:
                continue
        except (httpx.HTTPStatusError, ValueError) as exc:
            last_exc = exc
            break
    logger.warning("provider request failed", extra={"data": {"provider": provider, "error": type(last_exc).__name__}})
    raise ProviderError(provider, "unavailable or timed out")
