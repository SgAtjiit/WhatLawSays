from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict
from src.schemas.legal import ExtractedFacts, ImmediateActionStep, OffenseAnalysis


class GraphState(TypedDict, total=False):
    task_id: str
    scenario_text: str
    jurisdiction: str
    extracted_facts: Optional[ExtractedFacts]
    explicit_facts: List[str]
    unknown_facts: List[str]
    scenario_domain: str
    offense_status: str
    search_query_dense: Optional[str]
    search_query_sparse: Optional[str]
    # Offence-identification pool: BNS only. The procedural pool is kept separate
    # so BNSS/BSA/Constitution provisions cannot be mistaken for offences, and so
    # confidence grounding is measured against substantive law alone.
    candidate_chunks: List[Dict[str, Any]]
    retrieved_chunks: List[Dict[str, Any]]
    candidate_procedural_chunks: List[Dict[str, Any]]
    procedural_chunks: List[Dict[str, Any]]
    draft_offenses: List[OffenseAnalysis]
    # Sections the analyst excluded because a mandatory element is contradicted by
    # the facts. Previously these were only written to the log, so the compiler
    # could not tell "we confidently found no offence" from "we could not tell".
    contradicted_provisions: List[Dict[str, Any]]
    applied_defences: List[str]
    procedural_provisions: List[str]
    immediate_action_steps: List[ImmediateActionStep]
    citizen_duties: List[str]
    verification_passed: bool
    verification_feedback: Optional[str]
    is_conditional: Optional[bool]
    # retry_count was previously written by the analyst but never declared here.
    # LangGraph builds its channels from these annotations, so the increment was
    # dropped between nodes: the analyst always logged "Attempt 1/3" and the
    # max-retry guard in graph.py could never fire.
    retry_count: int
    # Degradation flags. Set to False by any node that fell back to its
    # rule-based engine so the confidence estimate can be capped accordingly.
    llm_available: bool
    reranker_available: bool
    confidence_score: Optional[float]
    confidence_basis: Optional[Dict[str, Any]]
    final_response: Optional[Dict[str, Any]]