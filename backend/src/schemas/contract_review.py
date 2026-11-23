"""Schemas for the contract-review pipeline's model-facing and response payloads.

Two rules shape everything here.

**The model never supplies offsets.** An LLM asked for character positions
invents them confidently. Model findings therefore carry only a verbatim
`quote`, which the pipeline locates in the document itself; a quote that cannot
be located is discarded rather than repaired. This keeps the guarantee the
deterministic rules give by construction -- every finding points at real text.

**The model never supplies legal conclusions.** Asked directly whether an Indian
non-compete is enforceable, `llama-3.3-70b-versatile` answers that it "may be
unenforceable in some jurisdictions" -- the US reasonableness framing, which is
wrong here: Contract Act s.27 voids it outright with no reasonableness test. So
statutory consequences come from the rules and the retrieved sections, and the
model's job is to explain what those found, in plain words.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.schemas.contract import (
    Citation,
    ClauseCategory,
    ContractType,
    MissingClauseFinding,
    PartyPosition,
    RedFlagFinding,
    Severity,
)


# ---------------------------------------------------------------------------
# Profiler
# ---------------------------------------------------------------------------

class ContractProfile(BaseModel):
    contract_type: ContractType = Field(
        default=ContractType.UNKNOWN, description="Best-supported contract type"
    )
    contract_type_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="How clearly the document states its own type"
    )
    party_names: Dict[str, str] = Field(
        default={},
        description="Role label as printed in the contract -> the party's name, e.g. {'the Company': 'Northwind Technologies Private Limited'}",
    )
    inferred_position: PartyPosition = Field(
        default=PartyPosition.UNKNOWN,
        description="Which side the reviewing user appears to be on, if the document makes it clear",
    )
    governing_law: Optional[str] = Field(None, description="Stated governing law, verbatim")
    stated_term: Optional[str] = Field(None, description="Stated duration or term, verbatim")
    notes: List[str] = Field(default=[], description="Anything notable about the document as a whole")


# ---------------------------------------------------------------------------
# Clause classification
# ---------------------------------------------------------------------------

class ClauseLabel(BaseModel):
    clause_index: int = Field(..., description="The clause's index, exactly as supplied")
    category: ClauseCategory = Field(..., description="Best-fitting category")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="", description="Short justification, grounded in the clause text")


class ClauseLabelBatch(BaseModel):
    labels: List[ClauseLabel] = Field(default=[], description="One entry per supplied clause")


# ---------------------------------------------------------------------------
# Query building
# ---------------------------------------------------------------------------

class ClauseQuery(BaseModel):
    clause_index: int
    dense_query: str = Field(
        ...,
        description="Statutory-register paraphrase for semantic search, e.g. 'agreement in restraint of trade void'",
    )
    sparse_query: str = Field(
        ...,
        description="Keyword terms as they appear in the statute book, e.g. 'restraint trade void lawful profession'",
    )


class ClauseQueryBatch(BaseModel):
    queries: List[ClauseQuery] = Field(default=[])


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------

class ClauseExplanation(BaseModel):
    clause_index: int
    plain_english: str = Field(
        ..., description="What this clause does, in plain words, addressed to the reviewing party"
    )
    obligations: List[str] = Field(
        default=[], description="What the reviewing party must actually do under this clause"
    )
    watch_outs: List[str] = Field(
        default=[], description="Practical consequences worth noticing. Not legal conclusions."
    )


class ClauseExplanationBatch(BaseModel):
    explanations: List[ClauseExplanation] = Field(default=[])


# ---------------------------------------------------------------------------
# Model-proposed red flags
# ---------------------------------------------------------------------------

class LlmRedFlag(BaseModel):
    """A concern the deterministic rules did not encode.

    `quote` must be copied verbatim from the clause. The pipeline locates it in
    the document to derive offsets; an unlocatable quote is dropped, because it
    is indistinguishable from an invented one.
    """

    clause_index: int
    title: str = Field(..., description="Short name for the concern")
    quote: str = Field(
        ...,
        description="The exact words from the clause that create the concern, copied character for character",
    )
    severity: Severity = Field(default=Severity.MEDIUM)
    plain_summary: str = Field(..., description="What the clause does, in plain words")
    why_it_matters: str = Field(..., description="The practical consequence for the reviewing party")


class LlmRedFlagBatch(BaseModel):
    findings: List[LlmRedFlag] = Field(default=[])


# ---------------------------------------------------------------------------
# Consistency
# ---------------------------------------------------------------------------

class ConsistencyIssue(BaseModel):
    kind: str = Field(
        ..., description="CONFLICT, UNDEFINED_TERM, MISSING_ANNEXURE, or BROKEN_CROSS_REFERENCE"
    )
    description: str
    clause_indices: List[int] = Field(default=[], description="The clauses involved")
    quotes: List[str] = Field(default=[], description="Verbatim supporting text from each clause")
    severity: Severity = Field(default=Severity.MEDIUM)


class ConsistencyReport(BaseModel):
    issues: List[ConsistencyIssue] = Field(default=[])


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------

class GroundingVerdict(BaseModel):
    audit_status: str = Field(..., description="'PASS' or 'FAIL'")
    audit_reasoning: str
    correction_feedback: Optional[str] = Field(
        None, description="What the analyst must fix. Null if PASS."
    )


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class ClauseReview(BaseModel):
    """One clause as presented to the reader."""

    index: int
    number: Optional[str] = None
    heading: Optional[str] = None
    category: ClauseCategory
    tier: str = Field(..., description="HOT, WARM or COLD -- how much analysis this clause received")
    text: str
    start_offset: int
    end_offset: int
    page: Optional[int] = None
    plain_english: str = Field(default="")
    obligations: List[str] = Field(default=[])
    watch_outs: List[str] = Field(default=[])
    findings: List[RedFlagFinding] = Field(default=[])
    citations: List[Citation] = Field(default=[])


class ContractReviewResponse(BaseModel):
    contract_id: Optional[str] = Field(
        None,
        description=(
            "Handle for this review. Required to fetch it again or to delete it, "
            "so it must survive serialization."
        ),
    )
    status: str = Field(..., description="SUCCESS, PARTIAL_SUCCESS, or NEEDS_CLARIFICATION")
    contract_type: ContractType = Field(default=ContractType.UNKNOWN)
    position: PartyPosition = Field(default=PartyPosition.UNKNOWN)
    position_source: str = Field(
        default="UNKNOWN", description="USER_DECLARED, LLM_INFERRED, or UNKNOWN"
    )
    party_names: Dict[str, str] = Field(default={})
    governing_law: Optional[str] = None

    confidence_score: float = Field(..., ge=0.0, le=1.0)
    confidence_basis: Optional[Dict[str, Any]] = Field(
        None, description="Auditable breakdown: components, caps applied, and why"
    )

    overall_risk: str = Field(
        default="UNKNOWN", description="CRITICAL, HIGH, MEDIUM, LOW, or UNKNOWN"
    )
    risk_counts: Dict[str, int] = Field(
        default={}, description="Findings by severity, e.g. {'CRITICAL': 2, 'HIGH': 3}"
    )

    clause_count: int = 0
    analysed_clause_count: int = Field(
        default=0, description="Clauses that received model analysis, as opposed to rule-only treatment"
    )
    clauses: List[ClauseReview] = Field(default=[])
    findings: List[RedFlagFinding] = Field(default=[])
    missing_clauses: List[MissingClauseFinding] = Field(default=[])
    consistency_issues: List[Dict[str, Any]] = Field(default=[])
    redlines: List[Dict[str, Any]] = Field(
        default=[], description="What to ask for on each flagged term, worst first"
    )

    source: str = Field(
        default="text_layer",
        description=(
            "'text_layer' when the words were lifted from the file, 'ocr' when "
            "they are our reading of an image. Findings from an OCR review carry "
            "a crop of the scan, because a quote checked against a transcription "
            "proves only that the transcription is self-consistent."
        ),
    )
    ocr_confidence: Optional[float] = None
    ocr_basis: Optional[Dict[str, Any]] = None

    extraction_warnings: List[str] = Field(default=[])
    degraded_nodes: List[str] = Field(
        default=[], description="Stages that fell back to their rule-based engine"
    )
    clarification_questions: List[str] = Field(default=[])

    disclaimer: str = (
        "This is source-grounded legal information about the document you uploaded, "
        "not legal advice, and not a recommendation to sign or refuse to sign. "
        "A finding here is a prompt to ask a question, not a conclusion about your "
        "rights. Have a lawyer review anything you are about to be bound by."
    )


# ---------------------------------------------------------------------------
# Question answering
# ---------------------------------------------------------------------------

class ContractAnswer(BaseModel):
    """An answer about the user's own contract.

    `cited_clauses` is not decoration. An answer about a contract that does not
    say which clause it rests on cannot be checked, and the reader has no way to
    tell a real term from an invented one.
    """

    answer: str = Field(..., description="The answer, in plain words, addressed to the reader")
    cited_clauses: List[int] = Field(
        default=[], description="clause_index values the answer is drawn from"
    )
    answered_from_contract: bool = Field(
        default=True,
        description="False when the contract does not address the question at all",
    )


class ContractAnswerResponse(BaseModel):
    contract_id: str
    question: str
    answer: str
    answered_from_contract: bool = True
    cited_clauses: List[Dict[str, Any]] = Field(
        default=[], description="The clauses the answer rests on, with their text"
    )
    statutory_context: List[Citation] = Field(
        default=[], description="Provisions bearing on the clauses cited"
    )
    degraded: bool = Field(
        default=False, description="True when the answer came from the rule-based engine"
    )
    disclaimer: str = (
        "This answers only what your document says. It is legal information about "
        "that document, not legal advice."
    )


# ---------------------------------------------------------------------------
# Redlines
# ---------------------------------------------------------------------------

class Redline(BaseModel):
    """What to ask for on a clause the review flagged.

    A negotiation ask, not drafting to paste unread: `ask` is the substantive
    change, `suggested_wording` is a starting point for the conversation.
    """

    rule_id: str
    clause_index: Optional[int] = None
    clause_number: Optional[str] = None
    title: str
    severity: Severity
    ask: str = Field(..., description="What to ask the other side to change, in plain words")
    suggested_wording: Optional[str] = Field(
        None, description="Illustrative replacement language, to be reviewed by a lawyer"
    )
    fallback: Optional[str] = Field(
        None, description="What to settle for if the full ask is refused"
    )
    source: str = Field(default="rule", description="'rule' or 'llm'")
