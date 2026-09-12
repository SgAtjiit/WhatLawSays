"""Tests for Phase 7: contract Q&A, redlines and PDF export.

Q&A is the part with real teeth. An answer about a contract that cannot say
which clause it rests on is unverifiable, and an answer drawn from what
contracts usually say is how a reader ends up believing their agreement contains
a protection it does not.
"""

import asyncio
import contextlib
import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.core.clause_search import search_clauses, tokenize
from src.core.clause_segmenter import segment_clauses
from src.core.contract_qa import answer_question
from src.core.document_parser import parse_document
from src.core.red_flag_rules import RULES, evaluate_clauses
from src.core.redlines import REDLINES, build_redlines, redline_for
from src.core.report_export import build_report_pdf
from src.main import app
from src.schemas.contract import PartyPosition


def _dead(*args, **kwargs):
    raise RuntimeError("Groq unreachable")


@pytest.fixture(scope="module")
def employment():
    with open("tests/fixtures/employment_agreement.txt", "rb") as handle:
        document = parse_document(handle.read(), "e.txt")
    clauses = segment_clauses(document)
    return document, clauses, evaluate_clauses(clauses, PartyPosition.EMPLOYEE)


# ---------------------------------------------------------------------------
# Clause search
# ---------------------------------------------------------------------------

def test_tokenizer_drops_contract_boilerplate():
    """'agreement', 'party' and 'shall' appear in nearly every clause and would
    otherwise dominate the score."""
    assert tokenize("The party shall, under this agreement, pay rent") == ["pay", "rent"]


@pytest.mark.parametrize("question,expected_number", [
    ("what is my notice period", "5"),
    ("can they fire me without a reason", "5"),
    ("how much is my salary", "2"),
    ("can I join a competitor after leaving", "8"),
    ("what happens to inventions I create", "7"),
    ("who picks the arbitrator", "10"),
])
def test_a_question_lands_on_the_clause_that_answers_it(employment, question, expected_number):
    _, clauses, _ = employment
    hits = search_clauses(clauses, question, limit=1)
    assert hits, question
    assert clauses[hits[0].clause_index].number == expected_number


def test_search_is_deterministic(employment):
    _, clauses, _ = employment
    first = [h.clause_index for h in search_clauses(clauses, "notice period")]
    second = [h.clause_index for h in search_clauses(clauses, "notice period")]
    assert first == second


def test_a_question_about_nothing_in_the_contract_returns_no_hits(employment):
    _, clauses, _ = employment
    assert search_clauses(clauses, "parking space allocation for bicycles") == []


def test_headings_outweigh_incidental_mentions(employment):
    """'termination' appears in half the clauses of an employment contract, but
    only one is the termination clause."""
    _, clauses, _ = employment
    top = search_clauses(clauses, "termination", limit=1)[0]
    assert clauses[top.clause_index].heading == "TERMINATION"


# ---------------------------------------------------------------------------
# Q&A
# ---------------------------------------------------------------------------

def _ask(question, clauses, findings=None):
    with patch("src.core.contract_qa.ChatGroq", side_effect=_dead):
        return asyncio.run(
            answer_question(
                question=question,
                clauses=clauses,
                findings=[f.model_dump(mode="json") for f in (findings or [])],
                position="EMPLOYEE",
            )
        )


def test_an_answer_cites_the_clauses_it_rests_on(employment):
    _, clauses, findings = employment
    result = _ask("what is my notice period", clauses, findings)
    assert result["cited_clauses"]
    assert all(c["text"] for c in result["cited_clauses"])
    assert result["answered_from_contract"]


def test_a_question_the_contract_does_not_address_is_told_so(employment):
    """Not answered from what contracts usually say."""
    _, clauses, _ = employment
    result = _ask("is there a parking space for my bicycle", clauses)
    assert result["answered_from_contract"] is False
    assert result["cited_clauses"] == []
    assert "does not" in result["answer"].lower() or "nothing" in result["answer"].lower()


def test_the_rule_based_answer_points_at_clauses_rather_than_pretending_to_compose(employment):
    _, clauses, _ = employment
    result = _ask("what is my notice period", clauses)
    assert result["degraded"]
    assert "Clause 5" in result["answer"]


def test_statutory_context_comes_from_verified_findings_not_fresh_retrieval(employment):
    """The citations attached to the cited clauses were placed by rules and
    checked; a fresh retrieval against a free-text question would be a new,
    unverified claim."""
    _, clauses, findings = employment
    result = _ask("can I join a competitor after leaving", clauses, findings)
    sections = {c["section_number"] for c in result["statutory_context"]}
    assert "Section 27" in sections


def test_a_model_citation_outside_the_clauses_it_was_shown_is_dropped(employment):
    """The model may only cite clauses it was given."""
    _, clauses, _ = employment

    class FakeAnswer:
        answer = "You have ninety days."
        answered_from_contract = True
        cited_clauses = [4, 999]

    class FakeLLM:
        def with_structured_output(self, *_):
            return self

        async def ainvoke(self, *_):
            return FakeAnswer()

    with patch("src.core.contract_qa.ChatGroq", return_value=FakeLLM()):
        result = asyncio.run(
            answer_question(question="notice period", clauses=clauses, position="EMPLOYEE")
        )
    assert [c["index"] for c in result["cited_clauses"]] == [4]


# ---------------------------------------------------------------------------
# Redlines
# ---------------------------------------------------------------------------

def test_every_rule_has_a_specific_redline():
    """A finding with no ask is a complaint without a remedy."""
    missing = {rule.rule_id for rule in RULES} - set(REDLINES)
    assert not missing, sorted(missing)


def test_redlines_are_deduplicated_per_rule_and_ordered_worst_first(employment):
    _, _, findings = employment
    doubled = list(findings) + list(findings)
    redlines = build_redlines(doubled)
    assert len({r.rule_id for r in redlines}) == len(redlines)
    from src.schemas.contract import SEVERITY_ORDER

    ranks = [SEVERITY_ORDER[r.severity] for r in redlines]
    assert ranks == sorted(ranks, reverse=True)


def test_a_redline_carries_the_finding_it_answers(employment):
    _, _, findings = employment
    non_compete = next(f for f in findings if f.rule_id == "NON_COMPETE_POST_TERM")
    redline = redline_for(non_compete)
    assert redline.clause_number == non_compete.clause_number
    assert redline.severity is non_compete.severity
    assert "delete" in redline.ask.lower()
    assert redline.suggested_wording and redline.fallback


def test_an_unknown_rule_still_gets_a_generic_ask():
    redline = redline_for({"rule_id": "LLM_SOMETHING_NEW", "title": "x", "severity": "LOW"})
    assert redline.source == "generic"
    assert redline.ask


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

def _offline_review():
    from src.core.contract_service import review_contract
    from src.schemas.contract import ContractType

    with open("tests/fixtures/employment_agreement.txt", "rb") as handle:
        data = handle.read()

    async def run():
        with contextlib.ExitStack() as stack:
            for name in ["profiler", "clause_classifier", "query_builder", "explainer", "red_flag_analyst"]:
                stack.enter_context(
                    patch(f"src.agents.contract_nodes.{name}.ChatGroq", side_effect=_dead)
                )
            stack.enter_context(
                patch("src.agents.contract_nodes.clause_retriever.vector_store.hybrid_search",
                      side_effect=RuntimeError("no qdrant"))
            )
            return await review_contract(
                data=data, filename="e.txt", persist=False,
                contract_type=ContractType.EMPLOYMENT, position=PartyPosition.EMPLOYEE,
            )

    return asyncio.run(run())


@pytest.fixture(scope="module")
def review():
    return _offline_review()


def test_the_review_response_carries_redlines(review):
    assert review["redlines"]
    assert {r["rule_id"] for r in review["redlines"]} <= {f["rule_id"] for f in review["findings"]}


def test_the_pdf_is_a_pdf_and_says_what_the_review_says(review):
    from pypdf import PdfReader

    pdf = build_report_pdf(review, review["redlines"])
    assert pdf.startswith(b"%PDF-")
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "What to ask for" in text
    assert "Post-employment non-compete" in text
    # Every quote the review made must survive into the document.
    for finding in review["findings"]:
        assert finding["matched_quote"][:40] in text.replace("\n", " ")


def test_the_pdf_carries_the_confidence_basis_not_just_the_number(review):
    from pypdf import PdfReader

    text = "\n".join(
        page.extract_text()
        for page in PdfReader(io.BytesIO(build_report_pdf(review, review["redlines"]))).pages
    )
    assert "How confident this review is" in text
    assert "not a calibrated probability" in text


def test_the_pdf_survives_hostile_characters():
    review = {
        "contract_type": "OTHER", "position": "UNKNOWN", "position_source": "UNKNOWN",
        "overall_risk": "LOW", "risk_counts": {}, "clause_count": 1, "analysed_clause_count": 1,
        "confidence_score": 0.5, "confidence_basis": {"components": {}, "caps_applied": [], "notes": []},
        "findings": [{
            "severity": "LOW", "title": "<b>Bold</b> & 'quotes'", "detector": "rule",
            "clause_number": "1", "plain_summary": "<script>alert(1)</script>",
            "matched_quote": "5 < 6 & 7 > 3", "why_it_matters": "x", "citations": [],
        }],
        "missing_clauses": [], "consistency_issues": [], "disclaimer": "d",
    }
    assert build_report_pdf(review, []).startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def uploaded(client):
    from src.api.v1.endpoints import contracts as endpoint

    endpoint._UPLOAD_HISTORY.clear()
    with open("tests/fixtures/employment_agreement.txt", "rb") as handle:
        data = handle.read()
    with contextlib.ExitStack() as stack:
        for name in ["profiler", "clause_classifier", "query_builder", "explainer", "red_flag_analyst"]:
            stack.enter_context(
                patch(f"src.agents.contract_nodes.{name}.ChatGroq", side_effect=_dead)
            )
        stack.enter_context(
            patch("src.agents.contract_nodes.clause_retriever.vector_store.hybrid_search",
                  side_effect=RuntimeError("no qdrant"))
        )
        response = client.post(
            "/api/v1/contracts",
            files={"file": ("e.txt", io.BytesIO(data), "text/plain")},
            data={"contract_type": "EMPLOYMENT", "position": "EMPLOYEE"},
        )
    assert response.status_code == 200
    yield response.json()
    client.delete(f"/api/v1/contracts/{response.json()['contract_id']}")


def test_asking_over_http_returns_a_cited_answer(client, uploaded):
    with patch("src.core.contract_qa.ChatGroq", side_effect=_dead):
        response = client.post(
            f"/api/v1/contracts/{uploaded['contract_id']}/ask",
            json={"question": "what is my notice period"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["cited_clauses"]
    assert body["question"] == "what is my notice period"


def test_asking_about_an_unknown_contract_is_a_404(client):
    response = client.post("/api/v1/contracts/nope/ask", json={"question": "anything at all"})
    assert response.status_code == 404


def test_a_too_short_question_is_rejected(client, uploaded):
    response = client.post(f"/api/v1/contracts/{uploaded['contract_id']}/ask", json={"question": "hi"})
    assert response.status_code == 422


def test_redlines_are_fetchable(client, uploaded):
    response = client.get(f"/api/v1/contracts/{uploaded['contract_id']}/redlines")
    assert response.status_code == 200
    assert response.json()["redlines"]


def test_the_pdf_downloads_as_an_attachment(client, uploaded):
    response = client.get(f"/api/v1/contracts/{uploaded['contract_id']}/report.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# Findings from the audit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("notice", "notices"), ("salary", "salaries"), ("leave", "leaves"),
    ("leave", "leaving"), ("bonus", "bonuses"), ("fire", "fired"),
    ("competitor", "competing"), ("employee", "employer"), ("employ", "employment"),
    ("policy", "policies"), ("clause", "clauses"),
    ("penalty", "penalties"), ("terminate", "termination"),
])
def test_a_word_and_its_inflections_share_a_stem(a, b):
    """A question about notices must reach the notice clause."""
    from src.core.clause_search import stem

    assert stem(a) == stem(b), (stem(a), stem(b))


def test_unrelated_words_keep_distinct_stems():
    from src.core.clause_search import stem

    assert stem("termination") != stem("terms")
    assert stem("status") == "status"


class _Answer:
    def __init__(self, **kw):
        self.answer = kw.get("answer", "An answer.")
        self.answered_from_contract = kw.get("answered_from_contract", True)
        self.cited_clauses = kw.get("cited_clauses", [])


def _fake_llm(answer):
    class FakeLLM:
        def with_structured_output(self, *_):
            return self

        async def ainvoke(self, *_):
            return answer

    return FakeLLM()


def _ask_with(answer, question, clauses, findings=None):
    with patch("src.core.contract_qa.ChatGroq", return_value=_fake_llm(answer)):
        return asyncio.run(
            answer_question(
                question=question, clauses=clauses,
                findings=[f.model_dump(mode="json") for f in (findings or [])],
                position="EMPLOYEE",
            )
        )


def test_a_citation_of_a_clause_the_model_was_not_shown_is_dropped(employment):
    """The check used to run against the whole contract, so an unseen
    governing-law clause passed as grounded."""
    _, clauses, _ = employment
    hits = {h.clause_index for h in search_clauses(clauses, "notice period", limit=5)}
    unseen = next(c.index for c in clauses if c.index not in hits)
    result = _ask_with(_Answer(cited_clauses=[unseen]), "notice period", clauses)
    assert unseen not in {c["index"] for c in result["cited_clauses"]}


def test_not_answered_means_nothing_cited_and_no_statute_attached(employment):
    """"The contract does not address this" used to arrive with five clauses
    and two statutory citations attached, as though it did."""
    _, clauses, findings = employment
    result = _ask_with(_Answer(answer="Not addressed.", answered_from_contract=False), "notice period", clauses, findings)
    assert result["answered_from_contract"] is False
    assert result["cited_clauses"] == []
    assert result["statutory_context"] == []


def test_statutory_context_follows_the_cited_clause_not_every_hit(employment):
    _, clauses, findings = employment
    termination = next(c.index for c in clauses if c.number == "5")
    result = _ask_with(_Answer(cited_clauses=[termination]), "notice period", clauses, findings)
    assert [c["index"] for c in result["cited_clauses"]] == [termination]
    # The bond clause's s.27/s.74 must not ride along just for being in the top five.
    assert not any(c["section_number"] in ("Section 27", "Section 74") for c in result["statutory_context"])


def test_duplicate_citations_collapse(employment):
    _, clauses, _ = employment
    termination = next(c.index for c in clauses if c.number == "5")
    result = _ask_with(_Answer(cited_clauses=[termination] * 3), "notice period", clauses)
    assert len(result["cited_clauses"]) == 1


def test_an_empty_model_answer_falls_back_to_the_rule_engine(employment):
    _, clauses, _ = employment
    result = _ask_with(_Answer(answer="   "), "notice period", clauses)
    assert result["degraded"]
    assert result["answer"].strip()


@pytest.mark.parametrize("question", ["   ", "🙂🙂🙂", "the and of"])
def test_a_question_with_no_searchable_words_is_told_so(employment, question):
    """Saying "the contract does not address that" would be false: nothing was
    looked up."""
    _, clauses, _ = employment
    with patch("src.core.contract_qa.ChatGroq", side_effect=_dead):
        result = asyncio.run(answer_question(question=question, clauses=clauses))
    assert result["answered_from_contract"] is False
    assert "couldn't find any words" in result["answer"]


def test_a_whitespace_question_is_rejected_over_http(client, uploaded):
    response = client.post(f"/api/v1/contracts/{uploaded['contract_id']}/ask", json={"question": "     "})
    assert response.status_code == 422


def test_the_rupee_sign_survives_into_the_pdf():
    """Helvetica has no glyph for U+20B9, so every amount rendered as a square."""
    from pypdf import PdfReader

    review = {
        "contract_type": "LEASE", "position": "TENANT", "position_source": "USER_DECLARED",
        "overall_risk": "HIGH", "risk_counts": {"HIGH": 1}, "clause_count": 1, "analysed_clause_count": 1,
        "confidence_score": 0.8, "confidence_basis": {"components": {}, "caps_applied": [], "notes": []},
        "findings": [{
            "severity": "HIGH", "title": "Deposit of ₹3,20,000", "detector": "rule", "clause_number": "3",
            "plain_summary": "You pay ₹3,20,000 up front.", "matched_quote": "deposit of ₹3,20,000",
            "why_it_matters": "x", "citations": [],
        }],
        "missing_clauses": [], "consistency_issues": [], "disclaimer": "d",
    }
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(build_report_pdf(review, []))).pages)
    assert "Rs. 3,20,000" in text
    assert "■" not in text and "\u25a0" not in text
