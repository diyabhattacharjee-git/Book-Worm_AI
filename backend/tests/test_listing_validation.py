"""Server-side rules for listings and reviews: nothing is stored unless it passes these."""

import pytest

from tests.conftest import book_id_by_title

GOOD = {"title": "The Trial", "author": "Franz Kafka", "condition": "good", "price_amount": 150, "delivery": "pickup",
        "location_city": "Pune", "description": "Paperback with light shelf wear."}


def errors_of(response) -> dict:
    assert response.status_code == 422, response.text
    return {e["field"]: e["message"] for e in response.json()["errors"]}


@pytest.mark.parametrize("field, value", [
    ("title", ""), ("title", "    "), ("title", "!!!"), ("title", "x" * 301),
    ("author", "   "), ("author", "x" * 201),
    ("isbn", "12345"), ("isbn", "9780735211293"),
    ("price_amount", -5), ("price_amount", 0), ("price_amount", 0.5), ("price_amount", 2000000), ("price_amount", 10.123), ("price_amount", "abc"),
    ("condition", "mint"), ("currency", "XYZ"), ("delivery", "drone"),
    ("description", ""), ("description", "short"), ("description", "          "), ("description", "x" * 3001),
    ("published_year", 1200), ("published_year", 3000), ("shipping_cost", -1),
    ("edition_text", "x" * 101), ("location_city", "x" * 81),
])
def test_invalid_values_are_rejected_with_the_field_named(user_client, field, value):
    c, _ = user_client
    before = c.get("/api/marketplace/seller-dashboard").json()["counts"]
    assert field in errors_of(c.post("/api/marketplace/listings", json={**GOOD, field: value}))
    assert c.get("/api/marketplace/seller-dashboard").json()["counts"] == before, "nothing was created"


@pytest.mark.parametrize("field", ["title", "author", "condition", "price_amount", "description"])
def test_required_fields(user_client, field):
    c, _ = user_client
    payload = {k: v for k, v in GOOD.items() if k != field}
    assert field in errors_of(c.post("/api/marketplace/listings", json=payload))


def test_city_is_required_unless_the_profile_has_one(user_client):
    c, _ = user_client
    payload = {k: v for k, v in GOOD.items() if k != "location_city"}
    assert "location_city" in errors_of(c.post("/api/marketplace/listings", json=payload))
    assert c.patch("/api/users/me", json={"location_city": "Kolkata"}).status_code == 200
    r = c.post("/api/marketplace/listings", json=payload)
    assert r.status_code == 201 and r.json()["location_city"] == "Kolkata"


def test_text_is_tidied_and_isbn_normalised(user_client):
    c, _ = user_client
    r = c.post("/api/marketplace/listings", json={**GOOD, "title": "  The   Trial ", "isbn": "0-306-40615-2", "price_amount": 151}).json()
    assert r["title"] == "The Trial" and r["isbn"] == "9780306406157"


def test_shipping_cost_needs_shipping(user_client):
    c, _ = user_client
    r = c.post("/api/marketplace/listings", json={**GOOD, "delivery": "pickup", "shipping_cost": 30})
    assert r.status_code == 422


def test_double_submit_is_refused(user_client):
    c, _ = user_client
    assert c.post("/api/marketplace/listings", json={**GOOD, "price_amount": 152}).status_code == 201
    assert c.post("/api/marketplace/listings", json={**GOOD, "price_amount": 152}).status_code == 409


def test_edits_follow_the_same_rules(user_client):
    c, _ = user_client
    lid = c.post("/api/marketplace/listings", json={**GOOD, "price_amount": 153}).json()["id"]
    url = f"/api/marketplace/listings/{lid}"
    for field, value in (("title", None), ("title", "   "), ("price_amount", None), ("price_amount", -1), ("description", None),
                         ("description", "tiny"), ("condition", None), ("isbn", "123"), ("published_year", 3000)):
        assert c.patch(url, json={field: value}).status_code == 422, (field, value)
    assert c.patch(url, json={"price_amount": 160}).json()["price_amount"] == 160
    assert c.patch(url, json={"isbn": None}).json()["isbn"] is None, "optional fields can still be cleared"


def test_review_length_limit(user_client, db):
    c, _ = user_client
    bid = book_id_by_title(db, "The Hobbit")
    url = f"/api/books/{bid}/reviews"
    assert c.post(url, json={"rating": 4, "body": "x" * 5001}).status_code == 422
    assert c.get(url).json()["my_review"] is None, "an over-long review isn't saved"
    long = "w" * 5000
    assert c.post(url, json={"rating": 4, "body": long}).status_code == 201
    assert c.get(url).json()["my_review"]["body"] == long


def test_blank_review_counts_as_a_rating_only(user_client, db):
    c, _ = user_client
    bid = book_id_by_title(db, "The Hobbit")
    r = c.post(f"/api/books/{bid}/reviews", json={"rating": 5, "body": "   "}).json()
    assert r["body"] is None


def test_reviews_can_be_paged_for_show_more(user_client, db):
    c, _ = user_client
    bid = book_id_by_title(db, "Dune")
    assert c.get(f"/api/books/{bid}/reviews", params={"page_size": 50}).status_code == 200
    assert c.get(f"/api/books/{bid}/reviews", params={"page_size": 51}).status_code == 422


def test_typeahead_searches_do_not_feed_recommendations(user_client, db):
    from sqlalchemy import select

    from app.models.social import SearchQuery

    c, user = user_client
    c.get("/api/books", params={"q": "typeahead probe", "track": "false"})
    assert not db.scalars(select(SearchQuery).where(SearchQuery.user_id == user["id"])).all()
    c.get("/api/books", params={"q": "real search"})
    assert [q.query for q in db.scalars(select(SearchQuery).where(SearchQuery.user_id == user["id"]))] == ["real search"]


def test_shelf_can_be_read_for_one_book(user_client, db):
    c, _ = user_client
    a, b = book_id_by_title(db, "Dune"), book_id_by_title(db, "The Hobbit")
    c.post("/api/bookshelf", json={"book_id": a})
    c.post("/api/bookshelf", json={"book_id": b})
    items = c.get("/api/bookshelf", params={"book_id": a}).json()["items"]
    assert [i["book"]["id"] for i in items] == [a]


def test_rate_limiter_uses_the_real_client_behind_vercel(monkeypatch):
    from starlette.requests import Request

    from app.core.ratelimit import client_ip

    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"203.0.113.9, 10.0.0.1")], "client": ("10.0.0.1", 1)}
    assert client_ip(Request(scope)) == "10.0.0.1", "the header can be forged, so it's ignored unless on Vercel"
    monkeypatch.setenv("VERCEL", "1")
    assert client_ip(Request(scope)) == "203.0.113.9"
