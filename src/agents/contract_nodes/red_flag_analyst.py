import re
from langchain_groq import ChatGroq
from src.agents.contract_state import ContractGraphState
from src.config import settings
from src.core.llm_batch import gather_batched
from src.core.logger import pipeline_logger
from src.schemas.contract import (
    SEVERITY_ORDER,
    PartyPosition,
    RedFlagFinding,
    Severity,
)
from src.schemas.contract_review import LlmRedFlagBatch

STAGE = "CONTRACT AGENT 5: RED FLAG ANALYST"


def locate(quote: str, clause_text: str, clause_start: int):
    """Find a model-supplied quote in the clause it claims to come from.

    The model is never asked for offsets -- it invents them. It is asked for the
    words, which are then located here. Whitespace is normalized on both sides
    because the model reflows the line wrapping it was given.
    """
    cleaned = " ".join((quote or "").split())
    if len(cleaned) < 12:
        return None

    exact = clause_text.find(cleaned)
    if exact != -1:
        return clause_start + exact, clause_start + exact + len(cleaned), cleaned

    # The clause text still carries its original line breaks; match across them.
    pattern = re.compile(r"\s+".join(re.escape(w) for w in cleaned.split()), re.I)
    found = pattern.search(clause_text)
    if found:
        return (
            clause_start + found.start(),
            clause_start + found.end(),
            " ".join(found.group(0).split()),
        )
    return None


async def run_red_flag_analyst(state: ContractGraphState) -> ContractGraphState:
    retry_count = state.get("retry_count", 0)
    feedback = state.get("grounding_feedback")
    clauses = {c.index: c for c in state.get("clauses", [])}
    position = PartyPosition(state.get("position", PartyPosition.UNKNOWN.value))
    side = position.value.replace("_", " ").lower() if position != PartyPosition.UNKNOWN else "reviewing party"

    rule_findings = state.get("rule_findings", [])
    covered = {(f.clause_index, f.rule_id) for f in rule_findings}

    # On a retry only the clauses whose quotes failed to ground are revisited.
    scoped = state.get("ungrounded_clause_indices") if retry_count else None
    targets = [i for i in (scoped or state.get("hot_clause_indices", [])) if i in clauses]

    pipeline_logger.log_step(
        STAGE,
        f"Scanning {len(targets)} HOT clauses for concerns beyond the {len(rule_findings)} rule findings "
        f"(Attempt {retry_count + 1}/3) -> Next: Gap Detector",
        details={"grounding_feedback": feedback} if feedback else None,
    )

    llm_available = state.get("llm_available", True)
    llm_calls = state.get("llm_calls_used", 0)
    degraded = list(state.get("degraded_nodes", []))
    llm_findings = []
    suppressed = list(state.get("suppressed_llm_findings", []))

    budget_left = settings.CONTRACT_LLM_CALL_BUDGET - llm_calls
    if llm_available and targets and budget_left > 0:
        async def worker(batch):
            llm = ChatGroq(
                model=settings.GROQ_MODEL,
                groq_api_key=settings.GROQ_API_KEY,
                temperature=0.0,
            ).with_structured_output(LlmRedFlagBatch)

            blocks = []
            for index in batch:
                clause = clauses[index]
                already = [f.title for f in rule_findings if f.clause_index == index]
                block = f"clause_index={index} category={clause.category.value}\n{clause.text[:1500]}"
                if already:
                    block += f"\n[ALREADY REPORTED - do not repeat]: {'; '.join(already)}"
                blocks.append(block)

            correction = (
                f"\n[CORRECTION FROM THE GROUNDING VERIFIER - your previous attempt failed]\n{feedback}\n"
                "Every quote must be copied character for character from the clause text above.\n"
                if feedback
                else ""
            )
            prompt = (
                f"You are the Red Flag Analyst for a contract reviewed on behalf of the {side}.\n"
                "Deterministic rules have already found the well-known problems. Your job is to "
                "find concerns those rules do not encode.\n\n"
                "[ABSOLUTE RULES]\n"
                "1. `quote` MUST be copied character for character from the clause text supplied. "
                "A quote that does not appear in the clause is discarded and your finding is lost.\n"
                "2. Do NOT repeat anything listed as ALREADY REPORTED.\n"
                "3. Do NOT state that a clause is void, illegal or unenforceable. Indian law is "
                "frequently not what you would assume, and statutory consequences are determined "
                "elsewhere in this pipeline from the actual statute text.\n"
                "4. Report a concern only if the clause text actually creates it. If the clause is "
                "unremarkable, return nothing for it. An empty list is a valid answer.\n"
                "5. Judge from the perspective of the %s.\n" % side
                + "6. Do NOT advise whether to sign.\n"
                + correction
                + "\n[CLAUSES]\n" + "\n\n---\n\n".join(blocks)
            )
            return await llm.ainvoke(prompt)

        outcome = await gather_batched(
            targets, settings.CONTRACT_HOT_BATCH, worker, settings.CONTRACT_LLM_CONCURRENCY
        )
        llm_calls += outcome.total_batches - outcome.failed_batches

        # Groq returns None when the model answers in prose instead of
        # calling the structured-output tool -- a real and frequent
        # outcome, and one that used to crash the whole node.
        for result in [r for r in outcome.results if r is not None]:
            for item in result.findings or []:
                clause = clauses.get(item.clause_index)
                if clause is None:
                    suppressed.append({"title": item.title, "reason": "unknown clause_index"})
                    continue
                located = locate(item.quote, clause.text, clause.start_offset)
                if located is None:
                    # Indistinguishable from an invented quote, so it is dropped
                    # rather than repaired. This is the whole guarantee.
                    suppressed.append({
                        "clause_index": item.clause_index,
                        "title": item.title,
                        "quote": item.quote[:120],
                        "reason": "quote not found in the clause",
                    })
                    continue
                start, end, quote = located
                key = (item.clause_index, f"LLM_{item.title.upper().replace(' ', '_')[:40]}")
                if key in covered:
                    continue
                covered.add(key)
                llm_findings.append(
                    RedFlagFinding(
                        rule_id=key[1],
                        title=item.title,
                        severity=item.severity,
                        clause_index=item.clause_index,
                        clause_number=clause.number,
                        matched_quote=quote,
                        match_start=start,
                        match_end=end,
                        harms=[position] if position != PartyPosition.UNKNOWN else [],
                        citations=[],
                        plain_summary=item.plain_summary,
                        why_it_matters=item.why_it_matters,
                        detector="llm",
                    )
                )

        if outcome.degraded:
            degraded.append(
                f"red_flag_analyst ({outcome.failed_batches}/{outcome.total_batches} batches)"
            )
        if outcome.all_failed:
            llm_available = False
            pipeline_logger.log_step(
                STAGE,
                f"Groq API Info (all {outcome.total_batches} batches failed). "
                "Deterministic rule findings stand alone.",
                status="WARNING",
            )
    elif budget_left <= 0:
        degraded.append("red_flag_analyst (LLM call budget exhausted)")

    # On a scoped retry, keep findings from clauses that were not revisited.
    if scoped:
        kept = [f for f in state.get("llm_findings", []) if f.clause_index not in set(scoped)]
        llm_findings = kept + llm_findings

    merged = list(rule_findings) + llm_findings
    merged.sort(key=lambda f: (-SEVERITY_ORDER[f.severity], f.clause_index or 0, f.rule_id))

    pipeline_logger.log_step(
        STAGE,
        f"{len(rule_findings)} rule findings + {len(llm_findings)} model findings "
        f"({len(suppressed)} suppressed as ungrounded) -> Next: Gap Detector",
        details={
            "suppressed": suppressed[:5],
            "severities": {
                s.value: sum(1 for f in merged if f.severity is s) for s in Severity
            },
        },
        status="SUCCESS",
    )

    return {
        **state,
        "llm_findings": llm_findings,
        "findings": merged,
        "suppressed_llm_findings": suppressed,
        "retry_count": retry_count + 1,
        "llm_available": llm_available,
        "llm_calls_used": llm_calls,
        "degraded_nodes": degraded,
    }
