"""Legal companion: saved conversations whose answers rest on statute text.

The model and the statute search are replaced with fakes, so these run with no
keys and no Qdrant. What they pin down is the contract around the model: which
sections it is shown, which citations survive, what is saved, and who can see it.
"""

import json

import pytest
from fastapi.testclient import TestClient

from src.api.v1.endpoints import conversations as endpoint
from src.core import legal_chat
from src.main import app
from tests.conftest import USER_B, sign_in_as


def section(n, act="The Information Technology Act, 2000 (IT Act)", number="Section 66E"):
    return legal_chat._source(
        n,
        {
            "act": act,
            "section_number": number,
            "title": f"Title {n}",
            "content": f"Whoever, intentionally or knowingly ... text of source {n}.",
            "source_url": "https://www.indiacode.nic.in/handle/x",
        },
    )


class Fakes:
    def __init__(self):
        self.sources = [section(n) for n in range(1, 4)]
        self.reply = ["The law treats this as a violation of privacy [1]. ", "Did you share them? [2]"]
        self.needs_law = True
        self.search_query = "publishing private images without consent"
        self.queries = []
        self.model_messages = None
        self.stream_error = None
        self.retrieve_error = None

    async def retrieve(self, query):
        self.queries.append(query)
        if self.retrieve_error:
            raise self.retrieve_error
        return self.sources

    async def plan_search(self, history, message):
        return legal_chat.SearchPlan(needs_law=self.needs_law, search_query=self.search_query)

    async def stream_reply(self, messages):
        self.model_messages = messages
        for piece in self.reply:
            yield piece
        if self.stream_error:
            raise self.stream_error


@pytest.fixture()
def fakes(monkeypatch):
    fake = Fakes()
    monkeypatch.setattr(legal_chat.settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(legal_chat, "retrieve", fake.retrieve)
    monkeypatch.setattr(legal_chat, "plan_search", fake.plan_search)
    monkeypatch.setattr(legal_chat, "stream_reply", fake.stream_reply)
    return fake


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _fresh_limits():
    endpoint._MESSAGE_HISTORY.clear()
    endpoint._ANSWERING.clear()
    yield
    endpoint._MESSAGE_HISTORY.clear()
    endpoint._ANSWERING.clear()


def events(response):
    parsed = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        parsed.append((lines["event"], json.loads(lines["data"])))
    return parsed


def new_conversation(client):
    response = client.post("/api/v1/conversations", json={})
    assert response.status_code == 201
    return response.json()["conversation_id"]


def send(client, conversation_id, content="Someone posted my photos online without asking me."):
    return client.post(f"/api/v1/conversations/{conversation_id}/messages", json={"content": content})


# --- a turn -------------------------------------------------------------------


def test_a_turn_streams_sources_first_then_text_then_saves_both(client, fakes):
    cid = new_conversation(client)
    response = send(client, cid)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    stream = events(response)
    kinds = [kind for kind, _ in stream]
    assert kinds == ["sources", "delta", "delta", "done"]
    assert [s["n"] for s in stream[0][1]["sources"]] == [1, 2, 3]

    done = stream[-1][1]
    assert done["question"]["role"] == "user"
    assert done["answer"]["cited"] == [1, 2]
    assert done["answer"]["degraded"] is False
    assert done["title"] == "Someone posted my photos online without asking me."

    saved = client.get(f"/api/v1/conversations/{cid}").json()
    assert saved["title"] == done["title"]
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]
    assert saved["messages"][1]["sources"][0]["short_act"] == "IT Act"
    assert saved["messages"][1]["cited"] == [1, 2]


def test_the_search_uses_the_rewritten_question_not_the_raw_follow_up(client, fakes):
    cid = new_conversation(client)
    send(client, cid)
    fakes.search_query = "intoxication as a defence BNS"
    send(client, cid, "what if he was drunk?")
    assert fakes.queries[-1] == "intoxication as a defence BNS"


def test_the_model_sees_the_conversation_and_this_turns_sections(client, fakes):
    cid = new_conversation(client)
    send(client, cid)
    send(client, cid, "It was my ex. Does that change anything?")
    roles = [type(m).__name__ for m in fakes.model_messages]
    assert roles == ["SystemMessage", "HumanMessage", "AIMessage", "HumanMessage"]
    # Earlier answers' [n] pointed at earlier sections; they are stripped.
    assert "[1]" not in fakes.model_messages[2].content
    last = fakes.model_messages[-1].content
    assert "[1] The Information Technology Act, 2000 (IT Act), Section 66E" in last
    assert last.endswith("[MY MESSAGE]\nIt was my ex. Does that change anything?")


def test_small_talk_is_not_searched(client, fakes):
    fakes.needs_law = False
    fakes.reply = ["You're welcome."]
    cid = new_conversation(client)
    stream = events(send(client, cid, "thanks!"))
    assert fakes.queries == []
    assert stream[0] == ("sources", {"sources": []})
    assert stream[-1][1]["answer"]["cited"] == []


# --- citations ----------------------------------------------------------------


def test_a_citation_of_a_section_the_model_was_not_shown_is_dropped(client, fakes):
    fakes.reply = ["This is covered [1, 2] and also [9]."]
    cid = new_conversation(client)
    answer = events(send(client, cid))[-1][1]["answer"]
    assert answer["content"] == "This is covered [1][2] and also."
    assert answer["cited"] == [1, 2]


def test_validate_citations_keeps_first_use_order():
    text, cited = legal_chat.validate_citations("A [3]. B [1][3]. C [0].", 3)
    assert text == "A [3]. B [1][3]. C."
    assert cited == [3, 1]


def test_short_act_names():
    assert legal_chat.short_act("The Digital Personal Data Protection Act, 2023. (DPDP Act)") == "DPDP Act"
    assert legal_chat.short_act("Constitution of India") == "Constitution of India"


# --- without the model, and when things fail ------------------------------------


def test_without_a_model_key_it_shows_the_sections_and_says_why(client, fakes, monkeypatch):
    monkeypatch.setattr(legal_chat.settings, "GROQ_API_KEY", "")
    cid = new_conversation(client)
    stream = events(send(client, cid, "my landlord kept my deposit"))
    answer = stream[-1][1]["answer"]
    assert answer["degraded"] is True
    assert answer["content"] == legal_chat.MODEL_UNAVAILABLE
    assert answer["cited"] == [1, 2, 3]
    assert fakes.model_messages is None
    assert fakes.queries == ["my landlord kept my deposit"]


def test_without_a_model_a_follow_up_is_searched_with_the_previous_message(client, fakes, monkeypatch):
    monkeypatch.setattr(legal_chat.settings, "GROQ_API_KEY", "")
    cid = new_conversation(client)
    send(client, cid, "my landlord kept my deposit")
    send(client, cid, "it was 50000 rupees")
    assert fakes.queries[-1] == "my landlord kept my deposit it was 50000 rupees"


def test_without_a_model_and_nothing_found_it_says_so(client, fakes, monkeypatch):
    monkeypatch.setattr(legal_chat.settings, "GROQ_API_KEY", "")
    fakes.sources = []
    cid = new_conversation(client)
    answer = events(send(client, cid))[-1][1]["answer"]
    assert answer["content"] == legal_chat.NOTHING_FOUND


def test_a_failed_search_plan_falls_back_instead_of_failing(client, fakes, monkeypatch):
    async def broken(history, message):
        raise RuntimeError("groq down")

    monkeypatch.setattr(legal_chat, "plan_search", broken)
    cid = new_conversation(client)
    answer = events(send(client, cid))[-1][1]["answer"]
    assert answer["degraded"] is True


def test_an_answer_that_fails_part_way_saves_nothing(client, fakes):
    fakes.stream_error = RuntimeError("connection reset")
    cid = new_conversation(client)
    stream = events(send(client, cid))
    assert stream[-1][0] == "error"
    assert client.get(f"/api/v1/conversations/{cid}").json()["messages"] == []
    # And the conversation is free for the retry.
    fakes.stream_error = None
    assert events(send(client, cid))[-1][0] == "done"


def test_a_failed_statute_search_saves_nothing(client, fakes):
    fakes.retrieve_error = ConnectionError("qdrant")
    cid = new_conversation(client)
    stream = events(send(client, cid))
    assert stream == [("error", {"detail": "The statute search isn't available right now. Try again in a minute."})]
    assert client.get(f"/api/v1/conversations/{cid}").json()["messages"] == []


def test_only_the_last_twelve_messages_reach_the_model(fakes):
    import asyncio

    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(20)]

    async def run():
        return [e async for e in legal_chat.answer(history, "now?")]

    asyncio.run(run())
    # System prompt, the window, then this turn.
    assert len(fakes.model_messages) == 1 + legal_chat.HISTORY_WINDOW + 1
    assert fakes.model_messages[1].content == "m8"


# --- limits -------------------------------------------------------------------


@pytest.mark.parametrize("content", ["", "   ", "x" * 4001])
def test_empty_or_overlong_messages_are_refused(client, fakes, content):
    cid = new_conversation(client)
    assert send(client, cid, content).status_code == 422


def test_messages_are_rate_limited_per_user(client, fakes, monkeypatch):
    monkeypatch.setattr(endpoint.settings, "RATE_LIMIT_PER_MINUTE", 2)
    cid = new_conversation(client)
    assert send(client, cid).status_code == 200
    assert send(client, cid).status_code == 200
    assert send(client, cid).status_code == 429


def test_a_second_message_waits_for_the_first_answer(client, fakes):
    cid = new_conversation(client)
    endpoint._ANSWERING.add(cid)
    response = send(client, cid)
    assert response.status_code == 409
    assert "Wait for the current answer" in response.json()["detail"]


# --- ownership and housekeeping ---------------------------------------------


def test_someone_elses_conversation_does_not_exist_for_you(client, fakes):
    cid = new_conversation(client)
    send(client, cid)
    sign_in_as(USER_B)
    assert client.get(f"/api/v1/conversations/{cid}").status_code == 404
    assert client.patch(f"/api/v1/conversations/{cid}", json={"title": "mine"}).status_code == 404
    assert send(client, cid).status_code == 404
    assert client.delete(f"/api/v1/conversations/{cid}").status_code == 404
    assert cid not in [c["conversation_id"] for c in client.get("/api/v1/conversations").json()["items"]]


def test_the_list_is_your_own_most_recent_first(client, fakes):
    first, second = new_conversation(client), new_conversation(client)
    send(client, second)
    send(client, first)  # now the most recently active
    items = client.get("/api/v1/conversations?limit=100").json()["items"]
    ids = [c["conversation_id"] for c in items]
    assert ids.index(first) < ids.index(second)
    assert all("owner_uid" not in c for c in items)


def test_a_conversation_whose_first_message_never_saved_is_not_listed(client, fakes):
    fakes.stream_error = RuntimeError("connection reset")
    cid = new_conversation(client)
    send(client, cid)
    ids = [c["conversation_id"] for c in client.get("/api/v1/conversations?limit=100").json()["items"]]
    assert cid not in ids
    # It still opens, so the page that made it can retry.
    assert client.get(f"/api/v1/conversations/{cid}").status_code == 200


def test_rename_and_delete(client, fakes):
    cid = new_conversation(client)
    send(client, cid)
    renamed = client.patch(f"/api/v1/conversations/{cid}", json={"title": "  Photos  "})
    assert renamed.json()["title"] == "Photos"
    assert client.patch(f"/api/v1/conversations/{cid}", json={"title": "  "}).status_code == 422
    assert client.delete(f"/api/v1/conversations/{cid}").status_code == 204
    assert client.get(f"/api/v1/conversations/{cid}").status_code == 404


def test_a_title_is_set_once_from_the_first_message(client, fakes):
    cid = new_conversation(client)
    send(client, cid, "First: " + "long words " * 20)
    send(client, cid, "Second message")
    title = client.get(f"/api/v1/conversations/{cid}").json()["title"]
    assert title.startswith("First: ") and title.endswith("…") and len(title) == 60


# --- weak matches and everyday words ------------------------------------------


def test_everyday_words_are_searched_in_the_statutes_own_terms():
    assert "information in cognizable cases" in legal_chat.expand("Police refused to register my FIR")
    assert "lessor lessee" in legal_chat.expand("my landlord kept my deposit")
    assert legal_chat.expand("a question about wills") == "a question about wills"


def test_a_section_is_weak_only_on_a_low_cross_encoder_score():
    doc = {"act": "A (X)", "section_number": "Section 1", "title": "t", "content": "c"}
    assert legal_chat._source(1, {**doc, "rerank_mode": "cross_encoder", "rerank_score": -2.0})["weak"]
    assert not legal_chat._source(1, {**doc, "rerank_mode": "cross_encoder", "rerank_score": 0.3})["weak"]
    # Without the cross-encoder there is no comparable score, so nothing is called weak.
    assert not legal_chat._source(1, {**doc, "rerank_mode": "rrf_fallback", "rerank_score": 0.01})["weak"]


def test_without_a_model_weak_matches_are_not_presented_as_the_law(client, fakes, monkeypatch):
    monkeypatch.setattr(legal_chat.settings, "GROQ_API_KEY", "")
    fakes.sources = [{**s, "weak": True} for s in fakes.sources]
    cid = new_conversation(client)
    answer = events(send(client, cid, "my salary is unpaid"))[-1][1]["answer"]
    assert answer["content"] == legal_chat.NOT_COVERED
    assert answer["cited"] == []
    assert len(answer["sources"]) == 3


def test_the_model_is_told_when_every_section_matched_weakly(client, fakes):
    fakes.sources = [{**s, "weak": True} for s in fakes.sources]
    cid = new_conversation(client)
    send(client, cid, "my salary is unpaid")
    assert "matched the question only weakly" in fakes.model_messages[-1].content
