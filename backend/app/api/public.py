"""Публичная отдача опубликованных сайтов по http.

Боевой способ доставки — TON Storage: контент лежит в «мешке», домен .ton
указывает на него DNS-записью, открывается TON-браузером. Но пока домен не
привязан (или на стенде, где storage работает в локальном режиме), увидеть
результат было бы негде — поэтому backend отдаёт опубликованную страницу и
обычной ссылкой.

Роутер намеренно без авторизации: это опубликованный сайт, он публичен.
Черновики и снятые с публикации сайты не отдаются.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.errors import NotFound
from sqlalchemy import select

from app.models import Site, SiteStatus
from app.services.publishing import build_site_html

router = APIRouter(tags=["public"])


def public_site_url(site: Site) -> str | None:
    """Ссылка на опубликованный сайт — то, что показываем пользователю."""
    if site.status != SiteStatus.published:
        return None
    base = (settings.PUBLIC_SITE_BASE_URL or settings.MINI_APP_URL or "").rstrip("/")
    return f"{base}/s/{site.id}" if base else None


@router.get("/s/{site_id}", response_class=HTMLResponse, include_in_schema=False)
async def serve_site(site_id: uuid.UUID) -> HTMLResponse:
    async with SessionLocal() as session:
        site = await session.get(Site, site_id)
        if site is None or site.status != SiteStatus.published:
            raise NotFound("Site is not published", code="SITE_NOT_PUBLISHED")

        # отдаём ровно то, что ушло в хранилище; если файла нет (например, том
        # пересоздали) — перерисовываем из content_json, он у нас первоисточник
        index = Path(settings.SITES_BUILD_DIR) / str(site.id) / "index.html"
        try:
            html = index.read_text(encoding="utf-8")
        except OSError:
            html = build_site_html(site)

    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "public, max-age=60",
            # чужой HTML не должен утаскивать реферер платформы
            "Referrer-Policy": "no-referrer",
        },
    )


async def _published_html(site: Site) -> str:
    """Отдаём ровно то, что ушло в хранилище; файла нет — рисуем из content_json."""
    index = Path(settings.SITES_BUILD_DIR) / str(site.id) / "index.html"
    try:
        return index.read_text(encoding="utf-8")
    except OSError:
        return build_site_html(site)


@router.get("/ton-site", response_class=HTMLResponse, include_in_schema=False)
@router.get("/ton-site/{path:path}", response_class=HTMLResponse, include_in_schema=False)
async def serve_ton_site(request: Request, path: str = "") -> HTMLResponse:
    """Отдача сайта в сеть TON: домен берётся из заголовка Host.

    Сюда nginx направляет всё, что пришло из TON через rldp-http-proxy. Один
    ADNL-адрес обслуживает все домены платформы, поэтому какой именно сайт
    показать — решает Host, а не путь.
    """
    host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    if not host:
        raise NotFound("Unknown domain", code="DOMAIN_UNKNOWN")

    async with SessionLocal() as session:
        site = await session.scalar(
            select(Site).where(Site.domain == host, Site.status == SiteStatus.published)
        )
        if site is None:
            raise NotFound("No published site on this domain", code="SITE_NOT_PUBLISHED")
        html = await _published_html(site)

    return HTMLResponse(
        html,
        headers={"Cache-Control": "public, max-age=60", "Referrer-Policy": "no-referrer"},
    )
