from datetime import date, timedelta

from app.models.book import Book
from tests.conftest import book_id_by_title


def test_list_and_search(client):
    r = client.get("/api/books", params={"q": "atomic habits"})
    assert r.status_code == 200
    assert r.json()["items"][0]["title"] == "Atomic Habits"
    r = client.get("/api/books", params={"q": "9780132350884"})  # ISBN search
    assert [b["title"] for b in r.json()["items"]] == ["Clean Code"]
    r = client.get("/api/books", params={"author": "Andy Weir", "sort": "year_desc"})
    titles = [b["title"] for b in r.json()["items"]]
    assert titles == ["Project Hail Mary", "The Martian"]


def test_filters_and_pagination(client):
    r = client.get("/api/books", params={"genre": "programming", "pages_max": 450, "page_size": 2})
    body = r.json()
    assert body["page_size"] == 2 and len(body["items"]) <= 2
    assert all(b["page_count"] <= 450 for b in body["items"])
    assert client.get("/api/books", params={"sort": "bogus"}).status_code == 422
    r = client.get("/api/books", params={"availability": "used", "sort": "price"}).json()
    prices = [b["lowest_used_price"] for b in r["items"]]
    assert prices == sorted(prices)


def test_facets_and_detail(client, db):
    f = client.get("/api/books/facets").json()
    assert any(g["slug"] == "thriller" for g in f["genres"])
    bid = book_id_by_title(db, "Atomic Habits")
    d = client.get(f"/api/books/{bid}").json()
    assert d["isbn13"] == "9780735211292"
    assert d["ratings"]["external_source"] in (None, "open_library")
    # Seeded ratings come from synthetic demo accounts and are labelled as such
    assert d["ratings"]["app_count"] > 0 and d["ratings"]["app_demo_count"] == d["ratings"]["app_count"]
    assert any(link["label"] == "Open Library" for link in d["external_links"])
    assert client.get("/api/books/999999").status_code == 404


def test_similar_books(client, db):
    bid = book_id_by_title(db, "Clean Code")
    sims = client.get(f"/api/books/{bid}/similar").json()
    titles = [s["book"]["title"] for s in sims]
    assert "Clean Code" not in titles and len(titles) > 0
    assert all(s["reason"] for s in sims)


def test_nl_search_and_refinement(client):
    r = client.post("/api/books/nl-search", json={"query": "I want a short, inspiring book that I can finish in a weekend"}).json()
    assert r["query"]["pages_max"] == 250
    assert all(x["book"]["page_count"] <= 250 for x in r["results"])
    r2 = client.post("/api/books/nl-search", json={"query": "Recommend something similar to The Alchemist"}).json()
    assert r2["query"]["similar_to_title"] == "The Alchemist"
    assert all(x["book"]["title"] != "The Alchemist" for x in r2["results"])
    r3 = client.post("/api/books/nl-search", json={"refinement": "shorter", "previous": r2["query"]}).json()
    assert r3["query"]["pages_max"] is not None


def test_reviews_crud_and_permissions(user_client, other_client, db):
    c, _ = user_client
    o, _ = other_client
    bid = book_id_by_title(db, "Deep Work")
    r = c.post(f"/api/books/{bid}/reviews", json={"rating": 4, "body": "Useful and focused."})
    assert r.status_code == 201
    rid = r.json()["id"]
    # Second submit updates the same review (no duplicate ratings)
    r = c.post(f"/api/books/{bid}/reviews", json={"rating": 5, "body": "Even better on re-read."})
    assert r.json()["id"] == rid and r.json()["rating"] == 5
    # Another user can't edit or delete it
    assert o.patch(f"/api/reviews/{rid}", json={"rating": 1}).status_code == 403
    assert o.delete(f"/api/reviews/{rid}").status_code == 403
    # Helpful vote & report
    assert o.post(f"/api/reviews/{rid}/helpful").json()["helpful_count"] == 1
    assert o.post(f"/api/reviews/{rid}/helpful").json()["helpful_count"] == 1  # idempotent
    assert o.post(f"/api/reviews/{rid}/report", json={"reason": "spam"}).status_code == 201
    assert o.post(f"/api/reviews/{rid}/report", json={"reason": "spam"}).status_code == 409
    assert c.post(f"/api/reviews/{rid}/helpful").status_code == 400  # own review
    listing = c.get(f"/api/books/{bid}/reviews").json()
    assert listing["my_review"]["id"] == rid
    assert c.delete(f"/api/reviews/{rid}").status_code == 204


def test_review_validation(user_client, db):
    c, _ = user_client
    bid = book_id_by_title(db, "Dune")
    assert c.post(f"/api/books/{bid}/reviews", json={"rating": 6}).status_code == 422
    assert c.post(f"/api/books/{bid}/reviews", json={"rating": 0}).status_code == 422


def test_bookshelf_progress_and_unknown_pages(user_client, db):
    c, _ = user_client
    known = book_id_by_title(db, "The Little Prince")
    r = c.post("/api/bookshelf", json={"book_id": known, "status": "reading"}).json()
    assert r["percent"] == 0.0 and r["started_on"] is not None
    r = c.patch(f"/api/bookshelf/{r['id']}", json={"pages_read": 48}).json()
    assert r["percent"] == round(100 * 48 / r["total_pages"], 1)
    assert c.patch(f"/api/bookshelf/{r['id']}", json={"pages_read": 10_000}).status_code == 422
    # A book without a page count never shows a percentage
    unknown = db.query(Book).filter(Book.page_count.is_(None)).first()
    r2 = c.post("/api/bookshelf", json={"book_id": unknown.id, "status": "reading"}).json()
    r2 = c.patch(f"/api/bookshelf/{r2['id']}", json={"pages_read": 30}).json()
    assert r2["percent"] is None and r2["total_pages"] is None
    shelf = c.get("/api/bookshelf").json()
    assert shelf["counts"]["reading"] == 2


def test_bookshelf_ownership(user_client, other_client, db):
    c, _ = user_client
    o, _ = other_client
    entry = c.post("/api/bookshelf", json={"book_id": book_id_by_title(db, "Dune")}).json()
    assert o.patch(f"/api/bookshelf/{entry['id']}", json={"status": "read"}).status_code == 404
    assert o.delete(f"/api/bookshelf/{entry['id']}").status_code == 404


def test_goals_and_history(user_client, db):
    c, _ = user_client
    year = date.today().year
    g = c.post("/api/reading-goals", json={"year": year, "target_books": 2}).json()
    assert g["completed_books"] == 0
    c.post("/api/bookshelf", json={"book_id": book_id_by_title(db, "The Great Gatsby"), "status": "read"})
    goals = c.get("/api/reading-goals").json()
    assert goals[0]["completed_books"] == 1 and goals[0]["percent"] == 50.0
    g2 = c.post("/api/reading-goals", json={"year": year, "target_books": 4}).json()  # update, not duplicate
    assert g2["id"] == g["id"] and len(c.get("/api/reading-goals").json()) == 1
    hist = c.get("/api/reading-history").json()
    assert hist["finished"][0]["book"]["title"] == "The Great Gatsby"


def test_custom_lists(user_client, db):
    c, _ = user_client
    lst = c.post("/api/reading-lists", json={"name": "Summer"}).json()
    assert c.post("/api/reading-lists", json={"name": "Summer"}).status_code == 409
    bid = book_id_by_title(db, "Circe")
    lst = c.post(f"/api/reading-lists/{lst['id']}/items", json={"book_id": bid}).json()
    assert [b["title"] for b in lst["books"]] == ["Circe"]
    assert c.post(f"/api/reading-lists/{lst['id']}/items", json={"book_id": bid}).status_code == 409


def test_reading_plan_generation_and_progress(user_client, db):
    c, _ = user_client
    bid = book_id_by_title(db, "The Little Prince")
    pages = db.get(Book, bid).page_count
    body = {"book_ids": [bid], "minutes_per_day": 20, "pages_per_minute": 1.0, "reading_days": [1, 2, 3, 4, 5, 6, 7]}
    preview = c.post("/api/reading-plans/generate", json=body).json()
    assert preview["pages_per_day"] == 20
    assert sum(d["end_page"] - d["start_page"] + 1 for d in preview["days"]) == pages
    target = (date.today() + timedelta(days=2)).isoformat()
    fitted = c.post("/api/reading-plans/generate", json={**body, "target_date": target, "fit_to_target": True}).json()
    assert len({d["day"] for d in fitted["days"]}) <= 3
    plan = c.post("/api/reading-plans", json=body).json()
    first = plan["items"][0]
    plan = c.patch(f"/api/reading-plans/{plan['id']}/items/{first['id']}", json={"completed": True}).json()
    assert plan["progress"]["actual_pages"] == first["end_page"] - first["start_page"] + 1
    ics = c.get(f"/api/reading-plans/{plan['id']}/calendar.ics")
    assert ics.headers["content-type"].startswith("text/calendar") and "BEGIN:VEVENT" in ics.text
    plan = c.post(f"/api/reading-plans/{plan['id']}/reschedule", json={"minutes_per_day": 60}).json()
    assert plan["minutes_per_day"] == 60


def test_reading_plan_rejects_unknown_page_count(user_client, db):
    c, _ = user_client
    unknown = db.query(Book).filter(Book.page_count.is_(None)).first()
    r = c.post("/api/reading-plans/generate", json={"book_ids": [unknown.id]})
    assert r.status_code == 422
    r = c.post("/api/reading-plans/generate", json={"book_ids": [unknown.id], "page_overrides": {str(unknown.id): 200}})
    assert r.status_code == 200 and r.json()["total_pages"] == 200


def test_compare_books(client, db):
    ids = [book_id_by_title(db, t) for t in ("Python Crash Course", "Introduction to Algorithms")]
    r = client.post("/api/books/compare", json={"book_ids": ids, "goal": "short read"}).json()
    assert len(r["rows"]) == 2
    assert any("shortest" in a["text"] for a in r["advice"])
    for row in r["rows"]:
        assert row["language"] is not None  # "Not available" rather than missing
