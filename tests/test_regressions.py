"""Regressions from the phase 1-8 audit.

Each test here corresponds to a bug that was reproduced, confirmed by two
independent skeptics, and fixed. They are grouped here rather than scattered
because what they have in common is how they failed: silently, in a path no
existing test exercised.
"""

import asyncio
from unittest.mock import patch

import pytest

from src.core.clause_segmenter import segment_clauses
from src.core.document_parser import parse_document


def _employment():
    with open("tests/fixtures/employment_agreement.txt", "rb") as handle:
        document = parse_document(handle.read(), "e.txt")
    return document, segment_clauses(document)


# ---------------------------------------------------------------------------
# Batch nodes crashed when the model answered in prose
# ---------------------------------------------------------------------------

class _NoToolCall:
    """Groq returns None when the model replies in prose instead of calling the
    structured-output tool. It is a frequent outcome, not an exotic one."""

    def with_structured_output(self, *_):
        return self

    async def ainvoke(self, *_):
        return None


@pytest.mark.parametrize("module,runner", [
    ("clause_classifier", "run_clause_classifier"),
    ("explainer", "run_clause_explainer"),
    ("red_flag_analyst", "run_red_flag_analyst"),
    ("query_builder", "run_contract_query_builder"),
])
def test_a_node_survives_a_model_that_calls_no_tool(module, runner):
    import importlib

    from src.core.clause_triage import triage_clauses
    from src.core.red_flag_rules import evaluate_clauses
    from src.schemas.contract import PartyPosition

    document, clauses = _employment()
    findings = evaluate_clauses(clauses, PartyPosition.EMPLOYEE)
    triage = triage_clauses(clauses, findings, PartyPosition.EMPLOYEE)
    state = {
        "clauses": clauses, "document": document, "document_text": document.text,
        "position": "EMPLOYEE", "contract_type": "EMPLOYMENT",
        "rule_findings": findings, "llm_findings": [], "findings": [],
        "clause_tier": triage.tiers, "hot_clause_indices": triage.hot,
        "warm_clause_indices": triage.warm, "clause_queries": {}, "clause_chunks": {},
        "explanations": {}, "suppressed_llm_findings": [], "degraded_nodes": [],
        "llm_available": True, "llm_calls_used": 0, "retry_count": 0,
    }
    if module == "query_builder":
        state["clause_queries"] = {}

    node = importlib.import_module(f"src.agents.contract_nodes.{module}")
    with patch.object(node, "ChatGroq", return_value=_NoToolCall()):
        result = asyncio.run(getattr(node, runner)(state))
    assert result is not None


def test_a_full_review_survives_a_model_that_calls_no_tool():
    """End to end: the deterministic findings must still come through."""
    import contextlib

    from src.agents.contract_graph import contract_review_app
    from src.core.contract_service import initial_state
    from src.schemas.contract import ContractType, PartyPosition

    document, clauses = _employment()
    state = initial_state(
        document, clauses, "notool-1", ContractType.EMPLOYMENT, PartyPosition.EMPLOYEE, "India"
    )
    modules = ["profiler", "clause_classifier", "query_builder", "explainer", "red_flag_analyst"]
    with contextlib.ExitStack() as stack:
        for name in modules:
            stack.enter_context(
                patch(f"src.agents.contract_nodes.{name}.ChatGroq", return_value=_NoToolCall())
            )
        stack.enter_context(
            patch("src.agents.contract_nodes.clause_retriever.vector_store.hybrid_search",
                  side_effect=RuntimeError("no qdrant"))
        )
        final = asyncio.run(contract_review_app.ainvoke(state))

    review = final["final_response"]
    assert review["findings"]
    assert {f["detector"] for f in review["findings"]} == {"rule"}


# ---------------------------------------------------------------------------
# Document-view highlights landed on the wrong text
# ---------------------------------------------------------------------------

def test_highlight_offsets_index_into_normalised_text():
    """The page kept the RAW bytes for the highlighted view while every offset
    in the review indexes into the NORMALISED text, so a CRLF or indented file
    highlighted the wrong words."""
    from src.core.document_parser import normalize
    from src.core.red_flag_rules import evaluate_clauses
    from src.schemas.contract import PartyPosition

    with open("tests/fixtures/employment_agreement.txt", "rb") as handle:
        raw = handle.read().decode()
    crlf = raw.replace("\n", "\r\n")

    document = parse_document(crlf.encode(), "crlf.txt")
    findings = evaluate_clauses(segment_clauses(document), PartyPosition.EMPLOYEE)
    assert findings

    displayed = normalize(crlf)  # what the page now stores
    for finding in findings:
        span = displayed[finding["match_start"]: finding["match_end"]] if isinstance(finding, dict) else \
            displayed[finding.match_start: finding.match_end]
        quote = finding["matched_quote"] if isinstance(finding, dict) else finding.matched_quote
        assert " ".join(span.split()) == quote

    # And the raw text would NOT have worked, which is the bug.
    assert crlf != displayed


# ---------------------------------------------------------------------------
# The model could delete a deterministic finding by relabelling its clause
# ---------------------------------------------------------------------------

def test_reclassification_can_add_a_finding_but_never_remove_one():
    """Most rules are gated on clause category, so a model relabel silently
    deleted findings. Calling clause 8 "confidentiality" removed
    NON_COMPETE_POST_TERM -- the rule that matters most, since Contract Act s.27
    voids the clause outright -- and demoted the clause out of HOT. The model is
    meant to explain what the rules found, never to decide whether a finding
    exists."""
    from src.agents.contract_nodes import clause_classifier as node
    from src.core.red_flag_rules import evaluate_clauses
    from src.schemas.contract import ClauseCategory, PartyPosition
    from src.schemas.contract_review import ClauseLabel, ClauseLabelBatch

    _, clauses = _employment()
    before = {f.rule_id for f in evaluate_clauses(clauses, PartyPosition.EMPLOYEE)}
    non_compete = next(c for c in clauses if c.number == "8")
    assert "NON_COMPETE_POST_TERM" in before

    class Relabel:
        def with_structured_output(self, *_):
            return self

        async def ainvoke(self, *_):
            return ClauseLabelBatch(labels=[ClauseLabel(
                clause_index=non_compete.index,
                category=ClauseCategory.CONFIDENTIALITY,
                confidence=0.95,
                reason="model thinks this is confidentiality",
            )])

    state = {
        "clauses": clauses, "position": "EMPLOYEE",
        "llm_available": True, "llm_calls_used": 0, "degraded_nodes": [],
    }
    with patch.object(node, "ChatGroq", return_value=Relabel()):
        result = asyncio.run(node.run_clause_classifier(state))

    after = {f.rule_id for f in result["rule_findings"]}
    assert before <= after, f"reclassification lost: {sorted(before - after)}"
    assert result["clause_tier"][non_compete.index] == "HOT"


# ---------------------------------------------------------------------------
# A trailing schedule had no clause boundary
# ---------------------------------------------------------------------------

def test_a_schedule_is_its_own_clause_not_part_of_the_one_above_it():
    """Schedules carry the real commercial terms -- rent, deposit, payment --
    but are rarely numbered. Without a boundary the whole schedule was absorbed
    into the last numbered clause and inherited its category, so every
    category-gated rule missed everything inside it. Found by running a sample
    contract whose deposit terms exist only in a schedule table."""
    from src.schemas.contract import ClauseCategory

    text = (
        "1. LICENCE FEE\nThe Licensee shall pay the monthly fee stated in the "
        "schedule below on or before the fifth day of each calendar month.\n\n"
        "2. GOVERNING LAW\nThis Agreement shall be governed by the laws of India "
        "and the courts at Pune shall have exclusive jurisdiction.\n\n"
        "SCHEDULE\n\n"
        "Security deposit | An interest-free security deposit equivalent to ten "
        "months licence fee, which shall stand forfeited if the Licensee vacates "
        "before the expiry of the lock-in period"
    )
    document = parse_document(text.encode(), "lease.txt")
    clauses = segment_clauses(document)

    schedule = next((c for c in clauses if "forfeited" in c.text), None)
    assert schedule is not None
    governing = next(c for c in clauses if c.number == "2")
    assert "forfeited" not in governing.text, "schedule leaked into the clause above it"
    assert schedule.category is ClauseCategory.SECURITY_DEPOSIT


def test_a_deposit_term_stated_only_in_a_schedule_is_still_found():
    from src.core.red_flag_rules import evaluate_clauses, verify_quotes
    from src.schemas.contract import PartyPosition

    text = (
        "1. PREMISES\nThe Licensor grants the Licensee a licence to occupy Flat 402 "
        "for a period of eleven months from the commencement date stated below.\n\n"
        "2. GOVERNING LAW\nThis Agreement shall be governed by the laws of India "
        "and the courts at Pune shall have exclusive jurisdiction.\n\n"
        "SCHEDULE\n\n"
        "Security deposit | An interest-free security deposit equivalent to ten "
        "months licence fee, which shall stand forfeited if the Licensee vacates early"
    )
    document = parse_document(text.encode(), "lease.txt")
    findings = evaluate_clauses(segment_clauses(document), PartyPosition.TENANT)
    assert "EXCESSIVE_SECURITY_DEPOSIT" in {f.rule_id for f in findings}
    assert verify_quotes(findings, document.text) == []


# ---------------------------------------------------------------------------
# "after you leave" is how an offer letter says it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wording", [
    # Real offer-letter prose. The pattern knew "leaving" but not "leave", and
    # "competes" fell outside competing/competitor, so this matched nothing.
    "During your employment and for a period of eighteen months after you leave "
    "the Company for any reason, you shall not accept employment with, or render "
    "services to, any organisation that competes with the business of the Company",
    "For one year after you exit the Company you shall not join any competitor "
    "of the Company in India",
    "You shall not render services to any competitive business for twelve months "
    "once you depart from the Company",
])
def test_an_offer_letter_non_compete_is_found(wording):
    from src.core.clause_segmenter import classify_clause
    from src.core.red_flag_rules import evaluate_clause
    from src.schemas.contract import Clause, ClauseCategory, PartyPosition

    category, _ = classify_clause(wording, None)
    assert category is ClauseCategory.NON_COMPETE
    clause = Clause(
        index=0, number=None, heading=None, text=wording,
        start_offset=0, end_offset=len(wording), body_offset=0, category=category,
    )
    fired = {f.rule_id for f in evaluate_clause(clause, PartyPosition.EMPLOYEE)}
    assert "NON_COMPETE_POST_TERM" in fired


def test_annual_leave_is_not_mistaken_for_leaving_the_company():
    """The fair sample contract has a LEAVE clause; widening the pattern to
    reach "after you leave" must not make an entitlement look like a restraint."""
    from src.core.clause_segmenter import classify_clause
    from src.core.red_flag_rules import evaluate_clause
    from src.schemas.contract import Clause, PartyPosition

    wording = (
        "The Employee shall be entitled to twenty days of earned leave and twelve "
        "days of casual and sick leave in each calendar year, in addition to "
        "public holidays declared by the Company."
    )
    category, _ = classify_clause(wording, "LEAVE")
    clause = Clause(
        index=0, number="4", heading="LEAVE", text=wording,
        start_offset=0, end_offset=len(wording), body_offset=0, category=category,
    )
    assert evaluate_clause(clause, PartyPosition.EMPLOYEE) == []


# ---------------------------------------------------------------------------
# The sample contracts must keep behaving as documented
# ---------------------------------------------------------------------------

def test_the_fair_sample_contract_raises_nothing():
    """The most important sample. A rule that fires on a fair contract teaches
    people to ignore the review."""
    import pathlib as _pathlib

    from src.core.red_flag_rules import evaluate_clauses
    from src.schemas.contract import PartyPosition

    sample = _pathlib.Path("samples/04_employment_fair.pdf")
    if not sample.exists():
        pytest.skip("run scripts/generate_sample_contracts.py first")
    document = parse_document(sample.read_bytes(), sample.name)
    assert evaluate_clauses(segment_clauses(document), PartyPosition.EMPLOYEE) == []


def test_the_blank_sample_is_still_refused():
    """OCR removes the refusal for scans that carry text. A page with nothing on
    it is not such a case, and must not start passing."""
    import pathlib as _pathlib

    from src.core.document_parser import DocumentParseError

    sample = _pathlib.Path("samples/06_scanned_no_text_layer.pdf")
    if not sample.exists():
        pytest.skip("run scripts/generate_sample_contracts.py first")
    with pytest.raises(DocumentParseError, match="[Nn]othing could be read|scan or an image"):
        parse_document(sample.read_bytes(), sample.name)
