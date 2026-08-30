"""Эндпоинты пользователя и кошелька (раздел 4 ТЗ)."""
from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Header
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep, get_or_create_user
from app.core.config import settings
from app.core.errors import BadRequest, Unauthorized
from app.core.telegram_auth import verify_init_data
from app.models import TonProofPayload, User, utcnow
from app.schemas import (
    AuthRequest,
    AuthResponse,
    ConnectWalletRequest,
    ConnectWalletResponse,
    SuccessResponse,
    TonProofPayloadResponse,
    UserOut,
    UserSettingsRequest,
)
from app.services.ton import normalize_address, verify_ton_proof

router = APIRouter(prefix="/user", tags=["user"])


@router.post("/auth", response_model=AuthResponse)
async def auth(
    session: SessionDep,
    body: AuthRequest | None = None,
    x_telegram_init_data: Annotated[str | None, Header(alias="X-Telegram-Init-Data")] = None,
) -> AuthResponse:
    """Вход в Mini App: валидация подписи initData, создание пользователя при первом входе."""
    init_data = (body.init_data if body else None) or x_telegram_init_data or ""
    tg = verify_init_data(init_data)
    user = await get_or_create_user(session, tg)
    return AuthResponse(user=UserOut.model_validate(user), is_admin=user.is_admin)


@router.get("/ton-proof-payload", response_model=TonProofPayloadResponse)
async def ton_proof_payload(session: SessionDep, user: CurrentUser) -> TonProofPayloadResponse:
    """Одноразовый nonce для ton_proof.

    Дополнение к контракту: без серверного nonce подпись кошелька можно
    переиспользовать, поэтому payload выдаём только мы и только на один раз.
    """
    payload = secrets.token_hex(16)
    expires_at = utcnow() + timedelta(seconds=settings.TONPROOF_PAYLOAD_TTL)
    session.add(
        TonProofPayload(payload=payload, telegram_id=user.telegram_id, expires_at=expires_at)
    )
    await session.flush()
    return TonProofPayloadResponse(payload=payload, expires_at=expires_at)


@router.post("/connect-wallet", response_model=ConnectWalletResponse)
async def connect_wallet(
    session: SessionDep, user: CurrentUser, body: ConnectWalletRequest
) -> ConnectWalletResponse:
    """Привязка кошелька: подтверждаем владение адресом проверкой ton_proof."""
    record = await session.scalar(
        select(TonProofPayload).where(TonProofPayload.payload == body.ton_proof.payload)
    )
    if record is None or record.used:
        raise Unauthorized("Unknown or already used ton_proof payload", code="TONPROOF_INVALID")
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        from datetime import timezone

        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < utcnow():
        raise Unauthorized("ton_proof payload expired", code="TONPROOF_EXPIRED")
    if record.telegram_id and record.telegram_id != user.telegram_id:
        raise Unauthorized("ton_proof payload belongs to another user", code="TONPROOF_INVALID")

    ok = await verify_ton_proof(
        body.wallet_address,
        body.ton_proof.timestamp,
        body.ton_proof.domain.value,
        body.ton_proof.signature,
        body.ton_proof.payload,
        state_init=body.ton_proof.state_init,
    )
    if not ok:
        raise Unauthorized("Invalid ton_proof signature", code="TONPROOF_INVALID")

    record.used = True
    address = normalize_address(body.wallet_address)

    # один кошелёк — один аккаунт: иначе чужие домены можно было бы «перехватить»
    other = await session.scalar(
        select(User).where(User.wallet_address == address, User.id != user.id)
    )
    if other is not None:
        raise BadRequest("This wallet is linked to another account", code="WALLET_ALREADY_LINKED")

    user.wallet_address = address
    await session.flush()
    return ConnectWalletResponse(success=True, wallet_address=address)


@router.patch("/settings", response_model=SuccessResponse)
async def update_settings(
    session: SessionDep, user: CurrentUser, body: UserSettingsRequest
) -> SuccessResponse:
    if body.language is not None:
        user.language = body.language
    if body.theme is not None:
        user.theme = body.theme
    await session.flush()
    return SuccessResponse()


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
