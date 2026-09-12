from langchain_groq import ChatGroq
from src.agents.contract_state import ContractGraphState
from src.config import settings
from src.core.clause_triage import triage_clauses
from src.core.llm_batch import gather_batched
from src.core.logger import pipeline_logger
from src.core.red_flag_rules import evaluate_clauses
from src.schemas.contract import SEVERITY_ORDER, ClauseCategory, PartyPosition
from src.schemas.contract_review import ClauseLabelBatch

STAGE = "CONTRACT AGENT 2: CLAUSE CLASSIFIER"

# Below this the model is less sure than the keyword evidence already gathered,
# so the deterministic label stands. The classifier refines; it does not reset.
_OVERRIDE_THRESHOLD = 0.7


def _format(clause) -> str:
    heading = f" [{clause.heading}]" if clause.heading else ""
    return (
        f"clause_index={clause.index} number={clause.number or '-'}{heading}\n"
        f"{clause.text[:1200]}"
    )


async def run_clause_classifier(state: ContractGraphState) -> ContractGraphState:
    clauses = state.get("clauses", [])
    position = PartyPosition(state.get("position", PartyPosition.UNKNOWN.value))

    pipeline_logger.log_step(
        STAGE,
        f"Refining deterministic labels across {len(clauses)} clauses -> Next: Contract Query Builder",
        details={"position": position.value},
    )

    deterministic = {c.index: c.category.value for c in clauses}
    # Rule findings under the deterministic labels, computed BEFORE the model is
    # allowed to relabel anything. See the union below.
    baseline_findings = evaluate_clauses(clauses, position)
    llm_available = state.get("llm_available", True)
    llm_calls = state.get("llm_calls_used", 0)
    degraded = list(state.get("degraded_nodes", []))
    reclassified = []

    if llm_available:
        async def worker(batch):
            llm = ChatGroq(
                model=settings.GROQ_MODEL,
                groq_api_key=settings.GROQ_API_KEY,
                temperature=0.0,
            ).with_structured_output(ClauseLabelBatch)
            categories = ", ".join(c.value for c in ClauseCategory)
            prompt = (
                "You are the Clause Classifier Agent for Indian contracts.\n"
                "Assign each supplied clause the single best-fitting category.\n\n"
                "[RULES]\n"
                "1. Return exactly one label per supplied clause, echoing clause_index unchanged.\n"
                "2. Classify what the clause DOES, not what it mentions. A confidentiality "
                "clause that mentions competitors is CONFIDENTIALITY, not NON_COMPETE.\n"
                "3. Set confidence below 0.7 when the clause genuinely covers several topics.\n"
                f"4. Allowed categories: {categories}\n\n"
                "[CLAUSES]\n" + "\n\n---\n\n".join(_format(c) for c in batch)
            )
            return await llm.ainvoke(prompt)

        outcome = await gather_batched(
            clauses,
            settings.CONTRACT_CLASSIFY_BATCH,
            worker,
            settings.CONTRACT_LLM_CONCURRENCY,
        )
        llm_calls += outcome.total_batches - outcome.failed_batches

        by_index = {c.index: c for c in clauses}
        # Groq returns None when the model answers in prose instead of
        # calling the structured-output tool -- a real and frequent
        # outcome, and one that used to crash the whole node.
        for result in [r for r in outcome.results if r is not None]:
            for label in result.labels or []:
                clause = by_index.get(label.clause_index)
                if clause is None or label.confidence < _OVERRIDE_THRESHOLD:
                    continue
                if label.category == clause.category:
                    continue
                reclassified.append({
                    "clause_index": clause.index,
                    "from": clause.category.value,
                    "to": label.category.value,
                    "confidence": label.confidence,
                    "reason": label.reason[:200],
                })
                clause.category = label.category

        if outcome.degraded:
            degraded.append(f"clause_classifier ({outcome.failed_batches}/{outcome.total_batches} batches)")
        if outcome.all_failed:
            llm_available = False
            pipeline_logger.log_step(
                STAGE,
                f"Groq API Info (all {outcome.total_batches} batches failed). Using Keyword Clause Classifier Engine.",
                status="WARNING",
            )

    # Rule findings are computed here, before any further model work, so the
    # triage tier is decided by evidence the model had no hand in.
    #
    # The union with `baseline_findings` is load-bearing. Most rules are gated on
    # clause category, so a relabel silently DELETED findings: the model calling
    # clause 8 "confidentiality" removed NON_COMPETE_POST_TERM -- the single most
    # consequential rule here, since Contract Act s.27 voids the clause outright --
    # and demoted the clause out of HOT. That inverts the design: the model is
    # meant to explain what the rules found, never to decide whether a finding
    # exists. Taking the union lets a better label ADD a finding and never remove
    # one.
    refined_findings = evaluate_clauses(clauses, position)
    seen = {(f.rule_id, f.clause_index) for f in refined_findings}
    restored = [f for f in baseline_findings if (f.rule_id, f.clause_index) not in seen]
    rule_findings = refined_findings + restored
    rule_findings.sort(
        key=lambda f: (-SEVERITY_ORDER[f.severity], f.clause_index or 0, f.rule_id)
    )
    if restored:
        pipeline_logger.log_step(
            STAGE,
            f"Kept {len(restored)} rule finding(s) the reclassification would have dropped",
            details=[f"{f.rule_id} @ clause {f.clause_number}" for f in restored],
            status="WARNING",
        )
    triage = triage_clauses(clauses, rule_findings, position)

    pipeline_logger.log_step(
        STAGE,
        f"Classified {len(clauses)} clauses ({len(reclassified)} refined) -> "
        f"Triage: {len(triage.hot)} HOT, {len(triage.warm)} WARM, {len(triage.cold)} COLD "
        f"-> Next: Contract Query Builder",
        details={
            "reclassified": reclassified[:8],
            "rule_findings": len(rule_findings),
            "triage": triage.to_payload(),
        },
        status="SUCCESS",
    )

    return {
        **state,
        "clauses": clauses,
        "deterministic_categories": deterministic,
        "reclassified": reclassified,
        "rule_findings": rule_findings,
        "clause_tier": triage.tiers,
        "triage_basis": triage.basis,
        "hot_clause_indices": triage.hot,
        "warm_clause_indices": triage.warm,
        "llm_available": llm_available,
        "llm_calls_used": llm_calls,
        "degraded_nodes": degraded,
    }
