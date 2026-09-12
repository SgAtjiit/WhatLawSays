from langchain_groq import ChatGroq
from src.agents.contract_state import ContractGraphState
from src.config import settings
from src.core.llm_batch import gather_batched
from src.core.logger import pipeline_logger
from src.schemas.contract import PartyPosition
from src.schemas.contract_review import ClauseExplanationBatch

STAGE = "CONTRACT AGENT 4: PLAIN LANGUAGE EXPLAINER"

# A COLD clause still gets a usable line, built from what the rules already know.
_TEMPLATES = {
    "PARTIES": "Identifies who the parties to this contract are.",
    "DEFINITIONS": "Defines terms used elsewhere in the contract.",
    "OTHER": "A general provision of this contract.",
}


def _template_for(clause) -> str:
    label = clause.heading or clause.category.value.replace("_", " ").lower()
    return _TEMPLATES.get(clause.category.value, f"This clause covers {label}.")


async def run_clause_explainer(state: ContractGraphState) -> ContractGraphState:
    clauses = {c.index: c for c in state.get("clauses", [])}
    position = PartyPosition(state.get("position", PartyPosition.UNKNOWN.value))
    side = position.value.replace("_", " ").lower() if position != PartyPosition.UNKNOWN else "reviewing party"

    hot = [i for i in state.get("hot_clause_indices", []) if i in clauses]
    warm = [i for i in state.get("warm_clause_indices", []) if i in clauses]

    pipeline_logger.log_step(
        STAGE,
        f"Explaining {len(hot)} HOT and {len(warm)} WARM clauses in plain language -> Next: Red Flag Analyst",
        details={"position": position.value},
    )

    explanations = {}
    # Every clause starts with a deterministic explanation, so a failed batch
    # degrades that clause to a plain line rather than to nothing at all.
    for index, clause in clauses.items():
        explanations[index] = {
            "plain_english": _template_for(clause),
            "obligations": [],
            "watch_outs": [],
            "source": "template",
        }

    llm_available = state.get("llm_available", True)
    llm_calls = state.get("llm_calls_used", 0)
    degraded = list(state.get("degraded_nodes", []))

    async def explain(batch_indices, with_statute):
        llm = ChatGroq(
            model=settings.GROQ_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=0.0,
        ).with_structured_output(ClauseExplanationBatch)

        blocks = []
        for index in batch_indices:
            clause = clauses[index]
            block = (
                f"clause_index={index} category={clause.category.value}\n"
                f"{clause.text[:1500]}"
            )
            if with_statute:
                chunks = state.get("clause_chunks", {}).get(index, [])[:3]
                if chunks:
                    law = "\n".join(
                        f"  {c.get('act', '')} {c.get('section_number', '')}: {c.get('title', '')}\n"
                        f"  {(c.get('content') or '')[:600]}"
                        for c in chunks
                    )
                    block += f"\n[RETRIEVED LAW FOR CONTEXT]\n{law}"
            blocks.append(block)

        prompt = (
            f"You are the Plain Language Explainer for a contract being reviewed on behalf of the {side}.\n"
            "Explain each clause so someone with no legal training understands what it does to them.\n\n"
            "[RULES]\n"
            "1. Write at about an eighth-grade reading level. Short sentences. Second person.\n"
            "2. Explain ONLY what the clause text says. Do not add obligations that are not written.\n"
            "3. Do NOT state whether a clause is legal, valid, enforceable or void. That is decided "
            "elsewhere from the statute, and your own assumptions about which country's law applies "
            "are frequently wrong.\n"
            "4. Do NOT advise whether to sign.\n"
            "5. `watch_outs` are practical consequences, not legal conclusions.\n"
            "6. Echo clause_index unchanged, one entry per supplied clause.\n\n"
            "[CLAUSES]\n" + "\n\n---\n\n".join(blocks)
        )
        return await llm.ainvoke(prompt)

    if llm_available:
        for indices, batch_size, with_statute, label in (
            (hot, settings.CONTRACT_HOT_BATCH, True, "HOT"),
            (warm, settings.CONTRACT_WARM_BATCH, False, "WARM"),
        ):
            if not indices:
                continue

            async def worker(batch, _with=with_statute):
                # The batch is returned alongside its result so the writer can
                # restrict itself to the clauses this call actually saw.
                return set(batch), await explain(batch, _with)

            outcome = await gather_batched(
                indices, batch_size, worker, settings.CONTRACT_LLM_CONCURRENCY
            )
            llm_calls += outcome.total_batches - outcome.failed_batches
            # Groq returns None when the model answers in prose instead of
            # calling the structured-output tool -- a real and frequent
            # outcome, and one that used to crash the whole node.
            for allowed, result in [r for r in outcome.results if r and r[1] is not None]:
                for item in result.explanations or []:
                    # Only clauses this batch was shown. A WARM batch was able to
                    # overwrite a HOT clause's explanation with prose about a
                    # clause it had never been given.
                    if item.clause_index in allowed and item.clause_index in explanations:
                        explanations[item.clause_index] = {
                            "plain_english": item.plain_english,
                            "obligations": list(item.obligations or []),
                            "watch_outs": list(item.watch_outs or []),
                            "source": "llm",
                        }
            if outcome.degraded:
                degraded.append(
                    f"explainer:{label} ({outcome.failed_batches}/{outcome.total_batches} batches)"
                )

    explained = sum(1 for v in explanations.values() if v["source"] == "llm")
    pipeline_logger.log_step(
        STAGE,
        f"Explained {explained} clauses via model, {len(explanations) - explained} from template -> Next: Red Flag Analyst",
        status="SUCCESS",
    )

    return {
        **state,
        "explanations": explanations,
        "llm_available": llm_available,
        "llm_calls_used": llm_calls,
        "degraded_nodes": degraded,
    }
