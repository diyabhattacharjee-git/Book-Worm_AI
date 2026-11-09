"""eBay seller tools against a simulated eBay: connect, publish, resume, end, and safety rules."""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.config import get_settings
from app.integrations import ebay_seller as seller
from app.integrations.http import reset_breakers
from app.security.tokens import create_purpose_token

BASE = {"title": "An Unusual Field Guide", "author": "James Clear", "isbn": "9780306406157", "condition": "good", "price_amount": 450,
        "currency": "INR", "delivery": "shipping", "shipping_cost": 40, "location_city": "Kolkata",
        "description": "Clean copy with a few highlighted lines."}
PUBLISH = {"price": 9.5, "fulfillment_policy_id": "F1", "payment_policy_id": "P1", "return_policy_id": "R1", "merchant_location_key": "bookworm-1"}


class FakeEbaySell:
    def __init__(self, monkeypatch):
        self.requests = []
        self.overrides = {}
        monkeypatch.setattr(seller.httpx, "post", self._token)
        monkeypatch.setattr(seller.httpx, "request", self._api)
        monkeypatch.setattr(seller.time, "sleep", lambda _: None)

    def _token(self, url, data=None, headers=None, timeout=None):
        self.requests.append(("TOKEN", data["grant_type"], None))
        return httpx.Response(200, json={"access_token": "ACCESS", "expires_in": 7200, "refresh_token": "REFRESH-SECRET",
                                         "refresh_token_expires_in": 47304000}, request=httpx.Request("POST", url))

    def _api(self, method, url, json=None, params=None, headers=None, timeout=None):
        path = urlparse(url).path
        self.requests.append((method, path, json))
        request = httpx.Request(method, url)
        for (m, p), response in self.overrides.items():
            if m == method and path.endswith(p):
                return httpx.Response(response[0], json=response[1], request=request)
        if "/inventory_item/" in path:
            assert headers["Content-Language"] == "en-US"
            return httpx.Response(204, request=request)
        if path.endswith("/offer") and method == "POST":
            return httpx.Response(201, json={"offerId": "OFFER-1"}, request=request)
        if path.endswith("/publish"):
            return httpx.Response(200, json={"listingId": "1234567"}, request=request)
        if path.endswith("/withdraw"):
            return httpx.Response(200, json={}, request=request)
        if "/offer/" in path and method == "PUT":
            return httpx.Response(204, request=request)
        if path.endswith("/fulfillment_policy"):
            return httpx.Response(200, json={"fulfillmentPolicies": [{"fulfillmentPolicyId": "F1", "name": "Standard"}]}, request=request)
        if path.endswith("/payment_policy"):
            return httpx.Response(200, json={"paymentPolicies": [{"paymentPolicyId": "P1", "name": "Pay"}]}, request=request)
        if path.endswith("/return_policy"):
            return httpx.Response(200, json={"returnPolicies": [{"returnPolicyId": "R1", "name": "30 days"}]}, request=request)
        if path.endswith("/location") and method == "GET":
            return httpx.Response(200, json={"locations": []}, request=request)
        if "/location/" in path and method == "POST":
            return httpx.Response(204, request=request)
        return httpx.Response(404, json={"errors": [{"message": "unknown"}]}, request=request)

    def paths(self, method=None):
        return [p for m, p, _ in self.requests if m != "TOKEN" and (method is None or m == method)]

    def body(self, suffix):
        return next(b for m, p, b in self.requests if p.endswith(suffix) and b)


@pytest.fixture
def ebay(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ebay_client_id", "client")
    monkeypatch.setattr(s, "ebay_client_secret", "secret")
    monkeypatch.setattr(s, "ebay_runame", "Run-Name")
    monkeypatch.setattr(s, "public_base_url", "https://books.example.com")
    seller._access_tokens.clear()
    reset_breakers()
    yield FakeEbaySell(monkeypatch)
    seller._access_tokens.clear()


def connect(c, user):
    state = create_purpose_token(str(user["id"]), "ebay_connect", get_settings(), minutes=10)
    r = c.get("/api/ebay/callback", params={"code": "AUTH", "state": state}, follow_redirects=False)
    assert r.status_code == 303 and "ebay=connected" in r.headers["location"]


def listing_with_photo(c, **overrides):
    from tests.test_marketplace import _png

    lid = c.post("/api/marketplace/listings", json={**BASE, **overrides}).json()["id"]
    assert c.post(f"/api/marketplace/listings/{lid}/images", files={"file": ("a.png", _png(), "image/png")}).status_code == 201
    return lid


def test_features_are_hidden_without_configuration(client):
    status = client.get("/api/ebay/status").json()
    assert status["market_check"] is False and status["seller_tools"] is False
    assert client.get("/api/ebay/connect").status_code == 404


def test_connect_builds_a_proper_consent_url(user_client, ebay):
    c, _ = user_client
    url = urlparse(c.get("/api/ebay/connect").json()["url"])
    q = parse_qs(url.query)
    assert url.netloc == "auth.sandbox.ebay.com"
    assert q["redirect_uri"] == ["Run-Name"] and q["response_type"] == ["code"]
    assert "sell.inventory" in q["scope"][0] and q["state"]


def test_callback_stores_only_an_encrypted_token(user_client, ebay, db):
    from app.models.ebay import EbayAccount

    c, user = user_client
    connect(c, user)
    assert c.get("/api/ebay/status").json()["connected"] is True
    row = db.query(EbayAccount).filter_by(user_id=user["id"]).one()
    assert "REFRESH-SECRET" not in row.refresh_token_encrypted
    assert seller._decrypt(row.refresh_token_encrypted) == "REFRESH-SECRET"


def test_callback_rejects_someone_elses_state(user_client, other_client, ebay):
    c, user = user_client
    o, _ = other_client
    state = create_purpose_token(str(user["id"]), "ebay_connect", get_settings(), minutes=10)
    r = o.get("/api/ebay/callback", params={"code": "AUTH", "state": state}, follow_redirects=False)
    assert "ebay=denied" in r.headers["location"]
    r = c.get("/api/ebay/callback", params={"code": "AUTH", "state": "forged"}, follow_redirects=False)
    assert "ebay=denied" in r.headers["location"]
    assert c.get("/api/ebay/status").json()["connected"] is False


def test_setup_reports_policies_and_missing_location(user_client, ebay):
    c, user = user_client
    connect(c, user)
    setup = c.get("/api/ebay/seller/setup").json()
    assert setup["fulfillment_policies"] == [{"id": "F1", "name": "Standard"}]
    assert setup["locations"] == [] and setup["ready"] is False


def test_publish_runs_the_full_inventory_flow(user_client, ebay):
    c, user = user_client
    connect(c, user)
    lid = listing_with_photo(c)
    r = c.post(f"/api/ebay/listings/{lid}/publish", json=PUBLISH)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published" and r.json()["url"] == "https://www.sandbox.ebay.com/itm/1234567"

    item = ebay.body(f"/inventory_item/bookworm-{lid}")
    assert item["condition"] == "USED_GOOD" and item["product"]["isbn"] == ["9780306406157"]
    assert item["product"]["aspects"]["Author"] == ["James Clear"]
    assert item["product"]["imageUrls"][0].startswith("https://books.example.com/")
    offer = ebay.body("/offer")
    assert offer["pricingSummary"]["price"] == {"value": "9.50", "currency": "USD"}
    assert offer["categoryId"] == "261186" and offer["format"] == "FIXED_PRICE"
    assert offer["listingPolicies"]["returnPolicyId"] == "R1"
    assert ebay.paths("POST")[-1].endswith("/offer/OFFER-1/publish")

    status = c.get("/api/ebay/status").json()
    assert status["publications"][0]["status"] == "published"


def test_republish_updates_instead_of_duplicating(user_client, ebay):
    c, user = user_client
    connect(c, user)
    lid = listing_with_photo(c)
    c.post(f"/api/ebay/listings/{lid}/publish", json=PUBLISH)
    before = len([p for p in ebay.paths("POST") if p.endswith("/offer")])
    r = c.post(f"/api/ebay/listings/{lid}/publish", json={**PUBLISH, "price": 11})
    assert r.status_code == 200 and r.json()["price_amount"] == 11
    assert len([p for p in ebay.paths("POST") if p.endswith("/offer")]) == before
    assert any(p.endswith("/offer/OFFER-1") for p in ebay.paths("PUT"))


def test_publish_resumes_from_an_existing_offer(user_client, ebay):
    c, user = user_client
    connect(c, user)
    lid = listing_with_photo(c)
    ebay.overrides[("POST", "/offer")] = (400, {"errors": [{"errorId": 25002, "message": "exists", "parameters": [{"name": "offerId", "value": "OLD-OFFER"}]}]})
    r = c.post(f"/api/ebay/listings/{lid}/publish", json=PUBLISH)
    assert r.status_code == 200
    assert ebay.paths("POST")[-1].endswith("/offer/OLD-OFFER/publish")


def test_ebay_rejection_is_shown_to_the_seller_and_recorded(user_client, ebay):
    c, user = user_client
    connect(c, user)
    lid = listing_with_photo(c)
    ebay.overrides[("POST", "/publish")] = (400, {"errors": [{"errorId": 25001, "message": "bad", "longMessage": "The return policy is invalid."}]})
    r = c.post(f"/api/ebay/listings/{lid}/publish", json=PUBLISH)
    assert r.status_code == 422 and r.json()["detail"] == "The return policy is invalid."
    pub = c.get("/api/ebay/status").json()["publications"][0]
    assert pub["status"] != "published" and pub["last_error"] == "The return policy is invalid."
    ebay.overrides.clear()
    assert c.post(f"/api/ebay/listings/{lid}/publish", json=PUBLISH).json()["status"] == "published"


def test_publish_guards(user_client, other_client, ebay):
    c, user = user_client
    o, ouser = other_client
    connect(c, user)
    lid = listing_with_photo(c)
    connect(o, ouser)
    assert o.post(f"/api/ebay/listings/{lid}/publish", json=PUBLISH).status_code == 403
    no_photo = c.post("/api/marketplace/listings", json={**BASE, "title": "An obscure pamphlet", "isbn": None}).json()["id"]
    r = c.post(f"/api/ebay/listings/{no_photo}/publish", json=PUBLISH)
    assert r.status_code == 422 and r.json()["detail"]["field"] == "photos"
    poor = listing_with_photo(c, condition="poor", price_amount=120)
    r = c.post(f"/api/ebay/listings/{poor}/publish", json=PUBLISH)
    assert r.status_code == 422 and r.json()["detail"]["field"] == "condition"
    assert c.post(f"/api/ebay/listings/{lid}/publish", json={**PUBLISH, "price": 0}).status_code == 422
    assert c.post(f"/api/ebay/listings/{lid}/publish", json={**PUBLISH, "fulfillment_policy_id": "../x"}).status_code == 422


def test_selling_here_ends_the_ebay_listing(user_client, ebay):
    c, user = user_client
    connect(c, user)
    lid = listing_with_photo(c)
    c.post(f"/api/ebay/listings/{lid}/publish", json=PUBLISH)
    assert c.post(f"/api/marketplace/listings/{lid}/mark-sold").status_code == 200
    assert ebay.paths("POST")[-1].endswith("/offer/OFFER-1/withdraw")
    assert c.get("/api/ebay/status").json()["publications"][0]["status"] == "ended"


def test_a_local_sale_still_succeeds_if_ebay_is_down(user_client, ebay):
    c, user = user_client
    connect(c, user)
    lid = listing_with_photo(c)
    c.post(f"/api/ebay/listings/{lid}/publish", json=PUBLISH)
    ebay.overrides[("POST", "/withdraw")] = (500, {"errors": [{"message": "down"}]})
    assert c.post(f"/api/marketplace/listings/{lid}/mark-sold").json()["status"] == "sold"
    assert c.get("/api/ebay/status").json()["publications"][0]["last_error"]


def test_disconnect_is_blocked_while_listings_are_live(user_client, ebay):
    c, user = user_client
    connect(c, user)
    lid = listing_with_photo(c)
    c.post(f"/api/ebay/listings/{lid}/publish", json=PUBLISH)
    assert c.delete("/api/ebay/account").status_code == 409
    assert c.post(f"/api/ebay/listings/{lid}/end").json()["status"] == "ended"
    assert c.delete("/api/ebay/account").status_code == 204
    assert c.get("/api/ebay/status").json()["connected"] is False


def test_market_check_estimates_from_live_listings(user_client, monkeypatch):
    from datetime import datetime, timezone

    from app.integrations import ebay as browse
    from app.marketplace.types import NormalizedListing

    c, _ = user_client
    s = get_settings()
    monkeypatch.setattr(s, "ebay_client_id", "client")
    monkeypatch.setattr(s, "ebay_client_secret", "secret")
    now = datetime.now(timezone.utc)
    items = [NormalizedListing(uid=f"ebay:{i}", provider="ebay", provider_label="eBay", is_external=True, external_id=str(i),
                               title="Atomic Habits by James Clear", condition="good", price=p, currency="USD",
                               url=f"https://www.ebay.com/itm/{i}", fetched_at=now, image_url="https://i.ebayimg.com/x.jpg", image_count=1)
             for i, p in enumerate((8.0, 10.0, 12.0, 14.0))]
    monkeypatch.setattr(browse, "search", lambda *a, **k: list(items))
    r = c.get("/api/ebay/market-check", params={"title": "Atomic Habits", "author": "James Clear", "condition": "good"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "USD" and body["total_found"] == 4 and body["lowest"] == 8.0
    assert body["estimate"]["status"] == "ok" and 8 <= body["estimate"]["median"] <= 14
    assert len(body["items"]) == 4


def test_market_check_requires_login_and_configuration(client, user_client):
    assert client.get("/api/ebay/market-check", params={"title": "x"}).status_code == 401
    c, _ = user_client
    assert c.get("/api/ebay/market-check", params={"title": "x"}).status_code == 404
