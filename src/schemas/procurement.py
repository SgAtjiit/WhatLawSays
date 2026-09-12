"""Schemas for procurement compliance review.

This pipeline asks a different question from the other two -- not "what offence do
these facts establish" and not "what does this contract do to me", but "did this
award obey the company's own policy and Indian statute". Four structural
consequences shape every type here.

**Evidence, not quotes.** Contract review grounds a finding with `matched_quote`
and offsets into the document, and `verify_quotes` re-derives the span. Most
procurement findings are about structured facts instead -- "policy requires three
quotes, the event carries two" -- where there is no document span to quote. The
`Evidence` union below generalises grounding to document spans, field reads,
absences and computations, and `verify_evidence` in
`src/core/procurement_evidence.py` holds all four to the same standard: every
field path is re-resolved against the source event, every comparator re-evaluated,
every computation re-executed. A finding whose evidence does not re-derive is
discarded, exactly as an unlocatable model quote is.

**Absence is not compliance.** Every optional fact defaults to `None`, never to
`False`, and `CheckStatus` carries `UNDETERMINED` alongside `BREACH` and `PASS`.
This is the criminal pipeline's UNKNOWN != FALSE, and it matters more here,
because a compliance report gets filed and relied on. The enforcement is not
convention but structure: see `provided_collections`.

**A missing collection is not an empty one.** `approvals: List[Approval] = []`
would be the single worst bug this feature could ship -- a payload that simply
omits its approvals array reads exactly like an event that genuinely had no
approvals, and the difference is "we could not check" versus "nobody approved
it". `ProcurementEvent.provided_collections` is the caller's explicit assertion
of what it actually supplied, and an `AbsenceEvidence` over a collection outside
that set can support only `UNDETERMINED` -- never a breach, and never a pass.

**Nothing here certifies compliance.** There is no `COMPLIANT` status and no
compliance percentage. `OverallStatus` tops out at `NO_BREACH_FOUND`, and where
any material check could not be evaluated it is `NO_BREACH_FOUND_WITH_GAPS`. A
word that reads as certification would be relied on as one.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set, Union

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Annotated

from src.schemas.contract import Citation, Severity


# Money is Decimal, never float. Evidence verification is equality-based -- the
# verifier re-executes a computation and requires the same answer -- and float
# arithmetic does not reliably give the same answer twice across platforms. A
# flaky verifier is a disabled verifier, so every amount and every derived
# statistic is quantised Decimal.
MONEY_EXPONENT = Decimal("0.01")
STAT_EXPONENT = Decimal("0.000001")


# ---------------------------------------------------------------------------
# Sides
# ---------------------------------------------------------------------------

class ProcurementSide(str, Enum):
    """Which side of the transaction the review is being run for.

    Kept separate from `PartyPosition` rather than folded into it. `PartyPosition`
    is validated against `POSITIONS_BY_TYPE`, which maps *contract types* to their
    two parties; a sourcing event is not a contract type, and adding BUYER there
    would make every one of those validations answer a question it was not asked.
    The translation happens at the one point it is needed -- when the awarded PO
    is handed to the contract pipeline.

    The two sides do not run the same checks, and pretending they do would be the
    dishonest kind of symmetry. A buyer's delegation-of-authority table is not an
    obligation the supplier owes anyone, so policy checks are `NOT_APPLICABLE` on
    a supplier-side review. What the supplier does get is every statutory check
    and the full purchase-order term review -- which is the half that actually
    bears on them, and the half they cannot get anywhere else.
    """

    BUYER = "BUYER"
    SUPPLIER = "SUPPLIER"
    UNKNOWN = "UNKNOWN"


# The side that did not write the purchase order and has least room to refuse it.
# Same role `WEAKER_POSITIONS` plays in contract review: it does not decide
# whether something is a breach, but it raises severity, because the same term is
# harder to escape from this side.
WEAKER_SIDES = frozenset({ProcurementSide.SUPPLIER})


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------

class CheckStatus(str, Enum):
    """The result of running one check.

    `UNDETERMINED` is why this is an enum and not a boolean. A check that needs
    the vendor's MSME status and is not given it has not found compliance; it has
    found that it could not look. Those are reported separately and never summed.

    `INDICATOR` is why it is not a three-valued enum. A pattern in a bid tab is
    grounds for enquiry; it is not a determination that anything unlawful
    happened, and it names real vendors while saying so. It gets its own status so
    that no downstream count, filter or renderer can quietly promote it.

    `NOT_EVALUATED` is a check that was never run -- no ratified rule enables it,
    or the caller did not ask for it. Distinct from `PASS` for the same reason
    `UNDETERMINED` is.
    """

    BREACH = "BREACH"
    INDICATOR = "INDICATOR"
    UNDETERMINED = "UNDETERMINED"
    PASS = "PASS"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_EVALUATED = "NOT_EVALUATED"


# Statuses that represent something the reader must act on. Used for counting and
# for deciding `OverallStatus`; deliberately excludes INDICATOR.
ACTIONABLE_STATUSES = frozenset({CheckStatus.BREACH})


class OverallStatus(str, Enum):
    """The headline. Note what is absent: there is no COMPLIANT."""

    BREACHES_FOUND = "BREACHES_FOUND"
    INDICATORS_ONLY = "INDICATORS_ONLY"
    NO_BREACH_FOUND_WITH_GAPS = "NO_BREACH_FOUND_WITH_GAPS"
    NO_BREACH_FOUND = "NO_BREACH_FOUND"


class CheckFamily(str, Enum):
    POLICY = "POLICY"
    STATUTE = "STATUTE"
    BID_INTEGRITY = "BID_INTEGRITY"
    PO_CONSISTENCY = "PO_CONSISTENCY"
    PO_TERMS = "PO_TERMS"


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class EvidenceKind(str, Enum):
    DOCUMENT_SPAN = "DOCUMENT_SPAN"
    FIELD = "FIELD"
    ABSENCE = "ABSENCE"
    DERIVED = "DERIVED"


class SourceRef(BaseModel):
    """Which artefact a piece of evidence was read out of."""

    kind: str = Field(..., description="EVENT, POLICY, PO or HISTORY")
    id: str = Field(default="", description="event_id, policy version, or PO number")


class Comparator(str, Enum):
    EQ = "EQ"
    NE = "NE"
    LT = "LT"
    LTE = "LTE"
    GT = "GT"
    GTE = "GTE"
    IN = "IN"
    NOT_IN = "NOT_IN"
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"


class DocumentSpanEvidence(BaseModel):
    """A verbatim span of a document, at offsets that index into its text.

    Identical in meaning to `RedFlagFinding.matched_quote` plus its offsets, and
    re-derived by the same whitespace-normalised string comparison `verify_quotes`
    performs.
    """

    kind: Literal[EvidenceKind.DOCUMENT_SPAN] = EvidenceKind.DOCUMENT_SPAN
    source: SourceRef
    quote: str
    start: int
    end: int
    note: str = ""


class FieldEvidence(BaseModel):
    """One read of the event, and the comparison made against it.

    `field_path` is never written freehand by a model. Every path emitted here
    comes from a check's declared `reads` tuple, which is code -- the direct
    analogue of the rule that the model never supplies offsets.
    """

    kind: Literal[EvidenceKind.FIELD] = EvidenceKind.FIELD
    source: SourceRef
    field_path: str = Field(
        ...,
        description=(
            "Restricted path grammar resolved by `procurement_evidence.resolve`, "
            "e.g. bids[vendor_id=\"V-002\"].payment_terms_days. A path that does "
            "not pick out exactly one node is a verification failure, not a "
            "first-match -- the same reason an ambiguous quote is discarded."
        ),
    )
    observed: Optional[Any] = Field(None, description="The value found at that path")
    observed_display: str = Field(
        default="", description="Human rendering, e.g. 'Rs 62,40,000'. Never compared."
    )
    comparator: Comparator
    required: Optional[Any] = Field(None, description="What the check required")
    requirement_source: str = Field(
        default="", description="The policy rule id or statutory section imposing it"
    )
    note: str = ""


class AbsenceEvidence(BaseModel):
    """Something that is not there.

    Only meaningful where the enclosing collection was declared complete. An
    absence inside a collection the caller never said it supplied proves nothing,
    and `verify_evidence` will let it support only an `UNDETERMINED` outcome.
    """

    kind: Literal[EvidenceKind.ABSENCE] = EvidenceKind.ABSENCE
    source: SourceRef
    field_path: str = Field(..., description="What was looked for")
    scope_path: str = Field(..., description="The collection that was enumerated, e.g. 'approvals'")
    scope_declared_complete: bool = Field(
        ..., description="Whether scope_path is in the event's provided_collections"
    )
    scope_size: int = 0
    note: str = ""


class DerivedEvidence(BaseModel):
    """A computed figure, carrying everything needed to recompute it.

    `computation` is a key into the registry in `procurement_evidence`, and the
    verifier re-executes it over the verified inputs and requires exact equality
    on the quantised Decimal. A bid-integrity statistic that cannot be reproduced
    is discarded exactly like an invented quote.
    """

    kind: Literal[EvidenceKind.DERIVED] = EvidenceKind.DERIVED
    source: SourceRef
    computation: str = Field(..., description="Registry key, e.g. 'bid_integrity.cv_of_totals'")
    inputs: List["Evidence"] = Field(default=[], description="Every operand, itself evidence")
    params: Dict[str, str] = Field(default={}, description="Scalars as strings, never floats")
    value: str = Field(..., description="Quantised Decimal as a string")
    note: str = ""


Evidence = Annotated[
    Union[DocumentSpanEvidence, FieldEvidence, AbsenceEvidence, DerivedEvidence],
    Field(discriminator="kind"),
]

DerivedEvidence.model_rebuild()


# ---------------------------------------------------------------------------
# The event
# ---------------------------------------------------------------------------

class MsmeStatus(str, Enum):
    MICRO = "MICRO"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    NOT_MSME = "NOT_MSME"
    UNKNOWN = "UNKNOWN"


# Chapter V of the MSMED Act -- s.15's payment period and s.16's interest -- runs
# in favour of a "supplier", which s.2(n) defines as a micro or small enterprise.
# A medium enterprise is an MSME for registration purposes and sits outside the
# delayed-payment provisions entirely; Income Tax s.43B(h) draws the same line.
# Treating all three sizes alike would raise breaches that do not exist.
MSME_PROTECTED = frozenset({MsmeStatus.MICRO, MsmeStatus.SMALL})

# s.15 sets two different periods, and which applies turns on a fact that is
# itself often absent. Where there is a written agreement, the agreed date governs
# and may not exceed 45 days from acceptance. Where there is none, the appointed
# day is 15 days from acceptance. Reading 45 as a flat statutory allowance would
# clear a 30-day term that, absent a written agreement, is already twice the
# permitted period.
MSMED_AGREED_MAX_DAYS = 45
MSMED_DEFAULT_DAYS = 15


class LineItem(BaseModel):
    code: Optional[str] = Field(None, description="Item or BOQ code, where the event carries one")
    line_no: Optional[int] = None
    description: str = ""
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    unit_price: Optional[Decimal] = None
    total: Optional[Decimal] = None


class Vendor(BaseModel):
    """A bidding or awarded supplier.

    Every optional flag defaults to `None`, never `False`. `None` means nobody
    said; `False` is an assertion somebody made. Defaulting `is_related_party` to
    `False` would silently clear every award of the Companies Act s.188 question.
    """

    vendor_id: str
    name: str
    gstin: Optional[str] = None
    pan: Optional[str] = None
    udyam_number: Optional[str] = None
    msme_status: MsmeStatus = MsmeStatus.UNKNOWN
    msme_status_as_of: Optional[date] = Field(
        None, description="When the status was established; a status dated after the award proves nothing"
    )
    on_approved_list: Optional[bool] = None
    is_related_party: Optional[bool] = None
    related_party_approval_ref: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    bank_account: Optional[str] = None
    bank_ifsc: Optional[str] = None
    processes_personal_data: Optional[bool] = None
    has_data_processing_agreement: Optional[bool] = None


class Bid(BaseModel):
    vendor: Vendor
    total: Optional[Decimal] = None
    currency: str = "INR"
    line_items: List[LineItem] = Field(default=[])
    submitted_at: Optional[datetime] = None
    submitted_from_ip: Optional[str] = None
    payment_terms_days: Optional[int] = None
    is_responsive: Optional[bool] = Field(
        None, description="Technically compliant. None where the event does not record it."
    )
    disqualified_reason: Optional[str] = None


class Approval(BaseModel):
    approver_name: Optional[str] = None
    approver_role: Optional[str] = Field(
        None, description="Authority level as the delegation-of-authority table names it"
    )
    approved_at: Optional[datetime] = None
    stage: Optional[str] = Field(None, description="e.g. REQUISITION, AWARD, PO, RELATED_PARTY")
    note: Optional[str] = None


class Award(BaseModel):
    vendor_id: Optional[str] = None
    value: Optional[Decimal] = None
    decided_at: Optional[datetime] = None
    justification: Optional[str] = Field(
        None, description="Recorded reason, required where the lowest responsive bid was not taken"
    )


class PriorAward(BaseModel):
    """An earlier award, carried with the event being reviewed.

    Structuring and winner rotation are invisible within a single event by
    construction -- each purchase looks unremarkable on its own, which is the
    point of splitting one. History travels in the payload rather than being
    fetched, so a review stays reproducible from what it was given.
    """

    vendor_id: str
    category: Optional[str] = None
    value: Optional[Decimal] = None
    decided_at: Optional[datetime] = None
    po_number: Optional[str] = None
    event_id: Optional[str] = None


class PurchaseOrder(BaseModel):
    po_number: Optional[str] = None
    vendor_id: Optional[str] = None
    value: Optional[Decimal] = None
    currency: str = "INR"
    payment_terms_days: Optional[int] = None
    has_written_agreement: Optional[bool] = Field(
        None,
        description=(
            "Whether the payment period is agreed in writing. Decides whether "
            "MSMED s.15 allows up to 45 days or defaults to 15."
        ),
    )
    issued_at: Optional[datetime] = None
    delivery_date: Optional[date] = None
    goods_accepted_at: Optional[datetime] = Field(
        None, description="Acceptance, from which the MSMED s.15 period runs"
    )
    paid_at: Optional[datetime] = None
    line_items: List[LineItem] = Field(default=[])
    linked_event_id: Optional[str] = None


class CompanyProfile(BaseModel):
    """The buying entity.

    Required for the Companies Act checks and for nothing else. s.188's approval
    requirements attach at prescribed value thresholds and carry ordinary-course
    and arm's-length carve-outs; s.177(4) applies only to companies obliged to
    constitute an audit committee. Without this, a related-party check is honestly
    `UNDETERMINED`, and reporting an s.188 breach from a bid tab alone would be
    wrong law rather than a strict reading.
    """

    entity_name: str = ""
    cin: Optional[str] = None
    is_listed: Optional[bool] = None
    paid_up_capital: Optional[Decimal] = None
    turnover: Optional[Decimal] = None
    has_audit_committee: Optional[bool] = None
    related_parties: List[str] = Field(
        default=[], description="Vendor ids or names on the company's related-party register"
    )
    interested_directors: List[str] = Field(default=[])


# The collections a caller can declare it actually supplied. A name outside this
# set is rejected at validation rather than silently believed.
KNOWN_COLLECTIONS = frozenset(
    {
        "bids",
        "approvals",
        "line_items",
        "prior_awards",
        "rfq_line_item_codes",
        "purchase_order",
        "company_profile",
        "vendor_msme_status",
        "vendor_identifiers",
        "submission_metadata",
        "budget",
    }
)


class ProcurementEvent(BaseModel):
    """One RFQ / RFP / auction, what was bid, and what came of it."""

    event_id: str
    title: str = ""
    category: Optional[str] = None
    business_unit: Optional[str] = None
    estimated_value: Optional[Decimal] = None
    currency: str = "INR"

    bids: List[Bid] = Field(default=[])
    bids_invited: Optional[int] = None
    published_at: Optional[datetime] = None
    closed_at: Optional[datetime] = Field(
        None, description="Submission deadline; a bid after this was late"
    )

    award: Optional[Award] = None
    approvals: List[Approval] = Field(default=[])

    requisition_ref: Optional[str] = None
    requisition_value: Optional[Decimal] = None
    budget_line: Optional[str] = None
    budget_remaining: Optional[Decimal] = None

    single_source: Optional[bool] = None
    single_source_reason: Optional[str] = None

    rfq_line_item_codes: List[str] = Field(default=[])
    prior_awards: List[PriorAward] = Field(default=[])
    rate_contract_refs: Dict[str, str] = Field(
        default={},
        description=(
            "Line item code -> rate contract reference. Identical unit prices "
            "across bidders have an innocent explanation when a published rate "
            "governs, and the suppression is reported rather than applied silently."
        ),
    )

    purchase_order: Optional[PurchaseOrder] = None
    company_profile: Optional[CompanyProfile] = None

    provided_collections: Set[str] = Field(
        default=set(),
        description=(
            "What the caller actually supplied. An empty `approvals` list means "
            "'no approvals' only if 'approvals' appears here; otherwise it means "
            "'not supplied', and every check that needs it returns UNDETERMINED. "
            "This is the structural enforcement of UNKNOWN != FALSE."
        ),
    )

    @model_validator(mode="after")
    def _reject_unknown_collections(self) -> "ProcurementEvent":
        unknown = set(self.provided_collections) - KNOWN_COLLECTIONS
        if unknown:
            raise ValueError(
                "provided_collections names collections this system does not know: "
                + ", ".join(sorted(unknown))
                + ". Known: "
                + ", ".join(sorted(KNOWN_COLLECTIONS))
            )
        return self

    def supplied(self, collection: str) -> bool:
        return collection in self.provided_collections

    def bid_for(self, vendor_id: Optional[str]) -> Optional[Bid]:
        if vendor_id is None:
            return None
        return next((b for b in self.bids if b.vendor.vendor_id == vendor_id), None)

    @property
    def awarded_bid(self) -> Optional[Bid]:
        return self.bid_for(self.award.vendor_id) if self.award else None

    @property
    def awarded_vendor(self) -> Optional[Vendor]:
        bid = self.awarded_bid
        return bid.vendor if bid else None

    def responsive_bids(self) -> List[Bid]:
        """Bids not recorded as disqualified.

        A bid whose `is_responsive` is None is counted, because nobody said it was
        not -- the opposite default would silently shrink the bid count and raise
        a quote-count breach out of missing data.
        """
        return [b for b in self.bids if b.is_responsive is not False]


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

class PolicyCheckKind(str, Enum):
    """The fixed catalogue of things a policy can require.

    A policy rule is an instance of one of these bound to company parameters. The
    model that reads a procurement manual chooses from this list and fills typed
    slots; it never invents a kind, and it never writes the logic that evaluates
    one. That is what keeps "rules first, model second" intact through a feature
    whose rules vary per customer.
    """

    MIN_QUOTES_BY_VALUE = "MIN_QUOTES_BY_VALUE"
    APPROVAL_AUTHORITY = "APPROVAL_AUTHORITY"
    APPROVAL_BEFORE_COMMITMENT = "APPROVAL_BEFORE_COMMITMENT"
    APPROVED_VENDOR_REQUIRED = "APPROVED_VENDOR_REQUIRED"
    LOWEST_RESPONSIVE_AWARD = "LOWEST_RESPONSIVE_AWARD"
    PO_EXCEEDS_AWARDED_VALUE = "PO_EXCEEDS_AWARDED_VALUE"
    SPLIT_PO_AVOIDANCE = "SPLIT_PO_AVOIDANCE"
    PAYMENT_TERMS_CAP = "PAYMENT_TERMS_CAP"
    SINGLE_SOURCE_JUSTIFICATION = "SINGLE_SOURCE_JUSTIFICATION"
    LATE_BID_REJECTION = "LATE_BID_REJECTION"
    MANDATORY_BID_WINDOW = "MANDATORY_BID_WINDOW"
    SCOPE_DRIFT = "SCOPE_DRIFT"
    BUDGET_AVAILABILITY = "BUDGET_AVAILABILITY"
    RATE_CONTRACT_ADHERENCE = "RATE_CONTRACT_ADHERENCE"


class RuleStatus(str, Enum):
    DRAFT = "DRAFT"
    RATIFIED = "RATIFIED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"


# A drafted rule is a model's reading of somebody's policy document. It becomes
# enforceable only once a person has confirmed or corrected it.
ENFORCEABLE_RULE_STATUSES = frozenset({RuleStatus.RATIFIED, RuleStatus.EDITED})


class RuleOrigin(str, Enum):
    MODEL_DRAFT = "MODEL_DRAFT"
    HUMAN = "HUMAN"


class PolicySetStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RuleScope(BaseModel):
    """Where a rule applies. An empty scope applies everywhere."""

    categories: List[str] = Field(default=[])
    business_units: List[str] = Field(default=[])
    min_value: Optional[Decimal] = None
    max_value: Optional[Decimal] = None


class PolicyRule(BaseModel):
    """One company requirement, bound to a kind in the catalogue."""

    rule_id: str
    kind: PolicyCheckKind
    params: Dict[str, Any] = Field(
        default={}, description="Bound parameters, validated against the kind's param model"
    )
    scope: RuleScope = Field(default_factory=RuleScope)
    severity_override: Optional[Severity] = None
    status: RuleStatus = RuleStatus.DRAFT
    origin: RuleOrigin = RuleOrigin.MODEL_DRAFT

    grounding: Optional[DocumentSpanEvidence] = Field(
        None, description="The sentence of the policy this came from. Required for MODEL_DRAFT."
    )
    policy_reference: Optional[str] = Field(
        None, description="Free-text citation, for a rule a person authored by hand"
    )

    ratified_by: Optional[str] = None
    ratified_at: Optional[datetime] = None
    note: str = ""

    @model_validator(mode="after")
    def _model_drafts_must_be_grounded(self) -> "PolicyRule":
        # Enforced at construction, not at review time. A drafted rule that cannot
        # point at the sentence it came from is not a reading of the policy, it is
        # a guess, and there is no later point at which that becomes acceptable.
        if self.origin == RuleOrigin.MODEL_DRAFT and self.grounding is None:
            raise ValueError(
                f"Policy rule {self.rule_id!r} is a model draft with no grounding quote. "
                "A drafted rule must quote the policy text it was read from."
            )
        return self

    @property
    def enforceable(self) -> bool:
        return self.status in ENFORCEABLE_RULE_STATUSES


class PolicyRuleSet(BaseModel):
    policy_id: str
    company_id: str = ""
    org_label: str = ""
    version: int = 1
    status: PolicySetStatus = PolicySetStatus.DRAFT
    supersedes: Optional[str] = None
    rules: List[PolicyRule] = Field(default=[])
    effective_from: Optional[date] = None
    compilation_issues: List[str] = Field(
        default=[],
        description="Contradictions found across rules -- overlapping bands, unreachable thresholds",
    )
    not_addressed: List[PolicyCheckKind] = Field(
        default=[],
        description="Catalogue entries this manual says nothing about. Silence is reported, never defaulted.",
    )

    def enforceable_rules(self) -> List[PolicyRule]:
        """Only ratified or edited rules in an activated set are ever enforced."""
        if self.status != PolicySetStatus.ACTIVE:
            return []
        return [r for r in self.rules if r.enforceable]

    def drafted_rules(self) -> List[PolicyRule]:
        return [r for r in self.rules if r.status == RuleStatus.DRAFT]


# So an award can be checked against statute before any policy exists. The
# statutory checks carry their own parameters and do not consult this.
EMPTY_RULE_SET = PolicyRuleSet(policy_id="none", status=PolicySetStatus.DRAFT)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

class ProcurementFinding(BaseModel):
    """A check's result, with what it rests on.

    Mirrors `RedFlagFinding` deliberately -- same severity ladder, same `detector`
    provenance, same carry-your-own-citation discipline -- so the existing
    renderers and the PDF builder extend rather than fork. It differs where the
    domain differs, and each difference is load-bearing:

    * `status` can be UNDETERMINED or INDICATOR, which a red flag cannot be.
    * `evidence` replaces the single quote-and-offsets triple.
    * `what_would_resolve_it` is required on UNDETERMINED, which turns an honest
      "I cannot tell" into a work item instead of merely an irritation.
    """

    check_id: str
    title: str
    severity: Severity
    status: CheckStatus
    family: CheckFamily

    subject_ref: Optional[str] = Field(
        None,
        description=(
            "What the finding is about -- a vendor id, a line item code, a PO "
            "number. With check_id this is the evaluation match key: the right "
            "check on the wrong vendor is a normalisation bug wearing a correct "
            "answer's clothes."
        ),
    )

    evidence: List[Evidence] = Field(default=[])
    citations: List[Citation] = Field(default=[])
    harms: List[ProcurementSide] = Field(default=[])

    plain_summary: str
    why_it_matters: str
    what_would_resolve_it: Optional[str] = None

    corroborating_signals: List[str] = Field(
        default=[],
        description=(
            "INDICATOR only. Corroboration is listed on one finding rather than "
            "raising severity or emitting several: three weak statistical signals "
            "are not one strong finding of fact."
        ),
    )

    detector: str = Field(
        default="rule", description="'rule' for a deterministic check, 'llm' for model prose"
    )
    source: str = Field(default="STATUTE", description="STATUTE or POLICY")
    policy_rule_id: Optional[str] = None
    missing_fields: List[str] = Field(
        default=[], description="UNDETERMINED only: exactly what was needed and not given"
    )
    provisional: bool = Field(
        default=False,
        description="Produced by a rule the customer has not ratified. Excluded from every count.",
    )

    @model_validator(mode="after")
    def _undetermined_must_say_what_would_fix_it(self) -> "ProcurementFinding":
        if self.status == CheckStatus.UNDETERMINED and not self.what_would_resolve_it:
            raise ValueError(
                f"Check {self.check_id!r} is UNDETERMINED without saying what would resolve it. "
                "An unanswerable gap is a work item, and the reader has to be told what to supply."
            )
        return self


class MissingProvisionFinding(BaseModel):
    """Something the award file or the policy should contain and does not.

    Absence is invisible to any check that walks what is present, so it is
    detected against a checklist instead -- the same reason `MissingClauseFinding`
    exists for contracts.
    """

    code: str
    title: str
    severity: Severity
    why_it_matters: str
    citations: List[Citation] = Field(default=[])


__all__ = [
    "ACTIONABLE_STATUSES",
    "AbsenceEvidence",
    "Approval",
    "Award",
    "Bid",
    "CheckFamily",
    "CheckStatus",
    "Comparator",
    "CompanyProfile",
    "DerivedEvidence",
    "DocumentSpanEvidence",
    "EMPTY_RULE_SET",
    "ENFORCEABLE_RULE_STATUSES",
    "Evidence",
    "EvidenceKind",
    "FieldEvidence",
    "KNOWN_COLLECTIONS",
    "LineItem",
    "MONEY_EXPONENT",
    "MSMED_AGREED_MAX_DAYS",
    "MSMED_DEFAULT_DAYS",
    "MSME_PROTECTED",
    "MissingProvisionFinding",
    "MsmeStatus",
    "OverallStatus",
    "PolicyCheckKind",
    "PolicyRule",
    "PolicyRuleSet",
    "PolicySetStatus",
    "PriorAward",
    "ProcurementEvent",
    "ProcurementFinding",
    "ProcurementSide",
    "PurchaseOrder",
    "RuleOrigin",
    "RuleScope",
    "RuleStatus",
    "STAT_EXPONENT",
    "SourceRef",
    "Vendor",
    "WEAKER_SIDES",
]
