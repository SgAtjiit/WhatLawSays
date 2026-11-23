"""Tests for the confidence estimator.

The estimate these guard against is the previous implementation's: a product of
four binary constants that could only ever return 0.73, 0.35 or 0.31.
"""

import pytest

from src.core.confidence import (
    DEGRADED_LLM_CAP,
    UNPROVEN_FLOOR,
    DEGRADED_RERANKER_CAP,
    MAX_CONFIDENCE,
    MIN_CONFIDENCE,
    UNDETERMINED_CAP,
    UNGROUNDED_CAP,
    act_family,
    build_chunk_index,
    classify_absence,
    element_support,
    estimate_absence_confidence,
    estimate_confidence,
    retrieval_decisiveness,
    section_key,
    verification_factor,
)
from src.schemas.legal import ElementAudit, OffenseAnalysis


def make_offense(section="303", statuses=("SUPPORTED",), severity="SERIOUS", act="Bharatiya Nyaya Sanhita (BNS)"):
    return OffenseAnalysis(
        act_name=act,
        section_number=f"Section {section}",
        offense_description="Theft",
        potential_punishment="Imprisonment up to 3 years",
        punishment_severity=severity,
        reasoning_chain=["Explicit fact mapped to section"],
        element_audits=[
            ElementAudit(element_name=f"element-{i}", status=s)
            for i, s in enumerate(statuses)
        ],
    )


def make_chunk(section="303", score=8.0, mode="cross_encoder", act="Bharatiya Nyaya Sanhita, 2023 (BNS)"):
    return {
        "act": act,
        "section_number": f"Section {section}",
        "title": "Theft",
        "content": "Whoever intends to take dishonestly any movable property...",
        "rerank_score": score,
        "rerank_mode": mode,
    }


# --- Section matching -------------------------------------------------------

def test_act_family_distinguishes_bnss_from_bns():
    """"bns" is a substring of "bnss"; the ordering of the checks must handle it."""
    assert act_family("Bharatiya Nyaya Sanhita, 2023 (BNS)") == "bns"
    assert act_family("Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS)") == "bnss"
    assert act_family("Bharatiya Sakshya Adhiniyam, 2023 (BSA)") == "bsa"
    assert act_family("Constitution of India") == "constitution"


def test_section_key_normalizes_citation_variants():
    """The analyst writes "Section 303"; the corpus may write "303"."""
    assert section_key("BNS", "Section 303") == section_key("Bharatiya Nyaya Sanhita (BNS)", "303")


# --- Component behaviour ----------------------------------------------------

def test_element_support_is_a_ratio_not_a_constant():
    assert element_support(make_offense(statuses=("SUPPORTED", "SUPPORTED"))) == 1.0
    assert element_support(make_offense(statuses=("SUPPORTED", "UNPROVEN"))) == 0.5


def test_unproven_is_weak_evidence_not_disproof():
    """All-unproven must stay above zero, or it annihilates the geometric mean."""
    assert element_support(make_offense(statuses=("UNPROVEN", "UNPROVEN"))) == UNPROVEN_FLOOR


def test_contradicted_element_zeroes_support():
    """Contradicted is affirmative disproof, and must outrank merely unproven."""
    contradicted = element_support(make_offense(statuses=("SUPPORTED", "CONTRADICTED_BY_FACT")))
    unproven = element_support(make_offense(statuses=("UNPROVEN", "UNPROVEN")))
    assert contradicted == 0.0
    assert contradicted < unproven


def test_relevance_is_scale_invariant():
    """BAAI/bge-reranker-base scores this corpus entirely below zero, so an
    absolute reading collapsed even the correct top hit to ~0. Only the ordering
    within one candidate set is meaningful, so a uniform shift must not matter."""
    positive = [make_chunk("1", 4.0), make_chunk("2", 2.0), make_chunk("3", 0.0)]
    shifted = [make_chunk("1", -0.5), make_chunk("2", -2.5), make_chunk("3", -4.5)]
    assert retrieval_decisiveness(positive) == pytest.approx(
        retrieval_decisiveness(shifted)
    )

    idx_pos = build_chunk_index(positive)
    idx_neg = build_chunk_index(shifted)
    assert idx_pos[section_key("BNS", "1")] == pytest.approx(idx_neg[section_key("BNS", "1")])


def test_decisiveness_separates_a_clear_winner_from_a_flat_field():
    clear = [make_chunk("1", 9.0), make_chunk("2", 1.0), make_chunk("3", 0.5)]
    flat = [make_chunk("1", 5.0), make_chunk("2", 4.9), make_chunk("3", 0.0)]
    assert retrieval_decisiveness(clear) > retrieval_decisiveness(flat)


def test_retrieval_decisiveness_is_zero_without_chunks():
    assert retrieval_decisiveness([]) == 0.0


def test_retrieved_but_low_ranked_section_is_not_called_a_hallucination():
    """Regression: a low relevance score was being read as "never retrieved",
    so a genuinely retrieved section was flagged as absent from the corpus."""
    chunks = [make_chunk("331", 9.0), make_chunk("329", 1.0), make_chunk("330", 0.0)]
    report = estimate_confidence(
        offenses=[make_offense(section="329")],
        retrieved_chunks=chunks,
        verification_passed=True,
        retry_count=1,
    )
    assert report.offenses[0]["in_retrieved_corpus"] is True
    assert not any("not present in the retrieved corpus" in n for n in report.notes)
    assert not any("ungrounded" in c for c in report.caps_applied)


def test_verification_factor_discounts_retries():
    """retry_count arrives pre-incremented by the analyst, so 1 == first attempt."""
    first_pass = verification_factor(True, retry_count=1)
    third_pass = verification_factor(True, retry_count=3)
    assert first_pass == 1.0
    assert third_pass < first_pass
    assert verification_factor(False, retry_count=3) < third_pass


# --- Response-level estimate ------------------------------------------------

def test_score_varies_with_evidence_quality():
    """The regression this whole module exists to prevent."""
    strong = estimate_confidence(
        offenses=[make_offense(statuses=("SUPPORTED", "SUPPORTED"))],
        retrieved_chunks=[make_chunk(score=9.0)],
        verification_passed=True,
        retry_count=1,
        unknown_facts=[],
    )
    weak = estimate_confidence(
        offenses=[make_offense(statuses=("SUPPORTED", "UNPROVEN", "UNPROVEN"))],
        retrieved_chunks=[make_chunk(score=-2.0)],
        verification_passed=True,
        retry_count=1,
        unknown_facts=["Was force used?", "Was consent given?"],
    )
    assert strong.score > weak.score


def test_ungrounded_citation_scores_below_grounded_one():
    """A section absent from retrieval is a possible hallucination."""
    chunks = [make_chunk("303", 9.0), make_chunk("331", 1.0)]
    grounded = estimate_confidence(
        offenses=[make_offense(section="303")],
        retrieved_chunks=chunks,
        verification_passed=True,
        retry_count=1,
    )
    ungrounded = estimate_confidence(
        offenses=[make_offense(section="777")],
        retrieved_chunks=chunks,
        verification_passed=True,
        retry_count=1,
    )
    assert ungrounded.score < grounded.score
    assert any("not present in the retrieved corpus" in n for n in ungrounded.notes)


def test_degraded_llm_caps_the_estimate():
    report = estimate_confidence(
        offenses=[make_offense(statuses=("SUPPORTED", "SUPPORTED"))],
        retrieved_chunks=[make_chunk(score=9.0)],
        verification_passed=True,
        retry_count=1,
        llm_available=False,
    )
    assert report.score <= DEGRADED_LLM_CAP
    assert report.caps_applied


def test_degraded_reranker_caps_the_estimate():
    report = estimate_confidence(
        offenses=[make_offense(statuses=("SUPPORTED", "SUPPORTED"))],
        retrieved_chunks=[make_chunk(score=1.0, mode="rrf_fallback")],
        verification_passed=True,
        retry_count=1,
        reranker_available=False,
    )
    assert report.score <= DEGRADED_RERANKER_CAP


def test_severity_weighting_favours_the_graver_offence():
    """A solid capital-life finding should not be dragged down by a weak minor one."""
    capital = make_offense(section="103", statuses=("SUPPORTED", "SUPPORTED"), severity="CAPITAL_LIFE")
    minor = make_offense(section="351", statuses=("UNPROVEN",), severity="MINOR")
    chunks = [make_chunk(section="103", score=9.0), make_chunk(section="351", score=9.0)]

    weighted = estimate_confidence(
        offenses=[capital, minor], retrieved_chunks=chunks,
        verification_passed=True, retry_count=1,
    )
    minor_only = estimate_confidence(
        offenses=[minor], retrieved_chunks=chunks,
        verification_passed=True, retry_count=1,
    )
    assert weighted.score > minor_only.score


def test_score_never_asserts_certainty_or_impossibility():
    """A saturating component must not report 1.00, nor a zero one collapse to 0.00."""
    for verification in (True, False):
        for chunks in ([], [make_chunk(score=50.0)], [make_chunk(score=-50.0)]):
            report = estimate_confidence(
                offenses=[make_offense()],
                retrieved_chunks=chunks,
                verification_passed=verification,
                retry_count=1,
            )
            assert MIN_CONFIDENCE <= report.score <= MAX_CONFIDENCE


def test_perfect_evidence_still_stops_short_of_certainty():
    """Every component saturated: top-ranked citation, a decisively separated
    retrieval set, all elements supported, first-pass verification, no unknowns."""
    report = estimate_confidence(
        offenses=[make_offense(section="303", statuses=("SUPPORTED", "SUPPORTED"))],
        retrieved_chunks=[
            make_chunk("303", 9.0), make_chunk("331", 0.1), make_chunk("330", 0.0)
        ],
        verification_passed=True,
        retry_count=1,
        unknown_facts=[],
    )
    assert report.score == MAX_CONFIDENCE


def test_single_chunk_is_treated_as_undecided_not_perfect():
    """One candidate separates from nothing, so it must not read as ideal retrieval."""
    one = estimate_confidence(
        offenses=[make_offense(section="303", statuses=("SUPPORTED",))],
        retrieved_chunks=[make_chunk("303", 9.0)],
        verification_passed=True, retry_count=1,
    )
    many = estimate_confidence(
        offenses=[make_offense(section="303", statuses=("SUPPORTED",))],
        retrieved_chunks=[make_chunk("303", 9.0), make_chunk("331", 0.1), make_chunk("330", 0.0)],
        verification_passed=True, retry_count=1,
    )
    assert one.score < many.score


def test_ungrounded_citation_caps_the_estimate():
    """Citing law that was never retrieved must dominate, not just nudge the mean."""
    report = estimate_confidence(
        offenses=[make_offense(section="303", statuses=("SUPPORTED", "SUPPORTED"))],
        retrieved_chunks=[make_chunk("999", 9.0), make_chunk("888", 1.0)],
        verification_passed=True,
        retry_count=1,
    )
    assert report.score <= UNGROUNDED_CAP
    assert any("ungrounded_citation" in c for c in report.caps_applied)


def test_empty_retrieval_does_not_collapse_to_zero():
    _, report = estimate_absence_confidence(
        retrieved_chunks=[], has_contradiction=False, unknown_facts=["a", "b"],
    )
    assert report.score >= MIN_CONFIDENCE


# --- Absence of an offence --------------------------------------------------

def test_contradiction_with_good_retrieval_is_an_affirmative_finding():
    """Previously both absence cases collapsed to a hardcoded 0.35."""
    status, report = estimate_absence_confidence(
        retrieved_chunks=[make_chunk(score=9.0)],
        has_contradiction=True,
        unknown_facts=[],
    )
    assert status == "NOT_ESTABLISHED"
    assert report.score > UNDETERMINED_CAP


def test_weak_retrieval_without_contradiction_stays_undetermined():
    status, report = estimate_absence_confidence(
        retrieved_chunks=[],
        has_contradiction=False,
        unknown_facts=["What happened?"],
    )
    assert status == "UNDETERMINED"
    assert report.score <= UNDETERMINED_CAP


def test_classify_absence_requires_both_signals():
    assert classify_absence(0.9, True) == "NOT_ESTABLISHED"
    assert classify_absence(0.9, False) == "UNDETERMINED"
    assert classify_absence(0.1, True) == "UNDETERMINED"


def test_absence_payload_is_serializable():
    _, report = estimate_absence_confidence(
        retrieved_chunks=[make_chunk()], has_contradiction=True,
    )
    payload = report.to_payload()
    assert set(payload) == {"score", "components", "offenses", "caps_applied", "notes"}
