"""Agent 1: work out what this review is looking at, and whether it can proceed."""

from src.agents.procurement_state import ProcurementGraphState
from src.core.logger import pipeline_logger
from src.schemas.procurement import CheckStatus

STAGE = "PROCUREMENT AGENT 1: EVENT PROFILER"

# Deterministic. There is nothing here a model could tell us that the event does
# not already say in a typed field, and asking one would introduce a failure mode
# where a mis-read category silently changes which rules are in scope.


async def run_event_profiler(state: ProcurementGraphState) -> ProcurementGraphState:
    event = state.get("event")
    outcomes = state.get("outcomes", [])

    breaches = sum(1 for o in outcomes if o.status == CheckStatus.BREACH)
    indicators = sum(1 for o in outcomes if o.status == CheckStatus.INDICATOR)
    gaps = sum(1 for o in outcomes if o.status == CheckStatus.UNDETERMINED)

    pipeline_logger.log_step(
        STAGE,
        f"Event [{getattr(event, 'event_id', '?')}] profiled: {len(outcomes)} checks run "
        f"-> {breaches} breaches, {indicators} indicators, {gaps} gaps "
        f"-> Next: Statutory Retriever",
        details={
            "category": getattr(event, "category", None),
            "side": state.get("side"),
            "supplied": sorted(getattr(event, "provided_collections", set())),
        },
    )

    state["statutory_context"] = {}
    state["narrative"] = None
    state["narrative_problems"] = []
    state["narrative_passed"] = False
    state.setdefault("retry_count", 0)
    state.setdefault("degraded_nodes", [])
    return state
