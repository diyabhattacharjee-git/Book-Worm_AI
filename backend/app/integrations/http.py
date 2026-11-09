"""Shared HTTP helpers for every free external API.

Goal: spend as little of each provider's free quota as possible and stay useful
when a quota runs out.

* DB-backed response cache, including negative caching of "not found".
* Stale-if-error: an expired cached response is better than an error page.
* Single-flight: identical concurrent lookups share one upstream request.
* Exponential backoff with jitter, for transient failures only (5xx, network).
* Circuit breaker: after a rate-limit or quota response the provider is left
  alone until it can have recovered. The state is also written to the database,
  so a fresh serverless instance doesn't burn another request to rediscover it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import as_utc
from app.models.book import ExternalCache

logger = logging.getLogger("bookworm.http")

USER_AGENT = "BookWorm/1.0 (open-source book discovery project)"

NEGATIVE_MARKER = {"__not_found__": True}
NEGATIVE_TTL = timedelta(hours=6)
STALE_RETENTION = timedelta(days=30)
MAX_KEY_LENGTH = 300
BACKOFF_BASE_SECONDS = 0.4
RETRY_BUDGET_SECONDS = 12.0
FAILURES_BEFORE_OPEN = 3
TRANSIENT_COOLDOWN_SECONDS = 60
DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 60
MAX_COOLDOWN_SECONDS = 24 * 3600
_GOOGLE_RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded", "quotaExceeded"}


class ProviderError(Exception):
    """Raised when an external provider fails; carries a user-safe message."""

    def __init__(self, provider: str, message: str, retry_after: int | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message
        self.retry_after = retry_after


def client(timeout: float | None = None) -> httpx.Client:
    t = timeout or get_settings().external_http_timeout_seconds
    return httpx.Client(
        timeout=httpx.Timeout(t, connect=min(t, 5.0)),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        max_redirects=3,
    )


# ------------------------------------------------------------------- cache
def _safe_key(key: str) -> str:
    """Primary keys are limited to 300 characters; hash anything longer."""
    if len(key) <= MAX_KEY_LENGTH:
        return key
    return f"{key[:200]}#{hashlib.sha256(key.encode()).hexdigest()}"


def cache_get(db: Session | None, key: str, *, allow_stale: bool = False) -> Any | None:
    if db is None:
        return None
    row = db.get(ExternalCache, _safe_key(key))
    if row and (allow_stale or as_utc(row.expires_at) > datetime.now(timezone.utc)):
        return json.loads(row.payload)
    return None


def cache_put(db: Session | None, key: str, provider: str, payload: Any, ttl: timedelta) -> None:
    if db is None:
        return
    now = datetime.now(timezone.utc)
    safe = _safe_key(key)
    data = json.dumps(payload)
    row = db.get(ExternalCache, safe)
    if row:
        row.payload, row.fetched_at, row.expires_at = data, now, now + ttl
    else:
        db.add(ExternalCache(key=safe, provider=provider, payload=data, fetched_at=now, expires_at=now + ttl))
    try:
        if random.random() < 0.01:  # occasional housekeeping; stale rows are only useful for a while
            db.execute(delete(ExternalCache).where(ExternalCache.expires_at < now - STALE_RETENTION))
        db.commit()
    except Exception:  # cache failures must never break a request
        db.rollback()


# --------------------------------------------------------- circuit breaker
_breaker_lock = threading.Lock()
_open_until: dict[str, float] = {}
_consecutive_failures: dict[str, int] = {}


def _breaker_key(provider: str) -> str:
    return f"breaker:{provider}"


def open_breaker(provider: str, seconds: float, reason: str, db: Session | None = None) -> None:
    seconds = max(1.0, min(float(seconds), MAX_COOLDOWN_SECONDS))
    with _breaker_lock:
        _open_until[provider] = time.time() + seconds
    logger.warning("provider paused", extra={"data": {"provider": provider, "seconds": int(seconds), "reason": reason}})
    cache_put(db, _breaker_key(provider), "breaker", {"reason": reason}, timedelta(seconds=seconds))


def breaker_remaining(provider: str, db: Session | None = None) -> int:
    """Seconds until the provider may be called again (0 = closed)."""
    now = time.time()
    with _breaker_lock:
        until = _open_until.get(provider, 0.0)
    if until > now:
        return int(until - now) + 1
    if db is not None:
        row = db.get(ExternalCache, _breaker_key(provider))
        if row:
            left = (as_utc(row.expires_at) - datetime.now(timezone.utc)).total_seconds()
            if left > 0:
                with _breaker_lock:
                    _open_until[provider] = now + left
                return int(left) + 1
    return 0


def _record_outcome(provider: str, ok: bool, db: Session | None) -> None:
    with _breaker_lock:
        if ok:
            _consecutive_failures.pop(provider, None)
            return
        failures = _consecutive_failures.get(provider, 0) + 1
        _consecutive_failures[provider] = 0 if failures >= FAILURES_BEFORE_OPEN else failures
    if failures >= FAILURES_BEFORE_OPEN:
        open_breaker(provider, TRANSIENT_COOLDOWN_SECONDS, "repeated failures", db)


def reset_breakers() -> None:
    with _breaker_lock:
        _open_until.clear()
        _consecutive_failures.clear()


def seconds_until_google_quota_reset(now: datetime | None = None) -> int:
    """Google's daily quotas reset at midnight Pacific; 08:00 UTC is safe all year round."""
    now = now or datetime.now(timezone.utc)
    reset = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if reset <= now:
        reset += timedelta(days=1)
    return int((reset - now).total_seconds())


def _parse_retry_after(resp: httpx.Response) -> int | None:
    raw = resp.headers.get("retry-after")
    try:
        return max(1, int(float(raw))) if raw else None
    except ValueError:
        return None


def _google_limit(resp: httpx.Response) -> tuple[bool, bool]:
    """(is a rate/quota response, is the daily quota)."""
    try:
        err = resp.json().get("error", {})
    except (ValueError, AttributeError):
        return resp.status_code == 429, False
    reasons = {e.get("reason") for e in err.get("errors", []) if isinstance(e, dict)}
    message = str(err.get("message", "")).lower()
    is_limit = resp.status_code == 429 or bool(reasons & _GOOGLE_RATE_REASONS)
    daily = "per day" in message or "dailyLimitExceeded" in reasons or "quotaExceeded" in reasons
    return is_limit, is_limit and daily


def _raise_if_limited(provider: str, resp: httpx.Response, db: Session | None) -> None:
    daily = False
    limited = resp.status_code == 429
    if provider == "google_books" and resp.status_code in (403, 429):
        limited, daily = _google_limit(resp)
    if not limited:
        return
    wait = seconds_until_google_quota_reset() if daily else (_parse_retry_after(resp) or DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS)
    open_breaker(provider, wait, "daily quota" if daily else "rate limited", db)
    raise ProviderError(provider, "daily limit reached" if daily else "rate limited", retry_after=wait)


# -------------------------------------------------------------- single flight
_flight_lock = threading.Lock()
_in_flight: dict[str, threading.Event] = {}


def _join_flight(key: str) -> threading.Event | None:
    """Register as the leader for `key` (returns None) or get the leader's event to wait on."""
    with _flight_lock:
        event = _in_flight.get(key)
        if event is None:
            _in_flight[key] = threading.Event()
        return event


def _finish_flight(key: str) -> None:
    with _flight_lock:
        event = _in_flight.pop(key, None)
    if event:
        event.set()


def _sleep_backoff(attempt: int) -> None:
    time.sleep(BACKOFF_BASE_SECONDS * (2 ** attempt) + random.uniform(0, 0.2))


def _decode_cached(cached: Any) -> Any:
    return None if cached == NEGATIVE_MARKER else cached


def get_json(
    provider: str,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    db: Session | None = None,
    cache_key: str | None = None,
    ttl: timedelta | None = None,
    retries: int = 2,
) -> Any:
    """GET JSON through the cache, breaker and retry policy described at the top of this module."""
    if cache_key:
        cached = cache_get(db, cache_key)
        if cached is not None:
            return _decode_cached(cached)

    waiting = _join_flight(cache_key) if cache_key else None
    if waiting is not None:
        waiting.wait(timeout=get_settings().external_http_timeout_seconds + 2)
        cached = cache_get(db, cache_key)
        if cached is not None:
            return _decode_cached(cached)

    try:
        return _fetch(provider, url, params, headers, db, cache_key, ttl, retries)
    except ProviderError:
        stale = cache_get(db, cache_key, allow_stale=True) if cache_key else None
        if stale is not None:
            logger.info("serving stale data", extra={"data": {"provider": provider}})
            return _decode_cached(stale)
        raise
    finally:
        if cache_key and waiting is None:
            _finish_flight(cache_key)


def _fetch(provider: str, url: str, params: dict | None, headers: dict | None, db: Session | None,
           cache_key: str | None, ttl: timedelta | None, retries: int) -> Any:
    remaining = breaker_remaining(provider, db)
    if remaining:
        raise ProviderError(provider, "temporarily paused to stay within its free limit", retry_after=remaining)

    started = time.monotonic()
    last_error = "unavailable"
    for attempt in range(retries + 1):
        may_retry = attempt < retries and time.monotonic() - started < RETRY_BUDGET_SECONDS
        try:
            with client() as c:
                resp = c.get(url, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = type(exc).__name__
            if may_retry and not isinstance(exc, httpx.TimeoutException):
                _sleep_backoff(attempt)
                continue
            if may_retry and attempt == 0:  # a timeout already cost several seconds: one more try at most
                continue
            break

        if resp.status_code == 404:
            _record_outcome(provider, True, db)
            if cache_key:
                cache_put(db, cache_key, provider, NEGATIVE_MARKER, NEGATIVE_TTL)
            return None
        _raise_if_limited(provider, resp, db)
        if resp.status_code >= 500:
            last_error = f"HTTP {resp.status_code}"
            if may_retry:
                _sleep_backoff(attempt)
                continue
            break
        if resp.status_code >= 400:
            # Bad key or bad request: retrying can't help.
            logger.warning("provider rejected request", extra={"data": {"provider": provider, "status": resp.status_code}})
            if resp.status_code in (401, 403):
                open_breaker(provider, 3600, f"HTTP {resp.status_code}", db)
            raise ProviderError(provider, "unavailable")
        try:
            data = resp.json()
        except ValueError:
            last_error = "invalid JSON"
            break
        _record_outcome(provider, True, db)
        if cache_key and ttl:
            cache_put(db, cache_key, provider, data, ttl)
        return data

    _record_outcome(provider, False, db)
    logger.warning("provider request failed", extra={"data": {"provider": provider, "error": last_error}})
    raise ProviderError(provider, "unavailable or timed out")
