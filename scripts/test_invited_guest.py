import asyncio
import sys
sys.path.insert(0, r"e:\resume Projects\whatLawSays")

from src.agents.graph import legal_agent_app
from src.core.logger import pipeline_logger


async def main():
    invited_scenario = (
        "A guest entered a house having a valid written invitation from the owner. "
        "The owner later accused the guest of entering without permission."
    )

    pipeline_logger.log_step(
        "INVITED GUEST TEST",
        "Testing Invited Guest Scenario -> Expecting Exoneration of Trespass Charge (BNS Section 329)",
        details=invited_scenario,
    )

    initial_state = {
        "task_id": "test-invited-guest-01",
        "scenario_text": invited_scenario,
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
        "INVITED GUEST TEST",
        "Final Compiled Response Payload:",
        details=final_state.get("final_response"),
        status="SUCCESS",
    )


if __name__ == "__main__":
    asyncio.run(main())
