"""Confidence estimation for a compiled contract review.

The sibling of `src/core/confidence.py`, and built on the same commitments:
every component is measured from a signal the pipeline actually produced, never
from a constant; a stage that silently degraded cannot report full confidence;
the result is bounded, and the full basis is emitted so a number can always be
argued with.

The signals differ, because contract review measures different things:

* **Quote grounding.** A finding quoting text that is not in the document is the
  strongest hallucination signal available here, exactly as a section the
  retriever never returned is in the criminal pipeline. It is enforced as a cap,
  because the weighted mean alone cannot express it.
* **Coverage.** A review that analysed 6 of 80 clauses is not wrong, but it has
  seen much less of the contract than one that analysed 40.
* **Provenance.** A deterministic rule finding is reproducible and carries a
  hand-checked citation; a model finding is neither. A review resting mostly on
  model findings is a weaker artefact than one resting on rules.
* **Segmentation.** Falling back to paragraph splitting means clause boundaries
  are guesses, and every offset downstream inherits that.

This is an estimate, not a calibrated probability. Nothing here is fitted
against labelled reviews.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

EPSILON = 1e-6

COMPONENT_WEIGHTS = {
    "segmentation": 0.18,
    "coverage": 0.18,
    "grounding": 0.32,
    "provenance": 0.13,
    "profile": 0.09,
    # How well the text was read off the page. 1.0 whenever it was lifted
    # verbatim from the file, which is every case but a scan.
    "text_fidelity": 0.10,
}

# Degradation caps, matching src/core/confidence.py's values so the two
# estimators speak the same language.
DEGRADED_LLM_CAP = 0.60
DEGRADED_RERANKER_CAP = 0.75
UNGROUNDED_CAP = 0.50
# A review that cannot say which side it is for cannot assign severity to
# anything: `_severity_for` returns the base severity for UNKNOWN, so every
# asymmetric clause is scored as though the reader were neither party.
UNKNOWN_POSITION_CAP = 0.65
# When nothing in the document is numbered, every clause boundary is a guess and
# each one mis-attributes whatever it splits. Measured across the labelled set
# (scripts/calibrate_confidence.py), finding quality falls to about 0.45 under
# paragraph fallback while the weighted mean alone still reported 0.81 -- the
# segmentation component carries only 0.20 of the weight, so it cannot express
# this on its own.
PARAGRAPH_FALLBACK_CAP = 0.70
# Text read off an image is a transcription, not the document. Every other path
# makes "this finding quotes the contract" an exact claim; here the quote is
# checked against our own reading, so verification is circular and cannot rule
# out a misread. The danger is not the words OCR flags as uncertain -- those are
# reported -- but the ones it gets confidently wrong, most often a digit in an
# amount. The cap therefore applies however clean the scan looks.
OCR_SOURCE_CAP = 0.75
# ...and it tightens as the read degrades. A flat ceiling gave a barely-legible
# scan the same score as a clean one, because fidelity carries only 0.10 of the
# weight and the cap flattened both. The ceiling now scales with fidelity
# between these bounds, so how well the page was read reaches the number.
OCR_MIN_CAP = 0.35
# Mean per-word OCR confidence is a percentage; below this the page was barely
# read and fidelity collapses rather than degrading smoothly.
OCR_CONFIDENCE_FLOOR = 55.0

MAX_CONFIDENCE = 0.95
MIN_CONFIDENCE = 0.05

# Tunables
PARAGRAPH_FALLBACK_SCORE = 0.45
NUMBERED_SEGMENTATION_SCORE = 0.95
NO_FINDINGS_PROVENANCE = 0.60
MIN_COVERAGE = 0.15
MIN_PROFILE = 0.30


@dataclass
class ContractConfidenceReport:
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


def segmentation_quality(clauses: Sequence[Any]) -> float:
    """Whether the document yielded real numbered clauses or guessed boundaries."""
    if not clauses:
        return 0.0
    numbered = sum(1 for c in clauses if getattr(c, "number", None))
    return (
        PARAGRAPH_FALLBACK_SCORE
        + (NUMBERED_SEGMENTATION_SCORE - PARAGRAPH_FALLBACK_SCORE) * (numbered / len(clauses))
    )


def coverage(clauses: Sequence[Any], analysed_indices: Sequence[int]) -> float:
    """Fraction of the contract's text that received analysis, by characters.

    Measured in characters rather than clause count: a review that analysed the
    two longest clauses has covered more of the contract than one that analysed
    five one-line definitions.
    """
    if not clauses:
        return 0.0
    total = sum(len(getattr(c, "text", "")) for c in clauses) or 1
    wanted = set(analysed_indices)
    seen = sum(len(getattr(c, "text", "")) for c in clauses if getattr(c, "index", None) in wanted)
    return max(MIN_COVERAGE, min(1.0, seen / total))


def quote_grounding(findings: Sequence[Any], document_text: str) -> Tuple[float, int]:
    """Fraction of findings whose quoted span really is at the offsets claimed."""
    if not findings:
        return 1.0, 0
    verified = 0
    for finding in findings:
        span = " ".join(
            document_text[getattr(finding, "match_start", 0) : getattr(finding, "match_end", 0)].split()
        )
        if span and span == getattr(finding, "matched_quote", None):
            verified += 1
    return verified / len(findings), len(findings) - verified


def text_fidelity(source: str, ocr_confidence: Optional[float]) -> float:
    """How much the text can be trusted to be what the page says.

    Exact for anything lifted from the file. For OCR it tracks the measured
    per-word confidence, floored so that a barely-legible scan cannot present
    itself as merely slightly uncertain.
    """
    if source != "ocr":
        return 1.0
    if ocr_confidence is None:
        return 0.5
    if ocr_confidence <= OCR_CONFIDENCE_FLOOR:
        return 0.25
    # 55% -> 0.25, 100% -> 1.0, linear between.
    span = (ocr_confidence - OCR_CONFIDENCE_FLOOR) / (100.0 - OCR_CONFIDENCE_FLOOR)
    return 0.25 + 0.75 * span


def provenance(findings: Sequence[Any]) -> float:
    """How much of the review rests on reproducible rules rather than on a model."""
    if not findings:
        return NO_FINDINGS_PROVENANCE
    rule = sum(1 for f in findings if getattr(f, "detector", "rule") == "rule")
    # Never zero: a model finding that grounds against the document is still
    # evidence, just weaker evidence than a rule with a hand-checked citation.
    return 0.55 + 0.45 * (rule / len(findings))


def profile_quality(position_source: str, contract_type: str) -> float:
    """How well the review knows what it is reading, and for whom."""
    score = MIN_PROFILE
    if position_source == "USER_DECLARED":
        score += 0.55
    elif position_source == "LLM_INFERRED":
        score += 0.25
    if contract_type and contract_type != "UNKNOWN":
        score += 0.15
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


def estimate_contract_confidence(
    *,
    clauses: Sequence[Any],
    findings: Sequence[Any],
    document_text: str,
    analysed_indices: Sequence[int],
    position_source: str = "UNKNOWN",
    contract_type: str = "UNKNOWN",
    llm_available: bool = True,
    reranker_available: bool = True,
    degraded_nodes: Sequence[str] = (),
    source: str = "text_layer",
    ocr_confidence: Optional[float] = None,
) -> ContractConfidenceReport:
    grounding, ungrounded = quote_grounding(findings, document_text)
    components = {
        "segmentation": segmentation_quality(clauses),
        "coverage": coverage(clauses, analysed_indices),
        "grounding": grounding,
        "provenance": provenance(findings),
        "profile": profile_quality(position_source, contract_type),
        "text_fidelity": text_fidelity(source, ocr_confidence),
    }
    score = weighted_geometric_mean(components, COMPONENT_WEIGHTS)

    extra: List[Tuple[float, str]] = []
    if ungrounded:
        extra.append((UNGROUNDED_CAP, f"ungrounded_quotes<={UNGROUNDED_CAP:.2f}"))
    if position_source == "UNKNOWN":
        extra.append((UNKNOWN_POSITION_CAP, f"unknown_position<={UNKNOWN_POSITION_CAP:.2f}"))
    if clauses and not any(getattr(c, "number", None) for c in clauses):
        extra.append(
            (PARAGRAPH_FALLBACK_CAP, f"guessed_clause_boundaries<={PARAGRAPH_FALLBACK_CAP:.2f}")
        )
    if source == "ocr":
        ceiling = OCR_MIN_CAP + (OCR_SOURCE_CAP - OCR_MIN_CAP) * components["text_fidelity"]
        extra.append((ceiling, f"read_by_ocr<={ceiling:.2f}"))

    score, caps = _apply_caps(score, llm_available, reranker_available, extra)

    notes: List[str] = []
    if ungrounded:
        notes.append(
            f"{ungrounded} finding(s) quote text not present at the offsets recorded."
        )
    if position_source == "UNKNOWN":
        notes.append(
            "No reviewing side was established, so severities are unweighted: the same "
            "clause is a serious risk to one party and routine to the other."
        )
    if clauses and not any(getattr(c, "number", None) for c in clauses):
        notes.append(
            "This document carries no clause numbering, so the boundaries between "
            "clauses were inferred from its paragraphs and may not match how it reads."
        )
    if source == "ocr":
        notes.append(
            "This document had no text layer, so every quoted passage is our "
            "reading of an image rather than text taken from the file"
            + (f" (mean confidence {ocr_confidence:.0f}%)." if ocr_confidence else ".")
            + " Check any amount or date a finding turns on against the original."
        )
    if not llm_available:
        notes.append("LLM unavailable; deterministic rules produced this review.")
    if not reranker_available:
        notes.append("Cross-encoder unavailable; provisions ranked by RRF position only.")
    for node in degraded_nodes:
        notes.append(f"Partially degraded: {node}.")

    return ContractConfidenceReport(
        score=round(score, 2),
        components=components,
        caps_applied=caps,
        notes=notes,
        detail={
            "clause_count": len(clauses),
            "analysed_clause_count": len(set(analysed_indices)),
            "finding_count": len(findings),
            "rule_findings": sum(1 for f in findings if getattr(f, "detector", "rule") == "rule"),
            "llm_findings": sum(1 for f in findings if getattr(f, "detector", "") == "llm"),
            "ungrounded_findings": ungrounded,
            "source": source,
            "ocr_confidence": round(ocr_confidence, 1) if ocr_confidence else None,
        },
    )
