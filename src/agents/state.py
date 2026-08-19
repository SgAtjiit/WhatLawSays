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
    candidate_chunks: List[Dict[str, Any]]
    retrieved_chunks: List[Dict[str, Any]]
    draft_offenses: List[OffenseAnalysis]
    applied_defences: List[str]
    procedural_provisions: List[str]
    immediate_action_steps: List[ImmediateActionStep]
    citizen_duties: List[str]
    verification_passed: bool
    verification_feedback: Optional[str]
    is_conditional: Optional[bool]
    confidence_score: Optional[float]
    final_response: Optional[Dict[str, Any]]