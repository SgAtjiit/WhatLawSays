import asyncio
from src.agents.graph import legal_agent_app
from src.core.logger import pipeline_logger


async def run_pipeline_test():
    scenario = (
        "Police officers stopped my vehicle on the highway, forced me to unlock my mobile phone, "
        "and searched my private chat messages without showing any warrant or recording any written reasons."
    )

    pipeline_logger.log_step(
        "INTEGRATION TEST",
        "Triggering full Agentic Orchestrator Pipeline for test scenario...",
        details=scenario,
    )

    initial_state = {
        "task_id": "test-integration-001",
        "scenario_text": scenario,
        "jurisdiction": "India",
        "extracted_facts": None,
        "candidate_chunks": [],
        "retrieved_chunks": [],
        "draft_offenses": [],
        "verification_passed": False,
        "verification_feedback": None,
        "retry_count": 0,
        "confidence_score": None,
        "final_response": None,
    }

    final_state = await legal_agent_app.ainvoke(initial_state)

    pipeline_logger.log_step(
        "INTEGRATION TEST",
        "Pipeline execution complete! Output payload:",
        details=final_state.get("final_response"),
        status="SUCCESS",
    )


if __name__ == "__main__":
    asyncio.run(run_pipeline_test())
