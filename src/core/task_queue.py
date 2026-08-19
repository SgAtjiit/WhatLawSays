import asyncio
import json
import uuid
from typing import Any, Callable, Dict, Optional
import redis.asyncio as aioredis
from src.config import settings
from src.core.logger import pipeline_logger


class RedisTaskQueue:

    def __init__(self):
        self.redis_url = settings.REDIS_URL
        self.queue_key = "whatlawsays:task_queue"
        self.results_key = "whatlawsays:task_results"
        self._redis_client: Optional[aioredis.Redis] = None
        self._in_memory_queue: asyncio.Queue = asyncio.Queue()
        self._in_memory_results: Dict[str, Any] = {}

    async def get_client(self) -> Optional[aioredis.Redis]:
        if self._redis_client is None:
            try:
                self._redis_client = aioredis.from_url(
                    self.redis_url, decode_responses=True
                )
                await self._redis_client.ping()
            except Exception as e:
                pipeline_logger.log_step(
                    "TASK QUEUE (REDIS)",
                    f"Redis connection fallback: {e}. Using asyncio internal in-memory queue.",
                    status="WARNING",
                )
                self._redis_client = False
        return self._redis_client if self._redis_client is not False else None

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
