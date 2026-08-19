from src.agents.state import GraphState
from src.core.logger import pipeline_logger
from src.core.reranker import reranker


async def run_cross_encoder_reranker(state: GraphState) -> GraphState:
    candidates = state.get("candidate_chunks", [])
    query = state.get("search_query_dense") or state["scenario_text"]

    pipeline_logger.log_step(
        "STEP 3: LEGAL RERANKER",
        f"Processing {len(candidates)} candidate chunks -> Filtering Top 8–12 Verified Provisions",
    )

    top_provisions = await reranker.rerank(
        query=query, candidate_chunks=candidates, top_k=10
    )

    pipeline_logger.log_step(
        "STEP 3: LEGAL RERANKER",
        f"Selected Top {len(top_provisions)} provisions -> Next: Legal Analyst Agent",
        status="SUCCESS",
    )

    return {**state, "retrieved_chunks": top_provisions}
