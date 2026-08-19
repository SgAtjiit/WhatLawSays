from src.agents.state import GraphState
from src.core.logger import pipeline_logger
from src.core.vector_store import vector_store


async def run_hybrid_retriever(state: GraphState) -> GraphState:
    dense_q = state.get("search_query_dense") or state["scenario_text"]
    sparse_q = state.get("search_query_sparse") or dense_q
    domain = state.get("scenario_domain", "POTENTIAL_CRIMINAL")

    pipeline_logger.log_step(
        "QDRANT VECTOR STORE",
        f"Executing Unfiltered Hybrid Search (Top 30 Dense + Top 30 BM25) across full legal corpus...",
        details={"dense_query": dense_q, "sparse_query": sparse_q, "scenario_domain": domain},
    )

    # Retrieve top 30 candidate chunks from Qdrant across ALL legal statutes (BNS, BNSS, BSS, Constitution)
    retrieved_payloads = await vector_store.hybrid_search(
        query_text=f"{dense_q} {sparse_q}", limit=30
    )

    pipeline_logger.log_step(
        "QDRANT VECTOR STORE",
        f"Retrieved {len(retrieved_payloads)} candidate provisions (Unfiltered Retrieval Recall) -> Next: Legal Reranker",
        details=[
            f"[{doc.get('act', '')} {doc.get('section_number', '')}] {doc.get('title', '')}"
            for doc in retrieved_payloads[:8]
        ],
        status="SUCCESS",
    )

    return {**state, "candidate_chunks": retrieved_payloads}