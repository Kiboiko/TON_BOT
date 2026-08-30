"""Воркер фоновых задач: публикация сайтов.

Запуск: python -m app.workers.publish_worker
"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import settings
from app.services.notifications import close_transport
from app.services.publishing import JOB_PUBLISH_SITE, run_publish_job
from app.workers.queue import Job, close_queue, get_queue

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("worker")

MAX_ATTEMPTS = 3


async def handle(job: Job) -> None:
    if job.name == JOB_PUBLISH_SITE:
        await run_publish_job(job.payload["site_id"])
    else:
        log.warning("unknown job: %s", job.name)


async def run() -> None:
    queue = get_queue()
    stopping = asyncio.Event()

    def _stop(*_: object) -> None:
        log.info("stop signal received")
        stopping.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:  # Windows
            signal.signal(sig, _stop)

    log.info("publish worker started (queue=%s)", settings.QUEUE_MODE)
    while not stopping.is_set():
        try:
            job = await queue.dequeue(timeout=5)
        except Exception:  # noqa: BLE001 - обрыв соединения с Redis не должен ронять воркер
            log.exception("queue error, retry in 3s")
            await asyncio.sleep(3)
            continue
        if job is None:
            continue
        try:
            await handle(job)
        except Exception:  # noqa: BLE001
            log.exception("job %s failed (attempt %s)", job.id, job.attempts + 1)
            requeue = getattr(queue, "requeue", None)
            if requeue and job.attempts + 1 < MAX_ATTEMPTS:
                await requeue(job)

    await close_queue()
    await close_transport()
    log.info("publish worker stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
