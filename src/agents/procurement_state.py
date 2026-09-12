"""State for the procurement review graph.

Deliberately narrower than `ContractGraphState`. The deterministic outcomes are
computed in `procurement_service` *before* `ainvoke` and are read-only here, so
nothing a node does can change what a check found. That is the opposite of the
contract graph, where `clause_classifier` legitimately changes which rules apply
-- there, relabelling a clause is new information; here, the event schema is
fixed and the model has no new information to contribute about it.

Every key a node writes is declared. LangGraph builds its channels from these
annotations, and an undeclared key is silently dropped between nodes -- the bug
`src/agents/state.py:36-40` already carries a comment about, where `retry_count`
vanished and the retry loop ran forever.
"""

from typing import Any, Dict, List, Optional

from typing_extensions import TypedDict


class ProcurementGraphState(TypedDict, total=False):
    task_id: str

    # Computed before ainvoke. Never recomputed in a node.
    event: Any
    outcomes: List[Any]
    side: str

    # statute_retriever
    statutory_context: Dict[str, List[Dict[str, Any]]]
    reranker_available: bool

    # narrator
    narrative: Optional[Dict[str, Any]]
    narrative_problems: List[str]
    narrative_passed: bool
    retry_count: int

    llm_available: bool
    llm_calls_used: int
    degraded_nodes: List[str]

    final_state: Optional[Dict[str, Any]]
