from src.agents.state import GraphState
from src.core.logger import pipeline_logger
from src.core.reranker import reranker


async def run_cross_encoder_reranker(state: GraphState) -> GraphState:
    candidates = state.get("candidate_chunks", [])
    procedural_candidates = state.get("candidate_procedural_chunks", [])
    query = state.get("search_query_dense") or state["scenario_text"]

    pipeline_logger.log_step(
        "STEP 3: LEGAL RERANKER",
        f"Processing {len(candidates)} substantive + {len(procedural_candidates)} "
        "procedural candidates -> Filtering top provisions per pool",
    )

    # The two pools are reranked independently. Scoring them together would put
    # BNS offences and BNSS/BSA procedure in one ranking, which is what the
    # offence-identification pass is meant to avoid.
    top_provisions = await reranker.rerank(
        query=query, candidate_chunks=candidates, top_k=10
    )
    top_procedural = await reranker.rerank(
        query=query, candidate_chunks=procedural_candidates, top_k=5
    )

    # Record whether the cross-encoder actually ran. A silent fall back to RRF
    # ordering must cap the confidence estimate rather than pass unnoticed.
    reranker_available = reranker.is_available

    pipeline_logger.log_step(
        "STEP 3: LEGAL RERANKER",
        f"Selected top {len(top_provisions)} offence provisions and "
        f"{len(top_procedural)} procedural provisions -> Next: Legal Analyst Agent",
        status="SUCCESS",
    )

    return {
        **state,
        "retrieved_chunks": top_provisions,
        "procedural_chunks": top_procedural,
        "reranker_available": reranker_available,
    }
