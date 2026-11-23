import time
import uuid
from pathlib import Path
from typing import Dict
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from src.agents.graph import legal_agent_app
from src.api.v1.router import api_router
from src.config import settings
from src.core.auth import User, require_user
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

# Contract review lives in the v1 router. Until now nothing mounted that router,
# so every endpoint defined under src/api/v1/endpoints was unreachable.
app.include_router(api_router, prefix=settings.API_V1_STR)

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
async def analyze_scenario(
    payload: ScenarioRequest, request: Request, user: User = Depends(require_user)
):
    """
    Intake a citizen scenario, validate payload, rate-limit, enqueue task,
    route through the Agentic LangGraph pipeline, and return structured analysis.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    now = time.time()

    # Rate limiting is per user: behind a proxy or a shared office network, every
    # user would otherwise share one IP and one budget.
    request_times = RATE_LIMIT_STORE.get(user.uid, [])
    request_times = [t for t in request_times if now - t < 60]  # keep last 60s
    if len(request_times) >= settings.RATE_LIMIT_PER_MINUTE:
        pipeline_logger.log_step(
            "API GATEWAY",
            f"Rate limit exceeded for user [{user.uid}]",
            status="WARNING",
        )
        raise HTTPException(
            status_code=429, detail="Rate limit exceeded. Please try again in a minute."
        )
    request_times.append(now)
    RATE_LIMIT_STORE[user.uid] = request_times

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

# The built React app, served from the same origin as the API. Registered last,
# so every API route above is matched first.
_NOT_THE_APP = ("api/", "docs", "redoc", "openapi.json", "health")


def mount_frontend(target: FastAPI, dist: Path) -> bool:
    dist = dist.resolve()
    if not (dist / "index.html").is_file():
        return False
    if (dist / "assets").is_dir():
        target.mount("/assets", StaticFiles(directory=dist / "assets"), name="frontend-assets")

    @target.get("/{path:path}", include_in_schema=False)
    async def serve_frontend(path: str):
        if path.startswith(_NOT_THE_APP):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        # Client-side routes. index.html must never be cached, or a deploy
        # leaves browsers holding asset names that no longer exist.
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return True


mount_frontend(app, Path(settings.FRONTEND_DIST))
