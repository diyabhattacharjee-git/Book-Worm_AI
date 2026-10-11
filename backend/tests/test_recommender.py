"""Recommender unit tests on a small, fully reproducible synthetic dataset."""

from datetime import datetime, timedelta, timezone

import pytest

from app.recommender.collaborative import ItemCF
from app.recommender.content import fit_content_model
from app.recommender.evaluation import evaluate, split_events
from app.recommender.hybrid import BookLite, HybridRecommender, Preferences, RecConfig
from app.recommender.popularity import fit_popularity
from app.recommender.signals import Event, aggregate

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeGenre:
    def __init__(self, name, kind="genre"):
        self.name, self.kind = name, kind


class FakeBook:
    def __init__(self, id, title, author, genres, desc, pages=300, lang="en"):
        self.id, self.title, self.subtitle = id, title, None
        self.author_names = [author]
        self.genres = [FakeGenre(g) for g in genres]
        self.description, self.page_count, self.language = desc, pages, lang


BOOKS = [
    FakeBook(1, "Python Basics", "A. Coder", ["Programming", "Python"], "learn python programming for beginners", 250),
    FakeBook(2, "Advanced Python", "A. Coder", ["Programming", "Python"], "advanced python programming techniques", 500),
    FakeBook(3, "Machine Learning Intro", "M. Learner", ["Machine Learning", "Programming"], "machine learning with python", 400),
    FakeBook(4, "Dark Secrets", "T. Hriller", ["Thriller", "Mystery"], "a psychological thriller with a twist", 350),
    FakeBook(5, "Silent Night", "T. Hriller", ["Thriller", "Mystery"], "murder mystery suspense thriller", 320),
    FakeBook(6, "Space Journey", "S. Fi", ["Science Fiction"], "astronaut space adventure on mars", 420),
    FakeBook(7, "Stars Beyond", "S. Fi", ["Science Fiction"], "space opera galaxy adventure", 600),
    FakeBook(8, "Short Calm", "Z. En", ["Self-Help", "Inspirational"], "short inspiring book about calm living", 120),
]


def lites():
    return {b.id: BookLite(b.id, b.title, b.author_names, {g.name.lower() for g in b.genres}, b.language, b.page_count,
                           (None, None), b.description) for b in BOOKS}


def rating(u, b, r, days_ago=10):
    return Event(u, b, "rating", 1.5 * (r - 3) / 2, NOW - timedelta(days=days_ago), rating=r)


@pytest.fixture
def content():
    return fit_content_model(BOOKS)


def test_content_model_is_fitted(content):
    assert content.backend == "tfidf"
    assert content.item_similarity(1, 2) > content.item_similarity(1, 4)


def test_bayesian_popularity_smoothing():
    events = [rating(10, 1, 5)]  # one 5-star rating
    events += [rating(u, 2, 4) for u in range(20, 40)] + [rating(u, 2, 5) for u in range(40, 50)]  # 30 strong ratings
    pop = fit_popularity(aggregate(events, 60, NOW), [1, 2, 3], {}, prior_m=5)
    assert pop[2].score > pop[1].score, "a single 5-star rating must not beat many high ratings"
    assert pop[1].bayes_rating < 5.0


def test_recency_decay():
    old = aggregate([Event(1, 1, "save", 1.0, NOW - timedelta(days=120))], 60, NOW).values[1][1]
    new = aggregate([Event(1, 1, "save", 1.0, NOW - timedelta(days=1))], 60, NOW).values[1][1]
    assert new > old and abs(old - 0.25) < 0.01


def test_cf_unreliable_with_sparse_data():
    events = [rating(1, 1, 5), rating(1, 2, 5), rating(2, 1, 5)]
    cf = ItemCF(aggregate(events, 60, NOW), min_users=5).fit()
    assert not cf.reliable


def test_cf_learns_co_occurrence():
    events = []
    for u in range(1, 9):  # thriller fans like 4 and 5 together
        events += [rating(u, 4, 5), rating(u, 5, 5), rating(u, 6, 2)]
    cf = ItemCF(aggregate(events, 60, NOW), min_users=5, min_user_interactions=1).fit()
    assert cf.reliable
    scores = cf.score_user({4: 1.5}, [5, 6])
    assert scores[5].score > scores.get(6, type("x", (), {"score": -9})()).score


def test_hybrid_personalised_with_grounded_explanations(content):
    events = [rating(1, 1, 5), rating(1, 3, 5)]
    rec = HybridRecommender(content, aggregate(events, 60, NOW), lites(), RecConfig(), cf_min_users=5)
    res = rec.recommend(1, k=3)
    assert res.mode == "personalized"
    ids = [i.book_id for i in res.items]
    assert 1 not in ids and 3 not in ids, "already-rated books are excluded"
    assert ids[0] == 2, "closest unseen programming book ranks first"
    reason = res.items[0].reasons[0]
    assert reason.signal == "content" and reason.evidence["similar_to_book_id"] in (1, 3)
    assert "readers with similar taste" in " ".join(res.notes)


def test_cold_start_with_preferences(content):
    rec = HybridRecommender(content, aggregate([], 60, NOW), lites(), RecConfig())
    res = rec.recommend(99, Preferences(genres=["Thriller"], length="short"), k=3)
    assert res.mode == "cold_start"
    assert {res.items[0].book_id, res.items[1].book_id} & {4, 5}
    assert any(r.signal == "preference" for r in res.items[0].reasons)


def test_negative_feedback_excludes_and_pushes_away(content):
    events = [Event(1, 4, "not_interested", -1.5, NOW), rating(1, 1, 5)]
    rec = HybridRecommender(content, aggregate(events, 60, NOW), lites(), RecConfig())
    ids = [i.book_id for i in rec.recommend(1, k=7).items]
    assert 4 not in ids
    assert ids.index(5) > ids.index(2), "a thriller ranks below programming after disliking a thriller"


def test_diversity_author_cap(content):
    rec = HybridRecommender(content, aggregate([rating(1, 8, 5)], 60, NOW), lites(), RecConfig(max_per_author=1))
    authors = [lites()[i.book_id].authors[0] for i in rec.recommend(1, k=5).items]
    assert len(authors) == len(set(authors))


def test_temporal_split_holds_out_recent_items():
    events = [Event(1, b, "rating", 1.5, NOW - timedelta(days=10 * (10 - b)), rating=5) for b in range(1, 8)]
    train, held = split_events(events)
    assert held[1] == {7}, "the most recent relevant item is held out"
    assert all(e.book_id != 7 for e in train)


def test_evaluation_reports_insufficient_real_data(db):
    out = evaluate(db, k=5, include_demo=False)
    assert out["status"] == "insufficient_data"
    assert "Not enough evaluation data" in out["message"]


def test_evaluation_with_demo_data_is_labelled(db):
    out = evaluate(db, k=5, include_demo=True)
    assert out["status"] == "ok"
    assert out["data_warning"] and "synthetic" in out["data_warning"]
    hybrid = out["results"]["hybrid"]
    assert 0 <= hybrid["precision_at_5"] <= 1 and 0 <= hybrid["ndcg_at_5"] <= 1


def test_recommendations_api_and_feedback(user_client, db):
    c, _ = user_client
    r = c.get("/api/recommendations?limit=5").json()
    assert r["mode"] == "cold_start" and len(r["items"]) == 5
    assert all(i["reasons"] for i in r["items"])
    first = r["items"][0]["book"]["id"]
    assert c.post("/api/recommendations/feedback", json={"book_id": first, "action": "dismiss"}).status_code == 200
    r2 = c.get("/api/recommendations?limit=10").json()
    assert first not in [i["book"]["id"] for i in r2["items"]]
    assert c.post("/api/recommendations/feedback", json={"book_id": first, "action": "rate"}).status_code == 422
    c.post("/api/users/me/reset-recommendations")
    assert c.get("/api/recommendations/metrics").status_code == 403
