"""The procurement review graph.

Shorter than the contract graph, and the reason is worth stating rather than
apologising for. The contract graph is long because a contract is prose: it has
to be segmented, classified, retrieved against, explained and analysed before
anything can be said about it, and each of those is a place a model earns its
keep. A sourcing event arrives as typed, structured data, and the whole
compliance determination over it is deterministic -- so the graph is not where
the work happens here. It runs *after* `evaluate_procurement`, and its job is to
attach the statute's own words and write the result up.

    (evaluate_procurement, bid integrity, PO sub-review -- all before ainvoke)
      START -> event_profiler
            -> statute_retriever
            -> narrator
            -> narrative_verifier --(ungrounded numbers)--> narrator
            -> procurement_compiler -> END

The retry loop exists for one failure: the write-up stating a number the review
does not contain. That is a false statement of fact about somebody's money sitting
next to findings that carry statutory citations, and a reader cannot tell them
apart -- so it is retried, and if it will not ground, the deterministic summary
is used instead.
"""

from langgraph.graph import END, START, StateGraph

from src.agents.procurement_nodes.compiler import run_procurement_compiler
from src.agents.procurement_nodes.narrative_verifier import run_narrative_verifier
from src.agents.procurement_nodes.narrator import run_narrator
from src.agents.procurement_nodes.profiler import run_event_profiler
from src.agents.procurement_nodes.statute_retriever import run_statute_retriever
from src.agents.procurement_state import ProcurementGraphState

MAX_NARRATIVE_RETRIES = 3


def build_procurement_graph():
    workflow = StateGraph(ProcurementGraphState)

    workflow.add_node("event_profiler", run_event_profiler)
    workflow.add_node("statute_retriever", run_statute_retriever)
    workflow.add_node("narrator", run_narrator)
    workflow.add_node("narrative_verifier", run_narrative_verifier)
    workflow.add_node("procurement_compiler", run_procurement_compiler)

    def route_from_verifier(state: ProcurementGraphState) -> str:
        if state.get("narrative_passed", False):
            return "procurement_compiler"
        if state.get("retry_count", 0) >= MAX_NARRATIVE_RETRIES:
            return "procurement_compiler"
        # The deterministic summary quotes the findings by construction, so with
        # the model down there is nothing a retry could repair.
        if not state.get("llm_available", True):
            return "procurement_compiler"
        return "narrator"

    workflow.add_edge(START, "event_profiler")
    workflow.add_edge("event_profiler", "statute_retriever")
    workflow.add_edge("statute_retriever", "narrator")
    workflow.add_edge("narrator", "narrative_verifier")
    workflow.add_conditional_edges(
        "narrative_verifier",
        route_from_verifier,
        {"procurement_compiler": "procurement_compiler", "narrator": "narrator"},
    )
    workflow.add_edge("procurement_compiler", END)

    return workflow.compile()


procurement_review_app = build_procurement_graph()
