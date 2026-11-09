"""Free-tier protection for external APIs: caching, backoff, circuit breaker and fallbacks."""

from datetime import timedelta

import httpx
import pytest

from app.core.config import get_settings
from app.integrations import ebay, http, metadata
from app.integrations.http import ProviderError, get_json


@pytest.fixture(autouse=True)
def _clean_state(db, monkeypatch):
    from sqlalchemy import delete

    from app.models.book import ExternalCache

    db.execute(delete(ExternalCache))
    db.commit()
    http.reset_breakers()
    monkeypatch.setattr(http.time, "sleep", lambda _: None)
    yield
    http.reset_breakers()


class FakeApi:
    """Replaces the HTTP client and counts how many requests really went out."""

    def __init__(self, monkeypatch, handler):
        self.calls = []

        def wrapped(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return handler(request, len(self.calls))

        monkeypatch.setattr(http, "client", lambda timeout=None: httpx.Client(transport=httpx.MockTransport(wrapped)))


GOOGLE_DAILY = {"error": {"code": 429, "message": "Quota exceeded for quota metric 'Queries' and limit 'Queries per day'",
                          "errors": [{"reason": "rateLimitExceeded"}]}}
TTL = timedelta(hours=1)


def test_cached_response_makes_no_second_request(db, monkeypatch):
    api = FakeApi(monkeypatch, lambda r, n: httpx.Response(200, json={"ok": n}))
    assert get_json("x", "https://x.test/a", db=db, cache_key="k1", ttl=TTL) == {"ok": 1}
    assert get_json("x", "https://x.test/a", db=db, cache_key="k1", ttl=TTL) == {"ok": 1}
    assert len(api.calls) == 1


def test_not_found_is_remembered(db, monkeypatch):
    api = FakeApi(monkeypatch, lambda r, n: httpx.Response(404))
    assert get_json("x", "https://x.test/a", db=db, cache_key="k2", ttl=TTL) is None
    assert get_json("x", "https://x.test/a", db=db, cache_key="k2", ttl=TTL) is None
    assert len(api.calls) == 1


def test_transient_errors_retry_with_backoff_then_succeed(db, monkeypatch):
    api = FakeApi(monkeypatch, lambda r, n: httpx.Response(503) if n < 3 else httpx.Response(200, json={"ok": True}))
    assert get_json("x", "https://x.test/a", db=db) == {"ok": True}
    assert len(api.calls) == 3


def test_google_daily_quota_stops_all_further_calls(db, monkeypatch):
    api = FakeApi(monkeypatch, lambda r, n: httpx.Response(429, json=GOOGLE_DAILY))
    with pytest.raises(ProviderError) as first:
        get_json("google_books", "https://g.test/a", db=db, cache_key="g1", ttl=TTL)
    assert first.value.retry_after and first.value.retry_after > 60, "waits for the daily reset, not a short pause"
    assert len(api.calls) == 1, "a quota error is never retried"
    with pytest.raises(ProviderError):
        get_json("google_books", "https://g.test/b", db=db, cache_key="g2", ttl=TTL)
    assert len(api.calls) == 1, "the open breaker prevents another wasted request"


def test_breaker_state_survives_a_new_server_instance(db, monkeypatch):
    api = FakeApi(monkeypatch, lambda r, n: httpx.Response(429, json=GOOGLE_DAILY))
    with pytest.raises(ProviderError):
        get_json("google_books", "https://g.test/a", db=db, cache_key="g3", ttl=TTL)
    http.reset_breakers()  # what a cold start looks like
    with pytest.raises(ProviderError):
        get_json("google_books", "https://g.test/b", db=db, cache_key="g4", ttl=TTL)
    assert len(api.calls) == 1


def test_rate_limit_respects_retry_after(db, monkeypatch):
    api = FakeApi(monkeypatch, lambda r, n: httpx.Response(429, headers={"Retry-After": "7"}))
    with pytest.raises(ProviderError) as err:
        get_json("open_library", "https://o.test/a", db=db)
    assert err.value.retry_after == 7 and len(api.calls) == 1


def test_expired_data_is_better_than_an_error(db, monkeypatch):
    from datetime import datetime, timezone

    from app.models.book import ExternalCache

    FakeApi(monkeypatch, lambda r, n: httpx.Response(200, json={"v": 1}))
    get_json("x", "https://x.test/a", db=db, cache_key="k3", ttl=TTL)
    row = db.get(ExternalCache, "k3")
    row.expires_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()
    FakeApi(monkeypatch, lambda r, n: httpx.Response(500))
    assert get_json("x", "https://x.test/a", db=db, cache_key="k3", ttl=TTL, retries=0) == {"v": 1}


def _ol_doc(i):
    return {"key": f"/works/OL{i}W", "title": f"Book {i}", "author_name": ["A"], "isbn": []}


def _gb_item(i):
    return {"id": f"g{i}", "volumeInfo": {"title": f"Google {i}", "authors": ["G"]}}


def test_search_shows_both_providers_and_falls_back(db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "enable_open_library", True)
    monkeypatch.setattr(s, "enable_google_books", True)

    def both(request, n):
        if "openlibrary" in str(request.url):
            return httpx.Response(200, json={"docs": [_ol_doc(i) for i in range(8)]})
        return httpx.Response(200, json={"items": [_gb_item(i) for i in range(8)]})

    FakeApi(monkeypatch, both)
    results, errors = metadata.search_metadata("Popular Book", db)
    assert errors == [] and len(results) == 16
    assert [r.source for r in results[:4]] == ["google_books", "open_library", "google_books", "open_library"], "both near the top"

    def out_of_quota(request, n):
        if "openlibrary" in str(request.url):
            return httpx.Response(200, json={"docs": [_ol_doc(1)]})
        return httpx.Response(429, json=GOOGLE_DAILY)

    FakeApi(monkeypatch, out_of_quota)
    results, errors = metadata.search_metadata("Rare Book", db)
    assert len(results) == 1, "Open Library's results survive Google being out of quota"
    assert errors == ["Google Books: daily limit reached"]


def test_query_cache_ignores_case_and_spacing(db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "enable_open_library", True)
    api = FakeApi(monkeypatch, lambda r, n: httpx.Response(200, json={"docs": []}))
    metadata.ol_search("Atomic  Habits", db)
    metadata.ol_search("atomic habits", db)
    assert len(api.calls) == 1


class FakeEbay:
    def __init__(self, monkeypatch, status=200, body=None):
        self.calls = []
        self.status = status
        self.body = body if body is not None else {"itemSummaries": []}

        def get(url, params=None, headers=None, timeout=None):
            self.calls.append(params)
            return httpx.Response(self.status, json=self.body, request=httpx.Request("GET", url))

        monkeypatch.setattr(ebay.httpx, "get", get)
        monkeypatch.setattr(ebay, "_get_token", lambda: "t")


@pytest.fixture
def ebay_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ebay_client_id", "id")
    monkeypatch.setattr(s, "ebay_client_secret", "secret")


def test_ebay_searches_are_cached_and_isbn_is_exact(db, monkeypatch, ebay_on):
    item = {"itemId": "1", "title": "Dune", "itemWebUrl": "https://www.ebay.com/itm/1", "price": {"value": "9.00", "currency": "USD"}}
    api = FakeEbay(monkeypatch, body={"itemSummaries": [item]})
    first = ebay.search("Dune Frank Herbert", isbn="9780441013593", db=db)
    assert first[0].isbn == "9780441013593", "a gtin match identifies the edition"
    assert api.calls[0]["gtin"] == "9780441013593" and "q" not in api.calls[0]
    ebay.search("Dune Frank Herbert", isbn="9780441013593", db=db)
    assert len(api.calls) == 1


def test_ebay_rate_limit_pauses_calls(db, monkeypatch, ebay_on):
    api = FakeEbay(monkeypatch, status=429)
    with pytest.raises(ProviderError):
        ebay.search("Dune", db=db)
    with pytest.raises(ProviderError):
        ebay.search("Another title", db=db)
    assert len(api.calls) == 1


def test_external_search_reports_a_provider_outage_without_failing(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "enable_open_library", True)
    FakeApi(monkeypatch, lambda r, n: httpx.Response(500))
    body = client.get("/api/books/external-search", params={"q": "something rare"}).json()
    assert body["results"] == [] and "Open Library" in body["errors"][0]
