"""Run a contract review, end to end.

The single place that turns uploaded bytes into a stored review. The API
endpoint and the Redis worker both call this, so a review means the same thing
however it was triggered -- the divergence that `src/api/v1/endpoints/analyze.py`
already carries a comment about, where two entry points scored the same scenario
differently.

Parsing and segmentation happen here rather than inside the graph: the grounding
retry re-enters the analyst, and a node that re-cut clause boundaries would move
text out from under offsets already recorded in first-pass findings.
"""

import uuid
from typing import Any, Dict, Optional

from src.agents.contract_graph import contract_review_app
from src.core.clause_segmenter import segment_clauses
from src.core.database import save_contract
from src.core.document_parser import DocumentParseError, parse_document
from src.core.logger import pipeline_logger
from src.schemas.contract import ContractType, PartyPosition

STAGE = "CONTRACT REVIEW SERVICE"


def new_contract_id() -> str:
    return uuid.uuid4().hex[:16]


def initial_state(document, clauses, contract_id, contract_type, position, jurisdiction):
    return {
        "task_id": contract_id,
        "jurisdiction": jurisdiction,
        "document": document,
        "document_text": document.text,
        "clauses": clauses,
        "declared_contract_type": contract_type,
        "declared_position": position,
        "contract_type": (contract_type or ContractType.UNKNOWN).value,
        "position": (position or PartyPosition.UNKNOWN).value,
        "clause_tier": {},
        "clause_queries": {},
        "clause_chunks": {},
        "explanations": {},
        "rule_findings": [],
        "llm_findings": [],
        "findings": [],
        "suppressed_llm_findings": [],
        "missing_clauses": [],
        "consistency_findings": [],
        "grounding_passed": False,
        "grounding_feedback": None,
        "ungrounded_clause_indices": [],
        "retry_count": 0,
        "llm_available": True,
        "reranker_available": True,
        "llm_calls_used": 0,
        "degraded_nodes": [],
        "confidence_score": None,
        "confidence_basis": None,
        "final_response": None,
    }


async def review_contract(
    *,
    data: bytes,
    filename: str,
    contract_id: Optional[str] = None,
    declared_media_type: Optional[str] = None,
    contract_type: Optional[ContractType] = None,
    position: Optional[PartyPosition] = None,
    jurisdiction: str = "India",
    persist: bool = True,
) -> Dict[str, Any]:
    """Parse, segment and review an uploaded contract.

    Raises DocumentParseError for anything that cannot honestly be reviewed --
    a scan with no text layer, a password-protected file, a document too short
    to be a contract. Those are reported to the caller rather than turned into
    an empty review that would read as a clean bill of health.
    """
    contract_id = contract_id or new_contract_id()

    # UNKNOWN is the absence of an answer, not an answer. Passed explicitly it
    # was recorded as USER_DECLARED, which suppressed the "which side are you
    # on?" question and lifted confidence for a review that had no idea which
    # party it was for.
    if contract_type == ContractType.UNKNOWN:
        contract_type = None
    if position == PartyPosition.UNKNOWN:
        position = None

    document = parse_document(data, filename, declared_media_type)
    clauses = segment_clauses(document)

    pipeline_logger.log_step(
        STAGE,
        f"Contract [{contract_id}] parsed: {document.char_count} characters, "
        f"{len(clauses)} clauses -> Executing Contract Review Orchestrator (LangGraph)",
        details={
            "filename": filename,
            "media_type": document.media_type,
            "pages": document.page_count,
            "declared_type": contract_type.value if contract_type else None,
            "declared_position": position.value if position else None,
            "extraction_warnings": document.extraction_warnings,
        },
    )

    if persist:
        await save_contract({
            "contract_id": contract_id,
            "filename": filename,
            "media_type": document.media_type,
            "contract_type": contract_type.value if contract_type else None,
            "position": position.value if position else None,
            "status": "RUNNING",
            "document_text": document.text,
            "char_count": document.char_count,
            "page_count": document.page_count,
            "clause_count": len(clauses),
        })

    try:
        final_state = await contract_review_app.ainvoke(
            initial_state(document, clauses, contract_id, contract_type, position, jurisdiction)
        )
        review = final_state.get("final_response")
        if not review:
            raise RuntimeError("Contract graph completed without producing a review.")
    except Exception as e:
        # Otherwise the row stays RUNNING for ever with error=None, and a poller
        # has no way to learn the review died.
        if persist:
            await save_contract(
                {"contract_id": contract_id, "status": "FAILED", "error": str(e)[:1000]},
                update_only=True,
            )
        raise

    review["contract_id"] = contract_id

    if persist:
        # Update-only: if the user deleted the contract while this ran, the
        # completion write must not bring it back.
        await save_contract({
            "contract_id": contract_id,
            "filename": filename,
            "status": review.get("status", "SUCCESS"),
            "contract_type": review.get("contract_type"),
            "position": review.get("position"),
            "confidence_score": review.get("confidence_score"),
            "overall_risk": review.get("overall_risk"),
            "clause_count": review.get("clause_count"),
            "review": review,
        }, update_only=True)

    pipeline_logger.log_step(
        STAGE,
        f"Contract [{contract_id}] reviewed -> Status [{review.get('status')}] "
        f"Risk [{review.get('overall_risk')}] Findings [{len(review.get('findings', []))}]",
        status="SUCCESS",
    )
    return review


__all__ = ["review_contract", "new_contract_id", "DocumentParseError"]
