import asyncio
import sys
sys.path.insert(0, r"e:\resume Projects\whatLawSays")

from src.agents.graph import legal_agent_app
from src.core.logger import pipeline_logger


async def main():
    scenario = "A person was going to enter the President's residence with an invitation to attend a party."

    pipeline_logger.log_step(
        "MASTER TEST",
        "Testing President's Residence Invitation Scenario -> Expecting NO_OFFENSE_ESTABLISHED",
        details=scenario,
    )

    initial_state = {
        "task_id": "test-president-invitation-001",
        "scenario_text": scenario,
        "jurisdiction": "India",
        "extracted_facts": None,
        "explicit_facts": [],
        "unknown_facts": [],
        "category": "CRIMINAL_OFFENSE",
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
        "MASTER TEST",
        "Final Compiled Response Payload:",
        details=final_state.get("final_response"),
        status="SUCCESS",
    )


if __name__ == "__main__":
    asyncio.run(main())
