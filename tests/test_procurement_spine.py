"""The deterministic procurement spine: evidence, checks, and the UNKNOWN gate.

The tests that matter most here are not the ones proving a breach is found. They
are the ones proving a breach is *not* found when the data cannot support it --
`test_missing_collection_*` and `test_unknown_msme_*`. A compliance engine that
reports green out of an incomplete payload is worse than no engine, because the
report gets filed.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.core.procurement_evidence import (
    COMPUTATIONS,
    Outcome,
    VerificationContext,
    quantise,
    resolve,
    verify_findings,
    verify_one,
)
from src.core.procurement_rules import (
    POLICY_TEMPLATES,
    STATUTORY_CHECKS,
    evaluate_procurement,
    overall_status,
    severity_for,
)
from src.schemas.contract import Severity
from src.schemas.procurement import (
    AbsenceEvidence,
    Approval,
    Award,
    Bid,
    CheckStatus,
    Comparator,
    CompanyProfile,
    DerivedEvidence,
    FieldEvidence,
    MsmeStatus,
    OverallStatus,
    PolicyCheckKind,
    PolicyRule,
    PolicyRuleSet,
    PolicySetStatus,
    PriorAward,
    ProcurementEvent,
    ProcurementSide,
    PurchaseOrder,
    RuleOrigin,
    RuleStatus,
    SourceRef,
    Vendor,
)

ALL = {
    "bids", "approvals", "purchase_order", "prior_awards", "vendor_msme_status",
    "company_profile", "rfq_line_item_codes", "budget",
}


def vendor(vid="V-1", name="Alpha Traders", **kw):
    return Vendor(vendor_id=vid, name=name, **kw)


def event(**kw):
    kw.setdefault("event_id", "E-1")
    kw.setdefault("category", "MRO")
    kw.setdefault("provided_collections", set(ALL))
    return ProcurementEvent(**kw)


def simple_event(msme=MsmeStatus.SMALL, days=30, written=True, **kw):
    v = vendor(msme_status=msme, on_approved_list=True)
    return event(
        bids=[Bid(vendor=v, total=Decimal("620000"))],
        award=Award(vendor_id="V-1", value=Decimal("620000"), decided_at=datetime(2026, 3, 1)),
        purchase_order=PurchaseOrder(
            po_number="PO-1", vendor_id="V-1", value=Decimal("620000"),
            payment_terms_days=days, has_written_agreement=written,
            issued_at=datetime(2026, 3, 2),
        ),
        approvals=[Approval(approver_role="CFO", approved_at=datetime(2026, 3, 1), stage="AWARD")],
        **kw,
    )


def rule(rid, kind, params=None, status=RuleStatus.RATIFIED):
    return PolicyRule(
        rule_id=rid, kind=kind, params=params or {}, status=status, origin=RuleOrigin.HUMAN
    )


def ruleset(*rules, status=PolicySetStatus.ACTIVE):
    return PolicyRuleSet(policy_id="P1", company_id="ACME", status=status, rules=list(rules))


def outcome_for(evaluation, check_id):
    return next(o for o in evaluation.outcomes if o.check_id == check_id)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def test_path_resolves_through_a_keyed_selector():
    ev = simple_event()
    assert resolve(ev, 'bids[vendor.vendor_id="V-1"].vendor.name').value == "Alpha Traders"
    assert resolve(ev, "purchase_order.payment_terms_days").value == 30


def test_a_null_field_resolves_but_a_missing_one_does_not():
    """The distinction the absence checks rest on.

    A field that exists and is null has been asked about and not answered. A path
    that does not exist at all is a bug in the check. Collapsing them would let a
    typo'd path read as missing data and quietly become UNDETERMINED.
    """
    ev = simple_event()
    null_field = resolve(ev, 'bids[vendor.vendor_id="V-1"].payment_terms_days')
    assert null_field.outcome is Outcome.FOUND and null_field.value is None
    assert resolve(ev, "bids[0].nonexistent_field").outcome is Outcome.NOT_FOUND


def test_an_ambiguous_path_is_a_failure_not_a_first_match():
    """Two matching elements is the structured analogue of a quote appearing twice."""
    v = vendor()
    ev = event(bids=[Bid(vendor=v), Bid(vendor=v)])
    got = resolve(ev, 'bids[vendor.vendor_id="V-1"].total')
    assert got.outcome is Outcome.AMBIGUOUS
    assert "pick out one" in got.detail


def test_malformed_paths_are_rejected_rather_than_guessed():
    ev = simple_event()
    assert resolve(ev, "bids[nope").outcome is Outcome.BAD_PATH
    assert resolve(ev, "").outcome is Outcome.BAD_PATH
    assert resolve(ev, "bids[99].total").outcome is Outcome.NOT_FOUND


# ---------------------------------------------------------------------------
# Evidence verification
# ---------------------------------------------------------------------------

def test_evidence_that_misquotes_its_own_source_is_rejected():
    ev = simple_event(days=60)
    lying = FieldEvidence(
        source=SourceRef(kind="EVENT", id="E-1"),
        field_path="purchase_order.payment_terms_days",
        observed=15, comparator=Comparator.GT, required=45,
    )
    assert "but the evidence claims" in verify_one(lying, VerificationContext(event=ev))


def test_evidence_asserting_a_relation_that_does_not_hold_is_rejected():
    ev = simple_event(days=30)
    bad = FieldEvidence(
        source=SourceRef(kind="EVENT", id="E-1"),
        field_path="purchase_order.payment_terms_days",
        observed=30, comparator=Comparator.GT, required=45,
    )
    assert "does not satisfy" in verify_one(bad, VerificationContext(event=ev))


def test_a_derived_value_is_recomputed_not_believed():
    ev = simple_event()
    bids = FieldEvidence(
        source=SourceRef(kind="EVENT"), field_path="bids",
        observed=ev.bids, comparator=Comparator.PRESENT,
    )
    honest = DerivedEvidence(
        source=SourceRef(kind="EVENT"), computation="responsive_bid_count",
        inputs=[bids], value=str(quantise(Decimal(1))),
    )
    assert verify_one(honest, VerificationContext(event=ev)) is None
    tampered = honest.model_copy(update={"value": str(quantise(Decimal(9)))})
    assert "recomputes to" in verify_one(tampered, VerificationContext(event=ev))


def test_an_unregistered_computation_cannot_be_verified():
    ev = simple_event()
    made_up = DerivedEvidence(
        source=SourceRef(kind="EVENT"), computation="vibes", inputs=[], value="1.000000"
    )
    assert "unknown computation" in verify_one(made_up, VerificationContext(event=ev))


def test_absence_over_an_undeclared_scope_cannot_support_a_breach():
    """The structural half of UNKNOWN != FALSE.

    A breach resting on something being missing from a collection nobody said
    they supplied is a breach resting on ignorance.
    """
    from src.core.procurement_rules import CheckSpec, EvalContext, finding
    from src.schemas.procurement import CheckFamily

    ev = event(provided_collections=set())
    spec = CheckSpec(
        check_id="X", title="X", severity=Severity.HIGH, family=CheckFamily.POLICY,
        plain_summary="s", why_it_matters="w",
    )
    bad = finding(
        spec, EvalContext(), CheckStatus.BREACH,
        evidence=[AbsenceEvidence(
            source=SourceRef(kind="EVENT"), field_path="approvals[0]",
            scope_path="approvals", scope_declared_complete=False,
        )],
    )
    problems = verify_findings([bad], VerificationContext(event=ev))
    assert any("that is UNDETERMINED, not a finding" in p for p in next(iter(problems.values())))


def test_a_breach_with_no_evidence_at_all_is_rejected():
    from src.core.procurement_rules import CheckSpec, EvalContext, finding
    from src.schemas.procurement import CheckFamily

    spec = CheckSpec(
        check_id="X", title="X", severity=Severity.HIGH, family=CheckFamily.POLICY,
        plain_summary="s", why_it_matters="w",
    )
    empty = finding(spec, EvalContext(), CheckStatus.BREACH)
    problems = verify_findings([empty], VerificationContext(event=event()))
    assert any("with no evidence" in p for p in next(iter(problems.values())))


# ---------------------------------------------------------------------------
# MSMED s.15 -- every branch, because the two periods are easy to conflate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "msme,days,written,expected",
    [
        (MsmeStatus.SMALL, 60, True, CheckStatus.BREACH),
        (MsmeStatus.MICRO, 46, True, CheckStatus.BREACH),
        (MsmeStatus.SMALL, 45, True, CheckStatus.PASS),
        (MsmeStatus.SMALL, 30, True, CheckStatus.PASS),
        # No written agreement: the appointed day is 15 days, not 45.
        (MsmeStatus.SMALL, 30, False, CheckStatus.BREACH),
        (MsmeStatus.SMALL, 15, False, CheckStatus.PASS),
        # Whether it is agreed in writing is itself a fact that can be missing.
        (MsmeStatus.SMALL, 30, None, CheckStatus.UNDETERMINED),
        # Chapter V protects micro and small only.
        (MsmeStatus.MEDIUM, 90, True, CheckStatus.NOT_APPLICABLE),
        (MsmeStatus.NOT_MSME, 90, True, CheckStatus.NOT_APPLICABLE),
        (MsmeStatus.UNKNOWN, 90, True, CheckStatus.UNDETERMINED),
    ],
)
def test_msmed_payment_period(msme, days, written, expected):
    ev = simple_event(msme=msme, days=days, written=written)
    got = outcome_for(evaluate_procurement(ev), "MSMED_TERM_EXCEEDS_STATUTORY_CAP")
    assert got.status is expected


def test_unknown_msme_status_never_reports_compliance():
    ev = simple_event(msme=MsmeStatus.UNKNOWN, days=90)
    got = outcome_for(evaluate_procurement(ev), "MSMED_TERM_EXCEEDS_STATUTORY_CAP")
    assert got.status is CheckStatus.UNDETERMINED
    assert got.status is not CheckStatus.PASS
    assert got.what_would_resolve_it and "Udyam" in got.what_would_resolve_it


def test_interest_quantum_is_never_asserted_from_a_hardcoded_rate():
    ev = simple_event(days=90)
    ev.purchase_order.goods_accepted_at = datetime(2026, 1, 1)
    got = outcome_for(evaluate_procurement(ev), "MSMED_INTEREST_QUANTUM")
    assert got.status is CheckStatus.UNDETERMINED
    assert "bank rate" in got.what_would_resolve_it


# ---------------------------------------------------------------------------
# The missing-collection gate
# ---------------------------------------------------------------------------

def test_missing_approvals_collection_is_a_gap_not_a_breach():
    """An approvals array that was never exported must not read as 'nobody approved'."""
    ev = simple_event(provided_collections={"bids", "purchase_order", "vendor_msme_status"})
    ev.approvals = []
    rs = ruleset(rule("R1", PolicyCheckKind.APPROVAL_AUTHORITY,
                      {"above_value": 500000, "required_role": "CFO"}))
    got = outcome_for(evaluate_procurement(ev, rs), "APPROVAL_AUTHORITY")
    assert got.status is CheckStatus.UNDETERMINED
    assert "approvals" in got.missing_fields


def test_declared_empty_approvals_is_a_breach():
    """Declared and empty is a real negative, and must be treated as one."""
    ev = simple_event()
    ev.approvals = []
    rs = ruleset(rule("R1", PolicyCheckKind.APPROVAL_AUTHORITY,
                      {"above_value": 500000, "required_role": "CFO"}))
    assert outcome_for(evaluate_procurement(ev, rs), "APPROVAL_AUTHORITY").status is CheckStatus.BREACH


def test_related_party_needs_a_company_profile():
    ev = simple_event(provided_collections={"bids", "purchase_order", "vendor_msme_status"})
    got = outcome_for(evaluate_procurement(ev), "RELATED_PARTY_AWARD_UNAPPROVED")
    assert got.status is CheckStatus.UNDETERMINED
    assert "register" in got.what_would_resolve_it


def test_related_party_award_without_approval_is_a_breach():
    ev = simple_event()
    ev.bids[0].vendor.is_related_party = True
    ev.company_profile = CompanyProfile(entity_name="Acme", related_parties=["V-1"],
                                        has_audit_committee=False)
    assert outcome_for(evaluate_procurement(ev), "RELATED_PARTY_AWARD_UNAPPROVED").status is CheckStatus.BREACH


def test_audit_committee_check_is_not_applicable_without_a_committee():
    ev = simple_event()
    ev.bids[0].vendor.is_related_party = True
    ev.company_profile = CompanyProfile(entity_name="Acme", related_parties=["V-1"],
                                        has_audit_committee=False)
    got = outcome_for(evaluate_procurement(ev), "RELATED_PARTY_AUDIT_COMMITTEE_APPROVAL")
    assert got.status is CheckStatus.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Policy checks
# ---------------------------------------------------------------------------

def test_split_awards_below_a_threshold_are_detected():
    v = vendor(msme_status=MsmeStatus.NOT_MSME, on_approved_list=True)
    ev = event(
        bids=[Bid(vendor=v, total=Decimal("480000"))],
        award=Award(vendor_id="V-1", value=Decimal("480000"), decided_at=datetime(2026, 3, 10)),
        prior_awards=[
            PriorAward(vendor_id="V-1", category="MRO", value=Decimal("460000"),
                       decided_at=datetime(2026, 3, 1)),
        ],
    )
    rs = ruleset(rule("R1", PolicyCheckKind.SPLIT_PO_AVOIDANCE,
                      {"window_days": 30, "threshold": 500000}))
    got = outcome_for(evaluate_procurement(ev, rs), "SPLIT_PO_AVOIDANCE")
    assert got.status is CheckStatus.BREACH
    assert "940,000" in got.plain_summary or "940000" in got.plain_summary


def test_an_award_already_above_the_threshold_is_not_structuring():
    ev = simple_event()
    ev.prior_awards = [PriorAward(vendor_id="V-1", category="MRO", value=Decimal("100000"),
                                  decided_at=datetime(2026, 2, 25))]
    rs = ruleset(rule("R1", PolicyCheckKind.SPLIT_PO_AVOIDANCE,
                      {"window_days": 30, "threshold": 500000}))
    assert outcome_for(evaluate_procurement(ev, rs), "SPLIT_PO_AVOIDANCE").status is CheckStatus.PASS


def test_a_clean_event_produces_no_breaches():
    """The fixture that keeps precision honest. An engine that flags everything is useless."""
    ev = simple_event(days=30, written=True)
    ev.company_profile = CompanyProfile(entity_name="Acme", has_audit_committee=False,
                                        related_parties=[])
    ev.bids[0].vendor.is_related_party = False
    ev.bids[0].vendor.processes_personal_data = False
    ev.bids.append(Bid(vendor=vendor("V-2", "Beta", on_approved_list=True), total=Decimal("700000")))
    ev.bids.append(Bid(vendor=vendor("V-3", "Gamma", on_approved_list=True), total=Decimal("715000")))
    rs = ruleset(
        rule("R1", PolicyCheckKind.MIN_QUOTES_BY_VALUE, {"above_value": 500000, "min_quotes": 3}),
        rule("R2", PolicyCheckKind.APPROVAL_AUTHORITY, {"above_value": 500000, "required_role": "CFO"}),
        rule("R3", PolicyCheckKind.PAYMENT_TERMS_CAP, {"max_days": 45}),
        rule("R4", PolicyCheckKind.LOWEST_RESPONSIVE_AWARD, {}),
        rule("R5", PolicyCheckKind.APPROVED_VENDOR_REQUIRED, {}),
    )
    evaluation = evaluate_procurement(ev, rs)
    breaches = evaluation.by_status(CheckStatus.BREACH)
    assert breaches == [], [b.check_id for b in breaches]


def test_out_of_scope_rules_do_not_fire():
    from src.schemas.procurement import RuleScope

    ev = simple_event()
    r = rule("R1", PolicyCheckKind.MIN_QUOTES_BY_VALUE, {"above_value": 0, "min_quotes": 9})
    r.scope = RuleScope(categories=["CAPEX"])
    assert outcome_for(evaluate_procurement(ev, ruleset(r)), "MIN_QUOTES_BY_VALUE").status is CheckStatus.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Ratification
# ---------------------------------------------------------------------------

def test_draft_rules_do_not_fire_by_default():
    ev = simple_event()
    r = PolicyRule(
        rule_id="R1", kind=PolicyCheckKind.MIN_QUOTES_BY_VALUE,
        params={"above_value": 0, "min_quotes": 5}, status=RuleStatus.DRAFT,
        origin=RuleOrigin.HUMAN,
    )
    evaluation = evaluate_procurement(ev, ruleset(r))
    assert not [o for o in evaluation.outcomes if o.check_id == "MIN_QUOTES_BY_VALUE"]


def test_draft_rules_are_provisional_when_explicitly_included():
    ev = simple_event()
    r = PolicyRule(
        rule_id="R1", kind=PolicyCheckKind.MIN_QUOTES_BY_VALUE,
        params={"above_value": 0, "min_quotes": 5}, status=RuleStatus.DRAFT,
        origin=RuleOrigin.HUMAN,
    )
    evaluation = evaluate_procurement(ev, ruleset(r), include_draft_rules=True)
    got = outcome_for(evaluation, "MIN_QUOTES_BY_VALUE")
    assert got.status is CheckStatus.BREACH
    assert got.provisional
    # Provisional findings are excluded from every count, and from the headline.
    assert "BREACH" not in evaluation.counts()
    assert overall_status(evaluation) is not OverallStatus.BREACHES_FOUND


def test_an_inactive_rule_set_enforces_nothing():
    ev = simple_event()
    rs = ruleset(rule("R1", PolicyCheckKind.MIN_QUOTES_BY_VALUE,
                      {"above_value": 0, "min_quotes": 5}),
                 status=PolicySetStatus.DRAFT)
    assert not [o for o in evaluate_procurement(ev, rs).outcomes if o.check_id == "MIN_QUOTES_BY_VALUE"]


def test_a_model_drafted_rule_must_quote_the_policy():
    with pytest.raises(ValueError, match="grounding quote"):
        PolicyRule(rule_id="R1", kind=PolicyCheckKind.PAYMENT_TERMS_CAP,
                   origin=RuleOrigin.MODEL_DRAFT)


# ---------------------------------------------------------------------------
# Sides
# ---------------------------------------------------------------------------

def test_supplier_side_gets_statute_but_not_the_buyers_internal_controls():
    ev = simple_event(days=60)
    rs = ruleset(rule("R1", PolicyCheckKind.MIN_QUOTES_BY_VALUE,
                      {"above_value": 0, "min_quotes": 9}))
    evaluation = evaluate_procurement(ev, rs, side=ProcurementSide.SUPPLIER)
    assert outcome_for(evaluation, "MIN_QUOTES_BY_VALUE").status is CheckStatus.NOT_APPLICABLE
    assert outcome_for(evaluation, "MSMED_TERM_EXCEEDS_STATUTORY_CAP").status is CheckStatus.BREACH


def test_the_weaker_side_carries_the_higher_severity():
    base = Severity.HIGH
    harms = (ProcurementSide.BUYER, ProcurementSide.SUPPLIER)
    assert severity_for(base, harms, ProcurementSide.SUPPLIER) is Severity.CRITICAL
    assert severity_for(base, harms, ProcurementSide.BUYER) is Severity.HIGH
    assert severity_for(base, harms, ProcurementSide.UNKNOWN) is Severity.HIGH


# ---------------------------------------------------------------------------
# Headline and registry integrity
# ---------------------------------------------------------------------------

def test_a_material_gap_prevents_a_clean_headline():
    ev = simple_event(msme=MsmeStatus.UNKNOWN)
    assert overall_status(evaluate_procurement(ev)) is OverallStatus.NO_BREACH_FOUND_WITH_GAPS


def test_overall_status_has_no_compliant_value():
    """The system is not in a position to certify compliance, so it cannot say so."""
    assert not any("COMPLIANT" in s.value for s in OverallStatus)


def test_every_policy_kind_has_a_template():
    missing = [k for k in PolicyCheckKind if k not in POLICY_TEMPLATES]
    assert missing == [], f"kinds with no predicate: {missing}"


def test_every_check_declares_citations_where_it_is_statutory():
    for spec, _ in STATUTORY_CHECKS:
        assert spec.citations, f"{spec.check_id} carries no citation"


def test_every_evaluation_verifies_against_its_own_event():
    """Whatever the checks produce must survive re-derivation from the payload."""
    for ev in [
        simple_event(days=60),
        simple_event(msme=MsmeStatus.UNKNOWN),
        simple_event(days=30, written=False),
        simple_event(provided_collections={"bids"}),
    ]:
        rs = ruleset(
            rule("R1", PolicyCheckKind.MIN_QUOTES_BY_VALUE, {"above_value": 0, "min_quotes": 3}),
            rule("R2", PolicyCheckKind.APPROVAL_AUTHORITY, {"above_value": 0, "required_role": "CFO"}),
            rule("R3", PolicyCheckKind.PAYMENT_TERMS_CAP, {"max_days": 45}),
            rule("R4", PolicyCheckKind.LOWEST_RESPONSIVE_AWARD, {}),
            rule("R5", PolicyCheckKind.SINGLE_SOURCE_JUSTIFICATION, {}),
            rule("R6", PolicyCheckKind.APPROVAL_BEFORE_COMMITMENT, {}),
        )
        evaluation = evaluate_procurement(ev, rs)
        problems = verify_findings(evaluation.outcomes, VerificationContext(event=ev))
        assert problems == {}, problems


def test_computations_are_all_registered_and_deterministic():
    for name, fn in COMPUTATIONS.items():
        assert callable(fn), name
    values = [Decimal("100"), Decimal("102")]
    first = COMPUTATIONS["relative_gap"](values, {})
    assert first == COMPUTATIONS["relative_gap"](values, {})
