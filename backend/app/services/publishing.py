"""A4 (часть 4). Фоновая публикация сайта: рендер → TON Storage → статус → уведомление.

Статусы сайта по ТЗ: publishing → published / publish_error.
Задача исполняется воркером (app/workers/publish_worker.py), поэтому открывает
собственную сессию БД и не зависит от жизненного цикла HTTP-запроса.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
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


def publish_is_stale(site: Site) -> bool:
    """Публикация занимает секунды. Дольше — задача потеряна (упал воркер,
    оборвался Redis), и сайт нужно вытаскивать из «публикуется»."""
    started = site.updated_at
    if started is None:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (utcnow() - started).total_seconds() > settings.PUBLISH_STALE_SECONDS


async def enqueue_publish(session: AsyncSession, site: Site) -> str:
    """Переводит сайт в publishing и ставит задачу в очередь.

    Статус коммитится ДО постановки в очередь. Воркер работает в своей сессии и
    успевает опубликовать сайт за десятки миллисекунд — раньше, чем закончится
    HTTP-запрос. Пока `publishing` жил во всё ещё открытой транзакции запроса,
    её коммит ложился поверх результата воркера и затирал `published`: сайт
    оставался в «публикуется» навсегда, хотя bag уже был залит.
    """
    site.status = SiteStatus.publishing
    site.publish_error = None
    await session.commit()

    job_id = await get_queue().enqueue(JOB_PUBLISH_SITE, {"site_id": str(site.id)})
    site.publish_job_id = job_id
    await session.commit()
    return job_id


def build_site_html(site: Site) -> str:
    return render_site(
        site.content_json,
        title=site.title,
        # свой код оплачивается разово: неоплаченный на страницу не попадает
        custom_code=site.custom_code if site.custom_code_paid else None,
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
    try:
        outcome = await _run_publish(site_uuid)
    except Exception:  # noqa: BLE001 — сайт не должен остаться в «публикуется»
        log.exception("publish job for site %s crashed", site_uuid)
        await _mark_publish_error(site_uuid, "Внутренняя ошибка публикации")
        return
    if outcome is not None:
        await _notify_publish_result(outcome)


async def _run_publish(site_uuid: uuid.UUID) -> dict[str, Any] | None:
    async with SessionLocal() as session:
        site = await session.get(Site, site_uuid)
        if site is None:
            log.warning("publish job: site %s not found", site_uuid)
            return None
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
    return outcome


async def _mark_publish_error(site_uuid: uuid.UUID, reason: str) -> None:
    """Аварийно снимает сайт с «публикуется», если задача упала целиком."""
    async with SessionLocal() as session:
        site = await session.get(Site, site_uuid)
        if site is None or site.status != SiteStatus.publishing:
            return
        site.status = SiteStatus.publish_error
        site.publish_error = reason
        await session.commit()


async def recover_stale_publishes() -> int:
    """Возвращает зависшие публикации в publish_error.

    Задача может пропасть безвозвратно: воркер снимает её из Redis через BLPOP
    и, если падает следом, вернуть её уже некому. Без этого прохода сайт вечно
    показывает спиннер, а кнопка «Опубликовать» упирается в 409.
    """
    recovered = 0
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(Site).where(Site.status == SiteStatus.publishing)
        )
        for site in rows.all():
            if not publish_is_stale(site):
                continue
            site.status = SiteStatus.publish_error
            site.publish_error = "Публикация прервалась — попробуйте ещё раз"
            recovered += 1
        if recovered:
            await session.commit()
            log.warning("recovered %s stale publish(es)", recovered)
    return recovered


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
            # Адрес нашего прокси не меняется, поэтому запись домена нужна
            # ровно один раз. Дёргаем владельца только когда точно знаем,
            # что она ещё не стоит: раньше просьба уходила после каждой
            # публикации, хотя подписывать было нечего.
            from app.services.dns import direct_delivery_ready

            if await direct_delivery_ready(outcome["domain"]) is False:
                await notifications.notify(
                    telegram_id, "dns_bind_required", language, title=title
                )
    elif outcome["status"] == SiteStatus.publish_error:
        await notifications.notify(
            telegram_id, "publish_error", language, title=title, error=(outcome["error"] or "")[:200]
        )
