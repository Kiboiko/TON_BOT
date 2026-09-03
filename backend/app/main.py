"""Точка входа backend-а TON Site Builder.

Запуск: uvicorn app.main:app --host 0.0.0.0 --port 8000
OpenAPI-схема (её отдаём Разработчику B под мок-сервер): /api/openapi.json
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.api.public import router as public_router
from app.api.uploads import router as uploads_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.services.notifications import close_transport
from app.services.dns_resolver import close_resolver
from app.services.storage import close_storage
from app.services.subdom_client import close_domain_service
from app.services.ton import close_ton_client
from app.workers.queue import close_queue

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("starting backend (env=%s, network=%s)", settings.ENV, settings.TON_NETWORK)
    if settings.ENV == "prod":
        problems = []
        if not settings.TELEGRAM_BOT_TOKEN:
            problems.append("TELEGRAM_BOT_TOKEN")
        if not settings.TREASURY_ADDRESS:
            problems.append("TREASURY_ADDRESS")
        if settings.ALLOW_INSECURE_AUTH:
            problems.append("ALLOW_INSECURE_AUTH must be false in prod")
        if settings.TON_VERIFY_MODE != "onchain":
            problems.append("TON_VERIFY_MODE must be onchain in prod")
        if problems:
            raise RuntimeError(f"Invalid production config: {', '.join(problems)}")
    yield
    await close_queue()
    await close_domain_service()
    await close_resolver()
    await close_ton_client()
    await close_storage()
    await close_transport()


app = FastAPI(
    title="TON Site Builder API",
    version="1.0.0",
    description="Backend Telegram Mini App для создания и публикации сайтов в сети TON",
    docs_url=f"{settings.API_PREFIX}/docs",
    redoc_url=f"{settings.API_PREFIX}/redoc",
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)
app.include_router(api_router, prefix=settings.API_PREFIX)
# опубликованные сайты отдаются с корня: https://host/s/<site_id>
app.include_router(public_router)
# загрузка и отдача картинок конструктора
app.include_router(uploads_router)


@app.get("/health", tags=["service"])
async def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.ENV, "network": settings.TON_NETWORK}


@app.get(f"{settings.API_PREFIX}/health", tags=["service"], include_in_schema=False)
async def api_health() -> dict[str, str]:
    return await health()
