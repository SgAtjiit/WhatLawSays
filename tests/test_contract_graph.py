"""Tests for the contract-review graph (Phases 3 and 4).

No test here reaches Groq or Qdrant. The point of the pipeline's design is that
every model stage has a deterministic fallback and every finding is verifiable
against the document, so the behaviour that matters is testable offline.
"""

import asyncio
from unittest.mock import patch

import pytest

from src.agents.contract_nodes.consistency_checker import run_consistency_checker
from src.agents.contract_nodes.gap_detector import run_gap_detector
from src.agents.contract_nodes.grounding_verifier import run_grounding_verifier
from src.agents.contract_nodes.query_builder import (
    STATUTORY_QUERIES,
    deterministic_queries,
)
from src.agents.contract_nodes.red_flag_analyst import locate
from src.core.clause_segmenter import segment_clauses
from src.core.clause_triage import HOT, HOT_CATEGORIES, WARM, triage_clauses
from src.core.contract_confidence import estimate_contract_confidence
from src.core.document_parser import parse_document
from src.core.llm_batch import chunk, gather_batched, is_transient
from src.core.red_flag_rules import evaluate_clauses
from src.schemas.contract import (
    Clause,
    ClauseCategory,
    ContractType,
    PartyPosition,
    RedFlagFinding,
    Severity,
)


def load(name):
    with open(f"tests/fixtures/{name}.txt", "rb") as handle:
        return parse_document(handle.read(), f"{name}.txt")


@pytest.fixture(scope="module")
def employment():
    document = load("employment_agreement")
    clauses = segment_clauses(document)
    findings = evaluate_clauses(clauses, PartyPosition.EMPLOYEE)
    return document, clauses, findings


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------

def test_triage_sends_statute_bearing_clauses_down_the_expensive_path(employment):
    _, clauses, findings = employment
    result = triage_clauses(clauses, findings, PartyPosition.EMPLOYEE)
    tier_of = {c.number: result.tiers[c.index] for c in clauses}
    assert tier_of["8"] == HOT   # non-compete
    assert tier_of["10"] == HOT  # arbitration


def test_every_clause_gets_a_tier_and_an_auditable_reason(employment):
    _, clauses, findings = employment
    result = triage_clauses(clauses, findings, PartyPosition.EMPLOYEE)
    assert set(result.tiers) == {c.index for c in clauses}
    assert all(result.basis[c.index] for c in clauses)


def test_the_hot_cap_bounds_cost_by_the_cap_not_by_the_contract():
    """This is what keeps a 120-clause contract from costing 120 LLM calls."""
    clauses = [
        Clause(
            index=i, number=str(i + 1), heading=None,
            text="The parties shall indemnify each other against all claims arising "
                 "under this agreement in any manner whatsoever. " * 3,
            start_offset=i * 500, end_offset=i * 500 + 400, body_offset=i * 500,
            category=ClauseCategory.INDEMNITY,
        )
        for i in range(60)
    ]
    result = triage_clauses(clauses, [], PartyPosition.CLIENT, hot_cap=10, warm_cap=20)
    assert len(result.hot) == 10
    assert len(result.warm) == 20
    assert len(result.cold) == 30
    demoted = [i for i in result.warm if any("demoted" in r for r in result.basis[i])]
    assert demoted


def test_a_short_statute_bearing_clause_is_not_demoted_for_being_short():
    """"The Employee shall not compete for two years after leaving." is 56
    characters and void under Contract Act s.27. Brevity is not unimportance."""
    clause = Clause(
        index=0, number="1", heading=None,
        text="The Employee shall not compete for two years after leaving.",
        start_offset=0, end_offset=59, body_offset=0,
        category=ClauseCategory.NON_COMPETE,
    )
    result = triage_clauses([clause], [], PartyPosition.EMPLOYEE)
    assert result.tiers[0] == HOT


def test_an_ordinary_clause_carrying_a_finding_goes_hot_for_the_weaker_side():
    clause = Clause(
        index=0, number="1", heading=None,
        text="The rent shall be payable monthly in advance without any demand "
             "being made by the Lessor at any time during this agreement.",
        start_offset=0, end_offset=120, body_offset=0,
        category=ClauseCategory.RENT,
    )
    finding = RedFlagFinding(
        rule_id="X", title="t", severity=Severity.MEDIUM, clause_index=0,
        matched_quote="rent", match_start=4, match_end=8,
        plain_summary="s", why_it_matters="w",
    )
    strong = triage_clauses([clause], [finding], PartyPosition.LANDLORD)
    weak = triage_clauses([clause], [finding], PartyPosition.TENANT)
    assert strong.tiers[0] == WARM
    assert weak.tiers[0] == HOT


def test_a_cold_clause_still_keeps_its_deterministic_finding(employment):
    """No tier suppresses a rule finding -- a COLD clause simply gets no prose."""
    _, clauses, findings = employment
    result = triage_clauses(clauses, findings, PartyPosition.EMPLOYEE)
    for finding in findings:
        assert finding.clause_index in result.tiers


# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------

def test_chunking_splits_evenly_with_a_remainder():
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_a_rate_limit_is_transient_but_a_bad_key_is_not():
    assert is_transient(Exception("Error code: 429 rate limit reached"))
    assert not is_transient(Exception("invalid api key"))


def test_one_failed_batch_does_not_lose_the_others():
    """Without return_exceptions a single 429 cancels its siblings and the whole
    node collapses to rules -- the all-or-nothing failure batching avoids."""
    async def worker(batch):
        if 3 in batch:
            raise ValueError("boom")
        return sum(batch)

    outcome = asyncio.run(
        gather_batched([1, 2, 3, 4, 5, 6], 2, worker, 2, retry_transient=0)
    )
    assert outcome.results == [3, 11]
    assert outcome.failed_batches == 1
    assert outcome.degraded and not outcome.all_failed


def test_all_failed_is_only_true_when_nothing_got_through():
    async def worker(batch):
        raise ValueError("boom")

    outcome = asyncio.run(gather_batched([1, 2], 1, worker, 2, retry_transient=0))
    assert outcome.all_failed


def test_a_transient_failure_is_retried_once():
    calls = {"n": 0}

    async def worker(batch):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Error code: 429 rate limit")
        return "ok"

    outcome = asyncio.run(
        gather_batched([1], 1, worker, 1, retry_transient=1, retry_delay=0.0)
    )
    assert outcome.results == ["ok"]
    assert calls["n"] == 2


def test_a_permanent_failure_is_not_retried():
    calls = {"n": 0}

    async def worker(batch):
        calls["n"] += 1
        raise RuntimeError("invalid api key")

    asyncio.run(gather_batched([1], 1, worker, 1, retry_transient=1, retry_delay=0.0))
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Statutory query translation
# ---------------------------------------------------------------------------

def test_every_hot_category_has_a_statutory_translation():
    """Retrieval driven by the contract's own words misses the governing
    provision entirely -- measured: "restraint of trade void" puts Contract Act
    s.27 at rank 1, while "employee shall not join a competing business" does
    not return it at all. The table is what closes that gap without an LLM."""
    missing = [c for c in HOT_CATEGORIES if c not in STATUTORY_QUERIES]
    assert not missing, f"HOT categories with no statutory query: {missing}"


def test_the_translation_uses_statutory_not_contract_register():
    dense, sparse = deterministic_queries(ClauseCategory.NON_COMPETE)
    assert "restraint of trade" in dense.lower()
    assert "employee" not in dense.lower()


def test_no_translation_names_a_section_number():
    """A query is a search, not a citation. A section number here would let the
    pipeline cite a provision it never actually retrieved."""
    import re

    for dense, sparse in STATUTORY_QUERIES.values():
        assert not re.search(r"\bs(?:ection)?\.?\s*\d+", f"{dense} {sparse}", re.I)


def test_an_unmapped_category_still_gets_a_query():
    assert deterministic_queries(ClauseCategory.OTHER)[0]


# ---------------------------------------------------------------------------
# Quote location -- the model never supplies offsets
# ---------------------------------------------------------------------------

def test_a_quote_is_located_in_the_clause_it_came_from():
    text = "The Employee shall not compete for twenty four months after leaving."
    located = locate("shall not compete", text, 500)
    assert located is not None
    start, end, quote = located
    assert (start, quote) == (513, "shall not compete")


def test_a_quote_is_located_across_the_line_wrap_the_model_dropped():
    text = "The Employee shall not,\nfor a period of twenty four months, compete."
    located = locate("shall not, for a period", text, 0)
    assert located is not None


def test_an_invented_quote_is_rejected():
    """The guarantee the whole feature rests on."""
    text = "The Employee shall not compete for twenty four months after leaving."
    assert locate("the moon is made of cheese entirely", text, 0) is None


def test_a_quote_too_short_to_be_evidence_is_rejected():
    assert locate("the", "The Employee shall not compete.", 0) is None


# ---------------------------------------------------------------------------
# Grounding verification
# ---------------------------------------------------------------------------

def test_grounding_passes_when_every_quote_is_real(employment):
    document, clauses, findings = employment
    state = {"findings": findings, "document_text": document.text, "retry_count": 1}
    result = asyncio.run(run_grounding_verifier(state))
    assert result["grounding_passed"]
    assert result["quote_problems"] == []


def test_grounding_fails_and_scopes_the_retry_to_the_offending_clause(employment):
    document, clauses, findings = employment
    tampered = [f.model_copy(deep=True) for f in findings]
    # A MODEL finding: only those can be repaired by re-prompting.
    tampered[0].detector = "llm"
    tampered[0].matched_quote = "a term that was never in this contract"
    state = {"findings": tampered, "document_text": document.text, "retry_count": 1}
    result = asyncio.run(run_grounding_verifier(state))
    assert not result["grounding_passed"]
    assert result["ungrounded_clause_indices"] == [tampered[0].clause_index]
    assert "character for character" in result["grounding_feedback"]


def test_a_rule_finding_with_bad_offsets_does_not_drive_the_retry_loop(employment):
    """Rules quote the document by construction, so an offset bug cannot be
    fixed by re-prompting the model. It used to spend three more analyst passes
    changing nothing. It is still reported, and the compiler drops it."""
    document, clauses, findings = employment
    tampered = [f.model_copy(deep=True) for f in findings]
    tampered[0].matched_quote = "a term that was never in this contract"
    assert tampered[0].detector == "rule"
    state = {"findings": tampered, "document_text": document.text, "retry_count": 1}
    result = asyncio.run(run_grounding_verifier(state))
    assert result["grounding_passed"]
    assert result["quote_problems"]


# ---------------------------------------------------------------------------
# Gap detection and consistency
# ---------------------------------------------------------------------------

def test_gap_detection_needs_no_model(employment):
    _, clauses, _ = employment
    state = {
        "clauses": clauses,
        "contract_type": ContractType.SERVICE.value,
        "position": PartyPosition.SERVICE_PROVIDER.value,
    }
    result = asyncio.run(run_gap_detector(state))
    assert result["missing_clauses"]


def test_conflicting_notice_periods_are_detected(employment):
    """The employment fixture says fifteen days one way and ninety the other."""
    document, clauses, _ = employment
    state = {"clauses": clauses, "document_text": document.text, "retry_count": 0}
    result = asyncio.run(run_consistency_checker(state))
    kinds = {i["kind"] for i in result["consistency_findings"]}
    assert "CONFLICT" in kinds


def test_a_reference_to_a_clause_that_does_not_exist_is_detected():
    text = (
        "1. SERVICES\nThe Consultant shall provide the services described in "
        "clause 47 of this agreement at the times stated in the schedule.\n"
        "2. FEES\nThe Client shall pay the fees stated in the schedule within "
        "thirty days of receipt of a valid invoice from the Consultant.\n"
        "3. TERM\nThis agreement commences on 1 May 2025 and continues for a "
        "period of twelve months from that date unless terminated earlier."
    )
    document = parse_document(text.encode(), "c.txt")
    state = {
        "clauses": segment_clauses(document),
        "document_text": document.text,
        "retry_count": 0,
    }
    result = asyncio.run(run_consistency_checker(state))
    assert "BROKEN_CROSS_REFERENCE" in {i["kind"] for i in result["consistency_findings"]}


def test_consistency_does_not_double_count_on_a_retry(employment):
    """The grounding retry re-enters the analyst, and this node is downstream of
    it. Without the guard, every issue is reported twice on the way back."""
    document, clauses, _ = employment
    first = asyncio.run(
        run_consistency_checker(
            {"clauses": clauses, "document_text": document.text, "retry_count": 0}
        )
    )
    second = asyncio.run(
        run_consistency_checker(
            {
                "clauses": clauses,
                "document_text": document.text,
                "retry_count": 1,
                "consistency_findings": first["consistency_findings"],
            }
        )
    )
    assert len(second["consistency_findings"]) == len(first["consistency_findings"])


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

def test_a_clean_review_scores_well_but_never_asserts_certainty(employment):
    document, clauses, findings = employment
    report = estimate_contract_confidence(
        clauses=clauses, findings=findings, document_text=document.text,
        analysed_indices=[c.index for c in clauses],
        position_source="USER_DECLARED", contract_type="EMPLOYMENT",
    )
    assert 0.8 <= report.score <= 0.95


def test_an_ungrounded_quote_caps_confidence(employment):
    """The strongest hallucination signal available, so it is a cap: the
    weighted mean alone cannot express it."""
    document, clauses, findings = employment
    tampered = [f.model_copy(deep=True) for f in findings]
    tampered[0].matched_quote = "text that is not in the document at all"
    report = estimate_contract_confidence(
        clauses=clauses, findings=tampered, document_text=document.text,
        analysed_indices=[c.index for c in clauses],
        position_source="USER_DECLARED", contract_type="EMPLOYMENT",
    )
    assert report.score <= 0.50
    assert any("ungrounded" in cap for cap in report.caps_applied)


def test_not_knowing_which_side_the_reader_is_on_caps_confidence(employment):
    document, clauses, findings = employment
    report = estimate_contract_confidence(
        clauses=clauses, findings=findings, document_text=document.text,
        analysed_indices=[c.index for c in clauses],
        position_source="UNKNOWN", contract_type="EMPLOYMENT",
    )
    assert report.score <= 0.65
    assert any("unknown_position" in cap for cap in report.caps_applied)


def test_a_degraded_llm_cannot_report_healthy_confidence(employment):
    document, clauses, findings = employment
    report = estimate_contract_confidence(
        clauses=clauses, findings=findings, document_text=document.text,
        analysed_indices=[c.index for c in clauses],
        position_source="USER_DECLARED", contract_type="EMPLOYMENT",
        llm_available=False,
    )
    assert report.score <= 0.60


def test_partial_coverage_scores_below_full_coverage(employment):
    document, clauses, findings = employment
    full = estimate_contract_confidence(
        clauses=clauses, findings=findings, document_text=document.text,
        analysed_indices=[c.index for c in clauses],
        position_source="USER_DECLARED", contract_type="EMPLOYMENT",
    )
    partial = estimate_contract_confidence(
        clauses=clauses, findings=findings, document_text=document.text,
        analysed_indices=[clauses[0].index],
        position_source="USER_DECLARED", contract_type="EMPLOYMENT",
    )
    assert partial.score < full.score


def test_a_review_resting_on_model_findings_scores_below_one_resting_on_rules(employment):
    document, clauses, findings = employment
    as_llm = [f.model_copy(deep=True) for f in findings]
    for finding in as_llm:
        finding.detector = "llm"
    rules = estimate_contract_confidence(
        clauses=clauses, findings=findings, document_text=document.text,
        analysed_indices=[c.index for c in clauses],
        position_source="USER_DECLARED", contract_type="EMPLOYMENT",
    )
    model = estimate_contract_confidence(
        clauses=clauses, findings=as_llm, document_text=document.text,
        analysed_indices=[c.index for c in clauses],
        position_source="USER_DECLARED", contract_type="EMPLOYMENT",
    )
    assert model.score < rules.score


def test_the_basis_payload_explains_the_number(employment):
    document, clauses, findings = employment
    payload = estimate_contract_confidence(
        clauses=clauses, findings=findings, document_text=document.text,
        analysed_indices=[c.index for c in clauses],
        position_source="USER_DECLARED", contract_type="EMPLOYMENT",
    ).to_payload()
    assert set(payload) == {"score", "components", "caps_applied", "notes", "detail"}
    assert set(payload["components"]) == {
        "segmentation", "coverage", "grounding", "provenance", "profile"
    }


# ---------------------------------------------------------------------------
# Graph wiring and end-to-end degradation
# ---------------------------------------------------------------------------

def test_the_graph_compiles_with_every_node_wired():
    from src.agents.contract_graph import build_contract_graph

    nodes = set(build_contract_graph().get_graph().nodes)
    assert {
        "profiler", "clause_classifier", "query_builder", "clause_retriever",
        "explainer", "red_flag_analyst", "gap_detector", "consistency_checker",
        "grounding_verifier", "contract_compiler",
    } <= nodes


def _dead(*args, **kwargs):
    raise RuntimeError("Connection refused: Groq unreachable")


def test_a_full_review_still_works_with_no_llm_at_all():
    """The whole pipeline degrades to its deterministic engines and still
    produces a complete, correctly-capped review."""
    import contextlib

    from src.agents.contract_graph import contract_review_app

    document = load("saas_services_agreement")
    clauses = segment_clauses(document)
    state = {
        "task_id": "test", "document": document, "document_text": document.text,
        "clauses": clauses,
        "declared_contract_type": ContractType.SAAS,
        "declared_position": PartyPosition.CLIENT,
        "llm_available": True, "reranker_available": True,
        "llm_calls_used": 0, "retry_count": 0, "degraded_nodes": [],
        "rule_findings": [], "llm_findings": [], "findings": [],
        "suppressed_llm_findings": [], "grounding_passed": False,
        "final_response": None,
    }

    modules = ["profiler", "clause_classifier", "query_builder", "explainer", "red_flag_analyst"]
    with contextlib.ExitStack() as stack:
        for name in modules:
            stack.enter_context(
                patch(f"src.agents.contract_nodes.{name}.ChatGroq", side_effect=_dead)
            )
        # Qdrant is not available offline either; the node already tolerates it.
        stack.enter_context(
            patch("src.agents.contract_nodes.clause_retriever.vector_store.hybrid_search",
                  side_effect=RuntimeError("no qdrant"))
        )
        final = asyncio.run(contract_review_app.ainvoke(state))

    response = final["final_response"]
    assert response["status"] == "PARTIAL_SUCCESS"
    assert response["findings"], "deterministic rules must still produce findings"
    assert {f["detector"] for f in response["findings"]} == {"rule"}
    assert response["confidence_score"] <= 0.60
    assert response["missing_clauses"]
    assert response["clause_count"] == len(clauses)


def test_a_document_that_is_not_a_contract_exits_before_spending_budget():
    from src.agents.contract_nodes.profiler import run_contract_profiler

    state = {"task_id": "t", "clauses": [], "document_text": "hello", "document": None}
    result = asyncio.run(run_contract_profiler(state))
    assert result["final_response"]["status"] == "NEEDS_CLARIFICATION"
    assert result["final_response"]["clarification_questions"]
