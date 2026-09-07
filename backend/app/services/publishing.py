"""A4 (часть 4). Фоновая публикация сайта: рендер → TON Storage → статус → уведомление.

Статусы сайта по ТЗ: publishing → published / publish_error.
Задача исполняется воркером (app/workers/publish_worker.py), поэтому открывает
собственную сессию БД и не зависит от жизненного цикла HTTP-запроса.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.errors import describe_error
from app.models import Site, SiteStatus, User, utcnow
from app.services import notifications
from app.services.renderer import render_site
from app.services.storage import get_storage, write_site_files
from app.workers.queue import get_queue

log = logging.getLogger(__name__)

JOB_PUBLISH_SITE = "publish_site"


async def enqueue_publish(session: AsyncSession, site: Site) -> str:
    """Переводит сайт в publishing и ставит задачу в очередь."""
    site.status = SiteStatus.publishing
    site.publish_error = None
    await session.flush()

    job_id = await get_queue().enqueue(JOB_PUBLISH_SITE, {"site_id": str(site.id)})
    site.publish_job_id = job_id
    await session.flush()
    return job_id


def build_site_html(site: Site) -> str:
    return render_site(
        site.content_json,
        title=site.title,
        custom_code=site.custom_code,
        domain=site.domain,
        site_type=site.type.value,
    )


async def publish_site(session: AsyncSession, site: Site) -> Site:
    """Синхронная часть публикации: рендер и заливка в TON Storage."""
    user = await session.get(User, site.user_id)
    html = build_site_html(site)
    build_dir = Path(settings.SITES_BUILD_DIR) / str(site.id)

    try:
        write_site_files(build_dir, html)
        bag = await get_storage().upload_directory(
            build_dir, description=f"{site.title} ({site.domain or site.id})"
        )
    except Exception as exc:  # noqa: BLE001 — любая ошибка публикации фиксируется в БД
        site.status = SiteStatus.publish_error
        site.publish_error = describe_error(exc)[:1000]
        await session.flush()
        log.exception("publish failed for site %s", site.id)
        if user:
            await notifications.notify(
                user.telegram_id,
                "publish_error",
                user.language,
                title=site.title,
                error=describe_error(exc)[:200],
            )
        return site

    site.storage_bag_id = bag.bag_id
    site.status = SiteStatus.published
    site.published_at = utcnow()
    site.publish_error = None
    await session.flush()
    log.info("site %s published, bag=%s", site.id, bag.bag_id)

    if user:
        domain = f" на {site.domain}" if site.domain else ""
        await notifications.notify(
            user.telegram_id, "site_published", user.language, title=site.title, domain=domain
        )
        if site.dns_item_address:
            # bag id обновился — владельцу нужно подписать новую DNS-запись
            await notifications.notify(
                user.telegram_id, "dns_bind_required", user.language, title=site.title
            )
    return site


async def run_publish_job(site_id: str | uuid.UUID) -> None:
    """Точка входа воркера: своя сессия, свой коммит."""
    site_uuid = site_id if isinstance(site_id, uuid.UUID) else uuid.UUID(str(site_id))
    async with SessionLocal() as session:
        site = await session.get(Site, site_uuid)
        if site is None:
            log.warning("publish job: site %s not found", site_uuid)
            return
        await publish_site(session, site)
        await session.commit()
