"""Integration tests for the response compiler's confidence and status wiring."""

import asyncio

from src.agents.nodes.compiler import run_response_compiler
from src.schemas.legal import ElementAudit, ExtractedFacts, OffenseAnalysis

FACTS = ExtractedFacts(
    explicit_facts=["The person had an invitation to the party"],
    established_facts=["The person had an invitation to the party"],
    actor="person",
    action="enter",
)


def offense(section="303", statuses=("SUPPORTED",), severity="SERIOUS"):
    return OffenseAnalysis(
        act_name="Bharatiya Nyaya Sanhita (BNS)",
        section_number=f"Section {section}",
        offense_description="Theft",
        potential_punishment="Imprisonment up to 3 years",
        punishment_severity=severity,
        reasoning_chain=["mapped"],
        element_audits=[
            ElementAudit(element_name=f"e{i}", status=s) for i, s in enumerate(statuses)
        ],
    )


def chunk(section="303", score=8.0):
    return {
        "act": "Bharatiya Nyaya Sanhita, 2023 (BNS)",
        "section_number": f"Section {section}",
        "title": "Theft",
        "content": "text",
        "rerank_score": score,
        "rerank_mode": "cross_encoder",
    }


def compile_response(**kw):
    """Run the compiler on a state and return its payload.

    pytest-asyncio is not a dependency of this project, so the coroutine is
    driven directly rather than through an async test marker.
    """
    base = dict(
        task_id="t",
        scenario_text="s",
        extracted_facts=FACTS,
        explicit_facts=FACTS.explicit_facts,
        unknown_facts=[],
        draft_offenses=[],
        retrieved_chunks=[],
        verification_passed=True,
        retry_count=1,
        llm_available=True,
        reranker_available=True,
        contradicted_provisions=[],
    )
    base.update(kw)
    return asyncio.run(run_response_compiler(base))["final_response"]


def test_contradiction_recorded_upstream_yields_not_established():
    """The analyst drops contradicted sections, so the evidence arrives via state."""
    payload = compile_response(
        retrieved_chunks=[chunk("329", 9.0)],
        contradicted_provisions=[
            {
                "act_name": "Bharatiya Nyaya Sanhita (BNS)",
                "section_number": "Section 329",
                "offense_description": "Criminal trespass",
                "contradicted_elements": ["A valid invitation, permission or consent exists."],
            }
        ],
    )
    assert payload["offense_status"] == "NOT_ESTABLISHED"
    assert payload["status"] == "SUCCESS"
    assert payload["confidence_score"] > 0.45
    assert payload["excluded_provisions"]


def test_no_contradiction_yields_low_confidence_undetermined():
    payload = compile_response(retrieved_chunks=[], unknown_facts=["a", "b"])
    assert payload["offense_status"] == "UNDETERMINED"
    assert payload["status"] == "UNDETERMINED"
    assert payload["confidence_score"] <= 0.45


def test_partial_success_outscores_a_non_answer():
    """The old implementation scored PARTIAL_SUCCESS 0.31 below a 0.35 non-answer."""
    partial = compile_response(
        draft_offenses=[offense("303", ("SUPPORTED", "UNPROVEN"))],
        retrieved_chunks=[chunk("303", 5.0)],
        verification_passed=False,
        retry_count=3,
    )
    non_answer = compile_response(retrieved_chunks=[], unknown_facts=["a"])

    assert partial["status"] == "PARTIAL_SUCCESS"
    assert non_answer["status"] == "UNDETERMINED"
    assert partial["confidence_score"] > non_answer["confidence_score"]


def test_identical_verified_scenarios_differ_by_evidence_quality():
    """Both are SUCCESS/ESTABLISHED; the old code returned 0.73 for both."""
    strong = compile_response(
        draft_offenses=[offense("303", ("SUPPORTED", "SUPPORTED"))],
        retrieved_chunks=[chunk("303", 9.0)],
    )
    weak = compile_response(
        draft_offenses=[offense("303", ("SUPPORTED", "UNPROVEN", "UNPROVEN"))],
        retrieved_chunks=[chunk("303", 0.5)],
        unknown_facts=["a", "b", "c"],
    )

    assert strong["status"] == weak["status"] == "SUCCESS"
    assert strong["confidence_score"] > weak["confidence_score"]


def test_confidence_basis_is_present_and_explains_caps():
    payload = compile_response(
        draft_offenses=[offense("303", ("SUPPORTED", "SUPPORTED"))],
        retrieved_chunks=[chunk("303", 9.0)],
        llm_available=False,
    )
    basis = payload["confidence_basis"]
    assert basis["components"]
    assert any("llm_fallback" in c for c in basis["caps_applied"])
    assert payload["confidence_score"] <= 0.60


def test_procedural_sections_are_still_excluded_from_offenses():
    """Guard the existing filter the confidence change sits on top of."""
    procedural = OffenseAnalysis(
        act_name="Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS)",
        section_number="Section 185",
        offense_description="Procedure for search",
        potential_punishment="N/A",
        reasoning_chain=["r"],
    )
    payload = compile_response(
        draft_offenses=[procedural], retrieved_chunks=[chunk("185", 9.0)]
    )
    assert payload["identified_offenses"] == []


def penalty_chunk(section, prescribes, act="Bharatiya Nyaya Sanhita, 2023 (BNS)"):
    return {
        "act": act,
        "section_number": f"Section {section}",
        "title": "t",
        "content": "text",
        "rerank_score": 5.0,
        "rerank_mode": "cross_encoder",
        "prescribes_penalty": prescribes,
    }


def test_section_prescribing_no_penalty_is_not_an_offence():
    """POSH s.8 (Grants and audit) and s.4 (Constitution of the Internal
    Complaints Committee) prescribe no penalty and must never be reported as
    offences, however the analyst labelled them."""
    payload = compile_response(
        draft_offenses=[offense("8", ("SUPPORTED",))],
        retrieved_chunks=[penalty_chunk("8", False)],
    )
    assert payload["identified_offenses"] == []


def test_section_prescribing_a_penalty_is_kept():
    payload = compile_response(
        draft_offenses=[offense("303", ("SUPPORTED",))],
        retrieved_chunks=[penalty_chunk("303", True)],
    )
    assert len(payload["identified_offenses"]) == 1


def test_chunk_without_the_flag_is_not_dropped():
    """Guards against a corpus indexed before the flag existed."""
    chunk_no_flag = penalty_chunk("303", True)
    del chunk_no_flag["prescribes_penalty"]
    payload = compile_response(
        draft_offenses=[offense("303", ("SUPPORTED",))],
        retrieved_chunks=[chunk_no_flag],
    )
    assert len(payload["identified_offenses"]) == 1
