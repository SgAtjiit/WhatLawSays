from langchain_groq import ChatGroq
from src.agents.contract_state import ContractGraphState
from src.config import settings
from src.core.llm_batch import gather_batched
from src.core.logger import pipeline_logger
from src.schemas.contract import ClauseCategory
from src.schemas.contract_review import ClauseQueryBatch

STAGE = "CONTRACT AGENT 3: STATUTORY QUERY BUILDER"

# Contracts and statutes are written in different registers, and the embedding
# model does not bridge the gap. Measured against this corpus:
#
#   "restraint of trade void agreement"                    -> Contract Act s.27 at rank 1
#   "employee shall not join a competing business ..."      -> s.27 absent from the top 5
#
# Retrieval driven by the contract's own wording therefore misses precisely the
# provisions that decide the clause. This table is the deterministic translation,
# and it is not merely a fallback: the clause category is already assigned by
# rules, so the mapping is available with no model call at all.
STATUTORY_QUERIES = {
    ClauseCategory.NON_COMPETE: (
        "agreement in restraint of trade is void, restraining exercise of a lawful profession",
        "restraint trade void lawful profession exercise",
    ),
    ClauseCategory.NON_SOLICIT: (
        "agreement in restraint of trade is void",
        "restraint trade void agreement",
    ),
    ClauseCategory.BOND: (
        "agreement in restraint of trade void, compensation for breach where a penalty is stipulated",
        "restraint trade void penalty stipulated compensation breach",
    ),
    ClauseCategory.LIQUIDATED_DAMAGES: (
        "compensation for breach of contract where a penalty is stipulated for",
        "penalty stipulated reasonable compensation breach",
    ),
    ClauseCategory.DISPUTE_RESOLUTION: (
        "arbitration agreement, grounds for challenge, ineligibility to act as arbitrator, appointment of arbitrators",
        "arbitrator appointment challenge ineligible arbitration agreement",
    ),
    ClauseCategory.GOVERNING_LAW: (
        "agreements in restraint of legal proceedings are void",
        "restraint legal proceedings void jurisdiction ordinary tribunals",
    ),
    ClauseCategory.INDEMNITY: (
        "contract of indemnity, rights of the indemnity-holder when sued",
        "indemnity contract indemnity-holder rights",
    ),
    ClauseCategory.LIABILITY: (
        "compensation for loss or damage caused by breach of contract",
        "compensation loss damage breach contract",
    ),
    ClauseCategory.SECURITY_DEPOSIT: (
        "rights and liabilities of lessor and lessee, relief against forfeiture for non-payment of rent",
        "lessor lessee rights liabilities forfeiture rent",
    ),
    ClauseCategory.RENT: (
        "lease defined, duration of certain leases in absence of written contract",
        "lease defined duration rent lessor lessee",
    ),
    ClauseCategory.LOCK_IN: (
        "determination of lease, rights and liabilities of lessor and lessee",
        "determination lease lessee liabilities",
    ),
    ClauseCategory.MAINTENANCE: (
        "rights and liabilities of lessor and lessee, repairs to the property",
        "lessor lessee repairs property liabilities",
    ),
    ClauseCategory.DATA_PROTECTION: (
        "consent of the data principal, general obligations of a data fiduciary",
        "consent data principal fiduciary obligations personal data",
    ),
    ClauseCategory.AMENDMENT: (
        "unfair contract term, unilateral variation of terms to the prejudice of a party",
        "unfair contract term unilateral variation prejudice",
    ),
    ClauseCategory.ASSIGNMENT: (
        "unfair contract term, assignment of the contract to the detriment of a party",
        "unfair contract assignment detriment consent",
    ),
    ClauseCategory.TERMINATION: (
        "unfair contract term permitting unilateral termination without reasonable cause",
        "unilateral termination without reasonable cause unfair term",
    ),
    ClauseCategory.IP_ASSIGNMENT: (
        "what considerations and objects are lawful, agreement without lawful object is void",
        "lawful object consideration void agreement",
    ),
    ClauseCategory.CONFIDENTIALITY: (
        "agreement in restraint of trade is void",
        "restraint trade void confidential",
    ),
    ClauseCategory.FORCE_MAJEURE: (
        "agreement to do an act afterwards becoming impossible or unlawful is void",
        "impossible unlawful act void frustration contract",
    ),
    ClauseCategory.WARRANTY: (
        "unfair contract term, defect in goods or services, consumer rights",
        "unfair contract defect goods services consumer",
    ),
    ClauseCategory.PAYMENT: (
        "compensation for loss or damage caused by breach of contract",
        "compensation breach contract payment",
    ),
    ClauseCategory.SALARY: (
        "compensation for loss or damage caused by breach of contract",
        "compensation breach contract remuneration",
    ),
    ClauseCategory.NOTICE_PERIOD: (
        "compensation for breach of contract, determination of the contract by notice",
        "notice determination contract breach compensation",
    ),
    ClauseCategory.PROBATION: (
        "compensation for loss or damage caused by breach of contract",
        "compensation breach contract employment",
    ),
}

# Used when a category carries no specific statutory anchor.
_DEFAULT_QUERY = (
    "what considerations and objects are lawful, void agreements",
    "void agreement lawful consideration object",
)


def deterministic_queries(category: ClauseCategory):
    return STATUTORY_QUERIES.get(category, _DEFAULT_QUERY)


async def run_contract_query_builder(state: ContractGraphState) -> ContractGraphState:
    clauses = {c.index: c for c in state.get("clauses", [])}
    hot = state.get("hot_clause_indices", [])

    pipeline_logger.log_step(
        STAGE,
        f"Translating {len(hot)} HOT clauses from contract wording into statutory register -> Next: Clause Retriever",
    )

    # The deterministic table is the baseline for every HOT clause, so retrieval
    # is never left holding the contract's own wording.
    queries = {}
    for index in hot:
        clause = clauses.get(index)
        if clause is None:
            continue
        dense, sparse = deterministic_queries(clause.category)
        queries[index] = {"dense": dense, "sparse": sparse, "source": "rule"}

    llm_available = state.get("llm_available", True)
    llm_calls = state.get("llm_calls_used", 0)
    degraded = list(state.get("degraded_nodes", []))

    if llm_available and hot:
        # Batched like every other model node: one call covering 24 HOT clauses
        # is both a large prompt and an all-or-nothing failure. A dropped batch
        # here costs only its own clauses, which keep their rule-mapped query.
        async def worker(batch):
            llm = ChatGroq(
                model=settings.GROQ_MODEL,
                groq_api_key=settings.GROQ_API_KEY,
                temperature=0.0,
            ).with_structured_output(ClauseQueryBatch)

            listing = "\n\n---\n\n".join(
                f"clause_index={i} category={clauses[i].category.value}\n{clauses[i].text[:700]}"
                for i in batch if i in clauses
            )
            prompt = (
                "You are the Statutory Query Builder for an Indian legal corpus containing "
                "the Indian Contract Act 1872, Transfer of Property Act 1882, Specific Relief "
                "Act 1963, Arbitration and Conciliation Act 1996, Consumer Protection Act 2019 "
                "and the DPDP Act 2023.\n\n"
                "Contract clauses and statute sections are written in different language. "
                "Searching with the contract's own words fails: 'employee shall not join a "
                "competing business' does not retrieve the section that governs it, while "
                "'agreement in restraint of trade void' retrieves it at rank 1.\n\n"
                "[TASK]\n"
                "For each clause, write the query in the words the STATUTE BOOK would use.\n\n"
                "[RULES]\n"
                "1. Use statutory vocabulary: 'restraint of trade', 'liquidated damages', "
                "'determination of lease', 'unfair contract term'.\n"
                "2. NEVER invent or name a section number. You are writing a search query, "
                "not a citation.\n"
                "3. Do not copy the contract's phrasing.\n"
                "4. Echo clause_index unchanged.\n\n"
                "[CLAUSES]\n" + listing
            )
            return await llm.ainvoke(prompt)

        outcome = await gather_batched(
            hot, settings.CONTRACT_HOT_BATCH, worker, settings.CONTRACT_LLM_CONCURRENCY
        )
        llm_calls += outcome.total_batches - outcome.failed_batches

        # Groq returns None when the model answers in prose instead of
        # calling the structured-output tool -- a real and frequent
        # outcome, and one that used to crash the whole node.
        for result in [r for r in outcome.results if r is not None]:
            for item in result.queries or []:
                if item.clause_index in queries and item.dense_query.strip():
                    queries[item.clause_index] = {
                        "dense": item.dense_query.strip(),
                        "sparse": (item.sparse_query or item.dense_query).strip(),
                        "source": "llm",
                        # The rule query is kept so the retriever searches both:
                        # it is the measured baseline and must not be lost to a
                        # worse model paraphrase.
                        "rule_dense": queries[item.clause_index]["dense"],
                    }

        if outcome.degraded:
            pipeline_logger.log_step(
                STAGE,
                f"Groq API Info ({outcome.failed_batches}/{outcome.total_batches} batches failed). "
                "Those clauses keep their Category-Mapped Statutory Query.",
                status="WARNING",
            )
            degraded.append(
                f"query_builder ({outcome.failed_batches}/{outcome.total_batches} batches)"
            )

    pipeline_logger.log_step(
        STAGE,
        f"Built {len(queries)} statutory queries -> Next: Clause Retriever",
        details={
            str(i): queries[i]["dense"][:90] for i in list(queries)[:6]
        },
        status="SUCCESS",
    )

    return {
        **state,
        "clause_queries": queries,
        "llm_calls_used": llm_calls,
        "degraded_nodes": degraded,
    }
