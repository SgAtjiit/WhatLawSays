from src.agents.state import GraphState
from src.core.logger import pipeline_logger
from src.core.vector_store import PROCEDURAL_ACTS, SUBSTANTIVE_ACTS, vector_store


async def run_hybrid_retriever(state: GraphState) -> GraphState:
    dense_q = state.get("search_query_dense") or state["scenario_text"]
    sparse_q = state.get("search_query_sparse") or dense_q
    domain = state.get("scenario_domain", "POTENTIAL_CRIMINAL")
    query_text = f"{dense_q} {sparse_q}"

    pipeline_logger.log_step(
        "QDRANT VECTOR STORE",
        "Executing Act-Scoped Hybrid Search (Dense + BM25, RRF fused) across two pools...",
        details={
            "dense_query": dense_q,
            "sparse_query": sparse_q,
            "scenario_domain": domain,
            "offence_pool": SUBSTANTIVE_ACTS,
            "procedural_pool": PROCEDURAL_ACTS,
        },
    )

    # Pass 1: offence identification, restricted to substantive penal law. Searching
    # the whole corpus left BNS outnumbered ~3:1 (358 of 1580 sections), so
    # procedural and constitutional provisions displaced the offence sections the
    # analyst needs.
    offence_candidates = await vector_store.hybrid_search(
        query_text=query_text, limit=30, acts=SUBSTANTIVE_ACTS
    )

    # Pass 2: procedural and constitutional context, retrieved separately and used
    # only to populate the procedural tab -- never the offences array.
    procedural_candidates = await vector_store.hybrid_search(
        query_text=query_text, limit=15, acts=PROCEDURAL_ACTS
    )

    pipeline_logger.log_step(
        "QDRANT VECTOR STORE",
        f"Retrieved {len(offence_candidates)} substantive (BNS) + "
        f"{len(procedural_candidates)} procedural provisions -> Next: Legal Reranker",
        details=[
            f"[{doc.get('act', '')} {doc.get('section_number', '')}] {doc.get('title', '')}"
            for doc in offence_candidates[:8]
        ],
        status="SUCCESS",
    )

    return {
        **state,
        "candidate_chunks": offence_candidates,
        "candidate_procedural_chunks": procedural_candidates,
    }
