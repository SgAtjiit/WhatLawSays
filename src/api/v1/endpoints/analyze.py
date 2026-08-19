from fastapi import APIRouter, HTTPException
from src.schemas.legal import ScenarioRequest, LegalAnalysisResponse
from src.agents.graph import legal_agent_app
from src.agents.state import GraphState

router = APIRouter()

@router.post("/analyze", response_model=LegalAnalysisResponse)
async def analyze_scenario(payload: ScenarioRequest):
    # Initialize the state object
    initial_state = GraphState(
        scenario_text=payload.scenario_text,
        extracted_facts=None,
        retrieved_chunks=[],
        draft_offenses=[],
        verification_passed=True,
        retry_count=0,
        final_response=None
    )
    
    try:
        # Execute the LangGraph workflow
        final_state = await legal_agent_app.ainvoke(initial_state)
        
        # If the extractor exited early due to missing facts
        if final_state.get("final_response"):
            return final_state["final_response"]
            
        # Standard successful response
        return LegalAnalysisResponse(
            status="SUCCESS",
            confidence_score=0.95 if final_state["verification_passed"] else 0.5,
            extracted_facts=final_state["extracted_facts"],
            identified_offenses=final_state["draft_offenses"],
            disclaimer="This is legal information, not legal advice."
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent workflow failed: {str(e)}")