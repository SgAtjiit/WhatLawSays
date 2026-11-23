import asyncio
import base64
import json
import time
import uuid
from typing import Any, Callable, Dict, Optional
import redis.asyncio as aioredis
from src.config import settings
from src.core.logger import pipeline_logger


class RedisTaskQueue:

    def __init__(self):
        self.redis_url = settings.REDIS_URL
        self.queue_key = "whatlawsays:task_queue"
        self.contract_queue_key = "whatlawsays:contract_queue"
        self.results_key = "whatlawsays:task_results"
        self._redis_client: Optional[aioredis.Redis] = None
        # When Redis was unreachable, when we last tried. A False sentinel used
        # to be cached for ever: an API process that started before Redis
        # answered QUEUED for the rest of its life while every task sat in an
        # asyncio.Queue no worker could ever see.
        self._redis_failed_at: Optional[float] = None
        self.reconnect_after: float = 15.0
        self._in_memory_queue: asyncio.Queue = asyncio.Queue()
        self._in_memory_contract_queue: asyncio.Queue = asyncio.Queue()
        self._in_memory_results: Dict[str, Any] = {}

    async def get_client(self) -> Optional[aioredis.Redis]:
        if self._redis_client is False:
            if time.monotonic() - (self._redis_failed_at or 0.0) < self.reconnect_after:
                return None
            self._redis_client = None
        if self._redis_client is None:
            try:
                client = aioredis.from_url(self.redis_url, decode_responses=True)
                await client.ping()
                self._redis_client = client
                self._redis_failed_at = None
            except Exception as e:
                pipeline_logger.log_step(
                    "TASK QUEUE (REDIS)",
                    f"Redis connection fallback: {e}. Using asyncio internal in-memory queue; "
                    f"retrying in {self.reconnect_after:.0f}s.",
                    status="WARNING",
                )
                self._redis_client = False
                self._redis_failed_at = time.monotonic()
        return self._redis_client if self._redis_client is not False else None

    def _drop_client(self) -> None:
        """Forget a client that raised mid-operation, so the next call reconnects."""
        self._redis_client = None

    async def enqueue_task(self, payload: Dict[str, Any]) -> str:
        """Enqueues scenario task into Redis queue and returns task_id."""
        task_id = payload.get("task_id") or str(uuid.uuid4())
        task_data = {
            "task_id": task_id,
            "payload": payload,
            "status": "QUEUED",
        }
        
        client = await self.get_client()
        if client:
            await client.rpush(self.queue_key, json.dumps(task_data))
            pipeline_logger.log_step(
                "TASK QUEUE (REDIS)",
                f"Enqueued task [{task_id}] -> Next: Worker Consumption",
                details={"task_id": task_id, "queue": self.queue_key},
                status="SUCCESS",
            )
        else:
            await self._in_memory_queue.put(task_data)
            pipeline_logger.log_step(
                "TASK QUEUE (MEMORY)",
                f"Enqueued task [{task_id}] into memory queue -> Next: Worker Consumption",
                details={"task_id": task_id},
                status="SUCCESS",
            )
        return task_id

    async def store_result(self, task_id: str, result: Dict[str, Any]):
        """Stores completed task result."""
        client = await self.get_client()
        if client:
            await client.hset(self.results_key, task_id, json.dumps(result))
        else:
            self._in_memory_results[task_id] = result

    async def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves stored task result."""
        client = await self.get_client()
        if client:
            res = await client.hget(self.results_key, task_id)
            return json.loads(res) if res else None
        return self._in_memory_results.get(task_id)

    async def enqueue_contract(self, payload: Dict[str, Any]) -> str:
        """Enqueue a contract review.

        The file bytes are base64-encoded onto the queue rather than written to
        a shared path: the worker may be a different process or container, and a
        filesystem both can reach is an assumption this deployment does not make.
        """
        contract_id = payload.get("contract_id") or str(uuid.uuid4())
        raw = payload.get("data") or b""
        task_data = {
            "contract_id": contract_id,
            "filename": payload.get("filename"),
            "media_type": payload.get("media_type"),
            "contract_type": payload.get("contract_type"),
            "position": payload.get("position"),
            "jurisdiction": payload.get("jurisdiction", "India"),
            "data_b64": base64.b64encode(raw).decode(),
            "status": "QUEUED",
        }

        client = await self.get_client()
        if client:
            try:
                await client.rpush(self.contract_queue_key, json.dumps(task_data))
            except Exception:
                self._drop_client()
                raise
            pipeline_logger.log_step(
                "TASK QUEUE (REDIS)",
                f"Enqueued contract [{contract_id}] -> Next: Contract Worker",
                details={"contract_id": contract_id, "bytes": len(raw)},
                status="SUCCESS",
            )
        else:
            await self._in_memory_contract_queue.put(task_data)
            pipeline_logger.log_step(
                "TASK QUEUE (MEMORY)",
                f"Enqueued contract [{contract_id}] into memory queue -> Next: Contract Worker",
                details={"contract_id": contract_id},
                status="SUCCESS",
            )
        return contract_id

    async def consume_next_contract(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """Pop the next contract task, blocking briefly so the worker does not spin."""
        client = await self.get_client()
        if client:
            try:
                popped = await client.blpop(self.contract_queue_key, timeout=timeout)
                if not popped:
                    return None
                task = json.loads(popped[1])
            except Exception as e:
                self._drop_client()
                pipeline_logger.log_step(
                    "TASK QUEUE (REDIS)", f"Consume failed ({type(e).__name__}: {e}); reconnecting.", status="WARNING"
                )
                return None
        else:
            try:
                task = await asyncio.wait_for(
                    self._in_memory_contract_queue.get(), timeout=timeout
                )
            except (asyncio.TimeoutError, asyncio.QueueEmpty):
                return None
        # A single malformed message -- a producer bug, version skew, an
        # operator typo -- otherwise crashed the worker on task["contract_id"]
        # and stranded every task queued behind it under a restart loop. The
        # message has already been popped, so dropping it here is the recovery.
        try:
            if not isinstance(task, dict) or not task.get("contract_id"):
                raise ValueError("not a contract message")
            task["data"] = base64.b64decode(task.pop("data_b64", "") or "")
        except Exception as e:
            pipeline_logger.log_step(
                "TASK QUEUE",
                f"Discarding malformed contract message ({type(e).__name__}: {e})",
                status="ERROR",
            )
            return None
        return task

    async def consume_next(self) -> Optional[Dict[str, Any]]:
        """Worker method to pop next task from Redis or Memory queue."""
        client = await self.get_client()
        if client:
            try:
                res = await client.lpop(self.queue_key)
                return json.loads(res) if res else None
            except Exception:
                return None
        else:
            try:
                return self._in_memory_queue.get_nowait()
            except asyncio.QueueEmpty:
                return None


task_queue = RedisTaskQueue()
