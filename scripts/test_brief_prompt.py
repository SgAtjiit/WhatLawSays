import asyncio
import sys
sys.path.insert(0, r"e:\resume Projects\whatLawSays")

from src.agents.graph import legal_agent_app
from src.core.logger import pipeline_logger


async def main():
    brief_scenario = "police caught a person doing a 1 crore rs theft in a house"

    pipeline_logger.log_step(
        "UX TEST",
        "Testing Brief Citizen Input -> Expecting CONDITIONAL PROCEED with Preliminary Legal Sections",
        details=brief_scenario,
    )

    initial_state = {
        "task_id": "ux-test-theft-100",
        "scenario_text": brief_scenario,
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
        "UX TEST",
        "Final Compiled Response Payload:",
        details=final_state.get("final_response"),
        status="SUCCESS",
    )


if __name__ == "__main__":
    asyncio.run(main())
