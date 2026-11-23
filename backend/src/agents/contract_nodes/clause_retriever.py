import asyncio
from src.agents.contract_state import ContractGraphState
from src.config import settings
from src.core.acts import CONTRACT_ACTS
from src.core.logger import pipeline_logger
from src.core.reranker import reranker
from src.core.vector_store import vector_store

STAGE = "CONTRACT QDRANT RETRIEVER"

_CANDIDATES_PER_CLAUSE = 12
_KEEP_PER_CLAUSE = 5


async def run_clause_retriever(state: ContractGraphState) -> ContractGraphState:
    queries = state.get("clause_queries", {})
    hot = [i for i in state.get("hot_clause_indices", []) if i in queries]

    pipeline_logger.log_step(
        STAGE,
        f"Act-scoped hybrid search over the civil pool for {len(hot)} HOT clauses -> Next: Clause Explainer",
        details={"pool": CONTRACT_ACTS},
    )

    # One Qdrant round trip per HOT clause, bounded by the same semaphore budget
    # as the LLM work: each search embeds its query with fastembed, which is CPU
    # work in this process rather than a free network call.
    semaphore = asyncio.Semaphore(max(1, settings.CONTRACT_LLM_CONCURRENCY))

    async def search(index: int):
        spec = queries[index]
        # Where the model rewrote the query, search its version and the
        # deterministic one together: the rule query is the measured baseline and
        # must not be lost to a worse model paraphrase.
        text = " ".join(
            part for part in (spec.get("dense"), spec.get("sparse"), spec.get("rule_dense")) if part
        )
        async with semaphore:
            try:
                candidates = await vector_store.hybrid_search(
                    query_text=text, limit=_CANDIDATES_PER_CLAUSE, acts=CONTRACT_ACTS
                )
                return index, await reranker.rerank(text, candidates, top_k=_KEEP_PER_CLAUSE)
            except Exception:
                return index, []

    settled = await asyncio.gather(*(search(i) for i in hot), return_exceptions=True)

    clause_chunks = {}
    for item in settled:
        if isinstance(item, BaseException):
            continue
        index, chunks = item
        clause_chunks[index] = chunks

    retrieved = sum(len(v) for v in clause_chunks.values())
    pipeline_logger.log_step(
        STAGE,
        f"Retrieved {retrieved} provisions across {len(clause_chunks)} clauses -> Next: Clause Explainer",
        details=[
            f"[clause {i}] {c.get('act', '')[:30]} {c.get('section_number', '')}: {c.get('title', '')[:40]}"
            for i, chunks in list(clause_chunks.items())[:5]
            for c in chunks[:2]
        ],
        status="SUCCESS",
    )

    return {
        **state,
        "clause_chunks": clause_chunks,
        "reranker_available": reranker.is_available,
    }
