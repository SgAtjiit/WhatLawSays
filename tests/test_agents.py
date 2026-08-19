import pytest
from src.agents.graph import legal_agent_app
from src.agents.state import GraphState
from src.core.logger import pipeline_logger


def test_initial_graph_state():
    """Verify that the GraphState initializes correctly before LLM execution."""
    scenario = "My landlord changed the locks without telling me."

    state = GraphState(
        task_id="test-123",
        scenario_text=scenario,
        jurisdiction="India",
        extracted_facts=None,
        candidate_chunks=[],
        retrieved_chunks=[],
        draft_offenses=[],
        verification_passed=False,
        verification_feedback=None,
        retry_count=0,
        confidence_score=None,
        final_response=None,
    )

    assert state["scenario_text"] == scenario
    assert state["retry_count"] == 0
    assert state["extracted_facts"] is None


def test_pipeline_logger():
    """Verify that the pipeline logger logs without crashing."""
    pipeline_logger.log_step(
        "TEST STAGE",
        "Verification log message",
        details={"key": "value"},
        status="SUCCESS",
    )


def test_graph_structure():
    """Verify that the LangGraph workflow compiles successfully."""
    assert legal_agent_app is not None