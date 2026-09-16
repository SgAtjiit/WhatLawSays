import uuid

from fastapi import APIRouter, HTTPException
from src.agents.graph import legal_agent_app
from src.agents.state import GraphState
from src.schemas.legal import LegalAnalysisResponse, ScenarioRequest

router = APIRouter()


@router.post("/analyze", response_model=LegalAnalysisResponse)
async def analyze_scenario(payload: ScenarioRequest):
    # Initialize the state object
    initial_state = GraphState(
        task_id=f"sync-{uuid.uuid4().hex[:12]}",
        scenario_text=payload.scenario_text,
        jurisdiction=payload.jurisdiction,
        extracted_facts=None,
        candidate_chunks=[],
        retrieved_chunks=[],
        candidate_procedural_chunks=[],
        procedural_chunks=[],
        draft_offenses=[],
        verification_passed=False,
        verification_feedback=None,
        retry_count=0,
        llm_available=True,
        reranker_available=True,
        confidence_score=None,
        confidence_basis=None,
        final_response=None,
    )

    try:
        # Execute the LangGraph workflow
        final_state = await legal_agent_app.ainvoke(initial_state)

        # The response compiler is the single owner of the confidence estimate and
        # of offense filtering. This endpoint previously recomputed the score
        # itself (0.95 / 0.5) and returned unfiltered draft offenses, so the same
        # scenario scored differently depending on which entry point was used.
        result_payload = final_state.get("final_response")

        if not result_payload:
            raise HTTPException(
                status_code=500,
                detail="Agent workflow completed without producing a final response.",
            )

        return LegalAnalysisResponse(**result_payload)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent workflow failed: {str(e)}")
