"""Schemas for contract review.

Contract review differs from scenario analysis in one structural way that shapes
every type here: a finding is only meaningful relative to a *side*. An uncapped
indemnity is catastrophic for the indemnifier and unremarkable for the
indemnitee; a lock-in is a burden on the tenant and a protection for the
landlord. So `PartyPosition` is not decoration -- nothing downstream can assign
severity without it.

Every finding also carries the character offsets of the text that triggered it.
That is what lets the grounding verifier prove a quote came from the uploaded
document rather than from a model, which is the same discipline the statutory
pipeline applies to section citations.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class ContractType(str, Enum):
    EMPLOYMENT = "EMPLOYMENT"
    NDA = "NDA"
    LEASE = "LEASE"
    SERVICE = "SERVICE"
    FREELANCE = "FREELANCE"
    LOAN = "LOAN"
    VENDOR = "VENDOR"
    SAAS = "SAAS"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class PartyPosition(str, Enum):
    """Which side of the contract the reviewing user sits on."""

    EMPLOYEE = "EMPLOYEE"
    EMPLOYER = "EMPLOYER"
    DISCLOSING_PARTY = "DISCLOSING_PARTY"
    RECEIVING_PARTY = "RECEIVING_PARTY"
    LANDLORD = "LANDLORD"
    TENANT = "TENANT"
    CLIENT = "CLIENT"
    SERVICE_PROVIDER = "SERVICE_PROVIDER"
    LENDER = "LENDER"
    BORROWER = "BORROWER"
    UNKNOWN = "UNKNOWN"


# The two sides each contract type is written between. Used to validate that a
# declared position actually belongs to the contract being reviewed, and to
# offer the right choice in the UI.
POSITIONS_BY_TYPE: Dict[ContractType, Tuple[PartyPosition, PartyPosition]] = {
    ContractType.EMPLOYMENT: (PartyPosition.EMPLOYEE, PartyPosition.EMPLOYER),
    ContractType.NDA: (PartyPosition.RECEIVING_PARTY, PartyPosition.DISCLOSING_PARTY),
    ContractType.LEASE: (PartyPosition.TENANT, PartyPosition.LANDLORD),
    ContractType.SERVICE: (PartyPosition.SERVICE_PROVIDER, PartyPosition.CLIENT),
    ContractType.FREELANCE: (PartyPosition.SERVICE_PROVIDER, PartyPosition.CLIENT),
    ContractType.VENDOR: (PartyPosition.SERVICE_PROVIDER, PartyPosition.CLIENT),
    ContractType.SAAS: (PartyPosition.CLIENT, PartyPosition.SERVICE_PROVIDER),
    ContractType.LOAN: (PartyPosition.BORROWER, PartyPosition.LENDER),
}

# The side that, as a matter of ordinary commercial reality, drafts less of the
# contract and accepts more of it. This does not decide whether a clause is a red
# flag -- the rule's own `harms` list does that -- but it does raise severity,
# because the same clause is harder to negotiate away from this side.
WEAKER_POSITIONS = frozenset(
    {
        PartyPosition.EMPLOYEE,
        PartyPosition.TENANT,
        PartyPosition.BORROWER,
        PartyPosition.SERVICE_PROVIDER,
        PartyPosition.RECEIVING_PARTY,
    }
)


class ClauseCategory(str, Enum):
    PARTIES = "PARTIES"
    DEFINITIONS = "DEFINITIONS"
    TERM = "TERM"
    TERMINATION = "TERMINATION"
    NOTICE_PERIOD = "NOTICE_PERIOD"
    PAYMENT = "PAYMENT"
    SALARY = "SALARY"
    RENT = "RENT"
    SECURITY_DEPOSIT = "SECURITY_DEPOSIT"
    INDEMNITY = "INDEMNITY"
    LIABILITY = "LIABILITY"
    LIQUIDATED_DAMAGES = "LIQUIDATED_DAMAGES"
    CONFIDENTIALITY = "CONFIDENTIALITY"
    NON_COMPETE = "NON_COMPETE"
    NON_SOLICIT = "NON_SOLICIT"
    IP_ASSIGNMENT = "IP_ASSIGNMENT"
    DISPUTE_RESOLUTION = "DISPUTE_RESOLUTION"
    GOVERNING_LAW = "GOVERNING_LAW"
    FORCE_MAJEURE = "FORCE_MAJEURE"
    RENEWAL = "RENEWAL"
    AMENDMENT = "AMENDMENT"
    ASSIGNMENT = "ASSIGNMENT"
    DATA_PROTECTION = "DATA_PROTECTION"
    WARRANTY = "WARRANTY"
    PROBATION = "PROBATION"
    WORKING_HOURS = "WORKING_HOURS"
    LEAVE = "LEAVE"
    BOND = "BOND"
    MAINTENANCE = "MAINTENANCE"
    LOCK_IN = "LOCK_IN"
    OTHER = "OTHER"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


SEVERITY_ORDER: Dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.INFO: 0,
}


class Citation(BaseModel):
    """A statutory provision bearing on a clause.

    Rules carry their citations directly rather than relying on retrieval to
    rediscover them. A handful of the provisions that matter most here live
    inside very large sections -- the definition of an unfair contract sits at
    roughly character 20,000 of CPA s.2 -- which a 512-token embedding window
    will never surface on its own.
    """

    act: str = Field(..., description="Act name exactly as indexed in the corpus")
    section_number: str = Field(..., description="e.g. Section 27")
    note: str = Field(..., description="Why this provision bears on the clause")


class Clause(BaseModel):
    index: int = Field(..., description="0-based position in the document")
    number: Optional[str] = Field(None, description="Clause number as printed, e.g. 4.2")
    heading: Optional[str] = Field(None, description="Clause heading as printed")
    text: str = Field(..., description="Verbatim clause text from the document")
    start_offset: int = Field(..., description="Start offset into the normalized document text")
    end_offset: int = Field(..., description="End offset into the normalized document text")
    body_offset: int = Field(
        ...,
        description=(
            "Offset into the normalized document text where the clause body begins, "
            "past its number and heading. Red-flag rules match from here so a quote "
            "reads as the obligation rather than as the heading above it."
        ),
    )
    category: ClauseCategory = Field(default=ClauseCategory.OTHER)
    category_matched_terms: List[str] = Field(
        default=[],
        description="Terms that drove the deterministic classification, so the label is auditable",
    )
    page: Optional[int] = Field(None, description="1-based source page, where the format carries one")


class RedFlagFinding(BaseModel):
    rule_id: str
    title: str
    severity: Severity
    clause_index: Optional[int] = None
    clause_number: Optional[str] = None
    matched_quote: str = Field(
        ..., description="Verbatim span from the document that triggered the rule"
    )
    match_start: int = Field(..., description="Offset of matched_quote in the normalized text")
    match_end: int
    harms: List[PartyPosition] = Field(
        default=[], description="Positions this clause works against"
    )
    citations: List[Citation] = Field(default=[])
    plain_summary: str = Field(..., description="What the clause does, in plain words")
    why_it_matters: str = Field(..., description="The practical consequence for the reviewing party")
    detector: str = Field(
        default="rule",
        description="Provenance: 'rule' for a deterministic match, 'llm' for a model-proposed finding",
    )
    read_confidence: Optional[float] = Field(
        None,
        description=(
            "Lowest OCR confidence across the quoted words, when the document was "
            "read from an image. None for text lifted from the file."
        ),
    )
    evidence_image: Optional[str] = Field(
        None,
        description=(
            "PNG data URI of the region of the scan this quote was read from. "
            "Textual grounding is circular once the text is a transcription, so "
            "the reader is shown the paper instead of being asked to trust it."
        ),
    )


class MissingClauseFinding(BaseModel):
    """A protection the contract does not contain.

    Absence is frequently the larger risk and is invisible to any clause-by-clause
    pass, so it is detected against a per-type checklist rather than from the text.
    """

    category: ClauseCategory
    severity: Severity
    title: str
    why_it_matters: str
    citations: List[Citation] = Field(default=[])


class ParsedDocument(BaseModel):
    """Extraction output, before any clause or legal analysis."""

    filename: str
    media_type: str
    text: str = Field(..., description="Normalized full text; all offsets index into this")
    source: str = Field(
        default="text_layer",
        description=(
            "How the text was obtained: 'text_layer' lifts it verbatim from the "
            "file, 'ocr' is our reading of an image. The distinction matters: a "
            "quote can verify against an OCR transcription that misread the paper."
        ),
    )
    ocr_confidence: Optional[float] = Field(
        None, description="Mean per-word OCR confidence, 0-100, when source is 'ocr'"
    )
    ocr_basis: Optional[Dict[str, Any]] = Field(
        None, description="Per-page confidences, word counts and unreadable pages"
    )
    ocr_words: List[Dict[str, Any]] = Field(
        default=[],
        description=(
            "Compact per-word map: character span, page and pixel box. This is "
            "what lets a finding be shown against the region of the scan it was "
            "read from, rather than only as text we transcribed."
        ),
    )
    page_count: Optional[int] = None
    page_offsets: List[int] = Field(
        default=[],
        description="Start offset of each page in `text`, for formats that paginate",
    )
    char_count: int = 0
    extraction_warnings: List[str] = Field(
        default=[],
        description="Non-fatal extraction problems the reviewer must be told about",
    )
