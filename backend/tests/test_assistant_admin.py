from app.agents.assistant import classify
from tests.conftest import book_id_by_title


def test_classifier_routes():
    assert classify("What should I read next?").tool == "recommend"
    assert classify("Find books similar to The Alchemist").tool == "similar_books"
    assert classify("Compare Deep Work and Atomic Habits").tool == "compare_books"
    assert classify("Help me find a used copy within my budget of 300").tool == "find_used_copy"
    assert classify("Save Dune to my wishlist").tool == "save_to_wishlist"
    plan = classify("Create a reading plan for the next month")
    assert plan.tool == "create_reading_plan" and plan.days == 30
    assert classify("shorter").tool == "refine_search"


def test_anonymous_chat_is_not_persisted(client):
    r = client.post("/api/assistant/chat", json={"message": "Suggest a beginner-friendly book on machine learning"}).json()
    assert r["persisted"] is False and r["conversation_id"] is None
    assert r["reply"]["tool"] == "search_books"
    items = r["reply"]["payloads"][0]["items"]
    assert items and all("id" in i["book"] for i in items)  # real catalogue books
    r2 = client.post("/api/assistant/chat", json={"message": "shorter", "context": r["context"]}).json()
    assert r2["reply"]["tool"] == "refine_search"
    assert client.post("/api/assistant/chat", json={"message": "save Dune to my wishlist"}).json()["reply"]["text"].startswith("Please log in")


def test_untrusted_context_is_sanitised(client):
    r = client.post("/api/assistant/chat", json={"message": "compare these two",
                                                 "context": {"last_book_ids": ["1; DROP TABLE", 2, 3], "evil": "x"}}).json()
    assert r["context"].get("evil") is None


def test_logged_in_chat_persists_and_can_be_cleared(user_client, db):
    c, _ = user_client
    r = c.post("/api/assistant/chat", json={"message": "books like The Alchemist"}).json()
    cid = r["conversation_id"]
    assert r["persisted"] and r["reply"]["tool"] == "similar_books"
    r2 = c.post("/api/assistant/chat", json={"message": "save the first one to my wishlist", "conversation_id": cid}).json()
    assert r2["reply"]["tool"] == "save_to_wishlist" and "Saved" in r2["reply"]["text"]
    shelf = c.get("/api/bookshelf").json()
    assert shelf["counts"].get("want_to_read") == 1
    conv = c.get(f"/api/assistant/conversations/{cid}").json()
    assert len(conv["messages"]) == 4
    assert c.delete("/api/assistant/conversations").status_code == 204
    assert c.get("/api/assistant/conversations").json() == []


def test_assistant_reading_plan(user_client, db):
    c, _ = user_client
    r = c.post("/api/assistant/chat", json={"message": "Create a reading plan for The Little Prince over 7 days"}).json()
    assert r["reply"]["tool"] == "create_reading_plan"
    assert r["reply"]["payloads"][0]["type"] == "plan"
    assert len(c.get("/api/reading-plans").json()) == 1


def test_conversation_ownership(user_client, other_client):
    c, _ = user_client
    o, _ = other_client
    cid = c.post("/api/assistant/chat", json={"message": "hello"}).json()["conversation_id"]
    assert o.get(f"/api/assistant/conversations/{cid}").status_code == 404
    assert o.post("/api/assistant/chat", json={"message": "hi", "conversation_id": cid}).status_code == 404


def test_admin_requires_role(user_client):
    c, _ = user_client
    for path in ("/api/admin/overview", "/api/admin/reports", "/api/admin/users", "/api/recommendations/metrics"):
        assert c.get(path).status_code == 403


def test_admin_moderation_flow(admin_client, user_client, other_client, db):
    a, _ = admin_client
    seller, _ = user_client
    reporter, _ = other_client
    lid = seller.post("/api/marketplace/listings", json={"title": "Dune", "author": "Frank Herbert", "condition": "good",
                                                         "price_amount": 300, "delivery": "pickup"}).json()["id"]
    reporter.post(f"/api/marketplace/listings/{lid}/report", json={"reason": "fraud", "details": "fake"})
    reports = a.get("/api/admin/reports").json()["listing_reports"]
    assert any(r["listing_id"] == lid for r in reports)
    assert a.patch(f"/api/admin/listings/{lid}", json={"status": "removed", "note": "Reported"}).json()["status"] == "removed"
    assert reporter.get(f"/api/marketplace/listings/{lid}").status_code == 404
    assert seller.post(f"/api/marketplace/listings/{lid}/reactivate").status_code == 403
    assert a.get("/api/admin/audit-log").json()[0]["action"] == "listing_moderated"
    ov = a.get("/api/admin/overview").json()
    assert ov["users"]["demo"] > 0 and "listings_by_status" in ov["marketplace"]
    bid = book_id_by_title(db, "Dune")
    rid = reporter.post(f"/api/books/{bid}/reviews", json={"rating": 1, "body": "spam spam"}).json()["id"]
    assert a.patch(f"/api/admin/reviews/{rid}", json={"status": "hidden"}).json()["status"] == "hidden"
    assert all(r["id"] != rid for r in reporter.get(f"/api/books/{bid}/reviews").json()["items"])
    ev = a.post("/api/recommendations/evaluate", json={"k": 5}).json()
    assert ev["status"] == "insufficient_data"
    assert a.get("/api/recommendations/metrics").json()["runs"][0]["status"] == "insufficient_data"
