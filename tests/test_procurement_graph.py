"""The procurement graph: statutory text, the write-up, and its guard rails.

The graph cannot change what a check found -- that is the point of running
evaluation before `ainvoke` -- so these tests are about the two things it can get
wrong: attaching the wrong statute, and writing a summary that states a number
the review does not contain.
"""

from datetime import datetime
from decimal import Decimal as D
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.procurement_nodes.narrative_verifier import run_narrative_verifier
from src.agents.procurement_nodes.narrator import run_narrator
from src.agents.procurement_nodes.compiler import run_procurement_compiler
from src.agents.procurement_nodes.statute_retriever import run_statute_retriever
from src.agents.procurement_graph import MAX_NARRATIVE_RETRIES, build_procurement_graph
from src.core.procurement_rules import evaluate_procurement
from src.schemas.procurement import (
    Approval,
    Award,
    Bid,
    CheckStatus,
    MsmeStatus,
    ProcurementEvent,
    PurchaseOrder,
    Vendor,
)
from src.schemas.procurement_review import AwardNarrative, FindingNote


def event():
    vendor = Vendor(vendor_id="V-1", name="Alpha", msme_status=MsmeStatus.SMALL,
                    on_approved_list=True)
    return ProcurementEvent(
        event_id="E-1", category="MRO",
        bids=[Bid(vendor=vendor, total=D("620000"))],
        award=Award(vendor_id="V-1", value=D("620000"), decided_at=datetime(2026, 3, 1)),
        approvals=[Approval(approver_role="CFO", approved_at=datetime(2026, 2, 28),
                            stage="AWARD")],
        purchase_order=PurchaseOrder(po_number="PO-1", vendor_id="V-1", value=D("620000"),
                                     payment_terms_days=60, has_written_agreement=True,
                                     issued_at=datetime(2026, 3, 2)),
        provided_collections={"bids", "approvals", "purchase_order", "vendor_msme_status"},
    )


def state(**kw):
    ev = kw.pop("event_obj", None) or event()
    base = {
        "task_id": "T", "event": ev, "side": "BUYER",
        "outcomes": evaluate_procurement(ev).outcomes,
        "statutory_context": {}, "retry_count": 0,
        "llm_available": True, "degraded_nodes": [], "narrative_problems": [],
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Statutory text
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_statute_is_fetched_by_identity_not_searched_for():
    """A citation names its section, so it is retrieved, not ranked for."""
    captured = {}

    async def fake_fetch(wanted):
        captured["wanted"] = list(wanted)
        return {
            w: {"act": w[0], "section_number": w[1], "title": "T", "content": "the text"}
            for w in wanted
        }

    with patch("src.core.vector_store.vector_store.fetch_sections", new=fake_fetch):
        result = await run_statute_retriever(state())

    assert captured["wanted"], "nothing was requested"
    assert any(section == "Section 15" for _, section in captured["wanted"])
    assert result["statutory_context"]


@pytest.mark.anyio
async def test_a_section_missing_from_the_corpus_loses_the_text_not_the_finding():
    async def fake_fetch(wanted):
        return {}

    with patch("src.core.vector_store.vector_store.fetch_sections", new=fake_fetch):
        result = await run_statute_retriever(state())

    assert result["statutory_context"] == {}
    assert result["outcomes"], "the findings must survive a corpus gap"


@pytest.mark.anyio
async def test_retrieval_failure_degrades_rather_than_raising():
    with patch("src.core.vector_store.vector_store.fetch_sections",
               new=AsyncMock(side_effect=RuntimeError("no qdrant"))):
        result = await run_statute_retriever(state())
    assert result["statutory_context"] == {}
    assert any("statutory context" in d for d in result["degraded_nodes"])


# ---------------------------------------------------------------------------
# The narrator
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_with_no_model_the_summary_is_written_from_the_findings():
    with patch("src.agents.procurement_nodes.narrator.ChatGroq",
               side_effect=RuntimeError("Groq unreachable")):
        result = await run_narrator(state())
    narrative = result["narrative"]
    assert narrative["source"] == "rule"
    assert narrative["headline"] and narrative["what_to_do_first"]
    assert result["llm_available"] is False


@pytest.mark.anyio
async def test_the_fallback_headline_is_grammatical():
    with patch("src.agents.procurement_nodes.narrator.ChatGroq",
               side_effect=RuntimeError("down")):
        result = await run_narrator(state())
    headline = result["narrative"]["headline"]
    assert "(s)" not in headline
    assert ", and and" not in headline
    assert headline.endswith(".")


@pytest.mark.anyio
async def test_a_note_about_a_check_not_in_this_review_is_dropped():
    """A note about nothing must not be shown against the wrong finding."""
    fake = AsyncMock(return_value=AwardNarrative(
        headline="Two things need attention.",
        what_to_do_first="Fix the payment term.",
        notes=[
            FindingNote(check_id="MSMED_TERM_EXCEEDS_STATUTORY_CAP", note="Real one."),
            FindingNote(check_id="A_CHECK_THAT_DOES_NOT_EXIST", note="Invented."),
        ],
    ))
    with patch("src.agents.procurement_nodes.narrator.ChatGroq") as chat:
        chat.return_value.with_structured_output.return_value.ainvoke = fake
        result = await run_narrator(state())
    ids = {n["check_id"] for n in result["narrative"]["notes"]}
    assert ids == {"MSMED_TERM_EXCEEDS_STATUTORY_CAP"}


# ---------------------------------------------------------------------------
# The verifier -- the reason the retry loop exists
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_a_number_the_review_does_not_contain_is_rejected():
    """A wrong figure about somebody's money reads exactly like a right one."""
    result = await run_narrative_verifier(state(narrative={
        "headline": "The payment term of 987654 days breaches the Act.",
        "what_to_do_first": "Fix it.",
        "notes": [],
        "source": "llm",
    }))
    assert result["narrative_passed"] is False
    assert any("987654" in p for p in result["narrative_problems"])
    assert result["retry_count"] == 1


@pytest.mark.anyio
async def test_numbers_that_are_in_the_review_pass():
    result = await run_narrative_verifier(state(narrative={
        "headline": "The payment term of 60 days exceeds the 45-day ceiling.",
        "what_to_do_first": "Cut it to 45 days.",
        "notes": [],
        "source": "llm",
    }))
    assert result["narrative_passed"] is True


@pytest.mark.anyio
async def test_describing_an_unperformed_check_as_passing_is_rejected():
    """The single most dangerous sentence this system could write."""
    base = state()
    gap = next(o for o in base["outcomes"] if o.status == CheckStatus.UNDETERMINED)
    result = await run_narrative_verifier(state(narrative={
        "headline": "All good.",
        "what_to_do_first": "Nothing.",
        "notes": [{"check_id": gap.check_id, "note": "This one passed, no issue here."}],
        "source": "llm",
    }))
    assert result["narrative_passed"] is False
    assert any("describes it as having passed" in p for p in result["narrative_problems"])


@pytest.mark.anyio
async def test_the_deterministic_summary_is_never_second_guessed():
    result = await run_narrative_verifier(state(narrative={
        "headline": "Anything at all, 999999.", "what_to_do_first": "x",
        "notes": [], "source": "rule",
    }))
    assert result["narrative_passed"] is True


@pytest.mark.anyio
async def test_a_narrative_that_never_grounds_is_replaced_not_shown():
    result = await run_procurement_compiler(state(
        narrative={"headline": "999999 breaches.", "what_to_do_first": "x",
                   "notes": [], "source": "llm"},
        narrative_passed=False,
    ))
    assert result["narrative"]["source"] == "rule"
    assert any("not in the review" in d for d in result["degraded_nodes"])


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

def test_the_retry_loop_is_bounded():
    assert MAX_NARRATIVE_RETRIES == 3


@pytest.mark.anyio
async def test_the_graph_runs_end_to_end_with_everything_down():
    """Both services unreachable must still produce a complete write-up."""
    app = build_procurement_graph()
    with patch("src.agents.procurement_nodes.narrator.ChatGroq",
               side_effect=RuntimeError("down")), \
         patch("src.core.vector_store.vector_store.fetch_sections",
               new=AsyncMock(side_effect=RuntimeError("no qdrant"))):
        final = await app.ainvoke(state())
    enriched = final["final_state"]
    assert enriched["narrative"]["source"] == "rule"
    assert enriched["llm_available"] is False
    assert enriched["degraded_nodes"]
