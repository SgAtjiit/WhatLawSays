"""The procurement confidence estimator, and the invariants that keep it honest.

The load-bearing tests are the ordering ones. An estimator that can report a
degraded review as confidently as a healthy one is not measuring anything, and
the failure is silent -- the number still looks like a number.
"""

from datetime import datetime
from decimal import Decimal as D

import pytest

from src.core.procurement_confidence import (
    DEGRADED_LLM_CAP,
    NO_MSME_STATUS_CAP,
    UNDETERMINED_HEAVY_CAP,
    UNRATIFIED_POLICY_CAP,
    UNVERIFIED_EVIDENCE_CAP,
    data_completeness,
    estimate_procurement_confidence,
    policy_authority,
)
from src.core.procurement_rules import evaluate_procurement
from src.schemas.procurement import (
    Approval,
    Award,
    Bid,
    CompanyProfile,
    MsmeStatus,
    PolicyCheckKind,
    PolicyRule,
    PolicyRuleSet,
    PolicySetStatus,
    ProcurementEvent,
    PurchaseOrder,
    RuleOrigin,
    RuleStatus,
    Vendor,
)

FULL = {"bids", "approvals", "purchase_order", "vendor_msme_status", "company_profile"}


def build(msme=MsmeStatus.SMALL, days=60, collections=None, ratified=True):
    v = Vendor(vendor_id="V-1", name="Alpha", msme_status=msme, on_approved_list=True,
               is_related_party=False, processes_personal_data=False)
    event = ProcurementEvent(
        event_id="E-1", category="MRO",
        bids=[Bid(vendor=v, total=D("620000")),
              Bid(vendor=Vendor(vendor_id="V-2", name="Beta"), total=D("700000"))],
        award=Award(vendor_id="V-1", value=D("620000"), decided_at=datetime(2026, 3, 1)),
        approvals=[Approval(approver_role="CFO", approved_at=datetime(2026, 2, 28), stage="AWARD")],
        purchase_order=PurchaseOrder(po_number="PO-1", vendor_id="V-1", value=D("620000"),
                                     payment_terms_days=days, has_written_agreement=True,
                                     issued_at=datetime(2026, 3, 2)),
        company_profile=CompanyProfile(entity_name="Acme", has_audit_committee=False),
        provided_collections=FULL if collections is None else collections,
    )
    rule_set = PolicyRuleSet(
        policy_id="P",
        status=PolicySetStatus.ACTIVE if ratified else PolicySetStatus.DRAFT,
        rules=[PolicyRule(
            rule_id="R1", kind=PolicyCheckKind.PAYMENT_TERMS_CAP, params={"max_days": 45},
            status=RuleStatus.RATIFIED if ratified else RuleStatus.DRAFT,
            origin=RuleOrigin.HUMAN,
        )],
    )
    return event, rule_set


def score(event, rule_set, *, include_drafts=False, **kw):
    evaluation = evaluate_procurement(event, rule_set, include_draft_rules=include_drafts)
    kw.setdefault("side", "BUYER")
    kw.setdefault("category", event.category)
    kw.setdefault("msme_status", event.awarded_vendor.msme_status)
    kw.setdefault("ratified_rule_count", len(rule_set.enforceable_rules()))
    kw.setdefault("total_rule_count", len(rule_set.rules))
    return estimate_procurement_confidence(outcomes=evaluation.outcomes, **kw)


def test_a_healthy_review_scores_well_but_never_certain():
    report = score(*build())
    assert 0.80 <= report.score <= 0.95
    assert report.caps_applied == []


@pytest.mark.parametrize(
    "label,kwargs,ceiling",
    [
        ("msme unknown", {"msme": MsmeStatus.UNKNOWN}, NO_MSME_STATUS_CAP),
        ("sparse payload", {"collections": {"bids"}}, UNDETERMINED_HEAVY_CAP),
    ],
)
def test_each_degradation_is_capped(label, kwargs, ceiling):
    assert score(*build(**kwargs)).score <= ceiling, label


def test_unratified_policy_carries_the_lowest_cap():
    event, rule_set = build(ratified=False)
    report = score(event, rule_set, include_drafts=True)
    assert report.score <= UNRATIFIED_POLICY_CAP
    assert any("unratified_policy" in c for c in report.caps_applied)


def test_unverified_evidence_is_capped():
    report = score(*build(), unverified_keys=["MSMED_TERM|V-1"])
    assert report.score <= UNVERIFIED_EVIDENCE_CAP


def test_a_degraded_llm_is_capped():
    assert score(*build(), llm_available=False).score <= DEGRADED_LLM_CAP


def test_no_degraded_condition_outscores_a_healthy_one():
    healthy = score(*build()).score
    degraded = [
        score(*build(msme=MsmeStatus.UNKNOWN)).score,
        score(*build(collections={"bids"})).score,
        score(*build(), llm_available=False).score,
        score(*build(), reranker_available=False).score,
        score(*build(), unverified_keys=["X|Y"]).score,
        score(*build(), po_document_supplied=True, po_review_confidence=0.70).score,
    ]
    assert all(d <= healthy for d in degraded), (healthy, degraded)


def test_a_weak_po_review_drags_the_whole_score_down():
    """The cap that crosses a pipeline boundary.

    A purchase order that segmented by paragraph fallback was read at 0.70, and a
    procurement review resting on it has inherited that whether or not it shows.
    """
    report = score(*build(), po_document_supplied=True, po_review_confidence=0.62)
    assert report.score <= 0.62
    assert any("po_subreview" in c for c in report.caps_applied)


def test_completeness_is_not_a_pass_rate():
    """A review where everything passed because nothing was supplied must score badly."""
    sparse = evaluate_procurement(build(collections=set())[0])
    full = evaluate_procurement(build()[0])
    assert data_completeness(sparse.outcomes) < data_completeness(full.outcomes)


def test_policy_authority_is_dropped_rather_than_assumed_for_statute_only_reviews():
    """Scoring 1.0 would reward never looking at the customer's policy."""
    assert policy_authority(0, 0, 0) is None
    report = score(*build(), ratified_rule_count=0, total_rule_count=0)
    assert "policy_authority" not in report.components
    assert report.detail["statute_only"] is True


def test_the_basis_always_explains_itself():
    report = score(*build(msme=MsmeStatus.UNKNOWN))
    payload = report.to_payload()
    assert payload["components"] and payload["caps_applied"] and payload["notes"]
    assert any("not supplied" in n or "gap" in n for n in payload["notes"])


def test_the_score_is_always_bounded():
    for event, rule_set in [build(), build(collections=set()), build(msme=MsmeStatus.UNKNOWN)]:
        assert 0.05 <= score(event, rule_set).score <= 0.95


def test_caps_match_the_contract_estimator_where_they_mean_the_same_thing():
    """Three estimators, one language."""
    from src.core import contract_confidence

    assert DEGRADED_LLM_CAP == contract_confidence.DEGRADED_LLM_CAP
    from src.core.procurement_confidence import DEGRADED_RERANKER_CAP

    assert DEGRADED_RERANKER_CAP == contract_confidence.DEGRADED_RERANKER_CAP
    assert UNVERIFIED_EVIDENCE_CAP == contract_confidence.UNGROUNDED_CAP
