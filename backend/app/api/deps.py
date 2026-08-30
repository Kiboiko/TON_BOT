"""Зависимости FastAPI: авторизация по initData и проверка прав администратора."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.errors import Forbidden, Unauthorized
from app.core.telegram_auth import TelegramUser, verify_init_data
from app.models import Language, User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_or_create_user(session: AsyncSession, tg: TelegramUser) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == tg.id))
    if user is None:
        user = User(
            telegram_id=tg.id,
            username=tg.username,
            first_name=tg.first_name,
            last_name=tg.last_name,
            language=Language.ru if (tg.language_code or "ru").startswith("ru") else Language.en,
            is_admin=tg.id in settings.admin_telegram_ids,
        )
        session.add(user)
        await session.flush()
    else:
        # профиль в Telegram мог измениться — держим копию свежей
        changed = False
        for field, value in (
            ("username", tg.username),
            ("first_name", tg.first_name),
            ("last_name", tg.last_name),
        ):
            if value and getattr(user, field) != value:
                setattr(user, field, value)
                changed = True
        if tg.id in settings.admin_telegram_ids and not user.is_admin:
            user.is_admin = True
            changed = True
        if changed:
            await session.flush()
    return user


async def current_user(
    session: SessionDep,
    x_telegram_init_data: Annotated[str | None, Header(alias="X-Telegram-Init-Data")] = None,
) -> User:
    """Пользователь текущего запроса. Заголовок обязателен для всех /api/*."""
    tg = verify_init_data(x_telegram_init_data or "")
    user = await get_or_create_user(session, tg)
    if user.is_blocked:
        raise Forbidden("User is blocked", code="USER_BLOCKED")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def current_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise Forbidden("Admin rights required", code="ADMIN_REQUIRED")
    return user


AdminUser = Annotated[User, Depends(current_admin)]


def require_wallet(user: User) -> str:
    if not user.wallet_address:
        raise Unauthorized("Connect your TON wallet first", code="WALLET_NOT_CONNECTED")
    return user.wallet_address
