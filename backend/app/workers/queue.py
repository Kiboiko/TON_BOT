"""Очередь фоновых задач.

Боевой режим — Redis (список + BLPOP), dev/тесты — очередь в памяти процесса.
Публикация сайта и рассылка уведомлений уходят сюда, чтобы HTTP-запрос отвечал
сразу, а фронт опрашивал статус через /api/sites/{id}/publish-status.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import settings

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Job:
    id: str
    name: str
    payload: dict[str, Any]
    attempts: int = 0

    def to_json(self) -> str:
        return json.dumps(
            {"id": self.id, "name": self.name, "payload": self.payload, "attempts": self.attempts}
        )

    @classmethod
    def from_json(cls, raw: str) -> "Job":
        data = json.loads(raw)
        return cls(
            id=data["id"],
            name=data["name"],
            payload=data.get("payload") or {},
            attempts=int(data.get("attempts") or 0),
        )


class JobQueue(Protocol):
    async def enqueue(self, name: str, payload: dict[str, Any]) -> str: ...

    async def dequeue(self, timeout: int = 5) -> Job | None: ...

    async def close(self) -> None: ...


class RedisQueue:
    def __init__(self, url: str | None = None, queue_name: str | None = None) -> None:
        self._url = url or settings.REDIS_URL
        self._name = queue_name or settings.QUEUE_NAME
        self._redis: Any = None

    async def _get(self) -> Any:
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._url, decode_responses=True)
        return self._redis

    async def enqueue(self, name: str, payload: dict[str, Any]) -> str:
        job = Job(id=uuid.uuid4().hex, name=name, payload=payload)
        redis = await self._get()
        await redis.rpush(self._name, job.to_json())
        log.info("job enqueued: %s (%s)", name, job.id)
        return job.id

    async def dequeue(self, timeout: int = 5) -> Job | None:
        redis = await self._get()
        item = await redis.blpop(self._name, timeout=timeout)
        if not item:
            return None
        return Job.from_json(item[1])

    async def requeue(self, job: Job) -> None:
        redis = await self._get()
        job.attempts += 1
        await redis.rpush(self._name, job.to_json())

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None


class MemoryQueue:
    """Очередь в памяти: для тестов и запуска без Redis."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self.processed: list[Job] = []

    async def enqueue(self, name: str, payload: dict[str, Any]) -> str:
        job = Job(id=uuid.uuid4().hex, name=name, payload=payload)
        await self._queue.put(job)
        return job.id

    async def dequeue(self, timeout: int = 5) -> Job | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def requeue(self, job: Job) -> None:
        job.attempts += 1
        await self._queue.put(job)

    def qsize(self) -> int:
        return self._queue.qsize()

    async def close(self) -> None:
        return None


_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = MemoryQueue() if settings.QUEUE_MODE == "memory" else RedisQueue()
    return _queue


def set_queue(queue: JobQueue | None) -> None:
    global _queue
    _queue = queue


async def close_queue() -> None:
    global _queue
    if _queue is not None:
        await _queue.close()
        _queue = None
