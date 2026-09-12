from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict
from src.schemas.contract import (
    Clause,
    ContractType,
    MissingClauseFinding,
    ParsedDocument,
    PartyPosition,
    RedFlagFinding,
)


class ContractGraphState(TypedDict, total=False):
    task_id: str
    jurisdiction: str

    # Parsing and segmentation are deterministic and run BEFORE ainvoke, not as
    # graph nodes. The grounding retry loop re-enters the analyst, and a node
    # that re-cut clause boundaries would move the text out from under offsets
    # already recorded in findings from the first pass.
    document: Optional[ParsedDocument]
    document_text: str
    declared_contract_type: Optional[ContractType]
    declared_position: Optional[PartyPosition]

    # Profiler
    contract_type: str
    contract_type_confidence: float
    party_names: Dict[str, str]
    position: str
    # USER_DECLARED beats LLM_INFERRED beats UNKNOWN. A declared position is
    # never overwritten by an inferred one: the user knows which side they are on
    # and the whole severity model turns on it.
    position_source: str
    governing_law: Optional[str]
    profile_notes: List[str]

    # Clause classification. `clauses` is seeded by segment_clauses; the
    # classifier refines .category in place and records what it changed.
    clauses: List[Clause]
    deterministic_categories: Dict[int, str]
    reclassified: List[Dict[str, Any]]

    # Triage. Rules decide the tier; the model never decides its own budget.
    clause_tier: Dict[int, str]
    triage_basis: Dict[int, List[str]]
    hot_clause_indices: List[int]
    warm_clause_indices: List[int]

    # Query building and retrieval
    clause_queries: Dict[int, Dict[str, str]]
    clause_chunks: Dict[int, List[Dict[str, Any]]]
    reranker_available: bool

    # Explanation
    explanations: Dict[int, Dict[str, Any]]

    # Findings. Rule findings are quoted by construction and are computed before
    # any LLM call, so they survive every degradation path.
    rule_findings: List[RedFlagFinding]
    llm_findings: List[RedFlagFinding]
    findings: List[RedFlagFinding]
    suppressed_llm_findings: List[Dict[str, Any]]

    missing_clauses: List[MissingClauseFinding]
    consistency_findings: List[Dict[str, Any]]

    # Grounding verification and the retry loop
    grounding_passed: bool
    grounding_feedback: Optional[str]
    ungrounded_clause_indices: List[int]
    quote_problems: List[str]
    # Declared here deliberately: LangGraph builds its channels from these
    # annotations, so an undeclared counter is silently dropped between nodes --
    # the bug recorded at src/agents/state.py:36-40.
    retry_count: int

    # Budget and degradation
    llm_available: bool
    llm_calls_used: int
    degraded_nodes: List[str]

    confidence_score: Optional[float]
    confidence_basis: Optional[Dict[str, Any]]
    final_response: Optional[Dict[str, Any]]
