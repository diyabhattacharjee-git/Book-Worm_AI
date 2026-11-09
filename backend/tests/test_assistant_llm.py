"""The assistant's model handling, with the provider replaced so no network is used."""

import json

import httpx
import pytest

from app.agents import assistant, llm
from app.core.config import get_settings
from tests.conftest import book_id_by_title


class FakeGroq:
    def __init__(self, monkeypatch, *replies):
        self.calls = []
        self.replies = list(replies)
        s = get_settings()
        monkeypatch.setattr(s, "groq_api_key", "test-key")
        monkeypatch.setattr(s, "llm_provider_order", "groq")
        monkeypatch.setattr(llm.time, "sleep", lambda _: None)

        def call(messages, json_mode, max_tokens, temperature):
            self.calls.append({"messages": messages, "json_mode": json_mode, "max_tokens": max_tokens})
            reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
            if isinstance(reply, Exception):
                raise reply
            return llm.LLMResult(reply, "groq", get_settings().groq_model)

        monkeypatch.setitem(llm._CALLERS, "groq", call)


@pytest.fixture(autouse=True)
def _reset(db):
    from sqlalchemy import delete

    from app.models.book import ExternalCache

    db.execute(delete(ExternalCache))
    db.commit()
    llm.reset_state()
    yield
    llm.reset_state()


def answer(text, book_ids=()):
    return json.dumps({"action": "answer", "reply": text, "book_ids": list(book_ids)})


def status_error(code, retry_after=None):
    headers = {"retry-after": str(retry_after)} if retry_after else {}
    response = httpx.Response(code, headers=headers, request=httpx.Request("POST", "https://groq.test"))
    return httpx.HTTPStatusError(f"HTTP {code}", request=response.request, response=response)


def test_default_model_is_the_requested_one():
    from app.core.config import Settings

    assert Settings.model_fields["groq_model"].default == "openai/gpt-oss-120b"


def test_general_question_uses_one_model_call_and_real_book_cards(client, db, monkeypatch):
    bid = book_id_by_title(db, "The Alchemist")
    groq = FakeGroq(monkeypatch, answer("A shepherd follows a dream.", [bid, 999999]))
    r = client.post("/api/assistant/chat", json={"message": "What is The Alchemist about?"}).json()
    assert len(groq.calls) == 1 and groq.calls[0]["json_mode"]
    assert r["reply"]["text"] == "A shepherd follows a dream." and r["reply"]["source"] == "llm"
    shown = [i["book"]["id"] for i in r["reply"]["payloads"][0]["items"]]
    assert shown == [bid], "an id the model invented is dropped"


def test_follow_up_receives_the_earlier_conversation(client, db, monkeypatch):
    bid = book_id_by_title(db, "The Alchemist")
    groq = FakeGroq(monkeypatch, answer("A shepherd follows a dream.", [bid]), answer("Yes, it's an easy read."))
    first = client.post("/api/assistant/chat", json={"message": "What is The Alchemist about?"}).json()
    client.post("/api/assistant/chat", json={"message": "Is it hard for a teenager?", "context": first["context"]})
    second = groq.calls[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert "shepherd" in second[2]["content"] and "Is it hard for a teenager?" in second[3]["content"]
    assert "The Alchemist" in second[3]["content"], "the book under discussion stays in the catalogue context"


def test_logged_in_history_comes_from_the_saved_conversation(user_client, monkeypatch):
    c, _ = user_client
    groq = FakeGroq(monkeypatch, answer("First answer."), answer("Second answer."))
    cid = c.post("/api/assistant/chat", json={"message": "Tell me about reading habits"}).json()["conversation_id"]
    c.post("/api/assistant/chat", json={"message": "and then?", "conversation_id": cid})
    assert "First answer." in groq.calls[1]["messages"][2]["content"]
    assert len(c.get(f"/api/assistant/conversations/{cid}").json()["messages"]) == 4


def test_rules_handle_clear_requests_without_the_model(client, monkeypatch):
    groq = FakeGroq(monkeypatch, "unused")
    client.post("/api/assistant/chat", json={"message": "hello"})
    client.post("/api/assistant/chat", json={"message": "Compare Deep Work and Atomic Habits"})
    assert groq.calls == []


def test_identical_first_question_comes_from_the_cache(client, monkeypatch):
    groq = FakeGroq(monkeypatch, answer("Cached answer."))
    for _ in range(2):
        r = client.post("/api/assistant/chat", json={"message": "Who wrote the Odyssey and why does it matter?"}).json()
        assert r["reply"]["text"] == "Cached answer."
    assert len(groq.calls) == 1


def test_model_can_only_choose_read_only_tools(client, monkeypatch):
    groq = FakeGroq(monkeypatch, json.dumps({"action": "tool", "tool": "create_reading_plan", "query": "plan"}))
    r = client.post("/api/assistant/chat", json={"message": "books about ancient history please"}).json()
    assert len(groq.calls) == 1
    assert r["reply"]["tool"] == "search_books" and r["reply"]["degraded"] is True, "invalid tool falls back, labelled"


def test_rate_limit_is_respected_and_reported_honestly(client, monkeypatch):
    groq = FakeGroq(monkeypatch, status_error(429, retry_after=42))
    r = client.post("/api/assistant/chat", json={"message": "books about machine learning for beginners"})
    assert r.status_code == 200
    reply = r.json()["reply"]
    assert reply["degraded"] is True and "closest matches" in reply["text"], "real matches, clearly labelled as a fallback"
    assert reply["payloads"], "the books are real catalogue records"
    assert llm.retry_after_seconds() >= 30
    client.post("/api/assistant/chat", json={"message": "books about machine learning for experts"})
    assert len(groq.calls) == 1, "no second call while the provider is cooling down"


def test_outage_with_nothing_to_show_is_an_error_and_saves_nothing(user_client, monkeypatch):
    c, _ = user_client
    FakeGroq(monkeypatch, status_error(429, retry_after=30))
    r = c.post("/api/assistant/chat", json={"message": "qwertyzzz plugh xyzzy"})
    assert r.status_code == 503 and int(r.headers["retry-after"]) > 0
    assert c.get("/api/assistant/conversations").json() == [], "a failed turn leaves no half-saved chat"


def test_bad_request_does_not_pause_the_provider(monkeypatch):
    FakeGroq(monkeypatch, status_error(400))
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("s", "u")
    assert llm.is_available(), "one rejected request says nothing about the provider"


def test_bad_key_pauses_for_a_long_time(monkeypatch):
    FakeGroq(monkeypatch, status_error(401))
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("s", "u")
    assert llm.retry_after_seconds() > 1800


def test_transient_failure_is_retried_once(monkeypatch):
    groq = FakeGroq(monkeypatch, status_error(503), "ok")
    assert llm.complete("s", "u").text == "ok"
    assert len(groq.calls) == 2


def test_empty_reply_does_not_pause_the_provider(monkeypatch):
    FakeGroq(monkeypatch, "   ")
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("s", "u")
    assert llm.is_available()


def test_blank_message_is_rejected(client):
    assert client.post("/api/assistant/chat", json={"message": "   "}).status_code == 422


def test_ordinal_references_pick_the_right_book(db):
    ids = [book_id_by_title(db, t) for t in ("Dune", "The Alchemist", "Deep Work")]
    picked = assistant._resolve_books(db, "books like the second one", {"last_book_ids": ids})
    assert [b.id for b in picked] == [ids[1]]


def test_everyday_uses_of_price_words_are_not_marketplace_searches():
    assert assistant.classify("What's the deal with the ending of Dune?") is None
    assert assistant.classify("Show me my wishlist").tool == "show_shelf"
    assert assistant.classify("Is ₹300 a fair price for The Alchemist?").tool == "find_used_copy"


def suggest(text, *books):
    return json.dumps({"action": "answer", "reply": text, "book_ids": [], "suggest": [{"title": t, "author": a} for t, a in books]})


def google_lookup(monkeypatch, known):
    """A stand-in for Google Books that knows only the given (title, author) pairs."""
    from app.integrations.metadata import BookMetadata
    from app.services import catalogue

    calls = []

    def search(query, db=None, limit=10):
        calls.append(query)
        return [BookMetadata(title=t, source="google_books", source_id=f"vol-{t}", authors=[a], cover_url="https://books.google.com/x.jpg")
                for t, a in known if t.lower() in query.lower()]

    monkeypatch.setattr(catalogue, "gb_search", search)
    monkeypatch.setattr(catalogue, "ol_search", lambda *a, **k: [])
    return calls


def test_books_outside_the_catalogue_are_recommended_as_real_records(client, db, monkeypatch):
    groq = FakeGroq(monkeypatch, suggest("These suit a five-year-old.", ("The Gruffalo", "Julia Donaldson"), ("Made Up Nonsense Book", "Nobody")))
    lookups = google_lookup(monkeypatch, [("The Gruffalo", "Julia Donaldson")])
    r = client.post("/api/assistant/chat", json={"message": "a birthday gift book for a 5 year old girl"}).json()
    assert len(groq.calls) == 1
    titles = [i["book"]["title"] for p in r["reply"]["payloads"] for i in p["items"]]
    assert titles == ["The Gruffalo"], "real books get cards; a title no provider knows is dropped"
    assert any("intitle" in q for q in lookups)
    assert r["context"]["last_book_ids"], "a follow-up can refer to it"
    again = client.post("/api/assistant/chat", json={"message": "another gift book for a 5 year old girl please"}).json()
    assert again["reply"]["tool"] == "chat"


def test_same_title_by_another_author_is_not_accepted(db, monkeypatch):
    from app.services.catalogue import find_or_add_by_title

    google_lookup(monkeypatch, [("Quiet Afternoons", "Someone Else")])
    assert find_or_add_by_title(db, "Quiet Afternoons", "Real Author") is None


def test_books_already_held_need_no_lookup(db, monkeypatch):
    from app.services.catalogue import find_or_add_by_title

    lookups = google_lookup(monkeypatch, [])
    assert find_or_add_by_title(db, "Dune", "Frank Herbert").title == "Dune"
    assert lookups == []


def test_system_prompt_forbids_dead_end_replies():
    assert "Never reply that nothing is available" in assistant.CHAT_SYSTEM


def test_specific_requests_reach_the_model_instead_of_generic_picks():
    assert assistant.classify("What should I read next?").tool == "recommend"
    assert assistant.classify("recommend me a book for my 5 year old niece") is None
    assert assistant.classify("a good book under 200 pages") is None
    assert assistant.classify("what should I buy for my dad") is None
    assert assistant.classify("Atomic Habits under ₹250").tool == "find_used_copy"


def test_similar_to_an_unheld_book_goes_to_the_model(client, monkeypatch):
    groq = FakeGroq(monkeypatch, answer("Try these."))
    r = client.post("/api/assistant/chat", json={"message": "books similar to The Wee Free Men"}).json()
    assert len(groq.calls) == 1 and r["reply"]["text"] == "Try these."


def test_misshapen_suggestions_do_not_break_the_turn(client, monkeypatch):
    FakeGroq(monkeypatch, json.dumps({"action": "answer", "reply": "Fine.", "suggest": ["bad", {"title": 5}, {"no": "title"}]}))
    google_lookup(monkeypatch, [])
    r = client.post("/api/assistant/chat", json={"message": "tell me about picture books for toddlers"}).json()
    assert r["reply"]["text"] == "Fine." and r["reply"]["degraded"] is False


def test_nothing_is_recommended_when_no_title_can_be_confirmed(client, monkeypatch):
    FakeGroq(monkeypatch, suggest("Here are some lovely books.", ("Imaginary Book One", "Nobody"), ("Imaginary Book Two", "Nobody")))
    google_lookup(monkeypatch, [])
    r = client.post("/api/assistant/chat", json={"message": "gift ideas for a toddler who likes trains"}).json()
    assert r["reply"]["payloads"] == [] and "couldn't confirm" in r["reply"]["text"]


def test_card_shows_the_reason_for_each_verified_book(client, monkeypatch):
    payload = {"action": "answer", "reply": "Some picks.", "suggest": [{"title": "Room on the Broom", "author": "Julia Donaldson", "why": "Gentle rhymes."}]}
    FakeGroq(monkeypatch, json.dumps(payload))
    google_lookup(monkeypatch, [("Room on the Broom", "Julia Donaldson")])
    r = client.post("/api/assistant/chat", json={"message": "a rhyming story for a four year old"}).json()
    assert r["reply"]["payloads"][0]["items"][0]["why"] == "Gentle rhymes."


def test_internal_ids_never_reach_the_reader(client, monkeypatch):
    FakeGroq(monkeypatch, answer("The Hobbit (id 72) is the shortest."))
    r = client.post("/api/assistant/chat", json={"message": "which of these has the fewest words overall"}).json()
    assert r["reply"]["text"] == "The Hobbit is the shortest."


def test_model_cannot_dead_end_on_comparison_tools():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        assistant.ChatTurn(action="tool", tool="similar_books", query="x")


def test_a_brief_rate_limit_waits_and_answers(monkeypatch):
    groq = FakeGroq(monkeypatch, status_error(429, retry_after=2), "ok")
    assert llm.complete("s", "u").text == "ok"
    assert len(groq.calls) == 2 and llm.is_available()


def test_outage_never_shows_unrelated_books(client, monkeypatch):
    FakeGroq(monkeypatch, status_error(429, retry_after=120))
    r = client.post("/api/assistant/chat", json={"message": "What's the capital of France?"})
    assert r.status_code == 503, "an unrelated question gets a retryable error, not keyword matches"


def test_catalogue_context_stays_small(db):
    ctx = {"last_book_ids": [book_id_by_title(db, t) for t in ("Dune", "The Alchemist", "Deep Work", "The Hobbit")]}
    assert len(assistant._catalogue_context(db, "fantasy adventure novels about friendship", ctx)) <= assistant.CATALOGUE_MAX_BOOKS


def test_ratings_from_a_handful_of_people_are_not_shown(db):
    from app.integrations.metadata import BookMetadata
    from app.services.catalogue import upsert_book

    few = upsert_book(db, BookMetadata(title="Tiny Sample Book", source="google_books", source_id="few", authors=["A"], rating_avg=1.0, rating_count=1))
    many = upsert_book(db, BookMetadata(title="Well Rated Book", source="google_books", source_id="many", authors=["B"], rating_avg=4.2, rating_count=80))
    db.commit()
    assert few.external_rating_avg is None and many.external_rating_avg == 4.2


def test_a_bare_greeting_gets_a_warm_welcome_without_a_model_call(client, monkeypatch):
    groq = FakeGroq(monkeypatch, answer("unused"))
    text = client.post("/api/assistant/chat", json={"message": "Hello!"}).json()["reply"]["text"]
    assert text.startswith("Hello") and "lovely" in text and groq.calls == []


def test_a_greeting_with_a_question_reaches_the_model(client, monkeypatch):
    groq = FakeGroq(monkeypatch, answer("How nice of you to ask."))
    r = client.post("/api/assistant/chat", json={"message": "hi, what makes a mystery satisfying to read?"}).json()
    assert r["reply"]["text"] == "How nice of you to ask." and len(groq.calls) == 1


def test_thanks_gets_a_kind_reply_and_no_more_books(client, monkeypatch):
    groq = FakeGroq(monkeypatch, answer("unused"))
    r = client.post("/api/assistant/chat", json={"message": "thank you so much!"}).json()
    assert "welcome" in r["reply"]["text"] and r["reply"]["payloads"] == [] and groq.calls == []


def test_reply_never_denies_a_book_that_is_being_shown(client, monkeypatch):
    FakeGroq(monkeypatch, suggest("I’m sorry, but I don’t have that title in our catalogue.", ("Room on the Broom", "Julia Donaldson")))
    google_lookup(monkeypatch, [("Room on the Broom", "Julia Donaldson")])
    r = client.post("/api/assistant/chat", json={"message": "do you stock that witch story with the broom?"}).json()
    assert r["reply"]["text"] == assistant.FOUND_IT and r["reply"]["payloads"][0]["items"]

