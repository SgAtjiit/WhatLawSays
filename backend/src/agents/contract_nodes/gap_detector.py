from src.agents.contract_state import ContractGraphState
from src.core.clause_checklists import find_missing_clauses
from src.core.logger import pipeline_logger
from src.schemas.contract import ContractType, PartyPosition

STAGE = "CONTRACT AGENT 6: GAP DETECTOR"


async def run_gap_detector(state: ContractGraphState) -> ContractGraphState:
    clauses = state.get("clauses", [])
    contract_type = ContractType(state.get("contract_type", ContractType.UNKNOWN.value))
    position = PartyPosition(state.get("position", PartyPosition.UNKNOWN.value))

    pipeline_logger.log_step(
        STAGE,
        f"Checking a {contract_type.value} contract against its protection checklist -> Next: Consistency Checker",
        details={"position": position.value},
    )

    # Deliberately model-free. Absence is invisible to any clause-by-clause pass,
    # and asking a model what is missing invites it to invent gaps that sound
    # plausible. The checklist is fixed, so the answer is reproducible.
    missing = find_missing_clauses(clauses, contract_type, position)

    pipeline_logger.log_step(
        STAGE,
        f"{len(missing)} checklist protection(s) absent from this contract -> Next: Consistency Checker",
        details=[f"{m.severity.value}: {m.title}" for m in missing],
        status="SUCCESS",
    )

    return {**state, "missing_clauses": missing}
