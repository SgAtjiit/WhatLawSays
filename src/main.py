import time
import uuid
from typing import Dict
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from src.agents.graph import legal_agent_app
from src.config import settings
from src.core.database import init_db
from src.core.vector_store import vector_store
from src.core.logger import pipeline_logger
from src.core.task_queue import task_queue
from src.schemas.legal import LegalAnalysisResponse, ScenarioRequest

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for frontend client interactions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple Rate Limiter state tracking per client IP
RATE_LIMIT_STORE: Dict[str, list] = {}


@app.on_event("startup")
async def startup_event():
    pipeline_logger.log_step(
        "API GATEWAY",
        f"Starting {settings.PROJECT_NAME}... Initializing DB & Vector Store dependencies.",
    )
    await init_db()
    await vector_store.setup_collection()


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "whatlawsays-backend"}


@app.post(
    f"{settings.API_V1_STR}/analyze",
    response_model=LegalAnalysisResponse,
    tags=["Legal Analysis"],
)
async def analyze_scenario(payload: ScenarioRequest, request: Request):
    """
    Intake a citizen scenario, validate payload, rate-limit, enqueue task,
    route through the Agentic LangGraph pipeline, and return structured analysis.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    now = time.time()

    # Rate Limiting Check
    request_times = RATE_LIMIT_STORE.get(client_ip, [])
    request_times = [t for t in request_times if now - t < 60]  # keep last 60s
    if len(request_times) >= settings.RATE_LIMIT_PER_MINUTE:
        pipeline_logger.log_step(
            "API GATEWAY",
            f"Rate limit exceeded for IP [{client_ip}]",
            status="WARNING",
        )
        raise HTTPException(
            status_code=429, detail="Rate limit exceeded. Please try again in a minute."
        )
    request_times.append(now)
    RATE_LIMIT_STORE[client_ip] = request_times

    task_id = str(uuid.uuid4())[:8]

    # Step 1: API Gateway intake logging
    pipeline_logger.log_step(
        "API GATEWAY",
        f"Request Intake received from [{client_ip}] -> Task ID [{task_id}]",
        details={
            "task_id": task_id,
            "scenario_length": len(payload.scenario_text),
            "jurisdiction": payload.jurisdiction,
            "scenario_preview": payload.scenario_text[:100] + "...",
        },
        status="SUCCESS",
    )

    try:
        # Step 2: Enqueue task to Task Queue (Redis / Memory)
        await task_queue.enqueue_task(
            {
                "task_id": task_id,
                "scenario_text": payload.scenario_text,
                "jurisdiction": payload.jurisdiction,
            }
        )

        # Step 3: Execute Agentic Graph Worker Orchestration
        initial_state = {
            "task_id": task_id,
            "scenario_text": payload.scenario_text,
            "jurisdiction": payload.jurisdiction,
            "extracted_facts": None,
            "candidate_chunks": [],
            "retrieved_chunks": [],
            "candidate_procedural_chunks": [],
            "procedural_chunks": [],
            "draft_offenses": [],
            "verification_passed": False,
            "verification_feedback": None,
            "retry_count": 0,
            "llm_available": True,
            "reranker_available": True,
            "confidence_score": None,
            "confidence_basis": None,
            "final_response": None,
        }

        pipeline_logger.log_step(
            "WORKER CONSUMER",
            f"Worker consuming task [{task_id}] -> Executing Agentic Orchestrator (LangGraph)",
        )

        final_graph_state = await legal_agent_app.ainvoke(initial_state)

        result_payload = final_graph_state.get("final_response")

        if not result_payload:
            raise HTTPException(
                status_code=500, detail="Graph execution failed to produce final response."
            )

        # Store result in Task Queue store
        await task_queue.store_result(task_id, result_payload)

        pipeline_logger.log_step(
            "CLIENT API",
            f"Returning JSON Response to Client for Task [{task_id}]",
            details={
                "status": result_payload.get("status"),
                "confidence_score": result_payload.get("confidence_score"),
                "confidence_caps": (result_payload.get("confidence_basis") or {}).get(
                    "caps_applied", []
                ),
                "offenses_count": len(result_payload.get("identified_offenses", [])),
            },
            status="SUCCESS",
        )

        return LegalAnalysisResponse(**result_payload)

    except HTTPException:
        raise
    except Exception as e:
        pipeline_logger.log_step(
            "API GATEWAY",
            f"Execution error processing Task [{task_id}]: {str(e)}",
            status="ERROR",
        )
        raise HTTPException(status_code=500, detail=str(e))