"""The response envelope for a procurement review.

Mirrors `ContractReviewResponse` field for field wherever the meaning carries
over -- same `status` vocabulary, same `confidence_basis`, same `degraded_nodes`,
same trailing disclaimer. That is not tidiness: the Streamlit renderers and the
PDF builder key off these names, and a divergent shape would mean forking both.

Three fields have no contract-review equivalent, and each exists to stop a
particular misreading:

* `undetermined_checks` is reported separately from `findings` so that "we could
  not check this" is never read as "this is fine".
* `indicators` is separate from `findings` so a statistical pattern in a bid tab
  is never counted alongside a breach of a section.
* `checks_run` lists everything, passes included, so a reader can tell a review
  that looked and found nothing from one that never looked.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.schemas.procurement import (
    MissingProvisionFinding,
    OverallStatus,
    ProcurementFinding,
    ProcurementSide,
)


class CheckRun(BaseModel):
    """One line of the audit trail: what was checked and how it came out."""

    check_id: str
    title: str
    status: str
    severity: str
    family: str
    subject_ref: Optional[str] = None
    source: str = "STATUTE"
    policy_rule_id: Optional[str] = None


class AwardReviewResponse(BaseModel):
    review_id: Optional[str] = Field(
        None, description="Handle for this review; required to fetch or delete it"
    )
    status: str = Field(..., description="SUCCESS, PARTIAL_SUCCESS, or NEEDS_CLARIFICATION")
    event_id: str = ""
    side: ProcurementSide = ProcurementSide.UNKNOWN
    category: Optional[str] = None

    policy_id: Optional[str] = None
    policy_version: Optional[int] = None
    policy_status: Optional[str] = None

    overall_status: OverallStatus = OverallStatus.NO_BREACH_FOUND_WITH_GAPS
    overall_risk: str = Field(
        default="UNKNOWN", description="CRITICAL, HIGH, MEDIUM, LOW, or UNKNOWN"
    )
    risk_counts: Dict[str, int] = Field(default={})
    status_counts: Dict[str, int] = Field(default={})

    confidence_score: float = Field(..., ge=0.0, le=1.0)
    confidence_basis: Optional[Dict[str, Any]] = Field(
        None, description="Auditable breakdown: components, caps applied, and why"
    )

    findings: List[ProcurementFinding] = Field(
        default=[], description="Breaches of policy or statute, worst first"
    )
    indicators: List[ProcurementFinding] = Field(
        default=[],
        description=(
            "Patterns warranting enquiry. Kept out of `findings` so nothing downstream "
            "can count a statistical signal as a breach."
        ),
    )
    undetermined_checks: List[ProcurementFinding] = Field(
        default=[],
        description=(
            "Checks that could not be performed, each naming what would resolve it. "
            "Separate from `findings` so a gap is never read as a pass."
        ),
    )
    checks_run: List[CheckRun] = Field(
        default=[],
        description="Every check and its outcome, passes included, so silence is legible",
    )
    missing_provisions: List[MissingProvisionFinding] = Field(default=[])
    remediations: List[Dict[str, Any]] = Field(
        default=[], description="What to do about each finding, worst first"
    )

    narrative: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "The review written up for someone about to release the order. Carries a "
            "`source` of 'llm' or 'rule' so a reader can tell which produced it."
        ),
    )
    statutory_context: Dict[str, List[Dict[str, Any]]] = Field(
        default={},
        description="The text of the sections the findings cite, keyed by check_id",
    )

    po_review: Optional[Dict[str, Any]] = Field(
        None, description="The contract review of the purchase order document, where one was supplied"
    )
    po_confidence: Optional[float] = None

    dropped_findings: List[str] = Field(
        default=[],
        description=(
            "Findings discarded because their evidence could not be re-derived from the "
            "event. Named rather than silently removed, since a disappearing finding is "
            "itself information."
        ),
    )
    degraded_nodes: List[str] = Field(default=[])
    clarification_questions: List[str] = Field(default=[])

    disclaimer: str = (
        "This is a source-grounded review of the sourcing data and documents supplied, "
        "not legal advice and not an audit opinion. Findings about statute cite the "
        "provision they rest on; findings about policy rest on rules your organisation "
        "ratified. Checks reported as undetermined were not performed at all, and must "
        "not be read as having passed. Patterns reported as indicators are grounds for "
        "asking a question, never a conclusion that anyone acted improperly."
    )


__all__ = ["AwardReviewResponse", "CheckRun"]


# ---------------------------------------------------------------------------
# The written summary
# ---------------------------------------------------------------------------

class FindingNote(BaseModel):
    """A sentence of context on one finding.

    Prose only. It cannot carry a status, a severity or a citation, because the
    model is not permitted to change any of them -- and a field it cannot write
    is a stronger guarantee than an instruction not to.
    """

    check_id: str = Field(..., description="Which finding this note is about")
    note: str = Field(..., description="One or two sentences of context, in plain words")


class AwardNarrative(BaseModel):
    """The review, written for someone about to release a purchase order.

    The model's entire contribution to this pipeline. It restates what the
    deterministic checks found and what the statute says; it does not decide that
    anything is a breach, and it has no field in which to say so.
    """

    headline: str = Field(
        ..., description="One sentence: what this review found, for someone with 30 seconds"
    )
    what_to_do_first: str = Field(
        ..., description="The single most important thing to do before releasing the order"
    )
    notes: List[FindingNote] = Field(
        default=[], description="Per-finding context, at most one entry per check"
    )
