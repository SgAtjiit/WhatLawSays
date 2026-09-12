"""Step 2: attach the text of the sections the findings already cite.

Retrieval is not asked to *discover* which provision applies -- every check
carries its citation, for the reason `red_flag_rules` sets out: commercial and
statutory registers do not match, and a search for "payment within 60 days of
invoice" does not return MSMED s.15. What retrieval adds is the section's actual
words, so the reader can check the claim against the statute rather than taking
the finding's word for it.

That makes this node safe to degrade: with Qdrant unreachable the findings and
their citations are unchanged, and only the quoted text is missing.
"""

from src.agents.procurement_state import ProcurementGraphState
from src.core.logger import pipeline_logger
from src.schemas.procurement import CheckStatus

STAGE = "PROCUREMENT QDRANT RETRIEVER"

_SHOWN = {CheckStatus.BREACH, CheckStatus.INDICATOR, CheckStatus.UNDETERMINED}


async def run_statute_retriever(state: ProcurementGraphState) -> ProcurementGraphState:
    outcomes = [o for o in state.get("outcomes", []) if o.status in _SHOWN]

    wanted = {}
    for outcome in outcomes:
        for citation in outcome.citations:
            wanted.setdefault((citation.act, citation.section_number), []).append(outcome.check_id)

    if not wanted:
        state["statutory_context"] = {}
        return state

    from src.core.vector_store import vector_store

    context = {}
    degraded = list(state.get("degraded_nodes", []))

    try:
        # Fetched by identity, not searched for. A semantic query for "MSMED Act
        # Section 15" competes against every other section of the same Act and
        # can lose -- which is not a ranking problem worth solving when the
        # citation already names exactly what it wants.
        sections = await vector_store.fetch_sections(list(wanted))
    except Exception as e:
        degraded.append(f"statutory context unavailable ({type(e).__name__})")
        state["degraded_nodes"] = degraded
        state["statutory_context"] = {}
        pipeline_logger.log_step(
            STAGE, f"Retrieval unavailable: {type(e).__name__}", status="WARNING"
        )
        return state

    for (act, section), check_ids in wanted.items():
        payload = sections.get((act, section))
        if payload is None:
            # A citation naming a section the corpus does not hold. The finding
            # still stands on its rule; it simply cannot show the text.
            continue
        for check_id in check_ids:
            context.setdefault(check_id, []).append({
                "act": payload.get("act"),
                "section_number": payload.get("section_number"),
                "title": payload.get("title"),
                "text": " ".join((payload.get("content") or "").split())[:1200],
            })

    pipeline_logger.log_step(
        STAGE,
        f"Attached statutory text to {len(context)} finding(s) from "
        f"{len(sections)}/{len(wanted)} cited provision(s) -> Next: Narrator",
        status="SUCCESS",
    )
    state["statutory_context"] = context
    return state
