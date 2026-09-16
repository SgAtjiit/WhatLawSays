"""Consume queued contract reviews.

The scenario pipeline enqueues a task and then immediately runs it inline
(src/main.py), so its queue is decorative. Contract review is where a real
worker earns its place: a review is roughly thirty LLM calls and a Qdrant round
trip per HOT clause, which is far too long to hold an HTTP request open.

Usage:
    uv run python -m scripts.contract_worker
"""

import asyncio
import signal

from src.core.contract_service import review_contract
from src.core.database import init_db, save_contract
from src.core.document_parser import DocumentParseError
from src.core.logger import pipeline_logger
from src.core.task_queue import task_queue
from src.core.vector_store import vector_store
from src.schemas.contract import ContractType, PartyPosition

STAGE = "CONTRACT WORKER"
_running = True


def _stop(*_args):
    global _running
    _running = False
    pipeline_logger.log_step(STAGE, "Shutdown signal received; finishing current task.", status="WARNING")


async def handle(task):
    contract_id = task["contract_id"]
    try:
        await review_contract(
            data=task["data"],
            filename=task.get("filename") or "contract",
            contract_id=contract_id,
            declared_media_type=task.get("media_type"),
            contract_type=ContractType(task["contract_type"]) if task.get("contract_type") else None,
            position=PartyPosition(task["position"]) if task.get("position") else None,
            jurisdiction=task.get("jurisdiction", "India"),
        )
    except DocumentParseError as e:
        # A document that cannot be read is a terminal outcome, not a retry: the
        # bytes will not improve. The reason is stored so the caller polling this
        # contract learns why rather than waiting forever.
        pipeline_logger.log_step(
            STAGE, f"Contract [{contract_id}] unreadable: {e}", status="WARNING"
        )
        await save_contract({
            "contract_id": contract_id,
            "filename": task.get("filename") or "contract",
            "status": "FAILED",
            "error": str(e),
        }, update_only=True)
    except Exception as e:
        pipeline_logger.log_step(
            STAGE, f"Contract [{contract_id}] review error: {e}", status="ERROR"
        )
        await save_contract({
            "contract_id": contract_id,
            "filename": task.get("filename") or "contract",
            "status": "FAILED",
            "error": str(e)[:1000],
        }, update_only=True)


async def main():
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    pipeline_logger.log_step(STAGE, "Contract worker starting; warming vector store...")
    await init_db()
    await vector_store.setup_collection()
    pipeline_logger.log_step(
        STAGE, "Contract worker ready, polling the queue.", status="SUCCESS"
    )

    while _running:
        task = await task_queue.consume_next_contract(timeout=5)
        if task is None:
            continue
        try:
            pipeline_logger.log_step(
                STAGE, f"Consuming contract [{task['contract_id']}] -> Contract Review Service"
            )
            await handle(task)
        except Exception as e:
            pipeline_logger.log_step(STAGE, f"Task skipped after unexpected error: {e}", status="ERROR")

    pipeline_logger.log_step(STAGE, "Contract worker stopped.", status="SUCCESS")


if __name__ == "__main__":
    asyncio.run(main())
