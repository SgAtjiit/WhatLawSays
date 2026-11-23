"""What a contract of each type should contain, and what it means if it does not.

Absence is invisible to any clause-by-clause pass: no amount of reading the
clauses that *are* there will tell you the liability cap is missing. So the gaps
are found by checking the categories present against a per-type checklist rather
than by reading the text at all.

The checklist is deliberately about protections, not formalities. A missing
signature block is a filing problem; a missing termination right is a trap.
"""

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from src.core.acts import ACT_ARBITRATION, ACT_CONTRACT, ACT_DPDP, ACT_TRANSFER_OF_PROPERTY
from src.schemas.contract import (
    Citation,
    Clause,
    ClauseCategory,
    ContractType,
    MissingClauseFinding,
    PartyPosition,
    Severity,
    WEAKER_POSITIONS,
)


@dataclass(frozen=True)
class ChecklistItem:
    category: ClauseCategory
    title: str
    severity: Severity
    why_it_matters: str
    citations: Tuple[Citation, ...] = ()
    # Categories that satisfy this item instead. A contract naming an arbitral
    # seat has addressed dispute resolution even with no court-jurisdiction clause.
    satisfied_by: Tuple[ClauseCategory, ...] = ()


def _cite(act: str, section: str, note: str) -> Citation:
    return Citation(act=act, section_number=section, note=note)


_TERMINATION = ChecklistItem(
    category=ClauseCategory.TERMINATION,
    title="No termination clause",
    severity=Severity.HIGH,
    why_it_matters=(
        "With no agreed exit, ending the contract early is a breach. You are left "
        "arguing about an implied reasonable notice period instead of pointing at a term."
    ),
)

_DISPUTE = ChecklistItem(
    category=ClauseCategory.DISPUTE_RESOLUTION,
    title="No dispute resolution clause",
    severity=Severity.MEDIUM,
    satisfied_by=(ClauseCategory.GOVERNING_LAW,),
    why_it_matters=(
        "Without an agreed forum, a dispute goes wherever the other side chooses to "
        "file, and you argue about jurisdiction before you argue about the merits."
    ),
    citations=(
        _cite(ACT_ARBITRATION, "Section 7",
              "An arbitration agreement must be in writing to be relied on at all."),
    ),
)

_GOVERNING_LAW = ChecklistItem(
    category=ClauseCategory.GOVERNING_LAW,
    title="No governing law clause",
    severity=Severity.LOW,
    satisfied_by=(ClauseCategory.DISPUTE_RESOLUTION,),
    why_it_matters="Which country's law applies becomes arguable, which delays everything else.",
)

_LIABILITY = ChecklistItem(
    category=ClauseCategory.LIABILITY,
    title="No limitation of liability",
    severity=Severity.HIGH,
    why_it_matters=(
        "Your exposure is unbounded. A cap tied to the fees paid is standard and is "
        "usually accepted if asked for before signing."
    ),
)

_PAYMENT = ChecklistItem(
    category=ClauseCategory.PAYMENT,
    title="No payment terms",
    severity=Severity.HIGH,
    satisfied_by=(ClauseCategory.SALARY, ClauseCategory.RENT),
    why_it_matters=(
        "Amount, schedule and due date are the terms most often disputed. If they are "
        "not written down, you have no date from which anything is overdue."
    ),
)

_CONFIDENTIALITY = ChecklistItem(
    category=ClauseCategory.CONFIDENTIALITY,
    title="No confidentiality clause",
    severity=Severity.MEDIUM,
    why_it_matters="Nothing restricts what the other side may repeat about your business.",
)

_IP = ChecklistItem(
    category=ClauseCategory.IP_ASSIGNMENT,
    title="No intellectual property clause",
    severity=Severity.MEDIUM,
    why_it_matters=(
        "Ownership of what gets created is left to default rules and to argument. Say "
        "explicitly who owns the deliverables and who keeps pre-existing material."
    ),
)

_NOTICE = ChecklistItem(
    category=ClauseCategory.NOTICE_PERIOD,
    title="No notice period",
    severity=Severity.MEDIUM,
    satisfied_by=(ClauseCategory.TERMINATION,),
    why_it_matters="Neither side knows how much warning the other is owed before things end.",
)

_TERM = ChecklistItem(
    category=ClauseCategory.TERM,
    title="No stated term or start date",
    severity=Severity.MEDIUM,
    why_it_matters="When the contract starts and how long it runs are both left open.",
)

_DATA = ChecklistItem(
    category=ClauseCategory.DATA_PROTECTION,
    title="No data protection clause",
    severity=Severity.MEDIUM,
    why_it_matters=(
        "Where personal data is handled, the DPDP Act's obligations apply whether or "
        "not the contract mentions them. Silence does not remove the duty; it only "
        "removes your agreed allocation of it."
    ),
    citations=(
        _cite(ACT_DPDP, "Section 8",
              "General obligations of a Data Fiduciary, including accountability for "
              "any processor it engages."),
    ),
)

_DEPOSIT_REFUND = ChecklistItem(
    category=ClauseCategory.SECURITY_DEPOSIT,
    title="No security deposit terms",
    severity=Severity.HIGH,
    why_it_matters=(
        "How much is held, what may be deducted and when it must be returned are the "
        "three things every deposit dispute turns on."
    ),
    citations=(
        _cite(ACT_TRANSFER_OF_PROPERTY, "Section 108",
              "Default rights and liabilities of lessor and lessee, which fill any gap "
              "the lease leaves."),
    ),
)

_MAINTENANCE = ChecklistItem(
    category=ClauseCategory.MAINTENANCE,
    title="No repairs or maintenance clause",
    severity=Severity.MEDIUM,
    why_it_matters="Who pays for what breaks is the most common running dispute in a tenancy.",
)

_FORCE_MAJEURE = ChecklistItem(
    category=ClauseCategory.FORCE_MAJEURE,
    title="No force majeure clause",
    severity=Severity.LOW,
    why_it_matters=(
        "Events outside anyone's control fall back on the narrow doctrine of "
        "frustration, which excuses far less than a drafted clause would."
    ),
    citations=(
        _cite(ACT_CONTRACT, "Section 56",
              "An agreement to do an act that becomes impossible is void -- a far "
              "narrower relief than a negotiated force majeure clause."),
    ),
)


CHECKLISTS: Dict[ContractType, Tuple[ChecklistItem, ...]] = {
    ContractType.EMPLOYMENT: (
        _TERMINATION, _NOTICE, _PAYMENT, _CONFIDENTIALITY, _IP, _TERM,
    ),
    ContractType.NDA: (
        _CONFIDENTIALITY, _TERM, _DISPUTE, _GOVERNING_LAW,
    ),
    ContractType.LEASE: (
        _TERM, _PAYMENT, _DEPOSIT_REFUND, _TERMINATION, _MAINTENANCE, _NOTICE,
    ),
    ContractType.SERVICE: (
        _PAYMENT, _TERMINATION, _LIABILITY, _IP, _CONFIDENTIALITY, _DISPUTE,
        _FORCE_MAJEURE, _DATA,
    ),
    ContractType.FREELANCE: (
        _PAYMENT, _TERMINATION, _IP, _LIABILITY, _CONFIDENTIALITY,
    ),
    ContractType.VENDOR: (
        _PAYMENT, _TERMINATION, _LIABILITY, _CONFIDENTIALITY, _DISPUTE,
        _FORCE_MAJEURE, _DATA,
    ),
    ContractType.SAAS: (
        _PAYMENT, _TERMINATION, _LIABILITY, _DATA, _CONFIDENTIALITY, _DISPUTE,
    ),
    ContractType.LOAN: (
        _PAYMENT, _TERM, _TERMINATION, _DISPUTE, _GOVERNING_LAW,
    ),
    ContractType.OTHER: (
        _PAYMENT, _TERMINATION, _DISPUTE, _GOVERNING_LAW,
    ),
    ContractType.UNKNOWN: (
        _PAYMENT, _TERMINATION, _DISPUTE, _GOVERNING_LAW,
    ),
}


def find_missing_clauses(
    clauses: Sequence[Clause],
    contract_type: ContractType,
    position: PartyPosition = PartyPosition.UNKNOWN,
) -> List[MissingClauseFinding]:
    """Report checklist items this contract does not cover.

    A gap matters more to the side that did not draft the contract, since the
    drafter's silence is rarely accidental and rarely against its own interest.
    """
    present = {clause.category for clause in clauses}
    escalate = position in WEAKER_POSITIONS

    missing: List[MissingClauseFinding] = []
    for item in CHECKLISTS.get(contract_type, CHECKLISTS[ContractType.UNKNOWN]):
        if item.category in present:
            continue
        if any(alternative in present for alternative in item.satisfied_by):
            continue
        severity = item.severity
        if escalate and severity is Severity.MEDIUM:
            severity = Severity.HIGH
        missing.append(
            MissingClauseFinding(
                category=item.category,
                severity=severity,
                title=item.title,
                why_it_matters=item.why_it_matters,
                citations=list(item.citations),
            )
        )
    return missing
