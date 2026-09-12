"""Confidence estimation for a compiled procurement review.

The third sibling of `src/core/confidence.py` and `src/core/contract_confidence.py`,
built on the same commitments: every component is measured from a signal the
pipeline actually produced, a stage that silently degraded cannot report full
confidence, the result is bounded, and the full basis is emitted so a number can
always be argued with. The cap values that mean the same thing as theirs are
deliberately identical, so the three estimators speak one language.

What differs is what there is to be uncertain about:

* **Evidence.** A finding whose field path no longer resolves, or whose stated
  comparison does not hold, is this pipeline's hallucination signal -- what an
  ungrounded quote is to contract review. Enforced as a cap, because a weighted
  mean cannot express it.
* **Data completeness.** The dominant uncertainty here is not what the system got
  wrong but what it was never shown. Measured against what the checks that ran
  actually needed, weighted by how serious those checks were: not knowing the
  vendor's MSME status costs more than not knowing the budget line.
* **Policy authority.** A review enforcing rules nobody has ratified is not
  measuring the customer's policy, it is measuring a model's reading of it.
* **Provenance.** As in contract review: deterministic outcomes are reproducible
  and carry hand-checked citations; model prose is neither.

One cap crosses a pipeline boundary. Where any finding rests on the purchase
order document, the procurement score cannot exceed the confidence of the
contract sub-review that read it -- a review resting on a document that segmented
by paragraph fallback has inherited that uncertainty whether or not it shows.

This is an estimate, not a calibrated probability. Nothing here is fitted against
labelled reviews.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.schemas.contract import SEVERITY_ORDER, Severity
from src.schemas.procurement import CheckStatus, MsmeStatus

EPSILON = 1e-6

COMPONENT_WEIGHTS = {
    "evidence": 0.30,
    "data_completeness": 0.25,
    "policy_authority": 0.20,
    "provenance": 0.15,
    "profile": 0.10,
}

# Shared with the other two estimators, and kept numerically equal on purpose.
DEGRADED_LLM_CAP = 0.60
DEGRADED_RERANKER_CAP = 0.75

# The sibling of UNGROUNDED_CAP: a finding that cannot be re-derived from the
# event is the strongest available signal that something is wrong.
UNVERIFIED_EVIDENCE_CAP = 0.50

# Lower than any cap in the other two pipelines, and deliberately so. A review
# enforcing unratified rules is not reporting on the customer's policy at all.
UNRATIFIED_POLICY_CAP = 0.45

# More than a third of the material checks could not be performed. The sibling of
# UNKNOWN_POSITION_CAP: the review does not know enough to be read as a result.
UNDETERMINED_HEAVY_CAP = 0.65
UNDETERMINED_HEAVY_FRACTION = 1 / 3

# MSME status decides whether the most consequential statutory check can run at
# all, and its absence is invisible in the output unless it is priced in here.
NO_MSME_STATUS_CAP = 0.70

# A review with no policy at all checked statute and nothing else. It cannot say
# whether the award followed the company's own process, because it was never told
# what that process is.
#
# This cap was found by measurement, not reasoning. Dropping `policy_authority`
# and renormalising over the remaining four components made a statute-only review
# score 0.889 -- *higher* than a full review at 0.817 -- because the component it
# dropped was the only one scoring below 1.0. The estimator was rewarding a
# review for not having looked. Observed quality under this condition is 0.667
# (scripts/calibrate_procurement_confidence.py), which the cap sits within 0.05
# of. The same failure the contract estimator hit with PARAGRAPH_FALLBACK_CAP: a
# weighted mean cannot express a component's absence, only its value.
STATUTE_ONLY_CAP = 0.70

MAX_CONFIDENCE = 0.95
MIN_CONFIDENCE = 0.05

NO_OUTCOMES_PROVENANCE = 0.60
MIN_PROFILE = 0.30
MIN_COMPLETENESS = 0.10


@dataclass
class ProcurementConfidenceReport:
    score: float
    components: Dict[str, float] = field(default_factory=dict)
    caps_applied: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "components": {k: round(v, 3) for k, v in self.components.items()},
            "caps_applied": self.caps_applied,
            "notes": self.notes,
            "detail": self.detail,
        }


def evidence_quality(outcomes: Sequence[Any], unverified_keys: Sequence[str]) -> Tuple[float, int]:
    """Fraction of findings whose evidence re-derived from the event."""
    asserted = [
        o for o in outcomes
        if o.status in {CheckStatus.BREACH, CheckStatus.INDICATOR, CheckStatus.PASS}
    ]
    if not asserted:
        return 1.0, 0
    failed = len(set(unverified_keys))
    verified = max(0, len(asserted) - failed)
    return verified / len(asserted), failed


def data_completeness(outcomes: Sequence[Any]) -> float:
    """How much of what the checks needed was actually supplied.

    Weighted by severity rather than counted flat. A review that could not check
    the budget line is in better shape than one that could not check whether the
    award went to a related party, and a flat count says they are the same.

    Deliberately NOT a pass rate. A review where every check passed because
    nothing was supplied must score badly, and a pass rate would score it
    perfectly -- which is the exact failure this whole feature is built against.
    """
    material = [o for o in outcomes if o.status != CheckStatus.NOT_APPLICABLE]
    if not material:
        return MIN_COMPLETENESS
    total = sum(SEVERITY_ORDER[o.severity] + 1 for o in material)
    lost = sum(
        SEVERITY_ORDER[o.severity] + 1
        for o in material
        if o.status in {CheckStatus.UNDETERMINED, CheckStatus.NOT_EVALUATED}
    )
    return max(MIN_COMPLETENESS, (total - lost) / total)


def policy_authority(
    ratified_count: int,
    total_rules: int,
    provisional_findings: int,
    covered_kinds: int = 0,
    available_kinds: int = 0,
) -> Optional[float]:
    """How far the policy in force is confirmed, and how much of it there is.

    Two things, because both bear on the same question and neither is sufficient.
    *Ratification* is whether a person confirmed these rules. *Breadth* is how
    much of the checkable surface the policy actually covers: a customer who has
    ratified three rules out of fourteen available controls has a review that
    looked at three things, and a review that looked at three things should not
    report the same confidence as one that looked at twelve. Saying so is the
    honest reading -- the alternative lets a narrow policy score as a thorough one
    purely because the little it checked came back clean.

    Returns None for a statute-only review, which drops the component and
    renormalises the remaining weights. Scoring it 1.0 would reward a review that
    never looked at the customer's policy; scoring it 0.0 would punish one that
    correctly had none to look at.
    """
    if total_rules == 0:
        return None
    if provisional_findings:
        return 0.25
    ratification = max(0.1, ratified_count / total_rules)
    if not available_kinds:
        return ratification
    breadth = min(1.0, covered_kinds / available_kinds)
    return max(0.1, ratification * (0.4 + 0.6 * breadth))


def provenance(outcomes: Sequence[Any]) -> float:
    """How much of the review rests on deterministic checks rather than a model."""
    if not outcomes:
        return NO_OUTCOMES_PROVENANCE
    rule = sum(1 for o in outcomes if getattr(o, "detector", "rule") == "rule")
    return 0.55 + 0.45 * (rule / len(outcomes))


def profile_quality(side: str, category: Optional[str], msme_known: bool) -> float:
    """How well the review knows what it is looking at, and for whom."""
    score = MIN_PROFILE
    if side and side != "UNKNOWN":
        score += 0.35
    if category:
        score += 0.15
    if msme_known:
        score += 0.20
    return min(1.0, score)


def weighted_geometric_mean(components: Dict[str, float], weights: Dict[str, float]) -> float:
    total_weight = sum(weights.get(k, 0.0) for k in components)
    if total_weight <= 0:
        return 0.0
    accumulated = sum(
        weights.get(name, 0.0) * math.log(max(value, EPSILON))
        for name, value in components.items()
    )
    return math.exp(accumulated / total_weight)


def _apply_caps(
    score: float,
    llm_available: bool,
    reranker_available: bool,
    extra: Sequence[Tuple[float, str]] = (),
) -> Tuple[float, List[str]]:
    caps: List[Tuple[float, str]] = []
    if not llm_available:
        caps.append((DEGRADED_LLM_CAP, f"llm_fallback<={DEGRADED_LLM_CAP:.2f}"))
    if not reranker_available:
        caps.append((DEGRADED_RERANKER_CAP, f"reranker_fallback<={DEGRADED_RERANKER_CAP:.2f}"))
    caps.extend(extra)

    applied: List[str] = []
    for value, label in caps:
        if score > value:
            score = value
            applied.append(label)
    return max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, score)), applied


def estimate_procurement_confidence(
    *,
    outcomes: Sequence[Any],
    unverified_keys: Sequence[str] = (),
    side: str = "UNKNOWN",
    category: Optional[str] = None,
    msme_status: MsmeStatus = MsmeStatus.UNKNOWN,
    ratified_rule_count: int = 0,
    total_rule_count: int = 0,
    covered_check_kinds: int = 0,
    available_check_kinds: int = 0,
    po_review_confidence: Optional[float] = None,
    po_document_supplied: bool = False,
    llm_available: bool = True,
    reranker_available: bool = True,
    degraded_nodes: Sequence[str] = (),
) -> ProcurementConfidenceReport:
    provisional = sum(1 for o in outcomes if getattr(o, "provisional", False))
    evidence, unverified = evidence_quality(outcomes, unverified_keys)
    msme_known = msme_status != MsmeStatus.UNKNOWN

    components: Dict[str, float] = {
        "evidence": evidence,
        "data_completeness": data_completeness(outcomes),
        "provenance": provenance(outcomes),
        "profile": profile_quality(side, category, msme_known),
    }
    authority = policy_authority(
        ratified_rule_count, total_rule_count, provisional,
        covered_check_kinds, available_check_kinds,
    )
    if authority is not None:
        components["policy_authority"] = authority

    score = weighted_geometric_mean(components, COMPONENT_WEIGHTS)

    material = [
        o for o in outcomes
        if o.status != CheckStatus.NOT_APPLICABLE
        and SEVERITY_ORDER[o.severity] >= SEVERITY_ORDER[Severity.MEDIUM]
    ]
    undetermined = [o for o in material if o.status == CheckStatus.UNDETERMINED]
    gap_fraction = len(undetermined) / len(material) if material else 0.0

    extra: List[Tuple[float, str]] = []
    if unverified:
        extra.append((UNVERIFIED_EVIDENCE_CAP, f"unverified_evidence<={UNVERIFIED_EVIDENCE_CAP:.2f}"))
    if provisional:
        extra.append((UNRATIFIED_POLICY_CAP, f"unratified_policy<={UNRATIFIED_POLICY_CAP:.2f}"))
    if gap_fraction > UNDETERMINED_HEAVY_FRACTION:
        extra.append((UNDETERMINED_HEAVY_CAP, f"undetermined_heavy<={UNDETERMINED_HEAVY_CAP:.2f}"))
    if not msme_known:
        extra.append((NO_MSME_STATUS_CAP, f"msme_status_unknown<={NO_MSME_STATUS_CAP:.2f}"))
    if authority is None:
        extra.append((STATUTE_ONLY_CAP, f"statute_only<={STATUTE_ONLY_CAP:.2f}"))
    if po_document_supplied and po_review_confidence is not None:
        # The cap that crosses a pipeline boundary. A procurement review resting
        # on a purchase order the contract pipeline read at 0.70 has inherited
        # that uncertainty, and burying it inside a nested payload would let a
        # 0.91 headline sit on top of a 0.70 document read.
        extra.append((po_review_confidence, f"po_subreview<={po_review_confidence:.2f}"))

    score, caps = _apply_caps(score, llm_available, reranker_available, extra)

    notes: List[str] = []
    if unverified:
        notes.append(
            f"{unverified} finding(s) could not be re-derived from the event data supplied "
            "and were dropped from the review."
        )
    if provisional:
        notes.append(
            f"{provisional} finding(s) come from policy rules nobody has ratified. They are "
            "this system's reading of the policy document, not the customer's confirmation "
            "of it, and are excluded from every count."
        )
    if gap_fraction > UNDETERMINED_HEAVY_FRACTION:
        notes.append(
            f"{len(undetermined)} of {len(material)} material checks could not be performed "
            "for want of data. This review has seen too little to be read as a result."
        )
    if not msme_known:
        notes.append(
            "The awarded vendor's MSME status was not supplied, so the MSMED payment "
            "provisions could not be applied. That is a gap, not a clean bill of health."
        )
    if po_document_supplied and po_review_confidence is not None:
        notes.append(
            f"Findings about the purchase order's own terms rest on a contract review that "
            f"scored {po_review_confidence:.2f}; this review cannot be more confident than that."
        )
    if authority is None:
        notes.append(
            "No procurement policy was supplied, so this review checked statute only. "
            "It cannot say whether the award followed your own process, because it was "
            "never told what that process is."
        )
    if not po_document_supplied:
        notes.append(
            "No purchase order document was supplied, so its terms were not reviewed."
        )
    if not llm_available:
        notes.append("LLM unavailable; deterministic checks produced this review.")
    if not reranker_available:
        notes.append("Cross-encoder unavailable; provisions ranked by RRF position only.")
    for node in degraded_nodes:
        notes.append(f"Partially degraded: {node}.")

    counts: Dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1

    return ProcurementConfidenceReport(
        score=round(score, 2),
        components=components,
        caps_applied=caps,
        notes=notes,
        detail={
            "checks_run": len(outcomes),
            "status_counts": counts,
            "material_checks": len(material),
            "material_gaps": len(undetermined),
            "unverified_findings": unverified,
            "provisional_findings": provisional,
            "ratified_rules": ratified_rule_count,
            "total_rules": total_rule_count,
            "covered_check_kinds": covered_check_kinds,
            "available_check_kinds": available_check_kinds,
            "po_review_confidence": po_review_confidence,
            "statute_only": authority is None,
        },
    )


__all__ = [
    "COMPONENT_WEIGHTS",
    "DEGRADED_LLM_CAP",
    "DEGRADED_RERANKER_CAP",
    "NO_MSME_STATUS_CAP",
    "STATUTE_ONLY_CAP",
    "ProcurementConfidenceReport",
    "UNDETERMINED_HEAVY_CAP",
    "UNRATIFIED_POLICY_CAP",
    "UNVERIFIED_EVIDENCE_CAP",
    "data_completeness",
    "estimate_procurement_confidence",
    "evidence_quality",
    "policy_authority",
    "profile_quality",
    "provenance",
    "weighted_geometric_mean",
]
