"""The procurement endpoints.

Two of these tests are about refusals rather than results.
`test_an_event_without_provided_collections_is_refused` and
`test_an_empty_event_is_refused_rather_than_reviewed` both exist because the
failure they guard is silent: a review with no findings looks exactly like a
clean award, so an event that cannot honestly be checked has to be turned away
at the door rather than returned as a reassuring empty result.
"""

import contextlib
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.v1.endpoints import procurement
from src.main import app


def _dead(*args, **kwargs):
    raise RuntimeError("Groq unreachable")


@contextlib.contextmanager
def offline():
    """No Groq, no Qdrant.

    These tests are about the HTTP contract -- validation, refusals, persistence,
    deletion -- not about model output, and the deterministic spine produces the
    entire finding set without either service. Patching them out also keeps the
    suite from depending on a network round trip per request, which is how a test
    suite starts failing for reasons that have nothing to do with the code.
    """
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch("src.agents.procurement_nodes.narrator.ChatGroq", side_effect=_dead)
        )
        stack.enter_context(
            patch(
                "src.core.vector_store.vector_store.hybrid_search",
                side_effect=RuntimeError("no qdrant"),
            )
        )
        yield

EVENT = {
    "event_id": "EVT-TEST",
    "title": "Conveyor spares",
    "category": "MRO",
    "bids": [
        {
            "vendor": {
                "vendor_id": "V-1", "name": "Alpha Traders", "msme_status": "SMALL",
                "on_approved_list": True, "is_related_party": False,
                "processes_personal_data": False, "gstin": "27AAACA1234A1Z5",
            },
            "total": "640000",
        },
        {
            "vendor": {
                "vendor_id": "V-2", "name": "Beta Supply", "msme_status": "NOT_MSME",
                "on_approved_list": True, "gstin": "29AAACA1234A1Z9",
            },
            "total": "641200",
        },
    ],
    "award": {"vendor_id": "V-1", "value": "640000", "decided_at": "2026-03-10T00:00:00"},
    "approvals": [
        {"approver_role": "MANAGER", "approved_at": "2026-03-12T00:00:00", "stage": "AWARD"}
    ],
    "purchase_order": {
        "po_number": "PO-900", "vendor_id": "V-1", "value": "640000",
        "payment_terms_days": 60, "has_written_agreement": True,
        "issued_at": "2026-03-11T00:00:00",
    },
    "company_profile": {"entity_name": "Acme", "has_audit_committee": True, "related_parties": []},
    "provided_collections": [
        "bids", "approvals", "purchase_order", "company_profile", "vendor_msme_status"
    ],
}


@pytest.fixture
def client():
    # The per-IP limit is real and is exercised by its own test below. Every
    # other test would otherwise spend it, and a 429 mid-suite reads as a broken
    # endpoint rather than as a working guard.
    procurement._HISTORY.clear()
    with offline(), TestClient(app) as c:
        yield c


def make_policy(client, rules, ratify=True, activate=True):
    response = client.post(
        "/api/v1/policies",
        json={"org_label": "Acme", "company_id": "ACME", "rules": rules},
    )
    policy_id = response.json()["policy_id"]
    if ratify:
        for rule in rules:
            client.patch(
                f"/api/v1/policies/{policy_id}/rules/{rule['rule_id']}",
                json={"action": "RATIFY", "actor": "tester"},
            )
    if activate:
        client.post(f"/api/v1/policies/{policy_id}/activate")
    return policy_id


DEFAULT_RULES = [
    {"rule_id": "R1", "kind": "MIN_QUOTES_BY_VALUE",
     "params": {"above_value": 500000, "min_quotes": 3}, "status": "DRAFT"},
    {"rule_id": "R2", "kind": "APPROVAL_AUTHORITY",
     "params": {"above_value": 500000, "required_role": "CFO"}, "status": "DRAFT"},
]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_an_event_without_provided_collections_is_refused(client):
    payload = {k: v for k, v in EVENT.items() if k != "provided_collections"}
    response = client.post("/api/v1/awards", data={"event": json.dumps(payload)})
    assert response.status_code == 422
    assert "provided_collections" in response.json()["detail"]


def test_an_empty_event_is_refused_rather_than_reviewed(client):
    response = client.post("/api/v1/awards", data={"event": json.dumps(
        {"event_id": "E", "provided_collections": ["bids"]}
    )})
    assert response.status_code == 422
    assert "nothing to check" in response.json()["detail"]


def test_malformed_json_is_refused(client):
    response = client.post("/api/v1/awards", data={"event": "{not json"})
    assert response.status_code == 422


def test_an_unknown_collection_name_is_refused(client):
    payload = dict(EVENT, provided_collections=["bids", "invented_collection"])
    response = client.post("/api/v1/awards", data={"event": json.dumps(payload)})
    assert response.status_code == 422


def test_an_unknown_side_is_refused(client):
    response = client.post(
        "/api/v1/awards", data={"event": json.dumps(EVENT), "side": "AUDITOR"}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Policy lifecycle
# ---------------------------------------------------------------------------

def test_a_policy_cannot_be_activated_while_rules_are_unreviewed(client):
    response = client.post(
        "/api/v1/policies", json={"org_label": "Acme", "rules": DEFAULT_RULES}
    )
    policy_id = response.json()["policy_id"]
    activate = client.post(f"/api/v1/policies/{policy_id}/activate")
    assert activate.status_code == 409
    assert "R1" in activate.json()["detail"]


def test_an_active_policy_version_is_immutable(client):
    """Past reviews have to stay re-derivable against the rules that produced them."""
    policy_id = make_policy(client, DEFAULT_RULES)
    response = client.patch(
        f"/api/v1/policies/{policy_id}/rules/R1", json={"action": "EDIT", "params": {}}
    )
    assert response.status_code == 409
    assert "immutable" in response.json()["detail"]


def test_editing_a_rule_transfers_it_to_the_human(client):
    response = client.post(
        "/api/v1/policies", json={"org_label": "Acme", "rules": DEFAULT_RULES}
    )
    policy_id = response.json()["policy_id"]
    edited = client.patch(
        f"/api/v1/policies/{policy_id}/rules/R1",
        json={"action": "EDIT", "params": {"above_value": 100000, "min_quotes": 2}},
    )
    body = edited.json()
    assert body["status"] == "EDITED"
    assert body["origin"] == "HUMAN"
    assert body["grounding"] is None
    assert body["params"]["min_quotes"] == 2


def test_a_new_policy_reports_what_it_does_not_address(client):
    """Silence is reported, never defaulted."""
    response = client.post(
        "/api/v1/policies", json={"org_label": "Acme", "rules": DEFAULT_RULES}
    )
    not_addressed = response.json()["not_addressed"]
    assert "PAYMENT_TERMS_CAP" in not_addressed
    assert "MIN_QUOTES_BY_VALUE" not in not_addressed


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

def test_a_review_finds_policy_and_statutory_breaches(client):
    policy_id = make_policy(client, DEFAULT_RULES)
    response = client.post(
        "/api/v1/awards",
        data={"event": json.dumps(EVENT), "policy_id": policy_id, "side": "BUYER"},
    )
    assert response.status_code == 200
    body = response.json()
    found = {f["check_id"] for f in body["findings"]}
    assert "MSMED_TERM_EXCEEDS_STATUTORY_CAP" in found
    assert "APPROVAL_AUTHORITY" in found
    assert "MIN_QUOTES_BY_VALUE" in found
    assert body["overall_status"] == "BREACHES_FOUND"


def test_indicators_are_reported_separately_from_breaches(client):
    """Nothing downstream may count a statistical pattern as a breach."""
    response = client.post("/api/v1/awards", data={"event": json.dumps(EVENT)})
    body = response.json()
    assert {f["check_id"] for f in body["indicators"]} >= {"SHARED_IDENTIFIERS"}
    assert all(f["status"] == "INDICATOR" for f in body["indicators"])
    assert all(f["status"] == "BREACH" for f in body["findings"])


def test_gaps_are_reported_separately_and_say_what_would_fix_them(client):
    sparse = dict(EVENT, provided_collections=["bids"])
    sparse.pop("company_profile")
    response = client.post("/api/v1/awards", data={"event": json.dumps(sparse)})
    body = response.json()
    assert body["undetermined_checks"]
    assert all(g["what_would_resolve_it"] for g in body["undetermined_checks"])
    assert body["overall_status"] != "NO_BREACH_FOUND"


def test_the_supplier_side_sees_statute_but_not_the_buyers_controls(client):
    policy_id = make_policy(client, DEFAULT_RULES)
    response = client.post(
        "/api/v1/awards",
        data={"event": json.dumps(EVENT), "policy_id": policy_id, "side": "SUPPLIER"},
    )
    found = {f["check_id"] for f in response.json()["findings"]}
    assert "MSMED_TERM_EXCEEDS_STATUTORY_CAP" in found
    assert "APPROVAL_AUTHORITY" not in found


def test_the_supplier_gets_a_different_action_from_the_buyer(client):
    """Same finding, same statute, opposite instruction."""
    def action_for(side):
        response = client.post(
            "/api/v1/awards", data={"event": json.dumps(EVENT), "side": side}
        )
        return next(
            r["action"] for r in response.json()["remediations"]
            if r["check_id"] == "MSMED_TERM_EXCEEDS_STATUTORY_CAP"
        )

    assert action_for("BUYER") != action_for("SUPPLIER")


def test_checks_run_records_passes_so_silence_is_legible(client):
    """A review showing only breaches cannot be told from one that never ran."""
    response = client.post("/api/v1/awards", data={"event": json.dumps(EVENT)})
    statuses = {c["status"] for c in response.json()["checks_run"]}
    assert "PASS" in statuses or "NOT_APPLICABLE" in statuses
    assert len(response.json()["checks_run"]) > len(response.json()["findings"])


def test_a_review_can_be_fetched_and_deleted(client):
    created = client.post("/api/v1/awards", data={"event": json.dumps(EVENT)})
    review_id = created.json()["review_id"]

    fetched = client.get(f"/api/v1/awards/{review_id}")
    assert fetched.status_code == 200 and fetched.json()["review_id"] == review_id

    deleted = client.delete(f"/api/v1/awards/{review_id}")
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True

    assert (client.get(f"/api/v1/awards/{review_id}")).status_code == 404


def test_the_report_renders_as_a_pdf(client):
    created = client.post("/api/v1/awards", data={"event": json.dumps(EVENT)})
    review_id = created.json()["review_id"]
    response = client.get(f"/api/v1/awards/{review_id}/report.pdf")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 2000


def test_an_unknown_review_is_a_404(client):
    assert (client.get("/api/v1/awards/nope")).status_code == 404
    assert (client.get("/api/v1/awards/nope/report.pdf")).status_code == 404


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

def test_the_check_catalogue_is_published(client):
    """What the system can check is a public statement of its reach."""
    body = (client.get("/api/v1/procurement/meta/checks")).json()
    assert body["statutory_checks"] and body["policy_kinds"] and body["bid_integrity_signals"]
    assert all(c["citations"] for c in body["statutory_checks"])
    assert all(s["reported_as"] == "INDICATOR" for s in body["bid_integrity_signals"])


def test_supported_options_drive_the_ui(client):
    body = (client.get("/api/v1/procurement/meta/supported")).json()
    assert "BUYER" in body["sides"] and "SUPPLIER" in body["sides"]
    assert "bids" in body["known_collections"]
    assert body["max_file_bytes"] > 0


def test_the_rate_limit_actually_fires(client):
    """One review is a contract sub-review's worth of LLM calls against a shared key."""
    limit = procurement.REVIEW_RATE_LIMIT_PER_MINUTE
    codes = [
        client.post("/api/v1/awards", data={"event": json.dumps(EVENT)}).status_code
        for _ in range(limit + 1)
    ]
    assert codes[:limit] == [200] * limit
    assert codes[-1] == 429


def test_the_review_degrades_to_the_rule_based_summary_with_no_model(client):
    """With Groq and Qdrant both down the findings are unchanged.

    The deterministic spine is the product; the graph only writes it up. This is
    the assertion that keeps that true.
    """
    response = client.post("/api/v1/awards", data={"event": json.dumps(EVENT)})
    body = response.json()
    assert response.status_code == 200
    assert body["findings"], "the findings must not depend on the model"
    assert body["narrative"]["source"] == "rule"
    assert body["narrative"]["headline"]
    assert body["confidence_basis"]["caps_applied"]
