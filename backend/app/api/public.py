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

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.errors import NotFound
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
