"""Sign-in and ownership.

A contract carries salaries, addresses and party names, so every route that
touches one must know who is asking, and must treat someone else's contract
exactly like one that does not exist.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from firebase_admin import auth as firebase_auth

from src.core import auth
from src.core.auth import require_user
from src.core.database import save_contract
from src.main import app, mount_frontend
from tests.conftest import USER_A, USER_B, sign_in_as
from tests.test_contract_api import offline

CONTRACT_ROUTES = [
    ("get", "/api/v1/contracts/{id}"),
    ("get", "/api/v1/contracts/{id}/redlines"),
    ("get", "/api/v1/contracts/{id}/report.pdf"),
    ("get", "/api/v1/contracts/{id}/document"),
    ("post", "/api/v1/contracts/{id}/ask"),
    ("delete", "/api/v1/contracts/{id}"),
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    from src.api.v1.endpoints import contracts as endpoint

    endpoint._UPLOAD_HISTORY.clear()
    yield
    endpoint._UPLOAD_HISTORY.clear()


@pytest.fixture()
def real_auth(monkeypatch):
    """The real dependency, with token verification stubbed per test."""
    app.dependency_overrides.pop(require_user, None)
    monkeypatch.setattr(auth.settings, "FIREBASE_PROJECT_ID", "demo-whatlawsays")
    return monkeypatch


def _upload(client):
    with open("tests/fixtures/employment_agreement.txt", "rb") as handle:
        data = handle.read()
    with offline():
        response = client.post(
            "/api/v1/contracts",
            files={"file": ("employment.txt", data, "text/plain")},
            data={"contract_type": "EMPLOYMENT", "position": "EMPLOYEE"},
        )
    assert response.status_code == 200, response.text
    return response.json()


def _call(client, method, path, contract_id):
    url = path.format(id=contract_id)
    if method == "post":
        return client.post(url, json={"question": "What is my notice period?"})
    return getattr(client, method)(url)


# --- Sign-in -----------------------------------------------------------------


def test_no_token_is_a_401(client, real_auth):
    response = client.get("/api/v1/contracts")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_scenario_analysis_needs_sign_in_too(client, real_auth):
    response = client.post("/api/v1/analyze", json={"scenario_text": "A theft occurred."})
    assert response.status_code == 401


def test_an_invalid_token_is_a_401(client, real_auth):
    def reject(_token):
        raise firebase_auth.InvalidIdTokenError("bad token")

    real_auth.setattr(auth, "_verify", reject)
    response = client.get("/api/v1/contracts", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401
    assert "Sign in again" in response.json()["detail"]


def test_an_unverified_email_account_is_a_403(client, real_auth):
    real_auth.setattr(auth, "_verify", lambda _t: {
        "uid": "fresh", "email_verified": False,
        "firebase": {"sign_in_provider": "password"},
    })
    response = client.get("/api/v1/contracts", headers={"Authorization": "Bearer t"})
    assert response.status_code == 403
    assert "Verify your email" in response.json()["detail"]


def test_a_verified_user_is_let_through_as_themselves(client, real_auth):
    real_auth.setattr(auth, "_verify", lambda _t: {
        "uid": "verified-user", "email_verified": True,
        "firebase": {"sign_in_provider": "google.com"},
    })
    response = client.get("/api/v1/contracts", headers={"Authorization": "Bearer t"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "has_more": False}


def test_an_unconfigured_server_says_so(client, real_auth):
    real_auth.setattr(auth.settings, "FIREBASE_PROJECT_ID", "")
    real_auth.setattr(auth, "_firebase_app", None)
    response = client.get("/api/v1/contracts", headers={"Authorization": "Bearer t"})
    assert response.status_code == 503


def test_public_routes_stay_public(client, real_auth):
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/contracts/meta/supported").status_code == 200


# --- Ownership ---------------------------------------------------------------


@pytest.mark.parametrize("method,path", CONTRACT_ROUTES)
def test_another_users_contract_is_indistinguishable_from_a_missing_one(
    client, method, path
):
    contract_id = _upload(client)["contract_id"]
    sign_in_as(USER_B)
    theirs = _call(client, method, path, contract_id)
    missing = _call(client, method, path, "doesnotexist")
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json()["detail"].replace(contract_id, "X") == missing.json()[
        "detail"
    ].replace("doesnotexist", "X")

    sign_in_as(USER_A)
    assert _call(client, "get", "/api/v1/contracts/{id}", contract_id).status_code == 200


def test_the_owner_can_use_every_route(client):
    contract_id = _upload(client)["contract_id"]
    for method, path in CONTRACT_ROUTES:
        assert _call(client, method, path, contract_id).status_code == 200, path


def test_a_contract_with_no_owner_is_reachable_by_nobody(client):
    # On the client's own event loop: the connection pool belongs to it.
    client.portal.call(save_contract, {
        "contract_id": "legacy-anonymous",
        "filename": "old.txt",
        "status": "SUCCESS",
        "review": {"status": "SUCCESS"},
    })
    assert client.get("/api/v1/contracts/legacy-anonymous").status_code == 404


def test_the_list_holds_only_your_own_reviews_newest_first(client):
    sign_in_as(USER_B)
    before = {r["contract_id"] for r in client.get("/api/v1/contracts?limit=100").json()["items"]}
    sign_in_as(USER_A)
    first = _upload(client)["contract_id"]
    second = _upload(client)["contract_id"]

    mine = client.get("/api/v1/contracts?limit=100").json()["items"]
    ids = [r["contract_id"] for r in mine]
    assert ids.index(second) < ids.index(first)
    assert set(mine[0]) == {
        "contract_id", "filename", "contract_type", "position", "status",
        "overall_risk", "confidence_score", "clause_count", "created_at",
    }

    sign_in_as(USER_B)
    theirs = {r["contract_id"] for r in client.get("/api/v1/contracts?limit=100").json()["items"]}
    assert theirs == before
    assert first not in theirs and second not in theirs


def test_the_list_pages(client):
    _upload(client)
    _upload(client)
    page = client.get("/api/v1/contracts?limit=1").json()
    assert len(page["items"]) == 1 and page["has_more"] is True


def test_the_document_is_the_text_every_offset_indexes_into(client):
    review = _upload(client)
    document = client.get(f"/api/v1/contracts/{review['contract_id']}/document").json()
    assert document["source"] == "text_layer"
    assert review["findings"], "fixture should produce findings"
    for finding in review["findings"]:
        # Quotes collapse line breaks, as the grounding verifier does.
        span = document["text"][finding["match_start"]:finding["match_end"]]
        assert " ".join(span.split()) == finding["matched_quote"]


def test_startup_migration_never_waits_on_another_transaction(monkeypatch):
    """A restart must not hang behind an open transaction on the table.

    ALTER TABLE wants an exclusive lock even when the column exists already;
    init_db once queued behind an idle transaction for ten minutes.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from src.config import settings
    from src.core import database

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    monkeypatch.setattr(database, "engine", engine)

    async def scenario():
        await database.init_db()
        async with engine.connect() as holder:
            await holder.execute(text("BEGIN"))
            await holder.execute(text("SELECT 1 FROM contract_documents LIMIT 1"))
            await asyncio.wait_for(database.init_db(), timeout=10)
            await holder.execute(text("ROLLBACK"))
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'contract_documents' AND column_name = 'owner_uid'"
            ))
            return rows.fetchall()

    try:
        found = asyncio.run(scenario())
    except OSError:
        pytest.skip("PostgreSQL is not reachable")
    assert len(found) == 1


# --- Serving the frontend ----------------------------------------------------


def test_the_built_frontend_is_served_without_shadowing_the_api(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")

    site = FastAPI()

    @site.get("/api/v1/ping")
    async def ping():
        return {"ok": True}

    assert mount_frontend(site, tmp_path)
    web = TestClient(site)

    assert web.get("/api/v1/ping").json() == {"ok": True}
    assert web.get("/api/v1/nope").status_code == 404
    assert web.get("/assets/app.js").text == "console.log(1)"
    assert web.get("/favicon.svg").text == "<svg/>"
    deep_link = web.get("/contracts/abc123")
    assert "<title>app</title>" in deep_link.text
    assert deep_link.headers["cache-control"] == "no-cache"
    assert web.get("/../pyproject.toml").status_code in (200, 404)
    assert "dependencies" not in web.get("/..%2fpyproject.toml").text


def test_no_build_means_nothing_is_mounted(tmp_path):
    assert mount_frontend(FastAPI(), tmp_path) is False
