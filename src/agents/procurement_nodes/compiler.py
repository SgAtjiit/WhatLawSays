"""Step 4: hand the enriched state back to the service.

Not an agent, and named accordingly. It drops a narrative that never grounded --
the same decision `contract_compiler` makes about an ungrounded quote, and for
the same reason: a reader cannot tell which half of a paragraph to trust, so a
duller summary that is certainly right beats a better one that might not be.
"""

from src.agents.procurement_state import ProcurementGraphState
from src.core.logger import pipeline_logger
from src.agents.procurement_nodes.narrator import _deterministic

STAGE = "PROCUREMENT STEP 4: COMPILER"


async def run_procurement_compiler(state: ProcurementGraphState) -> ProcurementGraphState:
    narrative = state.get("narrative")
    degraded = list(state.get("degraded_nodes", []))

    if narrative and narrative.get("source") == "llm" and not state.get("narrative_passed"):
        degraded.append(
            "the written summary used figures that are not in the review, so it was "
            "replaced with one built from the findings"
        )
        narrative = _deterministic(state.get("outcomes", []), state.get("side", "UNKNOWN"))

    pipeline_logger.log_step(
        STAGE,
        f"Compiled: narrative from [{(narrative or {}).get('source', 'none')}], "
        f"statutory text on {len(state.get('statutory_context', {}))} finding(s)",
        status="SUCCESS",
    )

    state["narrative"] = narrative
    state["degraded_nodes"] = degraded
    state["final_state"] = {
        "narrative": narrative,
        "statutory_context": state.get("statutory_context", {}),
        "degraded_nodes": degraded,
        "llm_available": state.get("llm_available", True),
        "reranker_available": state.get("reranker_available", True),
    }
    return state
