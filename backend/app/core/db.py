"""Асинхронный слой доступа к БД (SQLAlchemy 2.0)."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine() -> AsyncEngine:
    kwargs: dict = {"echo": settings.DB_ECHO, "future": True}
    if not settings.DATABASE_URL.startswith("sqlite"):
        kwargs.update(pool_size=10, max_overflow=20, pool_pre_ping=True)
    return create_async_engine(settings.DATABASE_URL, **kwargs)


engine: AsyncEngine = _make_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-зависимость: сессия на запрос с автокоммитом/откатом."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
