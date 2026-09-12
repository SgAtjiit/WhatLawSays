"""Bid-integrity signals, and the invariants that keep them from overclaiming.

The wording tests here are not style checks. `test_no_signal_can_report_a_breach`
and `test_every_indicator_carries_the_disclaimer` are what stop this module from
telling a buyer that named, identifiable companies colluded on the strength of a
statistic. They are asserted rather than trusted to review.
"""

from datetime import datetime
from decimal import Decimal as D

from src.core.bid_integrity import INTEGRITY_LANGUAGE, SPECS, analyse_bid_integrity
from src.core.procurement_evidence import VerificationContext, verify_findings
from src.core.procurement_rules import EvalContext
from src.schemas.contract import Severity
from src.schemas.procurement import (
    Award,
    Bid,
    CheckStatus,
    LineItem,
    MsmeStatus,
    PriorAward,
    ProcurementEvent,
    Vendor,
)

CTX = EvalContext()


def vendor(i, name, **kw):
    return Vendor(vendor_id=f"V-{i}", name=name, msme_status=MsmeStatus.NOT_MSME, **kw)


def line(code, price):
    return LineItem(code=code, description=code, quantity=D(1), unit_price=D(price), total=D(price))


def event(bids, **kw):
    kw.setdefault("provided_collections", {"bids"})
    kw.setdefault("category", "MRO")
    return ProcurementEvent(event_id="E-1", bids=bids, **kw)


def ids(findings):
    return {f.check_id for f in findings}


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def test_near_identical_totals_are_flagged():
    ev = event([
        Bid(vendor=vendor(1, "Alpha"), total=D("1000000")),
        Bid(vendor=vendor(2, "Beta"), total=D("1001500")),
        Bid(vendor=vendor(3, "Gamma"), total=D("1002000")),
    ])
    assert "NEAR_IDENTICAL_TOTALS" in ids(analyse_bid_integrity(ev, CTX))


def test_an_ordinary_spread_is_not_flagged():
    """The test that keeps precision honest."""
    ev = event([
        Bid(vendor=vendor(1, "Alpha"), total=D("1000000")),
        Bid(vendor=vendor(2, "Beta"), total=D("1180000")),
        Bid(vendor=vendor(3, "Gamma"), total=D("1425000")),
    ])
    assert ids(analyse_bid_integrity(ev, CTX)) == set()


def test_a_shared_pan_root_across_different_gstins_is_found():
    """Two GSTINs embedding one PAN are two registrations of one legal person."""
    ev = event([
        Bid(vendor=vendor(1, "Alpha", gstin="27AAACA1234A1Z5"), total=D("1000000")),
        Bid(vendor=vendor(2, "Beta", gstin="29AAACA1234A1Z9"), total=D("1400000")),
    ])
    found = [f for f in analyse_bid_integrity(ev, CTX) if f.check_id == "SHARED_IDENTIFIERS"]
    assert found and "PAN" in found[0].plain_summary


def test_a_public_email_domain_is_not_a_shared_identifier():
    ev = event([
        Bid(vendor=vendor(1, "Alpha", email="a@gmail.com"), total=D("1000000")),
        Bid(vendor=vendor(2, "Beta", email="b@gmail.com"), total=D("1400000")),
    ])
    assert "SHARED_IDENTIFIERS" not in ids(analyse_bid_integrity(ev, CTX))


def test_a_private_shared_email_domain_is_a_shared_identifier():
    ev = event([
        Bid(vendor=vendor(1, "Alpha", email="sales@vitrex-industries.in"), total=D("1000000")),
        Bid(vendor=vendor(2, "Beta", email="tender@vitrex-industries.in"), total=D("1400000")),
    ])
    assert "SHARED_IDENTIFIERS" in ids(analyse_bid_integrity(ev, CTX))


def test_identical_unit_prices_are_flagged():
    a = [line("X1", 100), line("X2", 200), line("X3", 300), line("X4", 400)]
    b = [line("X1", 100), line("X2", 200), line("X3", 300), line("X4", 450)]
    ev = event([
        Bid(vendor=vendor(1, "Alpha"), total=D("1000000"), line_items=a),
        Bid(vendor=vendor(2, "Beta"), total=D("1400000"), line_items=b),
    ])
    assert "IDENTICAL_UNIT_PRICES" in ids(analyse_bid_integrity(ev, CTX))


def test_a_rate_contract_explains_identical_prices_and_the_reason_is_reported():
    """The innocent explanation must be surfaced, not silently applied.

    Suppressing the pattern without saying why would leave a reader unable to
    tell a checked-and-explained event from an unchecked one.
    """
    items = [line("X1", 100), line("X2", 200), line("X3", 300)]
    ev = event(
        [
            Bid(vendor=vendor(1, "Alpha"), total=D("1000000"), line_items=items),
            Bid(vendor=vendor(2, "Beta"), total=D("1400000"), line_items=list(items)),
        ],
        rate_contract_refs={"X1": "RC-1", "X2": "RC-1", "X3": "RC-1"},
    )
    found = [f for f in analyse_bid_integrity(ev, CTX) if f.check_id == "IDENTICAL_UNIT_PRICES"]
    assert found and found[0].status is CheckStatus.PASS
    assert "rate contract" in found[0].plain_summary


def test_a_high_bid_alone_is_never_cover_bidding():
    """Somebody has to be most expensive in every competitive event ever run."""
    ev = event([
        Bid(vendor=vendor(1, "Alpha"), total=D("1000000")),
        Bid(vendor=vendor(2, "Beta"), total=D("1900000")),
    ])
    assert "COVER_BIDDING" not in ids(analyse_bid_integrity(ev, CTX))


def test_a_high_bid_from_the_winners_ip_is_cover_bidding():
    ev = event([
        Bid(vendor=vendor(1, "Alpha"), total=D("1000000"), submitted_from_ip="10.2.3.4"),
        Bid(vendor=vendor(2, "Beta"), total=D("1900000"), submitted_from_ip="10.2.3.4"),
    ])
    found = [f for f in analyse_bid_integrity(ev, CTX) if f.check_id == "COVER_BIDDING"]
    assert found and found[0].corroborating_signals


def test_rotating_winners_need_history():
    bids = [Bid(vendor=vendor(1, "Alpha"), total=D("1000000"))]
    ev = event(bids, provided_collections={"bids"})
    assert "ROTATING_WINNERS" not in ids(analyse_bid_integrity(ev, CTX))


def test_strict_rotation_across_a_category_is_flagged():
    bids = [Bid(vendor=vendor(1, "Alpha"), total=D("1000000"))]
    ev = event(
        bids,
        provided_collections={"bids", "prior_awards"},
        award=Award(vendor_id="V-1", value=D("1000000"), decided_at=datetime(2026, 5, 1)),
        prior_awards=[
            PriorAward(vendor_id="V-2", category="MRO", value=D("1"), decided_at=datetime(2026, 1, 1)),
            PriorAward(vendor_id="V-3", category="MRO", value=D("1"), decided_at=datetime(2026, 2, 1)),
            PriorAward(vendor_id="V-1", category="MRO", value=D("1"), decided_at=datetime(2026, 3, 1)),
            PriorAward(vendor_id="V-2", category="MRO", value=D("1"), decided_at=datetime(2026, 4, 1)),
        ],
    )
    assert "ROTATING_WINNERS" in ids(analyse_bid_integrity(ev, CTX))


def test_a_repeat_winner_breaks_rotation():
    bids = [Bid(vendor=vendor(1, "Alpha"), total=D("1000000"))]
    ev = event(
        bids,
        provided_collections={"bids", "prior_awards"},
        prior_awards=[
            PriorAward(vendor_id="V-2", category="MRO", value=D("1"), decided_at=datetime(2026, 1, 1)),
            PriorAward(vendor_id="V-2", category="MRO", value=D("1"), decided_at=datetime(2026, 2, 1)),
            PriorAward(vendor_id="V-3", category="MRO", value=D("1"), decided_at=datetime(2026, 3, 1)),
            PriorAward(vendor_id="V-1", category="MRO", value=D("1"), decided_at=datetime(2026, 4, 1)),
        ],
    )
    assert "ROTATING_WINNERS" not in ids(analyse_bid_integrity(ev, CTX))


def test_a_competitive_looking_event_with_one_responsive_bid_is_flagged():
    ev = event([
        Bid(vendor=vendor(1, "Alpha"), total=D("1000000"), is_responsive=True),
        Bid(vendor=vendor(2, "Beta"), total=D("900000"), is_responsive=False),
        Bid(vendor=vendor(3, "Gamma"), total=D("950000"), is_responsive=False),
    ])
    assert "SINGLE_RESPONSIVE_BID" in ids(analyse_bid_integrity(ev, CTX))


# ---------------------------------------------------------------------------
# The invariants that stop this module overclaiming
# ---------------------------------------------------------------------------

def _every_signal_event():
    a = [line("X1", 100), line("X2", 200), line("X3", 300)]
    return event(
        [
            Bid(vendor=vendor(1, "Alpha", gstin="27AAACA1234A1Z5", pan="AAACA1234A"),
                total=D("1000000"), line_items=a, submitted_from_ip="10.0.0.1", is_responsive=True),
            Bid(vendor=vendor(2, "Beta", gstin="29AAACA1234A1Z9"),
                total=D("1001000"), line_items=list(a), is_responsive=False),
            Bid(vendor=vendor(3, "Gamma"), total=D("1500000"),
                submitted_from_ip="10.0.0.1", is_responsive=False),
        ],
        provided_collections={"bids", "prior_awards"},
        award=Award(vendor_id="V-1", value=D("1000000"), decided_at=datetime(2026, 5, 1)),
        prior_awards=[
            PriorAward(vendor_id="V-2", category="MRO", value=D("1"), decided_at=datetime(2026, 1, 1)),
            PriorAward(vendor_id="V-3", category="MRO", value=D("1"), decided_at=datetime(2026, 2, 1)),
            PriorAward(vendor_id="V-1", category="MRO", value=D("1"), decided_at=datetime(2026, 3, 1)),
            PriorAward(vendor_id="V-2", category="MRO", value=D("1"), decided_at=datetime(2026, 4, 1)),
        ],
    )


def test_no_signal_can_report_a_breach():
    """A bid tab cannot establish the agreement s.3(3) attaches to."""
    for f in analyse_bid_integrity(_every_signal_event(), CTX):
        assert f.status in {CheckStatus.INDICATOR, CheckStatus.PASS}, f.check_id


def test_no_signal_can_be_critical():
    for f in analyse_bid_integrity(_every_signal_event(), CTX):
        assert f.severity is not Severity.CRITICAL, f.check_id


def test_every_indicator_carries_the_disclaimer_and_the_citation():
    for f in analyse_bid_integrity(_every_signal_event(), CTX):
        if f.status is not CheckStatus.INDICATOR:
            continue
        assert INTEGRITY_LANGUAGE in f.why_it_matters, f.check_id
        assert any("Competition Act" in c.act for c in f.citations), f.check_id
        assert f.title.startswith("Indicator:"), f.title


def test_the_citation_note_says_the_presumption_needs_an_agreement():
    for f in analyse_bid_integrity(_every_signal_event(), CTX):
        for citation in f.citations:
            if "Competition Act" in citation.act:
                assert "not to a statistical pattern" in citation.note


def test_corroboration_never_raises_severity():
    """Three weak signals are not one strong finding of fact."""
    findings = analyse_bid_integrity(_every_signal_event(), CTX)
    for f in findings:
        assert f.severity == SPECS[f.check_id].severity, f.check_id


def test_every_indicator_verifies_against_its_own_event():
    ev = _every_signal_event()
    problems = verify_findings(analyse_bid_integrity(ev, CTX), VerificationContext(event=ev))
    assert problems == {}, problems


def test_nothing_is_produced_when_bids_were_not_supplied():
    ev = event([Bid(vendor=vendor(1, "Alpha"), total=D("1"))], provided_collections=set())
    assert analyse_bid_integrity(ev, CTX) == []


def test_three_bids_are_never_enough_for_a_constant_spread_signal():
    """Two gaps always look consistent.

    The labelled clean event tripped this rule on an ordinary 790k/845k/902k
    spread before `MIN_BIDS_FOR_CONSTANT_SPREAD` existed. A signal that fires on
    what a competitive market routinely produces is not measuring collusion.
    """
    ev = event([
        Bid(vendor=vendor(1, "Alpha"), total=D("790000")),
        Bid(vendor=vendor(2, "Beta"), total=D("845000")),
        Bid(vendor=vendor(3, "Gamma"), total=D("902000")),
    ])
    assert "CONSTANT_SPREAD" not in ids(analyse_bid_integrity(ev, CTX))


def test_four_evenly_stepped_bids_do_raise_it():
    ev = event([
        Bid(vendor=vendor(1, "Alpha"), total=D("1000000")),
        Bid(vendor=vendor(2, "Beta"), total=D("1050000")),
        Bid(vendor=vendor(3, "Gamma"), total=D("1102500")),
        Bid(vendor=vendor(4, "Delta"), total=D("1157625")),
    ])
    assert "CONSTANT_SPREAD" in ids(analyse_bid_integrity(ev, CTX))
