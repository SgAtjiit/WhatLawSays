from langgraph.graph import END, START, StateGraph
from src.agents.nodes.analyst import run_legal_analyst
from src.agents.nodes.compiler import run_response_compiler
from src.agents.nodes.extractor import run_fact_extractor
from src.agents.nodes.query_builder import run_legal_query_builder
from src.agents.nodes.reranker_node import run_cross_encoder_reranker
from src.agents.nodes.retriever import run_hybrid_retriever
from src.agents.nodes.verifier import run_verifier
from src.agents.state import GraphState


def build_graph():
    workflow = StateGraph(GraphState)

    # 1. Add all graph nodes according to system architecture
    workflow.add_node("extractor", run_fact_extractor)
    workflow.add_node("query_builder", run_legal_query_builder)
    workflow.add_node("retriever", run_hybrid_retriever)
    workflow.add_node("reranker", run_cross_encoder_reranker)
    workflow.add_node("analyst", run_legal_analyst)
    workflow.add_node("verifier", run_verifier)
    workflow.add_node("compiler", run_response_compiler)

    # 2. Define routing logic functions
    def route_from_extractor(state: GraphState) -> str:
        facts = state.get("extracted_facts")
        if facts and getattr(facts, "should_early_exit", False):
            return END
        if state.get("final_response") and state["final_response"].get("status") == "NEEDS_CLARIFICATION":
            return END
        return "query_builder"


    def route_from_verifier(state: GraphState) -> str:
        # If verification passed, move to compiler
        if state.get("verification_passed", False):
            return "compiler"
        # If max retries (3) reached, proceed to compiler to prevent infinite loops
        if state.get("retry_count", 0) >= 3:
            return "compiler"
        # Otherwise, retry analyst with verifier feedback
        return "analyst"

    # 3. Connect workflow edges
    workflow.add_edge(START, "extractor")

    workflow.add_conditional_edges(
        "extractor",
        route_from_extractor,
        {"query_builder": "query_builder", END: END},
    )

    workflow.add_edge("query_builder", "retriever")
    workflow.add_edge("retriever", "reranker")
    workflow.add_edge("reranker", "analyst")
    workflow.add_edge("analyst", "verifier")

    workflow.add_conditional_edges(
        "verifier",
        route_from_verifier,
        {"compiler": "compiler", "analyst": "analyst"},
    )

    workflow.add_edge("compiler", END)

    # Compile into executable LangGraph app
    return workflow.compile()


legal_agent_app = build_graph()