"""Patterns in a bid tab that warrant enquiry.

This module is the one place in the codebase that could do real damage by being
slightly too confident, so the constraint is structural rather than editorial.

Section 3(3)(d) of the Competition Act presumes an appreciable adverse effect on
competition once bid rigging is established -- but what s.3(3) attaches to is an
*agreement or practice* between bidders. A bid tab cannot establish an agreement.
It can show a pattern consistent with one, and patterns of this kind have
ordinary explanations: a common published price list, a rate contract, an
identical BOQ template circulated with the enquiry, a single distributor
upstream of several "competing" resellers.

So every finding here is `CheckStatus.INDICATOR`, never `BREACH`. Severity is
capped below CRITICAL. Every title is prefixed "Indicator:". Corroboration is
listed on one finding rather than emitted as several, and it never raises
severity -- three weak statistical signals are not one strong finding of fact.
`INTEGRITY_LANGUAGE` is appended to every explanation. `tests/` asserts all of
this, so a later change that lets a model write this prose, or that promotes an
indicator to a breach, fails the build.

No LLM touches any of it. A model asked to explain a bid pattern writes that the
vendors colluded, which is the single sentence this system must not emit about
named, identifiable companies.

Every figure is a re-executable `DerivedEvidence`: the verifier recomputes the
statistic from the bid totals rather than believing the number, so an indicator
that cannot be reproduced is discarded exactly like an invented quote.
"""

from decimal import Decimal
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.acts import ACT_COMPETITION
from src.core.procurement_evidence import COMPUTATIONS, quantise
from src.core.procurement_rules import CheckSpec, EvalContext, _src, finding, read
from src.schemas.contract import Citation, Severity
from src.schemas.procurement import (
    Bid,
    CheckFamily,
    CheckStatus,
    Comparator,
    DerivedEvidence,
    Evidence,
    PriorAward,
    ProcurementEvent,
    ProcurementFinding,
    ProcurementSide,
)


INTEGRITY_LANGUAGE = (
    "This is a pattern in the bid data, not a finding of collusion. Bid rigging under "
    "Competition Act s.3(3)(d) is an agreement between bidders, and nothing in a bid tab "
    "can establish an agreement. Patterns of this kind have ordinary explanations -- a "
    "common published price list, a rate contract, an identical BOQ template, a single "
    "distributor upstream. What is reported here is that the pattern is present and that "
    "it is worth asking about before the award is released."
)

_COMPETITION_CITATION = Citation(
    act=ACT_COMPETITION,
    section_number="Section 3",
    note=(
        "Section 3(3)(d) presumes an appreciable adverse effect on competition where bid "
        "rigging or collusive bidding is established. The presumption attaches to a proved "
        "agreement or practice between bidders, not to a statistical pattern in a bid tab."
    ),
)

# Thresholds live here, named, so they can be argued with and tuned rather than
# being buried inside an expression somewhere.
NEAR_IDENTICAL_CV = Decimal("0.005")
NEAR_IDENTICAL_PAIR_GAP = Decimal("0.002")
CONSTANT_SPREAD_STDEV = Decimal("0.002")
# Four bids, so there are at least three gaps to compare. With three bids there
# are only two, and two numbers always look consistent -- the labelled clean
# event tripped this rule on an ordinary 790k/845k/902k spread, which is what a
# competitive market routinely produces. A signal that fires on that is not
# measuring collusion, it is measuring having too little data to tell.
MIN_BIDS_FOR_CONSTANT_SPREAD = 4
CONSTANT_SPREAD_MIN_RATIO = Decimal("1.001")
CONSTANT_SPREAD_MAX_RATIO = Decimal("1.20")
IDENTICAL_PRICE_FRACTION = Decimal("0.60")
IDENTICAL_PRICE_MIN_LINES = 3
COVER_BID_MARGIN = Decimal("0.25")
MIN_BIDS_FOR_SPREAD = 3
ROTATION_MIN_EVENTS = 4

# Domains that say nothing about a relationship between two bidders.
PUBLIC_EMAIL_DOMAINS = frozenset(
    {"gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com",
     "rediffmail.com", "live.com", "icloud.com", "protonmail.com"}
)


def _spec(check_id: str, title: str, severity: Severity, summary: str, why: str) -> CheckSpec:
    # Severity is capped here rather than at each call site, so a future signal
    # cannot introduce a CRITICAL bid-integrity finding by forgetting to.
    capped = severity if severity != Severity.CRITICAL else Severity.HIGH
    return CheckSpec(
        check_id=check_id,
        title=f"Indicator: {title}",
        severity=capped,
        family=CheckFamily.BID_INTEGRITY,
        plain_summary=summary,
        why_it_matters=f"{why}\n\n{INTEGRITY_LANGUAGE}",
        citations=(_COMPETITION_CITATION,),
        harms=(ProcurementSide.BUYER,),
        requires=("bids",),
    )


SPECS: Dict[str, CheckSpec] = {
    "NEAR_IDENTICAL_TOTALS": _spec(
        "NEAR_IDENTICAL_TOTALS", "bid totals almost identical", Severity.HIGH,
        "Two or more bids are priced within a fraction of a percent of each other.",
        "Independently prepared bids for the same scope rarely land this close. Genuine "
        "competitors price from different cost bases, and the spread usually shows it.",
    ),
    "CONSTANT_SPREAD": _spec(
        "CONSTANT_SPREAD", "bids separated by an almost constant margin", Severity.HIGH,
        "The gaps between successive bids are unusually regular.",
        "A ladder of bids each a near-identical step above the last is the shape a single "
        "price list produces, whether or not anyone intended it.",
    ),
    "IDENTICAL_UNIT_PRICES": _spec(
        "IDENTICAL_UNIT_PRICES", "line items priced identically across bidders", Severity.HIGH,
        "Different bidders quoted the same unit prices on most compared lines.",
        "Identical unit pricing across nominally independent bidders points at a shared "
        "source for the numbers.",
    ),
    "COVER_BIDDING": _spec(
        "COVER_BIDDING", "a bid well above the winner on every occasion", Severity.MEDIUM,
        "One bidder sits consistently far above the winning price.",
        "A bid priced so as not to win still makes the process look competitive.",
    ),
    "SHARED_IDENTIFIERS": _spec(
        "SHARED_IDENTIFIERS", "bidders sharing an identifier", Severity.HIGH,
        "Two bidders share an identifier that independent businesses would not.",
        "A shared PAN root, bank account or contact address means the bidders may not be "
        "independent of one another, which is a question about the bid list itself.",
    ),
    "ROTATING_WINNERS": _spec(
        "ROTATING_WINNERS", "wins rotating between the same bidders", Severity.MEDIUM,
        "The same bidders win in turn across recent events in this category.",
        "Rotation is what a market-sharing arrangement looks like from the buyer's side. It "
        "is also what a genuinely specialised supplier base looks like.",
    ),
    "SINGLE_RESPONSIVE_BID": _spec(
        "SINGLE_RESPONSIVE_BID", "competitive on paper, single-bid in substance", Severity.MEDIUM,
        "Several bids were received but only one was responsive.",
        "The quote count was met and the competition was not. If the disqualifications were "
        "proper the event was effectively single-source and should be recorded as one.",
    ),
}


def _totals_evidence(event: ProcurementEvent, bids: Sequence[Bid]) -> List[Evidence]:
    out: List[Evidence] = []
    for bid in bids:
        got = read(
            event,
            f'bids[vendor.vendor_id="{bid.vendor.vendor_id}"].total',
            Comparator.PRESENT,
            note=f"{bid.vendor.name}",
        )
        if got:
            out.append(got)
    return out


def _derived(
    event: ProcurementEvent,
    computation: str,
    inputs: Sequence[Evidence],
    value: Decimal,
    note: str,
    params: Optional[Dict[str, str]] = None,
) -> DerivedEvidence:
    return DerivedEvidence(
        source=_src(event),
        computation=computation,
        inputs=list(inputs),
        params=params or {},
        value=str(value),
        note=note,
    )


def _priced(event: ProcurementEvent) -> List[Bid]:
    return [b for b in event.responsive_bids() if b.total is not None and b.total > 0]


def _near_identical(event, ctx, bids):
    if len(bids) < 2:
        return []
    totals = [b.total for b in bids]
    evidence = _totals_evidence(event, bids)
    if len(evidence) != len(bids):
        return []

    findings = []
    if len(bids) >= MIN_BIDS_FOR_SPREAD:
        cv = COMPUTATIONS["coefficient_of_variation"](totals, {})
        if cv <= NEAR_IDENTICAL_CV:
            findings.append(finding(
                SPECS["NEAR_IDENTICAL_TOTALS"], ctx, CheckStatus.INDICATOR,
                evidence=evidence + [_derived(
                    event, "coefficient_of_variation", evidence, cv,
                    f"spread of {cv} across {len(bids)} bids",
                )],
                summary=f"All {len(bids)} bids fall within a spread of {cv * 100:.3f}% of the mean.",
            ))
            return findings

    for a, b in combinations(bids, 2):
        gap = COMPUTATIONS["relative_gap"]([a.total, b.total], {})
        if gap <= NEAR_IDENTICAL_PAIR_GAP:
            pair = _totals_evidence(event, [a, b])
            findings.append(finding(
                SPECS["NEAR_IDENTICAL_TOTALS"], ctx, CheckStatus.INDICATOR,
                subject=f"{a.vendor.vendor_id},{b.vendor.vendor_id}",
                evidence=pair + [_derived(
                    event, "relative_gap", pair, gap,
                    f"{a.vendor.name} and {b.vendor.name} differ by {gap}",
                )],
                summary=(
                    f"{a.vendor.name} and {b.vendor.name} are priced {gap * 100:.3f}% apart "
                    f"({a.total:,} and {b.total:,})."
                ),
            ))
    return findings


def _constant_spread(event, ctx, bids):
    if len(bids) < MIN_BIDS_FOR_CONSTANT_SPREAD:
        return []
    totals = sorted(b.total for b in bids)
    ratios = [b / a for a, b in zip(totals, totals[1:])]
    if any(r < CONSTANT_SPREAD_MIN_RATIO or r > CONSTANT_SPREAD_MAX_RATIO for r in ratios):
        return []
    stdev = COMPUTATIONS["stdev_of_ratios"](totals, {})
    if stdev > CONSTANT_SPREAD_STDEV:
        return []
    evidence = _totals_evidence(event, bids)
    if len(evidence) != len(bids):
        return []
    return [finding(
        SPECS["CONSTANT_SPREAD"], ctx, CheckStatus.INDICATOR,
        evidence=evidence + [_derived(
            event, "stdev_of_ratios", evidence, stdev,
            f"successive bid ratios vary by only {stdev}",
        )],
        summary=(
            f"The {len(bids)} bids step up by an almost constant ratio "
            f"(variation of {stdev} between successive gaps)."
        ),
    )]


def _identical_unit_prices(event, ctx, bids):
    findings = []
    for a, b in combinations(bids, 2):
        a_lines = {i.code: i.unit_price for i in a.line_items if i.code and i.unit_price is not None}
        b_lines = {i.code: i.unit_price for i in b.line_items if i.code and i.unit_price is not None}
        common = sorted(set(a_lines) & set(b_lines))
        if len(common) < IDENTICAL_PRICE_MIN_LINES:
            continue

        # A rate contract is the ordinary explanation, and suppressing it silently
        # would hide the reason the pattern is innocent. It is reported as a PASS
        # carrying the contract reference instead.
        governed = [c for c in common if c in event.rate_contract_refs]
        comparable = [c for c in common if c not in event.rate_contract_refs]
        matched = [c for c in comparable if a_lines[c] == b_lines[c]]

        if governed and not comparable:
            findings.append(finding(
                SPECS["IDENTICAL_UNIT_PRICES"], ctx, CheckStatus.PASS,
                subject=f"{a.vendor.vendor_id},{b.vendor.vendor_id}",
                evidence=[e for e in [read(event, "rate_contract_refs", Comparator.PRESENT)] if e],
                summary=(
                    f"{a.vendor.name} and {b.vendor.name} price {len(governed)} lines alike, "
                    f"and every one is governed by a rate contract."
                ),
                why="Identical pricing under a published rate is what a rate contract is for. "
                    "Reported rather than dropped, so the reason the pattern is unremarkable is "
                    "on the record.",
            ))
            continue

        if not comparable:
            continue
        fraction = COMPUTATIONS["shared_fraction"](
            [], {"matched": str(len(matched)), "compared": str(len(comparable))}
        )
        if fraction < IDENTICAL_PRICE_FRACTION:
            continue

        pair = _totals_evidence(event, [a, b])
        findings.append(finding(
            SPECS["IDENTICAL_UNIT_PRICES"], ctx, CheckStatus.INDICATOR,
            subject=f"{a.vendor.vendor_id},{b.vendor.vendor_id}",
            evidence=pair + [_derived(
                event, "shared_fraction", [], fraction,
                f"{len(matched)} of {len(comparable)} freely-priced lines match exactly",
                params={"matched": str(len(matched)), "compared": str(len(comparable))},
            )],
            summary=(
                f"{a.vendor.name} and {b.vendor.name} quote identical unit prices on "
                f"{len(matched)} of {len(comparable)} lines not covered by a rate contract."
            ),
            corroborating=(
                [f"{len(governed)} further lines match under a rate contract and were excluded"]
                if governed else []
            ),
        ))
    return findings


def _identifier_pairs(a, b) -> List[Tuple[str, str, str]]:
    """Identifiers two independent businesses would not share."""
    found = []
    va, vb = a.vendor, b.vendor
    if va.pan and vb.pan and va.pan.upper() == vb.pan.upper():
        found.append(("pan", va.pan.upper(), "the same PAN"))
    # A GSTIN embeds the holder's PAN at positions 3-12. Two different GSTINs
    # sharing that root are two registrations of one legal person.
    if va.gstin and vb.gstin and len(va.gstin) >= 12 and len(vb.gstin) >= 12:
        if va.gstin[2:12].upper() == vb.gstin[2:12].upper() and va.gstin.upper() != vb.gstin.upper():
            found.append(("gstin", va.gstin[2:12].upper(), "the same PAN inside different GSTINs"))
    if va.bank_account and vb.bank_account and va.bank_account == vb.bank_account:
        found.append(("bank_account", va.bank_account, "the same bank account"))
    if va.phone and vb.phone and va.phone.strip() == vb.phone.strip():
        found.append(("phone", va.phone.strip(), "the same telephone number"))
    for label, x, y in [("email", va.email, vb.email)]:
        if x and y and "@" in x and "@" in y:
            da, db = x.rsplit("@", 1)[1].lower(), y.rsplit("@", 1)[1].lower()
            if da == db and da not in PUBLIC_EMAIL_DOMAINS:
                found.append((label, da, "the same private email domain"))
    if va.address and vb.address:
        na = " ".join(va.address.lower().split())
        nb = " ".join(vb.address.lower().split())
        if na == nb:
            found.append(("address", na, "the same address"))
    return found


def _shared_identifiers(event, ctx, bids):
    findings = []
    for a, b in combinations(bids, 2):
        shared = _identifier_pairs(a, b)
        if not shared:
            continue
        field, value, description = shared[0]
        path_a = f'bids[vendor.vendor_id="{a.vendor.vendor_id}"].vendor.{field}'
        path_b = f'bids[vendor.vendor_id="{b.vendor.vendor_id}"].vendor.{field}'
        evidence = [
            e for e in [
                read(event, path_a, Comparator.PRESENT, note=f"{a.vendor.name}"),
                read(event, path_b, Comparator.PRESENT, note=f"{b.vendor.name}"),
            ] if e
        ]
        findings.append(finding(
            SPECS["SHARED_IDENTIFIERS"], ctx, CheckStatus.INDICATOR,
            subject=f"{a.vendor.vendor_id},{b.vendor.vendor_id}",
            evidence=evidence,
            summary=f"{a.vendor.name} and {b.vendor.name} share {description}.",
            corroborating=[f"also {d}" for _, _, d in shared[1:]],
        ))
    return findings


def _cover_bidding(event, ctx, bids):
    if len(bids) < 2:
        return []
    winner = min(bids, key=lambda b: b.total)
    findings = []
    for bid in bids:
        if bid is winner:
            continue
        margin = quantise((bid.total - winner.total) / winner.total)
        if margin < COVER_BID_MARGIN:
            continue
        corroborating = []
        if bid.is_responsive is False:
            corroborating.append("the bid was also recorded as non-responsive")
        if bid.submitted_from_ip and winner.submitted_from_ip and \
                bid.submitted_from_ip == winner.submitted_from_ip:
            corroborating.append("both bids were submitted from the same IP address")
        if not corroborating:
            # A high price on its own is not a signal. Somebody has to be most
            # expensive in every competitive event ever run.
            continue
        pair = _totals_evidence(event, [bid, winner])
        findings.append(finding(
            SPECS["COVER_BIDDING"], ctx, CheckStatus.INDICATOR,
            subject=bid.vendor.vendor_id,
            evidence=pair + [_derived(
                event, "relative_gap", pair, margin,
                f"{margin * 100:.1f}% above the lowest bid",
            )],
            summary=f"{bid.vendor.name} bid {margin * 100:.1f}% above the lowest bid.",
            corroborating=corroborating,
        ))
    return findings


def _rotating_winners(event, ctx, bids):
    if not event.supplied("prior_awards"):
        return []
    history = [
        p for p in event.prior_awards
        if (p.category or event.category) == event.category and p.decided_at
    ]
    if event.award and event.award.vendor_id and event.award.decided_at:
        history = history + [PriorAward(
            vendor_id=event.award.vendor_id, category=event.category,
            value=event.award.value, decided_at=event.award.decided_at,
        )]
    if len(history) < ROTATION_MIN_EVENTS:
        return []

    ordered = sorted(history, key=lambda p: p.decided_at)
    winners = [p.vendor_id for p in ordered]
    distinct = set(winners)
    if len(distinct) < 3:
        return []
    # Strict rotation: nobody wins twice in a row, and the wins are evenly spread.
    if any(x == y for x, y in zip(winners, winners[1:])):
        return []
    counts = {v: winners.count(v) for v in distinct}
    expected = len(winners) / len(distinct)
    if any(abs(c - expected) > 1 for c in counts.values()):
        return []

    return [finding(
        SPECS["ROTATING_WINNERS"], ctx, CheckStatus.INDICATOR,
        evidence=[e for e in [read(event, "prior_awards", Comparator.PRESENT,
                                   note=f"{len(winners)} awards in this category")] if e],
        summary=(
            f"Across {len(winners)} recent {event.category or 'category'} awards, "
            f"{len(distinct)} vendors won in turn with no vendor winning twice running."
        ),
    )]


def _single_responsive(event, ctx, bids):
    if len(event.bids) < 2:
        return []
    responsive = [b for b in event.bids if b.is_responsive is True]
    rejected = [b for b in event.bids if b.is_responsive is False]
    if len(responsive) != 1 or not rejected:
        return []
    return [finding(
        SPECS["SINGLE_RESPONSIVE_BID"], ctx, CheckStatus.INDICATOR,
        subject=responsive[0].vendor.vendor_id,
        evidence=[e for e in [read(event, "bids", Comparator.PRESENT,
                                   note=f"{len(event.bids)} bids, {len(rejected)} disqualified")] if e],
        summary=(
            f"{len(event.bids)} bids were received and {len(rejected)} were disqualified, "
            f"leaving {responsive[0].vendor.name} unopposed."
        ),
    )]


_SIGNALS = (
    _near_identical,
    _constant_spread,
    _identical_unit_prices,
    _shared_identifiers,
    _cover_bidding,
    _rotating_winners,
    _single_responsive,
)


def analyse_bid_integrity(event: ProcurementEvent, ctx: EvalContext) -> List[ProcurementFinding]:
    """Every bid-integrity signal present in this event.

    Returns `INDICATOR` findings (and the occasional `PASS` where a rate contract
    explains a pattern away). Never a `BREACH`: see the module docstring.
    """
    if not event.supplied("bids"):
        return []
    bids = _priced(event)
    out = []
    for signal in _SIGNALS:
        try:
            out.extend(signal(event, ctx, bids))
        except Exception:
            # A signal that cannot be computed produces nothing. It must never
            # produce a finding out of a partially-computed statistic, and it must
            # not take the other signals down with it.
            continue
    return out


__all__ = ["INTEGRITY_LANGUAGE", "SPECS", "analyse_bid_integrity"]
