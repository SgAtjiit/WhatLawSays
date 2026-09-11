"""Confidence estimation for compiled legal analyses.

Pure functions with no I/O and no LLM calls, so the scoring logic can be tested
in isolation from the LangGraph pipeline.

The estimate is a weighted geometric mean of independently measured components.
Every component is derived from a signal the pipeline actually produces --
cross-encoder relevance, statutory element audits, verification outcome, the
number of facts the citizen never supplied -- rather than from a constant.

This is an *estimate*, not a calibrated probability: nothing here has been
fitted against labelled outcomes. Calibration needs a labelled scenario set and
a reliability check that the 0.7 bucket is right roughly 70% of the time.
"""

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

EPSILON = 1e-6

# --- Component weights (weighted geometric mean over response-level factors) ---
OFFENSE_COMPONENT_WEIGHTS = {"element_support": 0.5, "grounding": 0.5}
RESPONSE_COMPONENT_WEIGHTS = {
    "offense_support": 0.40,
    "retrieval": 0.20,
    "verification": 0.30,
    "fact_completeness": 0.10,
}
ABSENCE_COMPONENT_WEIGHTS = {
    "retrieval": 0.50,
    "exclusion_evidence": 0.30,
    "fact_completeness": 0.20,
}

# --- Severity weights for aggregating per-offense scores ---
SEVERITY_WEIGHTS = {"CAPITAL_LIFE": 3.0, "SERIOUS": 2.0, "MINOR": 1.0}
DEFAULT_SEVERITY_WEIGHT = 1.5

# --- Caps applied when a pipeline stage silently degraded to a fallback ---
DEGRADED_LLM_CAP = 0.60
DEGRADED_RERANKER_CAP = 0.75
UNDETERMINED_CAP = 0.45
# An analysis citing a section the retriever never returned is unsupported by the
# corpus and is the strongest hallucination signal available. The weighted mean
# alone cannot express that, since offense_support carries only 0.40 of the
# weight, so it is enforced as a cap.
UNGROUNDED_CAP = 0.50

# The estimator is unvalidated, so it asserts neither certainty nor impossibility.
# The ceiling also keeps a single saturating component from reporting 1.00, and
# the floor keeps one zero component from collapsing the geometric mean to 0.00.
MAX_CONFIDENCE = 0.95
MIN_CONFIDENCE = 0.05

# --- Tunables ---
UNGROUNDED_SCORE = 0.15      # cited section absent from retrieved corpus
NO_AUDIT_SCORE = 0.50        # analyst produced no element audit at all
UNPROVEN_FLOOR = 0.20        # every element unproven, but none disproven
RETRY_PENALTY = 0.12         # per re-attempt, when verification eventually passed
MIN_VERIFICATION_FACTOR = 0.55
FAILED_VERIFICATION_FACTOR = 0.35
UNKNOWN_FACT_PENALTY = 0.08
MIN_FACT_COMPLETENESS = 0.45
NEUTRAL_DECISIVENESS = 0.5   # a single candidate separates from nothing
ABSENCE_RETRIEVAL_FLOOR = 0.45
CONTRADICTION_EVIDENCE = 0.90
WEAK_EXCLUSION_EVIDENCE = 0.25

_SECTION_DIGITS = re.compile(r"\d+[A-Za-z]*")


# ---------------------------------------------------------------------------
# Score normalization
# ---------------------------------------------------------------------------

def chunk_relevance_map(
    chunks: Sequence[Dict[str, Any]]
) -> Dict[int, float]:
    """Relevance of each retrieved chunk relative to the rest of the set.

    Cross-encoder logits are NOT calibrated relevance probabilities. Their
    absolute range is model- and corpus-dependent: BAAI/bge-reranker-base scores
    this statutory corpus entirely below zero, so passing the raw logit through a
    sigmoid reported the single correct section as ~0.39 and everything else as
    ~0. Absolute calibration would require a labelled relevance set.

    What the score does support is comparison *within one query's candidate set*,
    so relevance is min-max normalized over the retrieved chunks. This is ordinal
    and scale-free, and works unchanged for the rank-normalized RRF fallback.
    """
    values: List[float] = []
    for chunk in chunks or []:
        raw = chunk.get("rerank_score")
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            values.append(0.0)

    if not values:
        return {}
    top, bottom = max(values), min(values)
    spread = top - bottom
    if spread <= EPSILON:
        # A single chunk, or a set the reranker could not separate at all.
        return {i: 1.0 for i in range(len(values))}
    return {i: (v - bottom) / spread for i, v in enumerate(values)}


def retrieval_decisiveness(chunks: Sequence[Dict[str, Any]]) -> float:
    """How clearly retrieval separated a best match from the rest of the field.

    Also scale-free: the gap between the top score and the median, as a fraction
    of the set's full spread. A top hit that stands well clear of the pack scores
    high; a flat set the reranker could not distinguish scores low. This replaces
    an absolute quality reading, which the scores cannot support.
    """
    values: List[float] = []
    for chunk in chunks or []:
        raw = chunk.get("rerank_score")
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            values.append(0.0)

    if not values:
        return 0.0
    if len(values) == 1:
        # One candidate carries no separation information either way.
        return NEUTRAL_DECISIVENESS

    values.sort()
    top, bottom = values[-1], values[0]
    spread = top - bottom
    if spread <= EPSILON:
        return 0.0
    mid = len(values) // 2
    median = (
        values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0
    )
    return max(0.0, min(1.0, (top - median) / spread))


# ---------------------------------------------------------------------------
# Section matching (offense citation -> retrieved chunk)
# ---------------------------------------------------------------------------

def act_family(act: str) -> str:
    """Collapse act-name variants onto a stable family token."""
    a = (act or "").lower()
    # Special Acts first: without their own families they would all collapse into
    # "unknown", letting an IT Act section cross-match a POSH section of the same
    # number and ground one citation against the other's text.
    if "information technology" in a or "(it act" in a:
        return "it"
    if "sexual harassment" in a or "posh" in a:
        return "posh"
    # BNSS must be tested before BNS: the substring "bns" also matches "bnss".
    if "nagarik" in a or "nagrik" in a or "bnss" in a or "crpc" in a or "criminal procedure" in a:
        return "bnss"
    if "sakshya" in a or "bsa" in a or "bss" in a or "evidence" in a:
        return "bsa"
    if "constitution" in a:
        return "constitution"
    if "nyaya" in a or "bns" in a or "penal" in a or "ipc" in a:
        return "bns"
    return "unknown"


def section_key(act: str, section: Any) -> Tuple[str, str]:
    match = _SECTION_DIGITS.search(str(section or ""))
    return (act_family(act), match.group(0).lower() if match else "")


def build_chunk_index(chunks: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], float]:
    """Map (act family, section number) -> that chunk's set-relative relevance."""
    relevance = chunk_relevance_map(chunks)
    index: Dict[Tuple[str, str], float] = {}
    for position, chunk in enumerate(chunks or []):
        key = section_key(chunk.get("act", ""), chunk.get("section_number", ""))
        if key[1] and key not in index:
            index[key] = relevance.get(position, 0.0)
    return index


# ---------------------------------------------------------------------------
# Per-offense components
# ---------------------------------------------------------------------------

def _audit_status(audit: Any) -> str:
    return str(getattr(audit, "status", "") or "").upper()


def element_support(offense: Any) -> float:
    """Fraction of the section's mandatory elements actually supported by fact.

    UNPROVEN and CONTRADICTED_BY_FACT are deliberately not equivalent. A
    contradicted element is affirmatively disproven and scores 0.0; elements that
    are merely unproven mean the facts are silent, which is weak evidence but not
    disproof, so the ratio is floored rather than allowed to reach zero.

    Without that floor an all-unproven offence annihilated the geometric mean,
    and an analyst that emitted no audits at all scored NO_AUDIT_SCORE -- better
    than one that honestly reported UNPROVEN.
    """
    audits = getattr(offense, "element_audits", None) or []
    if not audits:
        return NO_AUDIT_SCORE
    statuses = [_audit_status(a) for a in audits]
    if any(s == "CONTRADICTED_BY_FACT" for s in statuses):
        return 0.0
    supported = sum(1 for s in statuses if s == "SUPPORTED")
    return max(UNPROVEN_FLOOR, supported / len(statuses))


def grounding(
    offense: Any, chunk_index: Dict[Tuple[str, str], float]
) -> Tuple[float, bool]:
    """Relevance of the source text the cited section was drawn from.

    Returns (score, found). `found` is reported separately rather than inferred
    from a low score: a section that was retrieved but ranked poorly is a weak
    citation, whereas one that was never retrieved at all is a possible
    hallucination, and conflating the two mislabels the former.

    This is the check the old constant c_authority = 1.00 pretended to perform.
    """
    key = section_key(getattr(offense, "act_name", ""), getattr(offense, "section_number", ""))
    score = chunk_index.get(key)
    if score is None:
        return UNGROUNDED_SCORE, False
    return score, True


def severity_weight(offense: Any) -> float:
    severity = str(getattr(offense, "punishment_severity", None) or "").upper()
    return SEVERITY_WEIGHTS.get(severity, DEFAULT_SEVERITY_WEIGHT)


# ---------------------------------------------------------------------------
# Response-level components
# ---------------------------------------------------------------------------

def verification_factor(verification_passed: bool, retry_count: int) -> float:
    """Verification outcome, discounted by how many attempts it took.

    The analyst increments retry_count on every pass, so a first-attempt pass
    arrives here as 1. Re-attempts are therefore retry_count - 1.
    """
    if not verification_passed:
        return FAILED_VERIFICATION_FACTOR
    retries = max(0, int(retry_count or 0) - 1)
    return max(MIN_VERIFICATION_FACTOR, 1.0 - RETRY_PENALTY * retries)


def fact_completeness(unknown_facts: Optional[Sequence[str]]) -> float:
    """How much of the picture the citizen actually supplied."""
    count = len(unknown_facts or [])
    return max(MIN_FACT_COMPLETENESS, 1.0 - UNKNOWN_FACT_PENALTY * count)


def weighted_geometric_mean(components: Dict[str, float], weights: Dict[str, float]) -> float:
    """Geometric mean so no single weak component silently zeroes the result."""
    total_weight = sum(weights.get(k, 0.0) for k in components)
    if total_weight <= 0:
        return 0.0
    accumulated = sum(
        weights.get(name, 0.0) * math.log(max(value, EPSILON))
        for name, value in components.items()
    )
    return math.exp(accumulated / total_weight)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class ConfidenceReport:
    score: float
    components: Dict[str, float] = field(default_factory=dict)
    offenses: List[Dict[str, Any]] = field(default_factory=list)
    caps_applied: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "components": {k: round(v, 3) for k, v in self.components.items()},
            "offenses": self.offenses,
            "caps_applied": self.caps_applied,
            "notes": self.notes,
        }


def _apply_caps(
    score: float,
    llm_available: bool,
    reranker_available: bool,
    extra_cap: Optional[Tuple[float, str]] = None,
) -> Tuple[float, List[str]]:
    """Degraded components must not be able to report full confidence."""
    caps: List[Tuple[float, str]] = []
    if not llm_available:
        caps.append((DEGRADED_LLM_CAP, f"llm_fallback<={DEGRADED_LLM_CAP:.2f}"))
    if not reranker_available:
        caps.append((DEGRADED_RERANKER_CAP, f"reranker_fallback<={DEGRADED_RERANKER_CAP:.2f}"))
    if extra_cap is not None:
        caps.append(extra_cap)

    applied: List[str] = []
    for cap_value, label in caps:
        if score > cap_value:
            score = cap_value
            applied.append(label)
    return max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, score)), applied


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def estimate_confidence(
    *,
    offenses: Sequence[Any],
    retrieved_chunks: Sequence[Dict[str, Any]],
    verification_passed: bool,
    retry_count: int = 0,
    unknown_facts: Optional[Sequence[str]] = None,
    llm_available: bool = True,
    reranker_available: bool = True,
) -> ConfidenceReport:
    """Confidence that the identified offenses are the right ones."""
    chunk_index = build_chunk_index(retrieved_chunks)

    per_offense: List[Dict[str, Any]] = []
    weights: List[float] = []
    scores: List[float] = []

    for offense in offenses:
        support = element_support(offense)
        ground, found = grounding(offense, chunk_index)
        offense_score = weighted_geometric_mean(
            {"element_support": support, "grounding": ground},
            OFFENSE_COMPONENT_WEIGHTS,
        )
        weight = severity_weight(offense)
        scores.append(offense_score)
        weights.append(weight)
        per_offense.append(
            {
                "act_name": getattr(offense, "act_name", ""),
                "section_number": getattr(offense, "section_number", ""),
                "score": round(offense_score, 3),
                "element_support": round(support, 3),
                "grounding": round(ground, 3),
                "in_retrieved_corpus": found,
                "severity_weight": weight,
            }
        )

    total_weight = sum(weights)
    offense_support = (
        sum(s * w for s, w in zip(scores, weights)) / total_weight if total_weight else 0.0
    )

    components = {
        "offense_support": offense_support,
        "retrieval": retrieval_decisiveness(retrieved_chunks),
        "verification": verification_factor(verification_passed, retry_count),
        "fact_completeness": fact_completeness(unknown_facts),
    }
    score = weighted_geometric_mean(components, RESPONSE_COMPONENT_WEIGHTS)

    ungrounded = [o for o in per_offense if not o["in_retrieved_corpus"]]
    ungrounded_cap = (
        (UNGROUNDED_CAP, f"ungrounded_citation<={UNGROUNDED_CAP:.2f}") if ungrounded else None
    )
    score, caps = _apply_caps(score, llm_available, reranker_available, ungrounded_cap)

    notes: List[str] = []
    if ungrounded:
        notes.append(
            f"{len(ungrounded)} cited section(s) were not present in the retrieved corpus."
        )
    if not llm_available:
        notes.append("LLM unavailable; rule-based engines produced this analysis.")
    if not reranker_available:
        notes.append("Cross-encoder unavailable; provisions ranked by RRF position only.")

    return ConfidenceReport(
        score=round(score, 2),
        components=components,
        offenses=per_offense,
        caps_applied=caps,
        notes=notes,
    )


def classify_absence(retrieval_score: float, has_contradiction: bool) -> str:
    """Distinguish 'confidently no offence' from 'we could not tell'.

    These are opposite epistemic states that the previous implementation
    collapsed into a single hardcoded 0.35.
    """
    if has_contradiction and retrieval_score >= ABSENCE_RETRIEVAL_FLOOR:
        return "NOT_ESTABLISHED"
    return "UNDETERMINED"


def estimate_absence_confidence(
    *,
    retrieved_chunks: Sequence[Dict[str, Any]],
    has_contradiction: bool,
    unknown_facts: Optional[Sequence[str]] = None,
    llm_available: bool = True,
    reranker_available: bool = True,
) -> Tuple[str, ConfidenceReport]:
    """Confidence for a response that identifies no offence."""
    retrieval = retrieval_decisiveness(retrieved_chunks)
    offense_status = classify_absence(retrieval, has_contradiction)

    components = {
        "retrieval": retrieval,
        "exclusion_evidence": CONTRADICTION_EVIDENCE if has_contradiction else WEAK_EXCLUSION_EVIDENCE,
        "fact_completeness": fact_completeness(unknown_facts),
    }
    score = weighted_geometric_mean(components, ABSENCE_COMPONENT_WEIGHTS)

    extra_cap = None
    if offense_status == "UNDETERMINED":
        extra_cap = (UNDETERMINED_CAP, f"undetermined<={UNDETERMINED_CAP:.2f}")
    score, caps = _apply_caps(score, llm_available, reranker_available, extra_cap)

    notes: List[str] = []
    if offense_status == "NOT_ESTABLISHED":
        notes.append(
            "Relevant law was retrieved and its elements are contradicted by the "
            "supplied facts: the absence of an offence is an affirmative finding."
        )
    else:
        notes.append(
            "Insufficient retrieval or fact support to determine whether an offence arises."
        )
    if not llm_available:
        notes.append("LLM unavailable; rule-based engines produced this analysis.")
    if not reranker_available:
        notes.append("Cross-encoder unavailable; provisions ranked by RRF position only.")

    return offense_status, ConfidenceReport(
        score=round(score, 2),
        components=components,
        offenses=[],
        caps_applied=caps,
        notes=notes,
    )
