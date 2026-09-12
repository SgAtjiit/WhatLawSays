"""Tests for the contract-review API surface.

The LLM is patched out throughout: these tests are about the HTTP contract --
limits, validation, persistence, deletion -- not about model output. The
pipeline's deterministic fallback means a full review is still produced.
"""

import contextlib
import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.core.document_parser import MAX_FILE_BYTES
from src.main import app

LLM_MODULES = [
    "profiler", "clause_classifier", "query_builder", "explainer", "red_flag_analyst",
]


def _dead(*args, **kwargs):
    raise RuntimeError("Groq unreachable")


@contextlib.contextmanager
def offline():
    """No Groq, no Qdrant -- the deterministic spine must still serve a review."""
    with contextlib.ExitStack() as stack:
        for name in LLM_MODULES:
            stack.enter_context(
                patch(f"src.agents.contract_nodes.{name}.ChatGroq", side_effect=_dead)
            )
        stack.enter_context(
            patch(
                "src.agents.contract_nodes.clause_retriever.vector_store.hybrid_search",
                side_effect=RuntimeError("no qdrant"),
            )
        )
        yield


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """The upload limiter is process-global; without this it bleeds between tests."""
    from src.api.v1.endpoints import contracts as endpoint

    endpoint._UPLOAD_HISTORY.clear()
    yield
    endpoint._UPLOAD_HISTORY.clear()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def contract_bytes():
    with open("tests/fixtures/employment_agreement.txt", "rb") as handle:
        return handle.read()


def _upload(client, data, name="employment.txt", **form):
    return client.post(
        "/api/v1/contracts",
        files={"file": (name, io.BytesIO(data), "text/plain")},
        data=form,
    )


def test_supported_options_are_discoverable(client):
    body = client.get("/api/v1/contracts/meta/supported").json()
    assert "application/pdf" in body["media_types"]
    assert body["max_file_bytes"] == MAX_FILE_BYTES
    assert "EMPLOYMENT" in body["contract_types"]
    assert body["positions_by_type"]["LEASE"] == ["TENANT", "LANDLORD"]


def test_uploading_a_contract_returns_a_review(client, contract_bytes):
    with offline():
        response = _upload(
            client, contract_bytes, contract_type="EMPLOYMENT", position="EMPLOYEE"
        )
    assert response.status_code == 200
    body = response.json()
    assert body["contract_type"] == "EMPLOYMENT"
    assert body["position"] == "EMPLOYEE"
    assert body["position_source"] == "USER_DECLARED"
    assert body["findings"]
    assert body["clause_count"] == 11
    assert body["disclaimer"]


def test_the_declared_side_changes_the_severities(client, contract_bytes):
    """The same document is a different contract to each party."""
    with offline():
        employee = _upload(
            client, contract_bytes, contract_type="EMPLOYMENT", position="EMPLOYEE"
        ).json()
        employer = _upload(
            client, contract_bytes, contract_type="EMPLOYMENT", position="EMPLOYER"
        ).json()

    def severity(review, rule_id):
        return next(f["severity"] for f in review["findings"] if f["rule_id"] == rule_id)

    assert severity(employee, "BROAD_IP_ASSIGNMENT") == "CRITICAL"
    assert severity(employer, "BROAD_IP_ASSIGNMENT") == "INFO"


def test_an_unreadable_document_is_refused_with_a_reason(client):
    """An empty review would read as a clean contract, so this must be a 422."""
    with offline():
        response = _upload(client, b"too short to be a contract", name="tiny.txt")
    assert response.status_code == 422
    assert "too little to review" in response.json()["detail"]


def test_an_unsupported_file_type_is_refused(client):
    response = client.post(
        "/api/v1/contracts",
        files={
            "file": ("contract.pages", io.BytesIO(b"x" * 5000), "application/octet-stream")
        },
    )
    assert response.status_code == 422
    assert "Unsupported file type" in response.json()["detail"]


def test_a_known_declared_type_is_honoured_when_the_extension_is_unknown(client, contract_bytes):
    """Browsers routinely send a generic or wrong type, so the extension is
    preferred -- but a recognised declared type still gets the file read."""
    with offline():
        response = client.post(
            "/api/v1/contracts",
            files={"file": ("contract.bin", io.BytesIO(contract_bytes), "text/plain")},
            data={"contract_type": "EMPLOYMENT", "position": "EMPLOYEE"},
        )
    assert response.status_code == 200


def test_an_oversized_upload_is_refused_before_parsing(client):
    response = _upload(client, b"x" * (MAX_FILE_BYTES + 10), name="big.txt")
    assert response.status_code == 413


def test_an_unknown_position_is_rejected_with_the_valid_values(client, contract_bytes):
    response = _upload(client, contract_bytes, position="LANDLORD_OF_THE_MANOR")
    assert response.status_code == 422
    assert "EMPLOYEE" in response.json()["detail"]


def test_a_review_can_be_fetched_and_then_deleted(client, contract_bytes):
    """Retention is only a promise if deletion actually works: the extracted
    text is stored so quotes stay verifiable, and it carries salary and address."""
    with offline():
        review = _upload(
            client, contract_bytes, contract_type="EMPLOYMENT", position="EMPLOYEE"
        ).json()
    contract_id = review["contract_id"]

    fetched = client.get(f"/api/v1/contracts/{contract_id}")
    assert fetched.status_code == 200
    assert fetched.json()["contract_id"] == contract_id

    deleted = client.delete(f"/api/v1/contracts/{contract_id}")
    assert deleted.status_code == 200 and deleted.json()["deleted"]

    assert client.get(f"/api/v1/contracts/{contract_id}").status_code == 404
    assert client.delete(f"/api/v1/contracts/{contract_id}").status_code == 404


def test_fetching_an_unknown_contract_is_a_404(client):
    assert client.get("/api/v1/contracts/doesnotexist").status_code == 404


def test_the_async_endpoint_enqueues_and_returns_a_poll_url(client, contract_bytes):
    response = client.post(
        "/api/v1/contracts/async",
        files={"file": ("e.txt", io.BytesIO(contract_bytes), "text/plain")},
        data={"contract_type": "EMPLOYMENT", "position": "EMPLOYEE"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["poll"].endswith(body["contract_id"])
    # The poll URL must resolve immediately, not only once a worker has run:
    # before this, a client following the documented URL got 404 for as long
    # as the task sat on the queue.
    polled = client.get(body["poll"])
    assert polled.status_code == 200
    assert polled.json()["status"] == "QUEUED"
    assert client.delete(f"/api/v1/contracts/{body['contract_id']}").status_code == 200


def test_the_queue_round_trips_the_file_bytes(contract_bytes):
    """The worker may be a different process, so the bytes travel on the queue
    rather than through a shared filesystem neither side is guaranteed."""
    import asyncio

    from src.core.task_queue import task_queue

    # The queue caches a Redis client bound to whichever event loop first touched
    # it, and asyncio.run() below opens a new one. The app has a single loop so
    # this only bites a test harness, but the cached client must be dropped or
    # every call here fails against the closed loop.
    task_queue._redis_client = None

    async def roundtrip():
        # Redis persists between tests, and the async-endpoint test above leaves a
        # real task queued with no worker to consume it. Drain first so this test
        # measures its own round trip, not that one.
        client = await task_queue.get_client()
        if client:
            await client.delete(task_queue.contract_queue_key)

        await task_queue.enqueue_contract({
            "contract_id": "queue-test",
            "filename": "e.txt",
            "contract_type": "EMPLOYMENT",
            "position": "EMPLOYEE",
            "data": contract_bytes,
        })
        return await task_queue.consume_next_contract(timeout=2)

    try:
        task = asyncio.run(roundtrip())
    finally:
        task_queue._redis_client = None
    assert task is not None
    assert task["data"] == contract_bytes
    assert task["contract_id"] == "queue-test"


def test_upload_rate_limiting_bites(client, contract_bytes):
    from src.api.v1.endpoints import contracts as endpoint

    with offline():
        codes = [
            _upload(client, contract_bytes).status_code
            for _ in range(endpoint.UPLOAD_RATE_LIMIT_PER_MINUTE + 1)
        ]
    assert codes[-1] == 429


# ---------------------------------------------------------------------------
# Findings from the audit
# ---------------------------------------------------------------------------

def test_an_explicit_unknown_position_is_not_treated_as_declared(client, contract_bytes):
    """UNKNOWN is the absence of an answer. Sent explicitly it was recorded as
    USER_DECLARED, silencing the "which side?" question and lifting confidence
    for a review that had no idea which party it was for."""
    with offline():
        body = _upload(client, contract_bytes, contract_type="EMPLOYMENT", position="UNKNOWN").json()
    assert body["position_source"] == "UNKNOWN"
    assert body["clarification_questions"]
    # Offline, the LLM cap (0.60) binds before the position cap (0.65) can be
    # recorded, so check the bound and the basis note rather than the label.
    assert body["confidence_score"] <= 0.65
    assert any("No reviewing side" in note for note in body["confidence_basis"]["notes"])


def test_a_side_from_a_different_contract_type_is_rejected(client, contract_bytes):
    response = _upload(client, contract_bytes, contract_type="EMPLOYMENT", position="TENANT")
    assert response.status_code == 422
    assert "EMPLOYEE" in response.json()["detail"]


def test_a_deleted_contract_is_not_resurrected_by_a_late_save():
    """A review runs for a minute or more. Deleting mid-flight returned
    {"deleted": true} and then the completion write re-inserted everything."""
    import asyncio

    from src.core import database as db

    def postgres_down():
        raise RuntimeError("postgres down")

    with patch.object(db, "AsyncSessionLocal", postgres_down):
        async def run():
            await db.save_contract({"contract_id": "late-1", "filename": "e.txt", "status": "RUNNING"})
            assert await db.delete_contract("late-1")
            written = await db.save_contract(
                {"contract_id": "late-1", "filename": "e.txt", "status": "SUCCESS", "review": {"x": 1}},
                update_only=True,
            )
            return written, await db.get_contract("late-1")

        written, after = asyncio.run(run())
    assert written is False
    assert after is None


def test_a_malformed_queue_message_does_not_crash_the_consumer():
    """One bad message otherwise took the worker down under a restart loop and
    stranded every task queued behind it."""
    import asyncio
    from unittest.mock import AsyncMock

    from src.core.task_queue import task_queue

    with patch.object(task_queue, "get_client", AsyncMock(return_value=None)):
        async def run():
            task_queue._in_memory_contract_queue = asyncio.Queue()
            task_queue._in_memory_contract_queue.put_nowait("not even a dict")
            task_queue._in_memory_contract_queue.put_nowait({"filename": "no id here"})
            first = await task_queue.consume_next_contract(timeout=1)
            second = await task_queue.consume_next_contract(timeout=1)
            await task_queue.enqueue_contract(
                {"contract_id": "ok-1", "filename": "e.txt", "data": b"hello"}
            )
            third = await task_queue.consume_next_contract(timeout=1)
            return first, second, third

        first, second, third = asyncio.run(run())
    assert first is None and second is None
    assert third["contract_id"] == "ok-1" and third["data"] == b"hello"


def test_redis_down_at_startup_is_retried_rather_than_cached_for_ever():
    """An API process that started before Redis used to answer QUEUED for the
    rest of its life while every task sat in a queue no worker could see."""
    import asyncio
    import time

    from src.core import task_queue as tq

    class Flaky:
        calls = 0

        def __init__(self, *a, **k):
            pass

        async def ping(self):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise ConnectionError("refused")

    q = tq.RedisTaskQueue()
    q.reconnect_after = 15.0
    with patch.object(tq.aioredis, "from_url", Flaky):
        async def run():
            first = await q.get_client()            # fails, cached as False
            too_soon = await q.get_client()         # inside the back-off: no retry
            q._redis_failed_at = time.monotonic() - 100
            later = await q.get_client()            # back-off elapsed: reconnects
            return first, too_soon, later

        first, too_soon, later = asyncio.run(run())
    assert first is None and too_soon is None
    assert later is not None
    assert Flaky.calls == 2


def test_the_async_endpoint_refuses_when_no_worker_could_ever_see_the_task(client, contract_bytes):
    from unittest.mock import AsyncMock

    from src.core.task_queue import task_queue

    with patch.object(task_queue, "get_client", AsyncMock(return_value=None)):
        response = client.post(
            "/api/v1/contracts/async",
            files={"file": ("e.txt", io.BytesIO(contract_bytes), "text/plain")},
        )
    assert response.status_code == 503
    assert "/api/v1/contracts" in response.json()["detail"]


class _FakeSession:
    """A PostgreSQL that answers, without needing one."""

    store = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, model, contract_id):
        return self.store.get(contract_id)

    def add(self, row):
        self.store[row.contract_id] = row

    async def commit(self):
        pass

    async def delete(self, row):
        self.store.pop(row.contract_id, None)


def test_memory_is_not_used_while_postgres_is_healthy():
    """It used to mirror every review -- full text, salaries, addresses --
    unbounded and never evicted, even with the database up."""
    import asyncio

    from src.core import database as db

    _FakeSession.store.clear()
    db._MEMORY_CONTRACTS.clear()
    with patch.object(db, "AsyncSessionLocal", lambda: _FakeSession()):
        async def run():
            await db.save_contract({"contract_id": "healthy-1", "filename": "e.txt", "status": "SUCCESS", "review": {"x": 1}})
            fetched = await db.get_contract("healthy-1")
            _FakeSession.store.clear()          # deleted out of band
            return fetched, await db.get_contract("healthy-1")

        fetched, after_external_delete = asyncio.run(run())
    assert fetched["status"] == "SUCCESS"
    assert "healthy-1" not in db._MEMORY_CONTRACTS
    assert after_external_delete is None


def test_memory_fallback_is_bounded():
    import asyncio

    from src.core import database as db

    def postgres_down():
        raise RuntimeError("postgres down")

    db._MEMORY_CONTRACTS.clear()
    with patch.object(db, "AsyncSessionLocal", postgres_down):
        async def run():
            for i in range(db._MEMORY_LIMIT + 25):
                await db.save_contract({"contract_id": f"flood-{i}", "filename": "e.txt", "status": "RUNNING"})

        asyncio.run(run())
    assert len(db._MEMORY_CONTRACTS) == db._MEMORY_LIMIT
    assert "flood-0" not in db._MEMORY_CONTRACTS
    assert f"flood-{db._MEMORY_LIMIT + 24}" in db._MEMORY_CONTRACTS
    db._MEMORY_CONTRACTS.clear()


def test_an_overlong_filename_is_stored_rather_than_silently_dropped():
    import asyncio

    from src.core import database as db

    _FakeSession.store.clear()
    with patch.object(db, "AsyncSessionLocal", lambda: _FakeSession()):
        asyncio.run(db.save_contract({"contract_id": "long-1", "filename": "x" * 600, "status": "RUNNING"}))
    assert len(_FakeSession.store["long-1"].filename) <= db._FILENAME_LIMIT
