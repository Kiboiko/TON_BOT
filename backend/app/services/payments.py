"""A5 (часть 1). Платежи: создание записи, сборка транзакции, подтверждение on-chain.

Схема одна для подписок, премиум-блока и доменов:

    1. создаём Payment(status=pending) с уникальным комментарием-нонсом;
    2. отдаём фронту транзакцию TON Connect (адрес казначейства + сумма + нонс);
    3. фронт присылает tx_hash → идём в блокчейн и проверяем платёж;
    4. только после успешной проверки активируем то, за что заплатили.
"""
from __future__ import annotations

import base64
import logging
import secrets
import time
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import BadRequest, Conflict, NotFound, PaymentNotConfirmed
from app.models import Payment, PaymentPurpose, PaymentStatus, User, utcnow
from app.services.subdom_client import TransactionMessage, TransactionResponse
from app.services.ton import to_nano, verify_payment

log = logging.getLogger(__name__)


def build_comment_payload(comment: str) -> str:
    """Тело сообщения с текстовым комментарием (op=0) в base64-BOC."""
    from pytoniq_core import begin_cell

    cell = begin_cell().store_uint(0, 32)
    data = comment.encode()
    if len(data) > 120:  # длиннее в одну ячейку не влезет, нонсы короткие
        data = data[:120]
    cell = cell.store_bytes(data)
    return base64.b64encode(cell.end_cell().to_boc()).decode()


def new_payment_comment(prefix: str = "tsb") -> str:
    return f"{prefix}-{secrets.token_hex(6)}"


async def create_payment(
    session: AsyncSession,
    *,
    user: User,
    amount: Decimal,
    purpose: PaymentPurpose,
    related_id: uuid.UUID | None = None,
    destination: str | None = None,
) -> Payment:
    destination = destination or settings.TREASURY_ADDRESS
    if not destination:
        raise BadRequest("Treasury address is not configured", code="TREASURY_NOT_CONFIGURED")

    payment = Payment(
        user_id=user.id,
        amount=Decimal(str(amount)),
        purpose=purpose,
        related_id=related_id,
        comment=new_payment_comment(),
        destination=destination,
        status=PaymentStatus.pending,
    )
    session.add(payment)
    await session.flush()
    return payment


def build_payment_transaction(payment: Payment, *, valid_for: int = 900) -> TransactionResponse:
    """Транзакция оплаты, готовая к подписи в TON Connect."""
    return TransactionResponse(
        valid_until=int(time.time()) + valid_for,
        messages=[
            TransactionMessage(
                address=payment.destination or settings.TREASURY_ADDRESS,
                amount=str(to_nano(payment.amount)),
                payload=build_comment_payload(payment.comment or ""),
            )
        ],
        network="-239" if settings.TON_NETWORK == "mainnet" else "-3",
    )


async def get_payment_for_user(
    session: AsyncSession, payment_id: uuid.UUID, user: User
) -> Payment:
    payment = await session.get(Payment, payment_id)
    if payment is None or payment.user_id != user.id:
        raise NotFound("Payment not found", code="PAYMENT_NOT_FOUND")
    return payment


async def confirm_payment(
    session: AsyncSession, payment: Payment, tx_hash: str
) -> Payment:
    """Проверяет платёж в блокчейне и переводит его в confirmed.

    Фронту здесь не верим: значение имеет только то, что нашлось on-chain.
    """
    if payment.status == PaymentStatus.confirmed:
        return payment

    # один и тот же хэш не может оплатить две разные покупки
    dup = await session.scalar(
        select(Payment).where(Payment.tx_hash == tx_hash, Payment.id != payment.id)
    )
    if dup is not None:
        raise Conflict("This transaction is already used", code="TX_ALREADY_USED")

    check = await verify_payment(
        tx_hash=tx_hash,
        destination=payment.destination or settings.TREASURY_ADDRESS,
        min_amount=Decimal(payment.amount),
        comment=payment.comment,
        since=int(payment.created_at.timestamp()) - 3600 if payment.created_at else None,
    )
    if not check.ok:
        payment.error = check.reason
        await session.flush()
        raise PaymentNotConfirmed(check.reason or "Transaction is not confirmed on-chain")

    payment.tx_hash = check.tx.tx_hash if check.tx and check.tx.tx_hash else tx_hash
    payment.status = PaymentStatus.confirmed
    payment.confirmed_at = utcnow()
    payment.error = None
    await session.flush()
    log.info("payment %s confirmed (%s TON)", payment.id, payment.amount)
    return payment
