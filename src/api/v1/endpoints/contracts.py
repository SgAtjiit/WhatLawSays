import time
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from src.config import settings
from src.core.contract_service import new_contract_id, review_contract
from src.core.database import delete_contract, get_contract, save_contract
from src.core.document_parser import (
    MAX_FILE_BYTES,
    SUPPORTED_MEDIA_TYPES,
    DocumentParseError,
)
from src.core.logger import pipeline_logger
from src.core.task_queue import task_queue
from src.schemas.contract import POSITIONS_BY_TYPE, ContractType, PartyPosition
from src.schemas.contract_review import ContractAnswerResponse, ContractReviewResponse

router = APIRouter()

STAGE = "CONTRACT API"

# Uploads are rate-limited far more tightly than scenario text: a review costs
# roughly thirty LLM calls and a Qdrant round trip per HOT clause, against one
# shared API key.
UPLOAD_RATE_LIMIT_PER_MINUTE = 6
_UPLOAD_HISTORY = {}


def _enforce_rate_limit(client_ip: str) -> None:
    now = time.time()
    recent = [t for t in _UPLOAD_HISTORY.get(client_ip, []) if now - t < 60]
    if len(recent) >= UPLOAD_RATE_LIMIT_PER_MINUTE:
        pipeline_logger.log_step(
            STAGE,
            f"Upload rate limit exceeded for IP [{client_ip}]",
            status="WARNING",
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Contract uploads are limited to {UPLOAD_RATE_LIMIT_PER_MINUTE} "
                "per minute. Please try again shortly."
            ),
        )
    recent.append(now)
    _UPLOAD_HISTORY[client_ip] = recent


def _parse_enum(raw: Optional[str], enum, field: str):
    if not raw:
        return None
    try:
        value = enum(raw.strip().upper())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown {field} {raw!r}. Valid values: "
                + ", ".join(member.value for member in enum)
            ),
        )
    # UNKNOWN is the absence of an answer, not an answer. Sent explicitly (the
    # frontend does, for contract type OTHER) it was recorded as USER_DECLARED,
    # which suppressed the "which side are you on?" question and lifted
    # confidence from 0.65 to 0.92 for a review with no idea which party it
    # was for.
    return None if value.value == "UNKNOWN" else value


def _check_side_belongs_to_type(contract_type, position, raw_position):
    """A side from a different kind of contract is a mistake, not a preference.

    Before this the profiler discarded it into notes the response never shows,
    then asked the reviewer which side they were on -- the question they had
    just answered.
    """
    if not contract_type or not position:
        return
    pair = POSITIONS_BY_TYPE.get(contract_type)
    if pair and position not in pair:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{raw_position!r} is not a party to a {contract_type.value} contract. "
                f"Valid sides: {', '.join(p.value for p in pair)}"
            ),
        )


@router.post("/contracts", response_model=ContractReviewResponse, tags=["Contract Review"])
async def upload_and_review_contract(
    request: Request,
    file: UploadFile = File(..., description="The contract: PDF, DOCX or TXT"),
    contract_type: Optional[str] = Form(
        None, description="EMPLOYMENT, NDA, LEASE, SERVICE, FREELANCE, LOAN, VENDOR, SAAS"
    ),
    position: Optional[str] = Form(
        None,
        description=(
            "Which side you are on, e.g. EMPLOYEE or TENANT. Strongly recommended: "
            "the same clause is a serious risk to one party and routine to the other."
        ),
    ),
    jurisdiction: str = Form("India"),
):
    """Upload a contract and get it reviewed.

    Runs synchronously so a caller gets the review in one request. `POST
    /contracts/async` enqueues the same work when the wait is unacceptable.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    _enforce_rate_limit(client_ip)

    parsed_type = _parse_enum(contract_type, ContractType, "contract_type")
    parsed_position = _parse_enum(position, PartyPosition, "position")
    _check_side_belongs_to_type(parsed_type, parsed_position, position)

    # Read with a hard ceiling rather than trusting the declared content length,
    # which a client controls.
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {MAX_FILE_BYTES // 1_048_576} MB limit.",
        )

    contract_id = new_contract_id()
    pipeline_logger.log_step(
        STAGE,
        f"Contract upload from [{client_ip}] -> Contract ID [{contract_id}]",
        details={
            "filename": file.filename,
            "bytes": len(data),
            "declared_type": contract_type,
            "declared_position": position,
        },
    )

    try:
        return ContractReviewResponse(
            **await review_contract(
                data=data,
                filename=file.filename or "contract",
                contract_id=contract_id,
                declared_media_type=file.content_type,
                contract_type=parsed_type,
                position=parsed_position,
                jurisdiction=jurisdiction,
            )
        )
    except DocumentParseError as e:
        # The document could not be read well enough to review honestly. Saying
        # so is the whole point: an empty review reads as a clean contract.
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        pipeline_logger.log_step(
            STAGE,
            f"Contract review failed for [{contract_id}]: {e}",
            status="ERROR",
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/contracts/async", tags=["Contract Review"])
async def enqueue_contract_review(
    request: Request,
    file: UploadFile = File(...),
    contract_type: Optional[str] = Form(None),
    position: Optional[str] = Form(None),
    jurisdiction: str = Form("India"),
):
    """Enqueue a review and return immediately with a contract_id to poll."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    _enforce_rate_limit(client_ip)

    parsed_type = _parse_enum(contract_type, ContractType, "contract_type")
    parsed_position = _parse_enum(position, PartyPosition, "position")
    _check_side_belongs_to_type(parsed_type, parsed_position, position)

    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {MAX_FILE_BYTES // 1_048_576} MB limit.",
        )

    # Without Redis the task would land in this process's asyncio.Queue, which
    # the worker -- a separate process -- can never see, while the client is
    # told QUEUED and polls for ever. Say so, and point at the sync endpoint.
    if await task_queue.get_client() is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "The background review queue is unavailable. "
                f"Use POST {settings.API_V1_STR}/contracts for a synchronous review."
            ),
        )

    contract_id = new_contract_id()
    # A poll URL that 404s until a worker happens to pick the task up -- or for
    # ever, if none is running -- is worse than no URL. Record the contract as
    # QUEUED first, so GET reports its state and DELETE has a row to remove.
    await save_contract({
        "contract_id": contract_id,
        "filename": file.filename or "contract",
        "media_type": file.content_type,
        "contract_type": parsed_type.value if parsed_type else None,
        "position": parsed_position.value if parsed_position else None,
        "status": "QUEUED",
    })
    await task_queue.enqueue_contract(
        {
            "contract_id": contract_id,
            "filename": file.filename or "contract",
            "media_type": file.content_type,
            "contract_type": parsed_type.value if parsed_type else None,
            "position": parsed_position.value if parsed_position else None,
            "jurisdiction": jurisdiction,
            "data": data,
        }
    )
    return {
        "contract_id": contract_id,
        "status": "QUEUED",
        "poll": f"{settings.API_V1_STR}/contracts/{contract_id}",
    }


@router.get("/contracts/{contract_id}", tags=["Contract Review"])
async def get_contract_review(contract_id: str):
    record = await get_contract(contract_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No contract {contract_id!r}.")

    status = record.get("status", "UNKNOWN")
    if record.get("review"):
        return record["review"]
    return {
        "contract_id": contract_id,
        "status": status,
        "error": record.get("error"),
        "filename": record.get("filename"),
        "clause_count": record.get("clause_count"),
    }


@router.delete("/contracts/{contract_id}", tags=["Contract Review"])
async def delete_contract_review(contract_id: str):
    """Delete an uploaded contract and its review.

    Contracts carry salaries, addresses and party names, and the extracted text
    is retained so findings stay re-verifiable. That makes a working delete a
    requirement, not a nicety.
    """
    removed = await delete_contract(contract_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No contract {contract_id!r}.")
    pipeline_logger.log_step(
        STAGE, f"Contract [{contract_id}] and its review deleted", status="SUCCESS"
    )
    return {"contract_id": contract_id, "deleted": True}


class AskRequest(BaseModel):
    question: str = Field(..., max_length=1000)

    @field_validator("question")
    @classmethod
    def _must_have_words(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("question must be at least 3 characters")
        return stripped


def _stored_review_or_404(record, contract_id):
    if record is None or not record.get("review"):
        raise HTTPException(
            status_code=404,
            detail=f"No completed review for contract {contract_id!r}.",
        )
    return record["review"]


def _clauses_from(review):
    # The BM25 index and the answer formatter address clauses by attribute; the
    # stored review holds them as plain dicts.
    return [SimpleNamespace(**clause) for clause in review.get("clauses", [])]


@router.post(
    "/contracts/{contract_id}/ask",
    response_model=ContractAnswerResponse,
    tags=["Contract Review"],
)
async def ask_about_contract(contract_id: str, payload: AskRequest):
    """Ask a question about a reviewed contract.

    Answered only from the clauses in the document, and says which. A question
    the contract does not address is told so, rather than answered from what
    contracts usually say.
    """
    from src.core.contract_qa import answer_question

    review = _stored_review_or_404(await get_contract(contract_id), contract_id)
    clauses = _clauses_from(review)
    explanations = {
        c["index"]: {"plain_english": c.get("plain_english", "")} for c in review.get("clauses", [])
    }
    result = await answer_question(
        question=payload.question,
        clauses=clauses,
        findings=review.get("findings", []),
        explanations=explanations,
        position=review.get("position", "UNKNOWN"),
    )
    return ContractAnswerResponse(
        contract_id=contract_id, question=payload.question, **result
    )


@router.get("/contracts/{contract_id}/redlines", tags=["Contract Review"])
async def get_redlines(contract_id: str):
    review = _stored_review_or_404(await get_contract(contract_id), contract_id)
    return {"contract_id": contract_id, "redlines": review.get("redlines", [])}


@router.get("/contracts/{contract_id}/report.pdf", tags=["Contract Review"])
async def download_report(contract_id: str):
    """The review as a PDF, leading with what to ask for."""
    from src.core.report_export import build_report_pdf

    review = _stored_review_or_404(await get_contract(contract_id), contract_id)
    pdf = build_report_pdf(review, review.get("redlines", []))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="contract-review-{contract_id}.pdf"'
        },
    )


@router.get("/contracts/meta/supported", tags=["Contract Review"])
async def supported_options():
    from src.schemas.contract import POSITIONS_BY_TYPE

    return {
        "media_types": sorted(SUPPORTED_MEDIA_TYPES),
        "max_file_bytes": MAX_FILE_BYTES,
        "contract_types": [t.value for t in ContractType],
        "positions_by_type": {
            t.value: [p.value for p in pair] for t, pair in POSITIONS_BY_TYPE.items()
        },
    }
