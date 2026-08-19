from langchain_groq import ChatGroq
from pydantic import BaseModel, Field
from src.agents.state import GraphState
from src.config import settings
from src.core.logger import pipeline_logger


class LegalQueryPayload(BaseModel):
    dense_semantic_query: str = Field(
        ..., description="Clean physical/scenario search query using ONLY explicit user facts"
    )
    sparse_keyword_query: str = Field(
        ..., description="Exact scenario terminology keywords for BM25 retrieval without fake sections"
    )


async def run_legal_query_builder(state: GraphState) -> GraphState:
    explicit_facts = state.get("explicit_facts", [])
    scenario = state["scenario_text"]
    facts = state.get("extracted_facts")

    pipeline_logger.log_step(
        "AGENT 2: LEGAL QUERY BUILDER",
        "Formulating Fact-Clean Search Queries (No Premature Section Injection) -> Next: Qdrant Database",
    )

    try:
        llm = ChatGroq(
            model=settings.GROQ_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=0.0,
        ).with_structured_output(LegalQueryPayload)

        prompt = (
            "You are a strict legal query generator agent.\n"
            "Your objective is to generate clean retrieval queries focusing strictly on the core legal action or incident using explicit facts and user terminology.\n\n"
            "[STRICT FORBIDDEN RULES]\n"
            "1. DO NOT inject assumptions, intent, criminality, illegality, or unauthorized status into queries.\n"
            "2. DO NOT inject section numbers (e.g., 'BNS Section 305', 'BNSS Section 12') unless explicitly mentioned in the user prompt.\n"
            "3. DO NOT inject non-essential demographic keywords ('two women', 'female') or object names ('phone') into sparse queries unless theft/loss/damage of that object is explicitly alleged.\n\n"
            f"User Explicit Facts: {explicit_facts}\n"
            f"Raw Scenario: {scenario}"
        )

        queries: LegalQueryPayload = await llm.ainvoke(prompt)
    except Exception as e:
        pipeline_logger.log_step(
            "AGENT 2: LEGAL QUERY BUILDER",
            f"Groq API Info ({type(e).__name__}). Using Rule-Based Fact-Clean Query Builder Engine.",
            status="WARNING",
        )
        # Rule-based clean query formulation strictly from extracted facts
        clean_terms = []
        if facts:
            clean_terms.extend([facts.action or "", facts.object_involved or ""])
        for ef in explicit_facts:
            clean_terms.append(ef)

        clean_text = " ".join([t for t in clean_terms if t]).strip()
        if not clean_text:
            clean_text = scenario

        queries = LegalQueryPayload(
            dense_semantic_query=f"{clean_text}",
            sparse_keyword_query=f"{clean_text}",
        )

    pipeline_logger.log_step(
        "AGENT 2: LEGAL QUERY BUILDER",
        "Fact-clean queries generated successfully -> Next: Qdrant Vector Store",
        details={
            "dense_query": queries.dense_semantic_query,
            "sparse_query": queries.sparse_keyword_query,
        },
        status="SUCCESS",
    )

    return {
        **state,
        "search_query_dense": queries.dense_semantic_query,
        "search_query_sparse": queries.sparse_keyword_query,
    }
