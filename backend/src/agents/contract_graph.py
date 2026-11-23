from langgraph.graph import END, START, StateGraph
from src.agents.contract_nodes.clause_classifier import run_clause_classifier
from src.agents.contract_nodes.contract_compiler import run_contract_compiler
from src.agents.contract_nodes.consistency_checker import run_consistency_checker
from src.agents.contract_nodes.explainer import run_clause_explainer
from src.agents.contract_nodes.gap_detector import run_gap_detector
from src.agents.contract_nodes.grounding_verifier import run_grounding_verifier
from src.agents.contract_nodes.profiler import run_contract_profiler
from src.agents.contract_nodes.query_builder import run_contract_query_builder
from src.agents.contract_nodes.red_flag_analyst import run_red_flag_analyst
from src.agents.contract_nodes.clause_retriever import run_clause_retriever
from src.agents.contract_state import ContractGraphState


def build_contract_graph():
    workflow = StateGraph(ContractGraphState)

    # 1. Add all graph nodes. Parsing and clause segmentation deliberately are
    # NOT nodes: they run before ainvoke, so the grounding retry loop can never
    # re-cut clause boundaries out from under offsets already recorded.
    workflow.add_node("profiler", run_contract_profiler)
    workflow.add_node("clause_classifier", run_clause_classifier)
    workflow.add_node("query_builder", run_contract_query_builder)
    workflow.add_node("clause_retriever", run_clause_retriever)
    workflow.add_node("explainer", run_clause_explainer)
    workflow.add_node("red_flag_analyst", run_red_flag_analyst)
    workflow.add_node("gap_detector", run_gap_detector)
    workflow.add_node("consistency_checker", run_consistency_checker)
    workflow.add_node("grounding_verifier", run_grounding_verifier)
    workflow.add_node("contract_compiler", run_contract_compiler)

    # 2. Define routing logic functions
    def route_from_profiler(state: ContractGraphState) -> str:
        # Bail before spending any retrieval or LLM budget on something that did
        # not segment into a reviewable contract.
        response = state.get("final_response") or {}
        if response.get("status") == "NEEDS_CLARIFICATION":
            return END
        return "clause_classifier"

    def route_from_grounding(state: ContractGraphState) -> str:
        if state.get("grounding_passed", False):
            return "contract_compiler"
        # Max retries reached: proceed and let the compiler drop whatever still
        # fails to ground, rather than loop.
        if state.get("retry_count", 0) >= 3:
            return "contract_compiler"
        # Deterministic findings quote the document by construction, so with the
        # LLM down there is nothing a retry could repair.
        if not state.get("llm_available", True):
            return "contract_compiler"
        return "red_flag_analyst"

    # 3. Connect workflow edges
    workflow.add_edge(START, "profiler")

    workflow.add_conditional_edges(
        "profiler",
        route_from_profiler,
        {"clause_classifier": "clause_classifier", END: END},
    )

    workflow.add_edge("clause_classifier", "query_builder")
    workflow.add_edge("query_builder", "clause_retriever")
    workflow.add_edge("clause_retriever", "explainer")
    workflow.add_edge("explainer", "red_flag_analyst")
    workflow.add_edge("red_flag_analyst", "gap_detector")
    workflow.add_edge("gap_detector", "consistency_checker")
    workflow.add_edge("consistency_checker", "grounding_verifier")

    workflow.add_conditional_edges(
        "grounding_verifier",
        route_from_grounding,
        {"contract_compiler": "contract_compiler", "red_flag_analyst": "red_flag_analyst"},
    )

    workflow.add_edge("contract_compiler", END)

    return workflow.compile()


contract_review_app = build_contract_graph()
