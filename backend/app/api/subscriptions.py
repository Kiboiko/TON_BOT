"""Тарифы и подписки: витрина, покупка, подтверждение оплаты, список подписок."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import BadRequest, NotFound
from app.models import (
    PaymentPurpose,
    Site,
    Subscription,
    Tariff,
    TariffKind,
)
from app.schemas import (
    ConfirmPaymentRequest,
    PurchaseRequest,
    PurchaseResponse,
    SubscriptionOut,
    SubscriptionResponse,
    TariffOut,
    TonConnectTransaction,
)
from app.services import payments as payments_service
from app.services import subscriptions as subs_service

router = APIRouter(tags=["subscriptions"])


@router.get("/tariffs", response_model=list[TariffOut])
async def list_tariffs(session: SessionDep, _: CurrentUser) -> list[TariffOut]:
    rows = await session.scalars(
        select(Tariff)
        .where(Tariff.is_active.is_(True), Tariff.kind != TariffKind.custom_code)
        # сначала младшие тарифы, внутри тарифа — от короткого срока к длинному
        .order_by(Tariff.sites_limit.asc(), Tariff.price_ton.asc())
    )
    return [TariffOut.model_validate(t) for t in rows.all()]


@router.post("/subscriptions/purchase", response_model=PurchaseResponse)
async def purchase(
    session: SessionDep, user: CurrentUser, body: PurchaseRequest
) -> PurchaseResponse:
    """Создаёт pending-платёж и отдаёт транзакцию для подписи в TON Connect."""
    tariff = await session.get(Tariff, body.tariff_id)
    if tariff is None or not tariff.is_active:
        raise NotFound("Tariff not found", code="TARIFF_NOT_FOUND")

    if body.site_id is not None:
        site = await session.get(Site, body.site_id)
        if site is None or site.user_id != user.id:
            raise NotFound("Site not found", code="SITE_NOT_FOUND")

    payment = await payments_service.create_payment(
        session,
        user=user,
        amount=tariff.price_ton,
        purpose=PaymentPurpose.subscription,
        related_id=tariff.id,
    )
    tx = payments_service.build_payment_transaction(payment)
    return PurchaseResponse(
        transaction=TonConnectTransaction(**tx.to_tonconnect()), payment_id=payment.id
    )


@router.post("/subscriptions/confirm", response_model=SubscriptionResponse)
async def confirm(
    session: SessionDep, user: CurrentUser, body: ConfirmPaymentRequest
) -> SubscriptionResponse:
    """Подтверждение оплаты: проверка транзакции on-chain, затем активация подписки."""
    payment = await payments_service.get_payment_for_user(session, body.payment_id, user)
    if payment.purpose != PaymentPurpose.subscription:
        raise BadRequest("Payment is not a subscription payment", code="PAYMENT_MISMATCH")

    tariff = await session.get(Tariff, payment.related_id) if payment.related_id else None
    if tariff is None:
        raise NotFound("Tariff not found", code="TARIFF_NOT_FOUND")

    await payments_service.confirm_payment(session, payment, body.tx_hash)
    subscription = await subs_service.activate_subscription(
        session, user=user, tariff=tariff
    )
    return SubscriptionResponse(subscription=SubscriptionOut.model_validate(subscription))


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def my_subscriptions(session: SessionDep, user: CurrentUser) -> list[SubscriptionOut]:
    rows = await session.scalars(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.created_at.desc())
    )
    return [SubscriptionOut.model_validate(s) for s in rows.all()]
