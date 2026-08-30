"""Планировщик подписок (A5): периодический прогон статусов и уведомлений.

Запуск: python -m app.workers.scheduler

Работает в связке с Redis-локом, чтобы при нескольких репликах прогон делал
только один процесс.
"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.subscriptions import refresh_statuses

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("scheduler")

LOCK_KEY = "ton_builder:scheduler:lock"


async def _acquire_lock(ttl: int) -> tuple[bool, object | None]:
    if settings.QUEUE_MODE == "memory":
        return True, None
    try:
        import redis.asyncio as aioredis

        redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        got = await redis.set(LOCK_KEY, "1", nx=True, ex=ttl)
        if not got:
            await redis.aclose()
            return False, None
        return True, redis
    except Exception:  # noqa: BLE001 - без Redis работаем в одиночном режиме
        log.warning("scheduler lock unavailable, running without it")
        return True, None


async def run_once() -> dict[str, int]:
    async with SessionLocal() as session:
        stats = await refresh_statuses(session)
        await session.commit()
    if any(stats.values()):
        log.info("subscriptions refreshed: %s", stats)
    return stats


async def run() -> None:
    stopping = asyncio.Event()

    def _stop(*_: object) -> None:
        stopping.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:  # Windows
            signal.signal(sig, _stop)

    log.info("scheduler started (interval=%ss)", settings.SCHEDULER_INTERVAL)
    while not stopping.is_set():
        acquired, redis = await _acquire_lock(settings.SCHEDULER_INTERVAL)
        if acquired:
            try:
                await run_once()
            except Exception:  # noqa: BLE001 - один сбой не должен убивать планировщик
                log.exception("scheduler pass failed")
            finally:
                if redis is not None:
                    await redis.aclose()
        try:
            await asyncio.wait_for(stopping.wait(), timeout=settings.SCHEDULER_INTERVAL)
        except asyncio.TimeoutError:
            pass
    log.info("scheduler stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
