"""Deterministic checks over a sourcing event, its policy and its purchase order.

The same commitment `red_flag_rules.py` makes, in a domain where it is harder to
keep: rules decide what exists, the model only explains it. Harder because a
contract red flag is a fixed pattern in text, while "three quotes above five
lakh" varies per customer -- so a naive reading of this feature would have a
model deciding whether an award complied. It does not. The split is:

* **`StatutoryCheck`** -- fixed, parameterless, hand-written, exactly like the 17
  entries in `RULES`. The law does not vary per customer.
* **`PolicyCheckTemplate`** -- a fixed predicate in code with typed parameter
  slots. The *shape* of every policy check is written here and regression-tested;
  a customer's policy supplies only the constants, and only after a human has
  ratified them. A model reading a procurement manual chooses a template and
  fills slots. It cannot express a predicate, and at evaluation time it is
  absent: rule set is data, predicate is code, the run is reproducible.

Three rules hold everywhere in this module.

**Evidence states a relation that is true.** Every `FieldEvidence` is built by
`read()`, which resolves the value out of the event itself, so `observed` cannot
disagree with the source. The comparator attached must be the one that actually
holds -- `verify_one` re-runs it, and a breach whose own evidence does not
support it is discarded.

**A check that cannot look says so.** Every predicate that needs a field it was
not given returns `UNDETERMINED` naming the missing path and what would resolve
it. It never returns `PASS`. The most dangerous version of this bug is silent: a
payload omitting its `approvals` array looks exactly like an award nobody
approved, which is why `requires` is declared per check and consulted before the
predicate runs at all.

**Nothing here decides that anyone broke the law.** A statutory check reports
that a term is outside what a section permits, citing the section. Whether that
is actionable, and against whom, is not a question a bid tab can answer.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.core.acts import ACT_COMPANIES, ACT_DPDP, ACT_MSMED
from src.core.procurement_evidence import quantise, resolve
from src.schemas.contract import SEVERITY_ORDER, Citation, Severity
from src.schemas.procurement import (
    MSME_PROTECTED,
    MSMED_AGREED_MAX_DAYS,
    MSMED_DEFAULT_DAYS,
    AbsenceEvidence,
    CheckFamily,
    DerivedEvidence,
    CheckStatus,
    Comparator,
    EMPTY_RULE_SET,
    Evidence,
    FieldEvidence,
    MsmeStatus,
    PolicyCheckKind,
    PolicyRule,
    PolicyRuleSet,
    ProcurementEvent,
    ProcurementFinding,
    ProcurementSide,
    SourceRef,
    WEAKER_SIDES,
)


# ---------------------------------------------------------------------------
# Context and helpers
# ---------------------------------------------------------------------------

@dataclass
class EvalContext:
    side: ProcurementSide = ProcurementSide.UNKNOWN
    rule_set: PolicyRuleSet = field(default_factory=lambda: EMPTY_RULE_SET.model_copy(deep=True))
    include_draft_rules: bool = False
    today: date = field(default_factory=date.today)


def _cite(act: str, section: str, note: str) -> Citation:
    return Citation(act=act, section_number=section, note=note)


def _shift(severity: Severity, steps: int) -> Severity:
    order = max(0, min(4, SEVERITY_ORDER[severity] + steps))
    return next(s for s, value in SEVERITY_ORDER.items() if value == order)


def severity_for(
    base: Severity, harms: Sequence[ProcurementSide], side: ProcurementSide
) -> Severity:
    """Severity of a finding for the side the review is being run for.

    The same reasoning as `red_flag_rules._severity_for`, with one difference: a
    procurement check that fired is material to whoever is reading, so nothing is
    demoted to INFO. A supplier reading that the buyer's payment term is void
    still needs to act on it; they simply act on it differently.
    """
    if side == ProcurementSide.UNKNOWN or not harms:
        return base
    if side in harms and side in WEAKER_SIDES:
        return _shift(base, 1)
    return base


def _display(value: Any) -> str:
    if isinstance(value, Decimal):
        return f"Rs {value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _src(event: ProcurementEvent) -> SourceRef:
    return SourceRef(kind="EVENT", id=event.event_id)


def read(
    event: ProcurementEvent,
    path: str,
    comparator: Comparator = Comparator.PRESENT,
    required: Any = None,
    *,
    note: str = "",
    requirement_source: str = "",
) -> Optional[FieldEvidence]:
    """Evidence for one field of the event, or None where it does not resolve.

    `observed` is taken from the event rather than passed in, so a check cannot
    misquote its own input. The comparator must be one that genuinely holds --
    the verifier re-runs it.
    """
    resolution = resolve(event, path)
    if not resolution.found or resolution.value is None:
        return None
    return FieldEvidence(
        source=_src(event),
        field_path=path,
        observed=resolution.value,
        observed_display=_display(resolution.value),
        comparator=comparator,
        required=required,
        requirement_source=requirement_source,
        note=note,
    )


def absent(event: ProcurementEvent, field_path: str, scope_path: str, note: str = "") -> AbsenceEvidence:
    scope = resolve(event, scope_path)
    size = len(scope.value) if scope.found and isinstance(scope.value, list) else 0
    return AbsenceEvidence(
        source=_src(event),
        field_path=field_path,
        scope_path=scope_path,
        scope_declared_complete=event.supplied(scope_path),
        scope_size=size,
        note=note,
    )


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """Compare timestamps without tripping over one side being naive.

    Event payloads mix the two constantly -- an ISO string with a Z alongside one
    without -- and a TypeError deep inside a check reads as the check passing.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Check definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CheckSpec:
    """What a check is, independent of whether it is statutory or policy."""

    check_id: str
    title: str
    severity: Severity
    family: CheckFamily
    plain_summary: str
    why_it_matters: str
    citations: Tuple[Citation, ...] = ()
    harms: Tuple[ProcurementSide, ...] = ()
    # Collections the check needs the caller to have actually supplied. Consulted
    # before the predicate runs, so a missing array can never read as an empty one.
    requires: Tuple[str, ...] = ()
    # Every path the check may read. The evidence contract: a path not declared
    # here should never appear in this check's findings.
    reads: Tuple[str, ...] = ()
    kind: Optional[PolicyCheckKind] = None


def finding(
    spec: CheckSpec,
    ctx: EvalContext,
    status: CheckStatus,
    *,
    subject: Optional[str] = None,
    evidence: Sequence[Evidence] = (),
    summary: Optional[str] = None,
    why: Optional[str] = None,
    resolution: Optional[str] = None,
    missing: Sequence[str] = (),
    corroborating: Sequence[str] = (),
    source: str = "STATUTE",
    rule_id: Optional[str] = None,
    provisional: bool = False,
    severity: Optional[Severity] = None,
) -> ProcurementFinding:
    return ProcurementFinding(
        check_id=spec.check_id,
        title=spec.title,
        severity=severity or severity_for(spec.severity, spec.harms, ctx.side),
        status=status,
        family=spec.family,
        subject_ref=subject,
        evidence=list(evidence),
        citations=list(spec.citations),
        harms=list(spec.harms),
        plain_summary=summary or spec.plain_summary,
        why_it_matters=why or spec.why_it_matters,
        what_would_resolve_it=resolution,
        missing_fields=list(missing),
        corroborating_signals=list(corroborating),
        detector="rule",
        source=source,
        policy_rule_id=rule_id,
        provisional=provisional,
    )


def undetermined(
    spec: CheckSpec,
    ctx: EvalContext,
    event: ProcurementEvent,
    missing: Sequence[str],
    resolution: str,
    *,
    subject: Optional[str] = None,
    scope: Optional[str] = None,
) -> ProcurementFinding:
    # Only claim absence where the field really is absent. A value that is present
    # but uninformative -- MsmeStatus.UNKNOWN is the live example -- is not the
    # same thing, and the verifier rightly rejects a finding that says it is.
    # Where the field does resolve, `missing_fields` carries what was needed
    # without the finding asserting something untrue about the data.
    evidence: List[Evidence] = []
    if scope and missing:
        probe = resolve(event, missing[0])
        if not probe.found or probe.value is None:
            evidence.append(absent(event, missing[0], scope, note="not supplied"))
    return finding(
        spec,
        ctx,
        CheckStatus.UNDETERMINED,
        subject=subject,
        evidence=evidence,
        summary=f"{spec.title}: could not be checked.",
        why=(
            "This is reported as a gap rather than as a pass. A compliance record "
            "that reads as clean because nobody supplied the input is worse than "
            "one that says plainly what it could not see."
        ),
        resolution=resolution,
        missing=list(missing),
    )


# ---------------------------------------------------------------------------
# Statutory checks
# ---------------------------------------------------------------------------
#
# Fixed and parameterless, exactly like the 17 entries in `RULES`. Each carries
# its own citations rather than waiting for retrieval to rediscover them, for the
# reason set out in `red_flag_rules`: statutory and commercial registers do not
# match, and a check that waited for a vector search to find MSMED s.15 from the
# words "payment within 60 days of invoice" would simply never fire.

_MSME_HARMS = (ProcurementSide.BUYER, ProcurementSide.SUPPLIER)


def _payment_terms(event: ProcurementEvent) -> Tuple[Optional[str], Optional[int]]:
    """Where the agreed payment period is stated, and what it says.

    The purchase order wins over the bid: it is the document that was actually
    issued, and a term that moved between quotation and PO is itself reportable
    (`PO_PAYMENT_TERMS_DIFFER`).
    """
    po = event.purchase_order
    if po is not None and po.payment_terms_days is not None:
        return "purchase_order.payment_terms_days", po.payment_terms_days
    bid = event.awarded_bid
    if bid is not None and bid.payment_terms_days is not None:
        vendor_id = bid.vendor.vendor_id
        return f'bids[vendor.vendor_id="{vendor_id}"].payment_terms_days', bid.payment_terms_days
    return None, None


def _check_msme_terms(
    spec: CheckSpec, event: ProcurementEvent, ctx: EvalContext
) -> List[ProcurementFinding]:
    vendor = event.awarded_vendor
    if vendor is None:
        return [
            undetermined(
                spec, ctx, event, ["award.vendor_id"],
                "Record which vendor was awarded, so the payment terms can be read against that vendor's MSME status.",
            )
        ]

    subject = vendor.vendor_id
    if vendor.msme_status == MsmeStatus.UNKNOWN:
        return [
            undetermined(
                spec, ctx, event,
                [f'bids[vendor.vendor_id="{subject}"].vendor.msme_status'],
                "Supply the vendor's Udyam registration as at the award date, or a signed "
                "declaration that it is not a registered micro or small enterprise.",
                subject=subject, scope="vendor_msme_status",
            )
        ]

    if vendor.msme_status not in MSME_PROTECTED:
        return [
            finding(
                spec, ctx, CheckStatus.NOT_APPLICABLE, subject=subject,
                evidence=[e for e in [read(
                    event, f'bids[vendor.vendor_id="{subject}"].vendor.msme_status',
                    Comparator.NOT_IN, [m.value for m in MSME_PROTECTED],
                    note="Chapter V protects micro and small enterprises only",
                )] if e],
                summary=f"{vendor.name} is not a micro or small enterprise, so the MSMED payment period does not apply.",
                why="Section 2(n) defines a protected supplier as a micro or small enterprise. "
                    "A medium enterprise is registered as an MSME but sits outside Chapter V entirely.",
            )
        ]

    path, days = _payment_terms(event)
    if days is None:
        return [
            undetermined(
                spec, ctx, event, ["purchase_order.payment_terms_days"],
                "Supply the agreed payment period, in days from acceptance, from the purchase order.",
                subject=subject, scope="purchase_order",
            )
        ]

    # s.15 sets two periods. Where the period is agreed in writing the agreed date
    # governs and the proviso caps it at 45 days from acceptance. Where there is
    # no written agreement the appointed day is 15 days. Reading 45 as a flat
    # statutory allowance would clear a 30-day term that, absent a written
    # agreement, is already twice what the section permits.
    written = event.purchase_order.has_written_agreement if event.purchase_order else None

    if days > MSMED_AGREED_MAX_DAYS:
        return [
            finding(
                spec, ctx, CheckStatus.BREACH, subject=subject,
                evidence=[e for e in [
                    read(event, path, Comparator.GT, MSMED_AGREED_MAX_DAYS,
                         note="beyond the proviso's ceiling however the period was agreed",
                         requirement_source="MSMED Act s.15 proviso"),
                ] if e],
                summary=f"The payment term of {days} days exceeds the 45-day ceiling for a micro or small supplier.",
                why=(
                    f"{vendor.name} is a {vendor.msme_status.value.lower()} enterprise. The proviso to "
                    "section 15 says that in no case may the agreed period exceed forty-five days from "
                    "acceptance, so the term is void to that extent whatever the purchase order says. "
                    "Interest then runs under section 16 at three times the RBI bank rate, compounded "
                    "monthly, and section 23 makes that interest non-deductible. Where the amount is "
                    "still unpaid at the year end the deduction for the purchase itself is also deferred."
                ),
            )
        ]

    if days > MSMED_DEFAULT_DAYS and written is None:
        return [
            undetermined(
                spec, ctx, event, ["purchase_order.has_written_agreement"],
                f"Confirm whether the {days}-day period is agreed in writing. If it is not, the "
                "appointed day under section 15 is 15 days from acceptance and this term is already "
                "outside it.",
                subject=subject, scope="purchase_order",
            )
        ]

    if days > MSMED_DEFAULT_DAYS and written is False:
        return [
            finding(
                spec, ctx, CheckStatus.BREACH, subject=subject,
                evidence=[e for e in [
                    read(event, path, Comparator.GT, MSMED_DEFAULT_DAYS,
                         note="no written agreement, so the appointed day is 15 days",
                         requirement_source="MSMED Act s.15"),
                    read(event, "purchase_order.has_written_agreement", Comparator.EQ, False),
                ] if e],
                summary=f"With no written agreement the permitted period is 15 days; this order allows {days}.",
                why=(
                    "Section 15 requires payment by the date agreed in writing, and where there is no "
                    "such agreement, before the appointed day -- fifteen days from acceptance. The "
                    "forty-five day figure is the ceiling on a written agreement, not a general "
                    "allowance, so it is not available here."
                ),
            )
        ]

    return [
        finding(
            spec, ctx, CheckStatus.PASS, subject=subject,
            evidence=[e for e in [read(event, path, Comparator.LTE, MSMED_AGREED_MAX_DAYS)] if e],
            summary=f"The payment term of {days} days is within what section 15 permits.",
            why="Checked against the agreed-period ceiling in the proviso to section 15.",
        )
    ]


def _check_msme_overdue(
    spec: CheckSpec, event: ProcurementEvent, ctx: EvalContext
) -> List[ProcurementFinding]:
    po = event.purchase_order
    vendor = event.awarded_vendor
    if vendor is None or vendor.msme_status not in MSME_PROTECTED:
        return [finding(spec, ctx, CheckStatus.NOT_APPLICABLE,
                        subject=vendor.vendor_id if vendor else None,
                        summary="Not a protected supplier, or no award recorded.",
                        why="Section 15's payment window runs only in favour of a micro or small enterprise.")]
    if po is None or po.goods_accepted_at is None:
        return [undetermined(
            spec, ctx, event, ["purchase_order.goods_accepted_at"],
            "Supply the date goods or services were accepted. The payment window runs from acceptance, "
            "not from the invoice date.",
            subject=vendor.vendor_id, scope="purchase_order",
        )]

    accepted = _aware(po.goods_accepted_at)
    paid = _aware(po.paid_at)
    allowed = MSMED_AGREED_MAX_DAYS if po.has_written_agreement else MSMED_DEFAULT_DAYS
    reference = paid or _aware(datetime.combine(ctx.today, datetime.min.time()))
    elapsed = (reference - accepted).days

    if elapsed <= allowed:
        return [finding(
            spec, ctx, CheckStatus.PASS, subject=vendor.vendor_id,
            evidence=[e for e in [read(event, "purchase_order.goods_accepted_at", Comparator.PRESENT)] if e],
            summary=f"Payment is within the {allowed}-day window.",
            why="Measured from acceptance, as section 15 requires.",
        )]

    return [finding(
        spec, ctx, CheckStatus.BREACH, subject=vendor.vendor_id,
        evidence=[e for e in [
            read(event, "purchase_order.goods_accepted_at", Comparator.PRESENT,
                 note=f"{elapsed} days elapsed against a {allowed}-day window"),
        ] if e],
        summary=(
            f"Payment to {vendor.name} is {elapsed} days from acceptance against a {allowed}-day "
            f"statutory window."
            if paid else
            f"{elapsed} days have passed since acceptance with no payment recorded, against a "
            f"{allowed}-day statutory window."
        ),
        why=(
            "Interest under section 16 runs from the appointed day at three times the bank rate "
            "notified by the Reserve Bank, compounded with monthly rests. Section 23 makes that "
            "interest non-deductible, and it accrues whether or not the supplier asks for it. "
            "This check reports that the window was missed; it does not compute the amount -- see "
            "MSMED_INTEREST_QUANTUM."
        ),
    )]


def _check_msme_interest_quantum(
    spec: CheckSpec, event: ProcurementEvent, ctx: EvalContext
) -> List[ProcurementFinding]:
    """Deliberately always UNDETERMINED where liability arises.

    The quantum is a function of the RBI bank rate over the whole delay period,
    compounded monthly, and the rate changes. This system has no dated rate table,
    so it can establish that interest is running and cannot say how much. Emitting
    a confident figure from a rate hardcoded at build time would be the exact
    failure this codebase exists to avoid -- and finance would book it.
    """
    vendor = event.awarded_vendor
    po = event.purchase_order
    if vendor is None or vendor.msme_status not in MSME_PROTECTED or po is None:
        return [finding(spec, ctx, CheckStatus.NOT_APPLICABLE,
                        summary="No protected supplier or no purchase order.",
                        why="Interest under section 16 arises only on a delayed payment to a micro or small enterprise.")]
    if po.goods_accepted_at is None:
        return [finding(spec, ctx, CheckStatus.NOT_EVALUATED,
                        subject=vendor.vendor_id,
                        summary="Not evaluated: the delay itself has not been established.",
                        why="Quantum is only meaningful once MSMED_PAYMENT_OVERDUE reports a breach.")]

    return [undetermined(
        spec, ctx, event, ["rbi_bank_rate_schedule"],
        "Supply the RBI bank rate as notified across the delay period. Section 16 compounds at three "
        "times that rate with monthly rests, and the rate changes, so a single figure fixed at build "
        "time would misstate the liability.",
        subject=vendor.vendor_id,
    )]


def _related_party(event: ProcurementEvent) -> Optional[bool]:
    vendor = event.awarded_vendor
    profile = event.company_profile
    if vendor is None:
        return None
    if vendor.is_related_party is not None:
        return vendor.is_related_party
    if profile is not None and event.supplied("company_profile"):
        return vendor.vendor_id in profile.related_parties or vendor.name in profile.related_parties
    return None


def _check_related_party_award(
    spec: CheckSpec, event: ProcurementEvent, ctx: EvalContext
) -> List[ProcurementFinding]:
    vendor = event.awarded_vendor
    if vendor is None:
        return [undetermined(spec, ctx, event, ["award.vendor_id"],
                             "Record which vendor was awarded.")]
    subject = vendor.vendor_id

    if not event.supplied("company_profile") or event.company_profile is None:
        return [undetermined(
            spec, ctx, event, ["company_profile.related_parties"],
            "Supply the buying entity's related-party register and its listing status. Whether "
            "section 188 requires approval turns on the entity, the transaction type and prescribed "
            "value thresholds -- none of which can be read off a bid tab.",
            subject=subject, scope="company_profile",
        )]

    is_related = _related_party(event)
    if is_related is None:
        return [undetermined(
            spec, ctx, event, [f'bids[vendor.vendor_id="{subject}"].vendor.is_related_party'],
            "Confirm whether the awarded vendor is a related party of the buying entity.",
            subject=subject, scope="company_profile",
        )]

    if not is_related:
        return [finding(
            spec, ctx, CheckStatus.PASS, subject=subject,
            evidence=[e for e in [read(
                event, f'bids[vendor.vendor_id="{subject}"].vendor.is_related_party',
                Comparator.EQ, False)] if e] or [absent(
                    event, f"company_profile.related_parties", "company_profile",
                    note="awarded vendor is not on the related-party register")],
            summary=f"{vendor.name} is not on the related-party register.",
            why="Checked against the register supplied with the event.",
        )]

    approved = any(
        (a.stage or "").upper() == "RELATED_PARTY" for a in event.approvals
    ) or bool(vendor.related_party_approval_ref)

    if approved:
        return [finding(
            spec, ctx, CheckStatus.PASS, subject=subject,
            evidence=[e for e in [read(
                event, f'bids[vendor.vendor_id="{subject}"].vendor.related_party_approval_ref',
                Comparator.PRESENT)] if e],
            summary=f"{vendor.name} is a related party and an approval is recorded.",
            why="Section 188 approval is on file. Whether it was the right form of approval for this "
                "transaction is a question for the company secretary, not for this check.",
        )]

    if not event.supplied("approvals"):
        return [undetermined(
            spec, ctx, event, ["approvals"],
            "Supply the approval record for this award. Without it, an empty approvals list cannot be "
            "distinguished from approvals that were simply not exported.",
            subject=subject, scope="approvals",
        )]

    return [finding(
        spec, ctx, CheckStatus.BREACH, subject=subject,
        evidence=[absent(event, "approvals[stage=\"RELATED_PARTY\"]", "approvals",
                         note="no related-party approval in a complete approvals record")],
        summary=f"Work was awarded to {vendor.name}, a related party, with no approval on record.",
        why=(
            "Section 188 requires the board's consent -- and, above prescribed thresholds, a "
            "shareholders' resolution -- for specified transactions with a related party. The "
            "ordinary-course-of-business and arm's-length carve-outs may apply and are not assessed "
            "here; if either is being relied on, the basis should be minuted. Section 184 separately "
            "requires an interested director to disclose and not participate."
        ),
    )]


def _check_audit_committee_approval(
    spec: CheckSpec, event: ProcurementEvent, ctx: EvalContext
) -> List[ProcurementFinding]:
    profile = event.company_profile
    vendor = event.awarded_vendor
    if vendor is None or not event.supplied("company_profile") or profile is None:
        return [undetermined(
            spec, ctx, event, ["company_profile.has_audit_committee"],
            "Supply whether the buying entity is required to constitute an audit committee.",
            subject=vendor.vendor_id if vendor else None, scope="company_profile",
        )]
    if profile.has_audit_committee is None:
        return [undetermined(
            spec, ctx, event, ["company_profile.has_audit_committee"],
            "Confirm whether the entity has an audit committee. Section 177(4) applies only where one "
            "is required.",
            subject=vendor.vendor_id, scope="company_profile",
        )]
    if not profile.has_audit_committee:
        return [finding(
            spec, ctx, CheckStatus.NOT_APPLICABLE, subject=vendor.vendor_id,
            evidence=[e for e in [read(event, "company_profile.has_audit_committee", Comparator.EQ, False)] if e],
            summary="The entity has no audit committee, so section 177(4) does not apply.",
            why="Section 177(4) obliges the audit committee to approve related-party transactions in "
                "companies required to constitute one.",
        )]
    if _related_party(event) is not True:
        return [finding(spec, ctx, CheckStatus.NOT_APPLICABLE, subject=vendor.vendor_id,
                        summary="Not a related-party transaction.",
                        why="Section 177(4) bites on related-party transactions.")]

    approved = any((a.stage or "").upper() == "AUDIT_COMMITTEE" for a in event.approvals)
    if approved:
        return [finding(spec, ctx, CheckStatus.PASS, subject=vendor.vendor_id,
                        evidence=[e for e in [read(event, "company_profile.has_audit_committee", Comparator.EQ, True)] if e],
                        summary="Audit committee approval is recorded.",
                        why="Section 177(4) satisfied on the record supplied.")]
    if not event.supplied("approvals"):
        return [undetermined(spec, ctx, event, ["approvals"],
                             "Supply the approval record so audit committee approval can be checked.",
                             subject=vendor.vendor_id, scope="approvals")]
    return [finding(
        spec, ctx, CheckStatus.BREACH, subject=vendor.vendor_id,
        evidence=[absent(event, "approvals[stage=\"AUDIT_COMMITTEE\"]", "approvals")],
        summary="A related-party award with no audit committee approval on record.",
        why="Section 177(4) requires the audit committee to approve related-party transactions, and "
            "the committee's approval is separate from the board's under section 188.",
    )]


def _check_vendor_dpa(
    spec: CheckSpec, event: ProcurementEvent, ctx: EvalContext
) -> List[ProcurementFinding]:
    vendor = event.awarded_vendor
    if vendor is None:
        return [finding(spec, ctx, CheckStatus.NOT_EVALUATED, summary="No award recorded.",
                        why="Nothing to check until a vendor is awarded.")]
    subject = vendor.vendor_id
    if vendor.processes_personal_data is None:
        return [undetermined(
            spec, ctx, event, [f'bids[vendor.vendor_id="{subject}"].vendor.processes_personal_data'],
            "Record whether this vendor will handle personal data on the company's behalf.",
            subject=subject,
        )]
    if not vendor.processes_personal_data:
        return [finding(spec, ctx, CheckStatus.NOT_APPLICABLE, subject=subject,
                        evidence=[e for e in [read(event, f'bids[vendor.vendor_id="{subject}"].vendor.processes_personal_data', Comparator.EQ, False)] if e],
                        summary="This vendor does not handle personal data.",
                        why="No processing, no processor obligations.")]
    if vendor.has_data_processing_agreement:
        return [finding(spec, ctx, CheckStatus.PASS, subject=subject,
                        evidence=[e for e in [read(event, f'bids[vendor.vendor_id="{subject}"].vendor.has_data_processing_agreement', Comparator.EQ, True)] if e],
                        summary="A data processing agreement is in place.",
                        why="Recorded on the vendor master.")]
    if vendor.has_data_processing_agreement is None:
        return [undetermined(
            spec, ctx, event, [f'bids[vendor.vendor_id="{subject}"].vendor.has_data_processing_agreement'],
            "Confirm whether a data processing agreement has been executed with this vendor.",
            subject=subject,
        )]
    return [finding(
        spec, ctx, CheckStatus.BREACH, subject=subject,
        evidence=[e for e in [read(event, f'bids[vendor.vendor_id="{subject}"].vendor.has_data_processing_agreement', Comparator.EQ, False)] if e],
        summary=f"{vendor.name} will handle personal data with no processing agreement in place.",
        why="The company remains the data fiduciary and answerable for what its processor does. "
            "The obligation is discharged through the contract with the processor, so its absence "
            "leaves the obligation undischarged rather than transferred.",
    )]


STATUTORY_CHECKS: Tuple[Tuple[CheckSpec, Callable[..., List[ProcurementFinding]]], ...] = (
    (
        CheckSpec(
            check_id="MSMED_TERM_EXCEEDS_STATUTORY_CAP",
            title="Payment term beyond what MSMED s.15 permits",
            severity=Severity.CRITICAL,
            family=CheckFamily.STATUTE,
            harms=_MSME_HARMS,
            requires=(),
            reads=("purchase_order.payment_terms_days", "purchase_order.has_written_agreement",
                   "award.vendor_id", "bids[].vendor.msme_status"),
            citations=(
                _cite(ACT_MSMED, "Section 15",
                      "Payment is due on the date agreed in writing, and where there is no written "
                      "agreement, before the appointed day -- 15 days from acceptance. The proviso "
                      "caps any agreed period at 45 days."),
                _cite(ACT_MSMED, "Section 16",
                      "Interest on a delayed payment runs at three times the bank rate notified by "
                      "the Reserve Bank, compounded with monthly rests."),
                _cite(ACT_MSMED, "Section 23",
                      "That interest is not allowed as a deduction from income."),
            ),
            plain_summary="The payment period agreed with a small supplier is longer than the law allows.",
            why_it_matters="The term is void to the extent it exceeds the cap, and interest accrues by "
                           "operation of law whether or not the supplier claims it.",
        ),
        _check_msme_terms,
    ),
    (
        CheckSpec(
            check_id="MSMED_PAYMENT_OVERDUE",
            title="Payment to a small supplier past the statutory window",
            severity=Severity.HIGH,
            family=CheckFamily.STATUTE,
            harms=_MSME_HARMS,
            reads=("purchase_order.goods_accepted_at", "purchase_order.paid_at"),
            citations=(
                _cite(ACT_MSMED, "Section 15", "The payment window runs from acceptance."),
                _cite(ACT_MSMED, "Section 16", "Interest runs from the appointed day."),
            ),
            plain_summary="Payment has run past the window section 15 allows.",
            why_it_matters="Interest accrues automatically from the appointed day.",
        ),
        _check_msme_overdue,
    ),
    (
        CheckSpec(
            check_id="MSMED_INTEREST_QUANTUM",
            title="Interest exposure under MSMED s.16",
            severity=Severity.MEDIUM,
            family=CheckFamily.STATUTE,
            harms=(ProcurementSide.BUYER,),
            reads=("purchase_order.goods_accepted_at",),
            citations=(_cite(ACT_MSMED, "Section 16",
                             "Three times the bank rate notified by the Reserve Bank, compounded monthly."),),
            plain_summary="Interest is running, and this system cannot say how much.",
            why_it_matters="The rate changes over the delay period and no dated rate table is available here.",
        ),
        _check_msme_interest_quantum,
    ),
    (
        CheckSpec(
            check_id="RELATED_PARTY_AWARD_UNAPPROVED",
            title="Award to a related party without approval",
            severity=Severity.CRITICAL,
            family=CheckFamily.STATUTE,
            harms=(ProcurementSide.BUYER,),
            reads=("company_profile.related_parties", "approvals", "award.vendor_id"),
            citations=(
                _cite(ACT_COMPANIES, "Section 188",
                      "Specified transactions with a related party require the board's consent and, "
                      "above prescribed thresholds, a shareholders' resolution."),
                _cite(ACT_COMPANIES, "Section 184",
                      "A director interested in a contract must disclose the interest and not "
                      "participate in the decision."),
            ),
            plain_summary="The awarded vendor is a related party and no approval is on file.",
            why_it_matters="Approval is a precondition, not a formality that can be regularised later.",
        ),
        _check_related_party_award,
    ),
    (
        CheckSpec(
            check_id="RELATED_PARTY_AUDIT_COMMITTEE_APPROVAL",
            title="Related-party award without audit committee approval",
            severity=Severity.HIGH,
            family=CheckFamily.STATUTE,
            harms=(ProcurementSide.BUYER,),
            reads=("company_profile.has_audit_committee", "approvals"),
            citations=(_cite(ACT_COMPANIES, "Section 177",
                             "The audit committee approves related-party transactions in companies "
                             "required to constitute one."),),
            plain_summary="A related-party award with no audit committee approval recorded.",
            why_it_matters="This approval is separate from the board's under section 188.",
        ),
        _check_audit_committee_approval,
    ),
    (
        CheckSpec(
            check_id="VENDOR_PROCESSES_DATA_WITHOUT_DPA",
            title="Vendor handles personal data with no processing agreement",
            severity=Severity.HIGH,
            family=CheckFamily.STATUTE,
            harms=(ProcurementSide.BUYER,),
            reads=("award.vendor_id",),
            citations=(_cite(ACT_DPDP, "Section 8",
                             "A data fiduciary remains responsible for compliance including for "
                             "processing undertaken on its behalf, and may engage a processor only "
                             "under a valid contract."),),
            plain_summary="A vendor will handle personal data without a processing agreement.",
            why_it_matters="The obligation stays with the company; the contract is how it is discharged.",
        ),
        _check_vendor_dpa,
    ),
)


# ---------------------------------------------------------------------------
# Policy checks
# ---------------------------------------------------------------------------
#
# The predicate is code; the policy supplies constants. That division is the
# whole reason this feature can claim "rules first, model second" while checking
# rules that differ per customer. A model reading a procurement manual picks a
# kind from `PolicyCheckKind` and fills the slots `param_keys` names. It cannot
# write a comparison, and by the time evaluation runs it is not in the loop at
# all: the rule set is data, the predicate is this file, and the same event
# scored twice gives the same answer.

@dataclass(frozen=True)
class PolicyCheckTemplate:
    kind: PolicyCheckKind
    spec: CheckSpec
    param_keys: Tuple[str, ...]
    predicate: Callable[
        [PolicyRule, CheckSpec, ProcurementEvent, EvalContext], List[ProcurementFinding]
    ]
    requires: Tuple[str, ...] = ()


def _dec(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _param(rule: PolicyRule, key: str) -> Any:
    return rule.params.get(key)


def _event_value(event: ProcurementEvent) -> Tuple[Optional[str], Optional[Decimal]]:
    """The money figure a threshold is tested against, and where it was read."""
    if event.award and event.award.value is not None:
        return "award.value", event.award.value
    if event.estimated_value is not None:
        return "estimated_value", event.estimated_value
    return None, None


def in_scope(rule: PolicyRule, event: ProcurementEvent) -> bool:
    scope = rule.scope
    if scope.categories and (event.category or "") not in scope.categories:
        return False
    if scope.business_units and (event.business_unit or "") not in scope.business_units:
        return False
    _, value = _event_value(event)
    if value is not None:
        if scope.min_value is not None and value < scope.min_value:
            return False
        if scope.max_value is not None and value > scope.max_value:
            return False
    return True


def _bid_count_evidence(event: ProcurementEvent) -> List[Evidence]:
    """The responsive bid count, as something that can be recomputed.

    A count is not a field, so it cannot be a `FieldEvidence` -- but it must still
    be re-derivable, so it is a `DERIVED` over the bids list and the verifier
    recounts it rather than believing the number.
    """
    bids = read(event, "bids", Comparator.PRESENT, note="all bids as supplied")
    if bids is None:
        return []
    count = len(event.responsive_bids())
    return [
        DerivedEvidence(
            source=_src(event),
            computation="responsive_bid_count",
            inputs=[bids],
            value=str(quantise(Decimal(count))),
            note=f"{count} bids not recorded as non-responsive",
        )
    ]



def _policy_min_quotes(rule, spec, event, ctx):
    above = _dec(_param(rule, "above_value")) or Decimal(0)
    minimum = int(_param(rule, "min_quotes") or 0)
    path, value = _event_value(event)
    if value is None:
        return [undetermined(spec, ctx, event, ["award.value"],
                             "Record the awarded value so the quote-count threshold can be applied.")]
    if value < above:
        return [finding(spec, ctx, CheckStatus.NOT_APPLICABLE,
                        evidence=[e for e in [read(event, path, Comparator.LT, above)] if e],
                        summary=f"Below the {above} threshold at which {minimum} quotes are required.",
                        why="The rule applies above its own threshold only.",
                        source="POLICY", rule_id=rule.rule_id)]
    if not event.supplied("bids"):
        return [undetermined(spec, ctx, event, ["bids"],
                             "Supply the full bid list. A partial export cannot be distinguished from "
                             "a short bid list, and the difference is the whole finding.",
                             scope="bids")]
    count = len(event.responsive_bids())
    evidence = [e for e in [read(event, path, Comparator.GTE, above)] if e] + _bid_count_evidence(event)
    if count >= minimum:
        return [finding(spec, ctx, CheckStatus.PASS, evidence=evidence,
                        summary=f"{count} responsive bids against a required minimum of {minimum}.",
                        why="Competitive requirement met.", source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH, evidence=evidence,
        summary=f"Only {count} responsive bids for a purchase of {_display(value)}; policy requires {minimum}.",
        why=(
            "The competitive requirement is what makes the price defensible. An award made on fewer "
            "quotes than policy requires is the finding an internal audit raises months later, by "
            "which time the money has gone out."
        ),
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_approval_authority(rule, spec, event, ctx):
    above = _dec(_param(rule, "above_value")) or Decimal(0)
    required_role = str(_param(rule, "required_role") or "").upper()
    path, value = _event_value(event)
    if value is None:
        return [undetermined(spec, ctx, event, ["award.value"],
                             "Record the awarded value so the approval threshold can be applied.")]
    if value < above:
        return [finding(spec, ctx, CheckStatus.NOT_APPLICABLE,
                        evidence=[e for e in [read(event, path, Comparator.LT, above)] if e],
                        summary=f"Below the {above} threshold requiring {required_role} approval.",
                        why="The delegation applies above its own threshold.",
                        source="POLICY", rule_id=rule.rule_id)]
    if not event.supplied("approvals"):
        return [undetermined(spec, ctx, event, ["approvals"],
                             "Supply the approval record. An approvals array that was never exported "
                             "looks exactly like an award nobody approved.",
                             scope="approvals")]
    roles = {(a.approver_role or "").upper() for a in event.approvals}
    evidence = [e for e in [read(event, path, Comparator.GTE, above)] if e]
    if required_role in roles:
        return [finding(spec, ctx, CheckStatus.PASS, evidence=evidence,
                        summary=f"{required_role} approval is on record.",
                        why="Delegation of authority satisfied.", source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH,
        evidence=evidence + [absent(event, f'approvals[approver_role="{required_role}"]', "approvals")],
        summary=f"A purchase of {_display(value)} needs {required_role} approval; the record shows {sorted(roles) or 'none'}.",
        why="Approval above the delegated limit is what makes the commitment the company's rather "
            "than the individual buyer's.",
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_approval_before_commitment(rule, spec, event, ctx):
    po = event.purchase_order
    if po is None or po.issued_at is None:
        return [undetermined(spec, ctx, event, ["purchase_order.issued_at"],
                             "Record when the purchase order was issued.", scope="purchase_order")]
    if not event.supplied("approvals") or not event.approvals:
        return [undetermined(spec, ctx, event, ["approvals"],
                             "Supply the approval record with timestamps.", scope="approvals")]
    stamps = [_aware(a.approved_at) for a in event.approvals if a.approved_at]
    if not stamps:
        return [undetermined(spec, ctx, event, ["approvals"],
                             "Supply approval timestamps. Without them the order of events cannot be checked.",
                             scope="approvals")]
    issued, last = _aware(po.issued_at), max(stamps)
    if issued >= last:
        return [finding(spec, ctx, CheckStatus.PASS,
                        evidence=[e for e in [read(event, "purchase_order.issued_at", Comparator.PRESENT)] if e],
                        summary="The purchase order was issued after the last approval.",
                        why="Commitment followed authorisation.", source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH,
        evidence=[e for e in [read(event, "purchase_order.issued_at", Comparator.PRESENT,
                                   note=f"issued {issued.isoformat()}, last approval {last.isoformat()}")] if e],
        summary="The purchase order was issued before it was approved.",
        why="A retrospective approval records a decision that had already been made. The company was "
            "committed before anyone with authority agreed to it, and the approval that followed had "
            "nothing left to decide.",
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_approved_vendor(rule, spec, event, ctx):
    vendor = event.awarded_vendor
    if vendor is None:
        return [undetermined(spec, ctx, event, ["award.vendor_id"], "Record which vendor was awarded.")]
    subject = vendor.vendor_id
    path = f'bids[vendor.vendor_id="{subject}"].vendor.on_approved_list'
    if vendor.on_approved_list is None:
        return [undetermined(spec, ctx, event, [path],
                             "Record whether the awarded vendor was on the approved supplier list at "
                             "the award date.", subject=subject)]
    if vendor.on_approved_list:
        return [finding(spec, ctx, CheckStatus.PASS, subject=subject,
                        evidence=[e for e in [read(event, path, Comparator.EQ, True)] if e],
                        summary=f"{vendor.name} is on the approved supplier list.",
                        why="Prequalification satisfied.", source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH, subject=subject,
        evidence=[e for e in [read(event, path, Comparator.EQ, False)] if e],
        summary=f"{vendor.name} was awarded without being on the approved supplier list.",
        why="Prequalification is where financial standing, capability and compliance checks happen. "
            "Awarding around it means none of those checks were made on this vendor.",
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_lowest_responsive(rule, spec, event, ctx):
    if not event.supplied("bids"):
        return [undetermined(spec, ctx, event, ["bids"],
                             "Supply the full bid list so the lowest responsive bid can be identified.",
                             scope="bids")]
    priced = [b for b in event.responsive_bids() if b.total is not None]
    if len(priced) < 2 or event.award is None or event.award.vendor_id is None:
        return [finding(spec, ctx, CheckStatus.NOT_APPLICABLE,
                        summary="Fewer than two priced bids, or no award recorded.",
                        why="There is no lowest bid to compare against.",
                        source="POLICY", rule_id=rule.rule_id)]
    lowest = min(priced, key=lambda b: b.total)
    awarded_id = event.award.vendor_id
    if lowest.vendor.vendor_id == awarded_id:
        return [finding(spec, ctx, CheckStatus.PASS, subject=awarded_id,
                        evidence=[e for e in [read(event, f'bids[vendor.vendor_id="{awarded_id}"].total', Comparator.PRESENT)] if e],
                        summary="The lowest responsive bid was awarded.",
                        why="No deviation to justify.", source="POLICY", rule_id=rule.rule_id)]
    if event.award.justification:
        return [finding(spec, ctx, CheckStatus.PASS, subject=awarded_id,
                        evidence=[e for e in [read(event, "award.justification", Comparator.PRESENT)] if e],
                        summary="The lowest bid was not awarded, and a justification is recorded.",
                        why="Whether the reason is adequate is a judgement for the approver; this "
                            "check confirms one was recorded at all.",
                        source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH, subject=awarded_id,
        evidence=[e for e in [
            read(event, f'bids[vendor.vendor_id="{lowest.vendor.vendor_id}"].total', Comparator.PRESENT,
                 note=f"lowest responsive bid, from {lowest.vendor.name}"),
        ] if e] + [absent(event, "award.justification", "bids",
                          note="no recorded reason for passing over the lowest bid")],
        summary=f"{lowest.vendor.name} bid {_display(lowest.total)} and was not awarded, with no reason recorded.",
        why="Passing over the lowest responsive bid can be entirely proper. What makes it defensible "
            "is the reason being written down at the time rather than reconstructed afterwards.",
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_po_exceeds_award(rule, spec, event, ctx):
    po, award = event.purchase_order, event.award
    tolerance = _dec(_param(rule, "tolerance_pct")) or Decimal(0)
    if po is None or po.value is None or award is None or award.value is None:
        return [undetermined(spec, ctx, event, ["purchase_order.value", "award.value"],
                             "Supply both the awarded value and the purchase order value.",
                             scope="purchase_order")]
    ceiling = award.value * (Decimal(1) + tolerance / Decimal(100))
    if po.value <= ceiling:
        return [finding(spec, ctx, CheckStatus.PASS,
                        evidence=[e for e in [read(event, "purchase_order.value", Comparator.LTE, ceiling)] if e],
                        summary="The purchase order is within the awarded value.",
                        why="No uplift between award and order.", source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH,
        evidence=[e for e in [read(event, "purchase_order.value", Comparator.GT, ceiling,
                                   note=f"awarded {_display(award.value)}")] if e],
        summary=f"The purchase order is for {_display(po.value)} against an award of {_display(award.value)}.",
        why="Value added after the award was never competed and never approved at the higher figure. "
            "This is the most common way an approved purchase becomes an unapproved one.",
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_split_po(rule, spec, event, ctx):
    window = int(_param(rule, "window_days") or 30)
    threshold = _dec(_param(rule, "threshold"))
    if threshold is None:
        return [finding(spec, ctx, CheckStatus.NOT_EVALUATED,
                        summary="No threshold parameter on the rule.",
                        why="Structuring is defined relative to the threshold being avoided.",
                        source="POLICY", rule_id=rule.rule_id)]
    if not event.supplied("prior_awards"):
        return [undetermined(spec, ctx, event, ["prior_awards"],
                             "Supply recent awards to the same vendor and category. Structuring is "
                             "invisible inside a single event by construction -- that is the point of "
                             "splitting one.", scope="prior_awards")]
    vendor = event.awarded_vendor
    if vendor is None or event.award is None or event.award.value is None or event.award.decided_at is None:
        return [undetermined(spec, ctx, event, ["award.decided_at", "award.value"],
                             "Record the award value and date.")]

    decided = _aware(event.award.decided_at)
    nearby = [
        p for p in event.prior_awards
        if p.vendor_id == vendor.vendor_id
        and (p.category or event.category) == event.category
        and p.value is not None and p.decided_at is not None
        and abs((decided - _aware(p.decided_at)).days) <= window
    ]
    combined = event.award.value + sum(p.value for p in nearby)
    if not nearby or combined <= threshold or event.award.value > threshold:
        return [finding(spec, ctx, CheckStatus.PASS, subject=vendor.vendor_id,
                        evidence=[e for e in [read(event, "award.value", Comparator.PRESENT)] if e],
                        summary="No pattern of awards below the threshold within the window.",
                        why="Checked against the award history supplied.",
                        source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH, subject=vendor.vendor_id,
        evidence=[e for e in [
            read(event, "award.value", Comparator.LTE, threshold,
                 note=f"this award is under the {threshold} threshold"),
            read(event, "prior_awards", Comparator.PRESENT,
                 note=f"{len(nearby)} further awards to the same vendor within {window} days"),
        ] if e],
        summary=(
            f"{len(nearby) + 1} awards to {vendor.name} within {window} days total "
            f"{_display(combined)}, each below the {_display(threshold)} threshold."
        ),
        why=(
            "Individually every one of these is inside the buyer's authority. Together they cross the "
            "threshold that would have required a higher approval and a competitive process. Whether "
            "the split was deliberate is not something this check can tell you -- a genuine run of "
            "small orders looks identical -- but the pattern is what the threshold exists to catch."
        ),
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_payment_terms_cap(rule, spec, event, ctx):
    cap = _dec(_param(rule, "max_days"))
    if cap is None:
        return [finding(spec, ctx, CheckStatus.NOT_EVALUATED, summary="No cap parameter on the rule.",
                        why="Nothing to compare against.", source="POLICY", rule_id=rule.rule_id)]
    path, days = _payment_terms(event)
    if days is None:
        return [undetermined(spec, ctx, event, ["purchase_order.payment_terms_days"],
                             "Supply the agreed payment period.", scope="purchase_order")]
    if Decimal(days) <= cap:
        return [finding(spec, ctx, CheckStatus.PASS,
                        evidence=[e for e in [read(event, path, Comparator.LTE, cap)] if e],
                        summary=f"Payment terms of {days} days are within the policy cap of {cap}.",
                        why="Within policy.", source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH,
        evidence=[e for e in [read(event, path, Comparator.GT, cap)] if e],
        summary=f"Payment terms of {days} days exceed the policy cap of {cap}.",
        why="Working capital terms agreed outside policy shift cash timing the company planned around.",
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_single_source(rule, spec, event, ctx):
    if event.single_source is None:
        return [undetermined(spec, ctx, event, ["single_source"],
                             "Record whether this was a single-source award.")]
    if not event.single_source:
        return [finding(spec, ctx, CheckStatus.NOT_APPLICABLE,
                        evidence=[e for e in [read(event, "single_source", Comparator.EQ, False)] if e],
                        summary="Not a single-source award.", why="Competitive process followed.",
                        source="POLICY", rule_id=rule.rule_id)]
    if event.single_source_reason:
        return [finding(spec, ctx, CheckStatus.PASS,
                        evidence=[e for e in [read(event, "single_source_reason", Comparator.PRESENT)] if e],
                        summary="Single-source award with a recorded justification.",
                        why="The reason is on file.", source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH,
        evidence=[e for e in [read(event, "single_source", Comparator.EQ, True)] if e]
                 + [absent(event, "single_source_reason", "bids")],
        summary="A single-source award with no justification recorded.",
        why="Single sourcing is often the right answer -- proprietary parts, an incumbent mid-project, "
            "a genuine emergency. What policy requires is that the reason exists in writing before the "
            "award, not that it be reconstructed when the auditor asks.",
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_late_bid(rule, spec, event, ctx):
    if event.closed_at is None:
        return [undetermined(spec, ctx, event, ["closed_at"],
                             "Record the bid submission deadline.")]
    if not event.supplied("bids"):
        return [undetermined(spec, ctx, event, ["bids"], "Supply the full bid list with timestamps.",
                             scope="bids")]
    deadline = _aware(event.closed_at)
    late = [
        b for b in event.bids
        if b.submitted_at and _aware(b.submitted_at) > deadline and b.is_responsive is not False
    ]
    if not late:
        return [finding(spec, ctx, CheckStatus.PASS,
                        evidence=[e for e in [read(event, "closed_at", Comparator.PRESENT)] if e],
                        summary="No late bid was treated as responsive.",
                        why="Deadline held.", source="POLICY", rule_id=rule.rule_id)]
    return [
        finding(
            spec, ctx, CheckStatus.BREACH, subject=b.vendor.vendor_id,
            evidence=[e for e in [
                read(event, f'bids[vendor.vendor_id="{b.vendor.vendor_id}"].submitted_at',
                     Comparator.PRESENT, note=f"deadline was {deadline.isoformat()}"),
                read(event, "closed_at", Comparator.PRESENT),
            ] if e],
            summary=f"{b.vendor.name} submitted after the deadline and was still in contention.",
            why="A bidder who sees the deadline is not enforced has time the others did not, and may "
                "have had sight of where the bidding stood. The unfairness lands on the bidders who "
                "submitted on time.",
            source="POLICY", rule_id=rule.rule_id,
        )
        for b in late
    ]


def _policy_bid_window(rule, spec, event, ctx):
    minimum = _dec(_param(rule, "min_days"))
    if minimum is None or event.published_at is None or event.closed_at is None:
        return [undetermined(spec, ctx, event, ["published_at", "closed_at"],
                             "Record when the enquiry was published and when it closed.")]
    days = (_aware(event.closed_at) - _aware(event.published_at)).days
    if Decimal(days) >= minimum:
        return [finding(spec, ctx, CheckStatus.PASS,
                        evidence=[e for e in [read(event, "closed_at", Comparator.PRESENT)] if e],
                        summary=f"Bidders had {days} days against a minimum of {minimum}.",
                        why="Adequate response time.", source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH,
        evidence=[e for e in [read(event, "published_at", Comparator.PRESENT,
                                   note=f"{days} days to the deadline against a {minimum}-day minimum")] if e],
        summary=f"Bidders had {days} days to respond; policy requires {minimum}.",
        why="A short window favours whoever already knew the requirement was coming, which is usually "
            "the incumbent. The competition is narrowed before a single bid arrives.",
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_budget(rule, spec, event, ctx):
    if not event.supplied("budget") or event.budget_remaining is None:
        return [undetermined(spec, ctx, event, ["budget_remaining"],
                             "Supply the remaining budget for the line this award is booked to.",
                             scope="budget")]
    path, value = _event_value(event)
    if value is None:
        return [undetermined(spec, ctx, event, ["award.value"], "Record the awarded value.")]
    if value <= event.budget_remaining:
        return [finding(spec, ctx, CheckStatus.PASS,
                        evidence=[e for e in [read(event, path, Comparator.LTE, event.budget_remaining)] if e],
                        summary="The award is within the remaining budget.",
                        why="Funds available.", source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH,
        evidence=[e for e in [read(event, path, Comparator.GT, event.budget_remaining,
                                   note=f"budget line {event.budget_line or 'unnamed'}")] if e],
        summary=f"The award of {_display(value)} exceeds the remaining budget of {_display(event.budget_remaining)}.",
        why="The overspend is committed at award, not discovered at invoice.",
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_scope_drift(rule, spec, event, ctx):
    po = event.purchase_order
    if po is None or not po.line_items:
        return [undetermined(spec, ctx, event, ["purchase_order.line_items"],
                             "Supply the purchase order line items.", scope="purchase_order")]
    if not event.supplied("rfq_line_item_codes") or not event.rfq_line_item_codes:
        return [undetermined(spec, ctx, event, ["rfq_line_item_codes"],
                             "Supply the item codes as tendered, so additions can be identified.",
                             scope="rfq_line_item_codes")]
    tendered = set(event.rfq_line_item_codes)
    added = [i.code for i in po.line_items if i.code and i.code not in tendered]
    if not added:
        return [finding(spec, ctx, CheckStatus.PASS,
                        evidence=[e for e in [read(event, "rfq_line_item_codes", Comparator.PRESENT)] if e],
                        summary="Every ordered line was tendered.",
                        why="No scope added after bidding.", source="POLICY", rule_id=rule.rule_id)]
    return [finding(
        spec, ctx, CheckStatus.BREACH, subject=",".join(sorted(added)[:5]),
        evidence=[e for e in [
            read(event, "purchase_order.line_items", Comparator.PRESENT,
                 note=f"{len(added)} line(s) not in the enquiry: {', '.join(sorted(added)[:5])}"),
            read(event, "rfq_line_item_codes", Comparator.PRESENT),
        ] if e],
        summary=f"{len(added)} line item(s) on the purchase order were never tendered.",
        why="Lines added after bidding closed were priced by one vendor with no competitor. The "
            "competitive result on the tendered lines says nothing about these.",
        source="POLICY", rule_id=rule.rule_id,
    )]


def _policy_rate_contract(rule, spec, event, ctx):
    po = event.purchase_order
    if po is None or not po.line_items or not event.rate_contract_refs:
        return [finding(spec, ctx, CheckStatus.NOT_APPLICABLE,
                        summary="No rate contract covers these lines.",
                        why="Nothing to compare against.", source="POLICY", rule_id=rule.rule_id)]
    covered = [i for i in po.line_items if i.code and i.code in event.rate_contract_refs]
    if not covered:
        return [finding(spec, ctx, CheckStatus.NOT_APPLICABLE,
                        summary="No ordered line is covered by a rate contract.",
                        why="Nothing to compare against.", source="POLICY", rule_id=rule.rule_id)]
    return [undetermined(
        spec, ctx, event, ["rate_contract_prices"],
        "Supply the contracted unit price for each covered line. The reference alone identifies the "
        "contract but does not carry its prices, so adherence cannot be measured from it.",
        subject=",".join(sorted(i.code for i in covered)[:5]),
    )]


POLICY_TEMPLATES: Dict[PolicyCheckKind, PolicyCheckTemplate] = {}


def _template(kind, check_id, title, severity, summary, why, param_keys, predicate,
              harms=(ProcurementSide.BUYER,), citations=(), requires=()):
    POLICY_TEMPLATES[kind] = PolicyCheckTemplate(
        kind=kind,
        spec=CheckSpec(
            check_id=check_id, title=title, severity=severity, family=CheckFamily.POLICY,
            plain_summary=summary, why_it_matters=why, citations=citations, harms=harms,
            requires=requires, kind=kind,
        ),
        param_keys=param_keys,
        predicate=predicate,
        requires=requires,
    )


_template(PolicyCheckKind.MIN_QUOTES_BY_VALUE, "MIN_QUOTES_BY_VALUE",
          "Fewer competitive quotes than policy requires", Severity.HIGH,
          "The award rests on fewer quotes than the policy requires at this value.",
          "The competitive requirement is what makes the price defensible.",
          ("above_value", "min_quotes"), _policy_min_quotes, requires=("bids",))

_template(PolicyCheckKind.APPROVAL_AUTHORITY, "APPROVAL_AUTHORITY",
          "Approved below the delegated authority", Severity.CRITICAL,
          "The purchase was approved below the level the delegation of authority requires.",
          "Approval at the right level is what makes the commitment the company's.",
          ("above_value", "required_role"), _policy_approval_authority, requires=("approvals",))

_template(PolicyCheckKind.APPROVAL_BEFORE_COMMITMENT, "APPROVAL_BEFORE_COMMITMENT",
          "Purchase order issued before approval", Severity.HIGH,
          "The order went out before it was approved.",
          "A retrospective approval has nothing left to decide.",
          (), _policy_approval_before_commitment, requires=("approvals",))

_template(PolicyCheckKind.APPROVED_VENDOR_REQUIRED, "APPROVED_VENDOR_REQUIRED",
          "Award to a vendor outside the approved list", Severity.HIGH,
          "The awarded vendor was not on the approved supplier list.",
          "Prequalification is where capability and compliance checks happen.",
          (), _policy_approved_vendor)

_template(PolicyCheckKind.LOWEST_RESPONSIVE_AWARD, "LOWEST_RESPONSIVE_AWARD",
          "Lowest responsive bid passed over without a reason", Severity.HIGH,
          "A cheaper responsive bid was not awarded and no reason was recorded.",
          "Passing over the lowest bid can be proper; the reason has to exist in writing.",
          ("tolerance_pct",), _policy_lowest_responsive, requires=("bids",))

_template(PolicyCheckKind.PO_EXCEEDS_AWARDED_VALUE, "PO_EXCEEDS_AWARDED_VALUE",
          "Purchase order exceeds the awarded value", Severity.HIGH,
          "The order was raised for more than was awarded.",
          "Value added after award was never competed and never approved.",
          ("tolerance_pct",), _policy_po_exceeds_award)

_template(PolicyCheckKind.SPLIT_PO_AVOIDANCE, "SPLIT_PO_AVOIDANCE",
          "Awards split below an approval threshold", Severity.HIGH,
          "Several awards to one vendor sit just under a threshold they would cross together.",
          "The threshold exists to catch exactly this shape.",
          ("window_days", "threshold"), _policy_split_po, requires=("prior_awards",))

_template(PolicyCheckKind.PAYMENT_TERMS_CAP, "PAYMENT_TERMS_CAP",
          "Payment terms beyond the policy cap", Severity.MEDIUM,
          "The agreed payment period is longer than policy allows.",
          "Terms agreed outside policy shift cash timing the company planned around.",
          ("max_days",), _policy_payment_terms_cap)

_template(PolicyCheckKind.SINGLE_SOURCE_JUSTIFICATION, "SINGLE_SOURCE_JUSTIFICATION",
          "Single-source award without justification", Severity.HIGH,
          "A single-source award with no recorded reason.",
          "The reason must exist before the award, not after the question.",
          (), _policy_single_source)

_template(PolicyCheckKind.LATE_BID_REJECTION, "LATE_BID_REJECTION",
          "Late bid left in contention", Severity.HIGH,
          "A bid submitted after the deadline was still treated as responsive.",
          "The unfairness lands on the bidders who submitted on time.",
          (), _policy_late_bid, requires=("bids",))

_template(PolicyCheckKind.MANDATORY_BID_WINDOW, "MANDATORY_BID_WINDOW",
          "Bidding window shorter than policy requires", Severity.MEDIUM,
          "Bidders had less time to respond than policy allows.",
          "A short window narrows the field before a single bid arrives.",
          ("min_days",), _policy_bid_window)

_template(PolicyCheckKind.BUDGET_AVAILABILITY, "BUDGET_AVAILABILITY",
          "Award exceeds the available budget", Severity.MEDIUM,
          "The award is larger than the budget remaining on its line.",
          "The overspend is committed at award, not discovered at invoice.",
          (), _policy_budget, requires=("budget",))

_template(PolicyCheckKind.SCOPE_DRIFT, "SCOPE_DRIFT",
          "Purchase order lines that were never tendered", Severity.MEDIUM,
          "The order contains lines the enquiry did not.",
          "Lines added after bidding closed had no competitor.",
          (), _policy_scope_drift, requires=("rfq_line_item_codes",))

_template(PolicyCheckKind.RATE_CONTRACT_ADHERENCE, "RATE_CONTRACT_ADHERENCE",
          "Ordered price against the rate contract", Severity.MEDIUM,
          "Ordered unit prices should be checked against the rate contract.",
          "A rate contract only saves money if orders are actually placed at its prices.",
          ("tolerance_pct",), _policy_rate_contract)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@dataclass
class ProcurementEvaluation:
    """Every check's outcome, and the subset a reader has to act on.

    `outcomes` carries PASS and NOT_APPLICABLE as well, and that is not padding.
    A compliance report showing only breaches cannot be distinguished from one
    where the check never ran -- the same failure as an empty contract review
    reading as a clean contract. The reader needs to see what was looked at.
    """

    outcomes: List[ProcurementFinding] = field(default_factory=list)

    @property
    def findings(self) -> List[ProcurementFinding]:
        """What the reader must act on, worst first."""
        wanted = {CheckStatus.BREACH, CheckStatus.INDICATOR, CheckStatus.UNDETERMINED}
        actionable = [o for o in self.outcomes if o.status in wanted]
        order = {
            CheckStatus.BREACH: 0,
            CheckStatus.INDICATOR: 1,
            CheckStatus.UNDETERMINED: 2,
        }
        actionable.sort(
            key=lambda f: (order[f.status], -SEVERITY_ORDER[f.severity], f.check_id)
        )
        return actionable

    def by_status(self, status: CheckStatus) -> List[ProcurementFinding]:
        return [o for o in self.outcomes if o.status == status]

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for outcome in self.outcomes:
            if outcome.provisional:
                continue
            counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1
        return counts


def _missing_collections(spec: CheckSpec, event: ProcurementEvent) -> List[str]:
    return [c for c in spec.requires if not event.supplied(c)]


def evaluate_procurement(
    event: ProcurementEvent,
    rule_set: Optional[PolicyRuleSet] = None,
    *,
    side: ProcurementSide = ProcurementSide.BUYER,
    include_draft_rules: bool = False,
    today: Optional[date] = None,
) -> ProcurementEvaluation:
    """Run every applicable check. Pure: no I/O, no model, no clock beyond `today`.

    `include_draft_rules` exists because a customer who has uploaded a policy but
    not yet ratified it would otherwise see nothing, and that makes the product
    useless on day one. It is off by default, and what it produces is marked
    `provisional`: excluded from every count, and capping the review's confidence.
    A caller that wants output from rules nobody has confirmed has to ask for it.
    """
    ctx = EvalContext(
        side=side,
        rule_set=rule_set or EMPTY_RULE_SET.model_copy(deep=True),
        include_draft_rules=include_draft_rules,
        today=today or date.today(),
    )
    outcomes: List[ProcurementFinding] = []

    # --- Statute. Runs whoever is reading and whether or not a policy exists.
    for spec, predicate in STATUTORY_CHECKS:
        missing = _missing_collections(spec, event)
        if missing:
            outcomes.append(
                undetermined(
                    spec, ctx, event, missing,
                    "Supply " + ", ".join(missing) + " and re-run. Until then this check has not been "
                    "performed, which is not the same as having passed.",
                    scope=missing[0],
                )
            )
            continue
        outcomes.extend(predicate(spec, event, ctx))

    # --- Bid integrity. Deterministic statistics, and never a breach: a pattern
    # in a bid tab cannot establish the agreement Competition Act s.3(3) attaches
    # to. Imported here rather than at module scope because `bid_integrity` builds
    # its specs out of this module's helpers.
    from src.core.bid_integrity import analyse_bid_integrity

    outcomes.extend(analyse_bid_integrity(event, ctx))

    # --- Policy.
    #
    # A supplier-side review does not run them. A buyer's delegation of authority
    # is an internal control of the buyer's, not an obligation the supplier owes
    # anyone, and reporting it to them as a finding would be inventing a duty.
    # What the supplier does get is every statutory check above and the full
    # purchase-order term review -- which is the half that bears on them.
    rules = list(ctx.rule_set.enforceable_rules())
    if include_draft_rules:
        rules += ctx.rule_set.drafted_rules()

    for rule in rules:
        template = POLICY_TEMPLATES.get(rule.kind)
        if template is None:
            continue
        spec = template.spec
        if side == ProcurementSide.SUPPLIER:
            outcomes.append(finding(
                spec, ctx, CheckStatus.NOT_APPLICABLE, source="POLICY", rule_id=rule.rule_id,
                summary="Not checked on a supplier-side review.",
                why="This is the buying organisation's own internal control. It is not an obligation "
                    "the supplier owes, so reporting it here would invent a duty that does not exist.",
            ))
            continue
        if not in_scope(rule, event):
            outcomes.append(finding(
                spec, ctx, CheckStatus.NOT_APPLICABLE, source="POLICY", rule_id=rule.rule_id,
                summary="Outside this rule's scope.",
                why="The rule is limited by category, business unit or value band.",
            ))
            continue

        provisional = not rule.enforceable
        missing = [c for c in template.requires if not event.supplied(c)]
        if missing:
            produced = [undetermined(
                spec, ctx, event, missing,
                "Supply " + ", ".join(missing) + " and re-run.",
                scope=missing[0],
            )]
        else:
            try:
                produced = template.predicate(rule, spec, event, ctx)
            except Exception as e:
                # A check that raised has not passed. Reporting it as a gap keeps
                # a bug in one predicate from silently clearing an award.
                produced = [undetermined(
                    spec, ctx, event, [f"{rule.kind.value}:{type(e).__name__}"],
                    f"This check could not be completed ({type(e).__name__}). Re-run once the event "
                    "data is corrected, or report it as a defect.",
                )]

        for item in produced:
            item.source = "POLICY"
            item.policy_rule_id = rule.rule_id
            item.provisional = provisional
            if rule.severity_override and item.status in {CheckStatus.BREACH, CheckStatus.INDICATOR}:
                item.severity = rule.severity_override
        outcomes.extend(produced)

    return ProcurementEvaluation(outcomes=outcomes)


def overall_status(evaluation: ProcurementEvaluation) -> "OverallStatusValue":
    """The headline, which can never read as a certificate of compliance.

    A material gap keeps the result at NO_BREACH_FOUND_WITH_GAPS however clean
    everything that could be checked looks. The alternative -- letting a review
    that could not see the approvals report the same headline as one that saw
    them and found them in order -- is how a compliance tool becomes a liability.
    """
    from src.schemas.procurement import OverallStatus

    real = [o for o in evaluation.outcomes if not o.provisional]
    if any(o.status == CheckStatus.BREACH for o in real):
        return OverallStatus.BREACHES_FOUND
    material_gap = any(
        o.status == CheckStatus.UNDETERMINED and SEVERITY_ORDER[o.severity] >= SEVERITY_ORDER[Severity.MEDIUM]
        for o in real
    )
    if any(o.status == CheckStatus.INDICATOR for o in real):
        return OverallStatus.INDICATORS_ONLY
    if material_gap:
        return OverallStatus.NO_BREACH_FOUND_WITH_GAPS
    return OverallStatus.NO_BREACH_FOUND


OverallStatusValue = Any


__all__ = [
    "CheckSpec",
    "EvalContext",
    "POLICY_TEMPLATES",
    "PolicyCheckTemplate",
    "ProcurementEvaluation",
    "STATUTORY_CHECKS",
    "absent",
    "evaluate_procurement",
    "finding",
    "in_scope",
    "overall_status",
    "read",
    "severity_for",
    "undetermined",
]
