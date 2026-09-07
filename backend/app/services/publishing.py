"""A4 (часть 4). Фоновая публикация сайта: рендер → TON Storage → статус → уведомление.

Статусы сайта по ТЗ: publishing → published / publish_error.
Задача исполняется воркером (app/workers/publish_worker.py), поэтому открывает
собственную сессию БД и не зависит от жизненного цикла HTTP-запроса.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

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
        return site

    site.storage_bag_id = bag.bag_id
    site.status = SiteStatus.published
    site.published_at = utcnow()
    site.publish_error = None
    await session.flush()
    log.info("site %s published, bag=%s", site.id, bag.bag_id)
    return site


async def run_publish_job(site_id: str | uuid.UUID) -> None:
    """Точка входа воркера: своя сессия, свой коммит.

    Уведомления отправляются строго после коммита. Раньше они шли внутри
    транзакции, и зависший запрос к Telegram оставлял сайт навсегда в статусе
    «публикуется»: результат публикации так и не сохранялся.
    """
    site_uuid = site_id if isinstance(site_id, uuid.UUID) else uuid.UUID(str(site_id))
    async with SessionLocal() as session:
        site = await session.get(Site, site_uuid)
        if site is None:
            log.warning("publish job: site %s not found", site_uuid)
            return
        await publish_site(session, site)
        user = await session.get(User, site.user_id)
        # значения снимаем до коммита: после него атрибуты нужно было бы перечитывать
        outcome = {
            "telegram_id": user.telegram_id if user else None,
            "language": user.language if user else None,
            "status": site.status,
            "title": site.title,
            "domain": site.domain,
            "dns_item_address": site.dns_item_address,
            "error": site.publish_error,
        }
        await session.commit()

    await _notify_publish_result(outcome)


async def _notify_publish_result(outcome: dict[str, Any]) -> None:
    """Сообщение пользователю об итоге публикации — уже вне транзакции."""
    telegram_id = outcome["telegram_id"]
    if telegram_id is None:
        return
    language = outcome["language"]
    title = outcome["title"]

    if outcome["status"] == SiteStatus.published:
        domain = f" на {outcome['domain']}" if outcome["domain"] else ""
        await notifications.notify(
            telegram_id, "site_published", language, title=title, domain=domain
        )
        if outcome["dns_item_address"]:
            # bag id обновился — владельцу нужно подписать новую DNS-запись
            await notifications.notify(telegram_id, "dns_bind_required", language, title=title)
    elif outcome["status"] == SiteStatus.publish_error:
        await notifications.notify(
            telegram_id, "publish_error", language, title=title, error=(outcome["error"] or "")[:200]
        )
