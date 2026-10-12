"""Marketplace intelligence: intent, validation, pricing, quality, ranking, graph and providers."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agents import llm, used_book_graph
from app.agents.intent import parse_rules
from app.integrations import ebay
from app.integrations.http import ProviderError
from app.marketplace import providers
from app.marketplace.identify import IdentifiedBook, identify
from app.marketplace.pricing import estimate_price, interpret_price
from app.marketplace.quality import assess
from app.marketplace.ranking import Constraints, rank
from app.marketplace.types import NormalizedListing
from app.marketplace.validate import validate_and_dedupe

NOW = datetime.now(timezone.utc)
BOOK = IdentifiedBook(found=True, confidence=1.0, method="isbn_catalogue", book_id=1, title="Atomic Habits",
                      authors=["James Clear"], isbns=["9780735211292"], requested_isbn="9780735211292")


def L(uid, price, cond="good", isbn="9780735211292", title="Atomic Habits", ship=40.0, currency="INR", provider="community",
      images=1, **kw):
    return NormalizedListing(uid=uid, provider=provider, provider_label=provider, is_external=provider != "community",
                             external_id=uid, title=title, author="James Clear", isbn=isbn, condition=cond, price=price,
                             currency=currency, shipping_cost=ship, shipping_known=ship is not None, delivery="both",
                             image_count=images, image_url="/x.png" if images else None, fetched_at=NOW,
                             listed_at=NOW - timedelta(days=5), description="A clean, well kept copy of the book.",
                             seller_name=f"seller-{uid}", **kw)


# ------------------------------------------------------------------ intent
@pytest.mark.parametrize("text,expected", [
    ("Find a good-condition copy of Clean Code under ₹500.", {"title": "Clean Code", "max_price": 500.0, "min_condition": "good"}),
    ("I want to buy a used copy of Atomic Habits. My budget is ₹250", {"title": "Atomic Habits", "max_price": 250.0}),
    ("Is ₹300 a fair price for The Alchemist?", {"intent": "price_estimate", "asking_price": 300.0, "max_price": None}),
    ("second hand copy of 0132350882 for pickup in Kolkata", {"isbn": "9780132350884", "delivery": "pickup", "location": "Kolkata"}),
])
def test_intent_rules(db, text, expected):
    p = parse_rules(db, text)
    for k, v in expected.items():
        assert getattr(p, k) == v, (k, getattr(p, k))


def test_intent_needs_clarification(db):
    assert parse_rules(db, "under ₹200 please").needs_clarification


# --------------------------------------------------------------- identify
def test_identify_by_isbn_and_title(db):
    assert identify(db, isbn="9780735211292", title=None, author=None, allow_network=False).method == "isbn_catalogue"
    ib = identify(db, isbn=None, title="atomic habit", author="James Clear", allow_network=False)
    assert ib.found and ib.title == "Atomic Habits" and ib.confidence >= 0.8
    nope = identify(db, isbn=None, title="A Book That Does Not Exist Anywhere", author=None, allow_network=False)
    assert not nope.found and nope.confidence == 0


# --------------------------------------------------------------- validate
def test_validation_matching_and_duplicates():
    items = [
        L("a", 200), L("a", 200),  # exact duplicate result
        L("b", 210, isbn=None),  # approximate (title match, edition unknown)
        L("c", 150, title="Summary of Atomic Habits"),  # companion product
        L("d", 300, title="Clean Code", isbn="9780132350884"),  # different book
        L("e", 220, isbn="9781847941831"),  # different ISBN, same title -> approximate, flagged
        L("f", 220, isbn="9781847941831"),  # probable duplicate of e (same seller key differs) -> not dup
        L("g", 199, status="sold"),
    ]
    items[6].seller_name = items[5].seller_name
    kept, excluded = validate_and_dedupe(items, BOOK)
    kept_ids = {k.uid for k in kept}
    assert kept_ids == {"a", "b", "e", "f"}
    reasons = {e["uid"]: e["reason"] for e in excluded}
    assert "companion" in reasons["c"] and "Listing is sold" == reasons["g"] and "Exact duplicate" in reasons["a"]
    by = {k.uid: k for k in kept}
    assert by["a"].match == "exact" and by["b"].match == "approximate"
    assert any("ISBN differs" in i for i in by["e"].validation_issues)
    assert by["f"].probable_duplicate_of == "e"


def test_optional_metadata_does_not_discard():
    kept, _ = validate_and_dedupe([L("x", 200, isbn=None, ship=None, images=0)], BOOK)
    assert len(kept) == 1
    issues = " ".join(kept[0].validation_issues)
    assert "Shipping cost unknown" in issues and "No photos" in issues


# ---------------------------------------------------------------- pricing
def _matched(items):
    kept, _ = validate_and_dedupe(items, BOOK)
    return kept


def test_insufficient_data_refuses_estimate():
    est = estimate_price(_matched([L("a", 200), L("b", 220)]), "INR", "good")
    assert est.status == "insufficient_data" and est.low is None
    assert "Insufficient data" in est.explanation
    assert interpret_price(250, est)["verdict"] == "unknown"


def test_rule_based_fallback_only_with_reference():
    est = estimate_price(_matched([L("a", 200)]), "INR", "good", new_price_reference=500)
    assert est.status == "rule_based" and est.low == 175 and est.high == 275 and est.confidence == "low"


def test_estimate_from_comparables_and_currency_isolation():
    items = _matched([L(str(i), p) for i, p in enumerate([200, 210, 220, 230, 240, 250])] + [L("usd", 5, currency="USD")])
    est = estimate_price(items, "INR", "good")
    assert est.status == "ok" and est.tier == "exact" and est.n_comparables == 6
    assert 200 <= est.low <= est.median <= est.high <= 250
    assert est.excluded_other_currency == 1
    assert any("other currencies" in lim for lim in est.limitations)
    assert est.confidence in ("medium", "high")
    assert interpret_price(150, est)["verdict"] == "well_below"
    assert interpret_price(225, est)["verdict"] == "within"


def test_condition_adjustment():
    items = _matched([L(str(i), 200) for i in range(5)])
    good = estimate_price(items, "INR", "good")
    like_new = estimate_price(items, "INR", "like_new")
    assert like_new.median > good.median


def test_sample_data_lowers_confidence():
    real = estimate_price(_matched([L(str(i), 200 + i) for i in range(6)]), "INR")
    sample = estimate_price(_matched([L(str(i), 200 + i, is_sample=True) for i in range(6)]), "INR")
    assert sample.confidence_score < real.confidence_score
    assert any("sample" in lim.lower() for lim in sample.limitations)


# ---------------------------------------------------- quality and ranking
def test_cheap_suspicious_listing_not_ranked_first():
    good_ones = [L(str(i), 220 + i * 5) for i in range(5)]
    suspicious = L("cheap", 60, isbn=None, images=0, ship=None)
    suspicious.description = None
    items = _matched(good_ones + [suspicious])
    est = estimate_price(items, "INR", "good")
    q = {it.uid: assess(it, est) for it in items}
    assert any("far below" in f for f in q["cheap"].flags)
    assert q["cheap"].score < q["0"].score
    ranked = rank(items, q, est, {}, Constraints(max_price=400, currency="INR"))
    assert ranked[0].uid != "cheap"


def test_ranking_respects_constraints():
    items = _matched([L("ok", 200, cond="very_good"), L("worn", 120, cond="acceptable"), L("pricey", 900)])
    est = estimate_price(items, "INR")
    q = {it.uid: assess(it, est) for it in items}
    ranked = {r.uid: r for r in rank(items, q, est, {}, Constraints(max_price=300, min_condition="good"))}
    assert ranked["ok"].group == "match"
    assert ranked["worn"].group == "near_match" and "below your minimum" in ranked["worn"].unmet[0]
    assert ranked["pricey"].group == "other"


# ------------------------------------------------------------- the graph
def test_graph_end_to_end_without_credentials():
    res = used_book_graph.run("I want to buy a used copy of Atomic Habits. My budget is ₹250, and I prefer a "
                              "good-condition copy.", allow_network=False)
    assert res["status"] == "ok"
    assert [t["step"] for t in res["trace"]] == [s for s, _ in used_book_graph.STEPS]
    assert res["book"]["title"] == "Atomic Habits"
    ebay_status = next(p for p in res["providers"] if p["provider"] == "ebay")
    assert not ebay_status["ok"] and ebay_status["skipped"]
    assert res["deals"] and all(d["listing"]["url"] for d in res["deals"])
    assert res["summary"]["source"] == "deterministic"
    assert "meet all your constraints" in res["summary"]["text"]
    # Prices in the response are exactly the stored asking prices
    assert all(d["listing"]["price"] in (260.0, 210.0, 340.0, 140.0, 230.0, 199.0, 205.0, 210.0, 215.0, 220.0, 225.0, 230.0)
               for d in res["deals"])


def test_graph_clarification_route():
    res = used_book_graph.run("under ₹200 please", allow_network=False)
    assert res["status"] == "needs_clarification"
    assert [t["step"] for t in res["trace"]] == ["understand", "explain"]


def test_graph_stream_emits_running_and_completed():
    events = [json.loads(line) for line in used_book_graph.stream("Find Clean Code", allow_network=False)]
    steps = [(e["step"], e["status"]) for e in events if e["type"] == "step"]
    assert steps[0] == ("understand", "running") and ("understand", "completed") in steps
    assert events[-1]["type"] == "result"


def test_provider_failure_does_not_lose_community_results(monkeypatch):
    monkeypatch.setattr(providers, "provider_enabled", lambda key: (True, None))

    def boom(db, req):
        raise ProviderError("ebay", "rate limit reached")

    monkeypatch.setitem(providers.PROVIDERS, "ebay", ("eBay", boom))
    results = providers.search_all(providers.SearchRequest(title="Atomic Habits", isbn="9780735211292"))
    by = {r.provider: r for r in results}
    assert by["community"].ok and by["community"].listings
    assert not by["ebay"].ok and by["ebay"].error == "rate limit reached"


def test_llm_summary_rejected_when_inventing_numbers(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: llm.LLMResult("Grab it now for only ₹99999!", "groq", "test"))
    res = used_book_graph.run("used copy of Atomic Habits under ₹400")
    assert res["summary"]["text"] == res["summary"]["deterministic_text"]
    assert "rejected" in res["summary"]["source"]


def test_llm_summary_accepted_when_grounded(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: llm.LLMResult("There are good options available.", "groq", "test"))
    res = used_book_graph.run("used copy of Atomic Habits under ₹400")
    assert res["summary"]["source"].startswith("llm:groq")


# ---------------------------------------------------------- eBay adapter
def test_ebay_normalisation_from_api_payload():
    item = {"itemId": "v1|123|0", "title": "Atomic Habits by James Clear Hardcover", "price": {"value": "12.50", "currency": "USD"},
            "conditionId": "4000", "condition": "Very Good", "itemWebUrl": "https://www.ebay.com/itm/123",
            "image": {"imageUrl": "https://i.ebayimg.com/x.jpg"}, "seller": {"username": "bookshop", "feedbackPercentage": "99.1",
                                                                         "feedbackScore": 812},
            "shippingOptions": [{"shippingCost": {"value": "4.00", "currency": "USD"}}],
            "itemLocation": {"country": "US", "city": "Austin"}}
    n = ebay.normalize_item(item, NOW)
    assert n.price == 12.5 and n.currency == "USD" and n.condition == "very_good"
    assert n.shipping_cost == 4.0 and n.shipping_known and n.total_known_cost == 16.5
    assert n.country == "US" and n.url == "https://www.ebay.com/itm/123"
    assert ebay.normalize_item({**item, "itemWebUrl": "javascript:alert(1)"}, NOW) is None
    no_ship = ebay.normalize_item({**item, "shippingOptions": []}, NOW)
    assert no_ship.shipping_cost is None and not no_ship.total_cost_complete


def test_ebay_not_configured_raises():
    with pytest.raises(ProviderError):
        ebay.search("anything")


# ------------------------------------------------------------- endpoints
def test_intelligence_endpoints(client):
    r = client.post("/api/marketplace/search-used-books", json={"query": "Atomic Habits under ₹300", "include_external": False})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    r = client.post("/api/marketplace/estimate-price", json={"isbn": "9780735211292", "condition": "good", "asking_price": 250})
    body = r.json()
    assert body["estimate"]["status"] == "ok" and body["asking_price_verdict"]["verdict"] in ("within", "above", "below", "well_above", "well_below")
    assert "no machine-learning" in body["method_note"]
    s = client.post("/api/marketplace/search-used-books/stream", json={"query": "Clean Code"})
    lines = [json.loads(x) for x in s.text.strip().splitlines()]
    assert lines[-1]["type"] == "result"
    st = client.get("/api/marketplace/providers/status").json()
    assert {p["key"] for p in st["providers"]} == {"community", "ebay"} and st["llm"]["mode"] == "deterministic"
    assert client.post("/api/marketplace/search-used-books", json={}).status_code == 422


def test_compare_listings_endpoint(client):
    ids = [x["id"] for x in client.get("/api/marketplace/listings", params={"isbn": "9780735211292"}).json()["items"]][:3]
    r = client.post("/api/marketplace/compare-listings", json={"listing_ids": ids}).json()
    assert len(r["rows"]) == len(ids) and r["same_book"]
    assert all("quality" in row and "price_verdict" in row for row in r["rows"])
