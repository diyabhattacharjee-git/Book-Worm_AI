"""eBay Marketplace Account Deletion endpoint (needed for eBay production keys)."""

import hashlib
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.marketplace import CachedExternalListing

URL = "/api/ebay/account-deletion"
TOKEN = "bookworm_verification_token_0123456789-abc"
ENDPOINT = "https://bookworm.example.com/api/ebay/account-deletion"


@pytest.fixture
def configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ebay_verification_token", TOKEN)
    monkeypatch.setattr(s, "ebay_deletion_endpoint", ENDPOINT)


def test_disabled_until_configured(client):
    assert client.get(URL, params={"challenge_code": "x"}).status_code == 404


def test_challenge_response_matches_ebay_spec(client, configured):
    r = client.get(URL, params={"challenge_code": "a8628072-3d33-45ee-9004-bee86830a22d"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    expected = hashlib.sha256(("a8628072-3d33-45ee-9004-bee86830a22d" + TOKEN + ENDPOINT).encode()).hexdigest()
    assert r.json() == {"challengeResponse": expected}
    assert client.get(URL).status_code == 400


def test_notification_deletes_that_sellers_cached_listings(client, db, configured):
    now = datetime.now(timezone.utc)
    for ext, seller in (("del-1", "closing_seller"), ("del-2", "closing_seller"), ("keep-1", "other_seller")):
        db.add(CachedExternalListing(provider="ebay", external_id=ext, normalized_title="atomic habits",
                                     payload={"seller_name": seller}, fetched_at=now))
    db.commit()
    body = {"metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION", "schemaVersion": "1.0", "deprecated": False},
            "notification": {"notificationId": "n1", "eventDate": "2026-10-12T00:00:00.000Z",
                             "publishDate": "2026-10-12T00:00:00.000Z", "publishAttemptCount": 1,
                             "data": {"username": "closing_seller", "userId": "u1", "eiasToken": "t"}}}
    # eBay sends no X-Requested-With header; the webhook must not be blocked by CSRF protection.
    r = client.post(URL, json=body, headers={"X-Requested-With": ""})
    assert r.status_code == 204
    db.expire_all()
    left = db.scalars(select(CachedExternalListing.external_id).where(
        CachedExternalListing.external_id.in_(["del-1", "del-2", "keep-1"]))).all()
    assert left == ["keep-1"]
    # Malformed bodies are still acknowledged so eBay doesn't retry forever.
    assert client.post(URL, content=b"not json", headers={"X-Requested-With": ""}).status_code == 204
