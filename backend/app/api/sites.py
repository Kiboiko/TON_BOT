"""Эндпоинты конструктора сайтов, превью, публикации и проектов «Свой код»."""
from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.errors import BadRequest, Conflict, NotFound, PaymentRequired
from app.models import (
    PaymentPurpose,
    Site,
    SiteStatus,
    SiteType,
    Tariff,
    TariffKind,
    utcnow,
)
from app.schemas import (
    ConfirmPaymentRequest,
    CustomCodePriceResponse,
    CustomCodeRequest,
    DnsBindResponse,
    DnsStatusResponse,
    PreviewResponse,
    PublishResponse,
    PublishStatusResponse,
    PurchaseResponse,
    SiteCreateRequest,
    SiteListItem,
    SiteResponse,
    SiteUpdateRequest,
    SuccessResponse,
    TonConnectTransaction,
)
from app.services import payments as payments_service
from app.services import subscriptions as subs_service
from app.api.public import public_site_url
from app.services.dns import (
    build_set_site_transaction,
    build_set_storage_transaction,
    direct_delivery_ready,
)
from app.services.publishing import build_site_html, enqueue_publish, publish_is_stale
from app.services.renderer import content_size, default_content_for, render_site

router = APIRouter(prefix="/sites", tags=["sites"])


async def _get_site(session: SessionDep, site_id: uuid.UUID, user) -> Site:
    site = await session.get(Site, site_id)
    if site is None or site.user_id != user.id:
        raise NotFound("Site not found", code="SITE_NOT_FOUND")
    return site


def _ensure_custom_code_site(site: Site) -> None:
    """Свой код живёт только в проекте соответствующего типа, а не внутри визитки."""
    if site.type is not SiteType.custom_code:
        raise BadRequest(
            "Custom code is only available for sites of type custom_code",
            code="NOT_A_CUSTOM_CODE_SITE",
        )


def _ensure_custom_code_paid(site: Site) -> None:
    """Возможность своего кода оплачивается разово и отдельно на каждый сайт."""
    if not site.custom_code_paid:
        raise PaymentRequired(
            "Custom code is not paid for this site", code="CUSTOM_CODE_NOT_PAID"
        )


async def _custom_code_tariff(session: AsyncSession) -> Tariff:
    """Строка тарифа с ценой своего кода. Цену меняет админ в разделе тарифов."""
    tariff = await session.scalar(
        select(Tariff)
        .where(Tariff.kind == TariffKind.custom_code, Tariff.is_active.is_(True))
        .order_by(Tariff.price_ton.asc())
    )
    if tariff is None:
        raise NotFound("Custom code price is not configured", code="TARIFF_NOT_FOUND")
    return tariff


def _check_content_size(content: dict | None) -> None:
    if content and content_size(content) > settings.MAX_CONTENT_JSON_BYTES:
        raise BadRequest(
            f"content_json is too large (limit {settings.MAX_CONTENT_JSON_BYTES} bytes)",
            code="CONTENT_TOO_LARGE",
        )


@router.get("", response_model=list[SiteListItem])
async def list_sites(session: SessionDep, user: CurrentUser) -> list[SiteListItem]:
    rows = await session.scalars(
        select(Site).where(Site.user_id == user.id).order_by(Site.created_at.desc())
    )
    return [SiteListItem.model_validate(s) for s in rows.all()]


@router.post("", response_model=SiteResponse, status_code=201)
async def create_site(
    session: SessionDep, user: CurrentUser, body: SiteCreateRequest
) -> SiteResponse:
    await subs_service.ensure_can_create_site(session, user)
    _check_content_size(body.content_json)

    content = body.content_json or default_content_for(body.type.value, body.title)
    site = Site(user_id=user.id, type=body.type, title=body.title, content_json=content)
    session.add(site)
    await session.flush()
    return SiteResponse(site=site)


@router.get("/{site_id}", response_model=SiteResponse)
async def get_site(session: SessionDep, user: CurrentUser, site_id: uuid.UUID) -> SiteResponse:
    return SiteResponse(site=await _get_site(session, site_id, user))


@router.patch("/{site_id}", response_model=SiteResponse)
async def update_site(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID, body: SiteUpdateRequest
) -> SiteResponse:
    site = await _get_site(session, site_id, user)
    if body.title is not None:
        site.title = body.title
    if body.content_json is not None:
        _check_content_size(body.content_json)
        site.content_json = body.content_json
    if body.custom_code is not None:
        _ensure_custom_code_site(site)
        _ensure_custom_code_paid(site)
        site.custom_code = body.custom_code.model_dump()
    site.updated_at = utcnow()
    await session.flush()
    return SiteResponse(site=site)


@router.delete("/{site_id}", response_model=SuccessResponse)
async def delete_site(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID
) -> SuccessResponse:
    site = await _get_site(session, site_id, user)
    await session.delete(site)
    await session.flush()
    return SuccessResponse()


@router.post("/{site_id}/preview", response_model=PreviewResponse)
async def preview_site(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID
) -> PreviewResponse:
    """HTML-превью ровно тем же рендером, что и публикация — без заливки в Storage."""
    site = await _get_site(session, site_id, user)
    html = render_site(
        site.content_json,
        title=site.title,
        # неоплаченный код на страницу не попадает — ни в превью, ни в публикации
        custom_code=site.custom_code if site.custom_code_paid else None,
        domain=site.domain,
        site_type=site.type.value,
    )
    return PreviewResponse(preview_html=html)


@router.post("/{site_id}/publish", response_model=PublishResponse)
async def publish(session: SessionDep, user: CurrentUser, site_id: uuid.UUID) -> PublishResponse:
    site = await _get_site(session, site_id, user)
    # Публикация занимает секунды. Если статус висит дольше, задача потеряна
    # (упал воркер, зависла сеть) — иначе из этого состояния было бы не выйти:
    # кнопка «Опубликовать» вечно отвечала бы 409.
    if site.status == SiteStatus.publishing and not publish_is_stale(site):
        raise Conflict("Site is already being published", code="PUBLISH_IN_PROGRESS")
    await subs_service.ensure_can_publish(session, user, site)

    job_id = await enqueue_publish(session, site)
    return PublishResponse(status=SiteStatus.publishing.value, job_id=job_id)


@router.get("/{site_id}/publish-status", response_model=PublishStatusResponse)
async def publish_status(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID
) -> PublishStatusResponse:
    site = await _get_site(session, site_id, user)
    await session.refresh(site)
    return PublishStatusResponse(
        status=site.status,
        storage_bag_id=site.storage_bag_id,
        published_at=site.published_at,
        error=site.publish_error,
        public_url=public_site_url(site),
        has_unpublished_changes=site.has_unpublished_changes,
    )


@router.post("/{site_id}/dns-bind", response_model=DnsBindResponse)
async def dns_bind(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID
) -> DnsBindResponse:
    """Транзакция привязки опубликованного bag id к домену (подписывает владелец)."""
    site = await _get_site(session, site_id, user)
    if not site.storage_bag_id:
        raise BadRequest("Site is not published yet", code="SITE_NOT_PUBLISHED")
    tx = build_set_storage_transaction(site.dns_item_address or "", site.storage_bag_id)
    return DnsBindResponse(transaction=TonConnectTransaction(**tx.to_tonconnect()))


@router.get("/{site_id}/dns-status", response_model=DnsStatusResponse)
async def dns_status(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID
) -> DnsStatusResponse:
    """Настроен ли домен на прямую отдачу — чтобы не просить подпись повторно."""
    site = await _get_site(session, site_id, user)
    return DnsStatusResponse(
        domain=site.domain, direct=await direct_delivery_ready(site.domain)
    )


@router.post("/{site_id}/site-bind", response_model=DnsBindResponse)
async def site_bind(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID
) -> DnsBindResponse:
    """Транзакция «направить домен на наш TON-сайт» (DNS-запись `site`).

    Запись `storage` отдаёт сайт из TON Storage и зависит от чужих шлюзов;
    запись `site` ведёт прямо на наш rldp-http-proxy, поэтому домен открывается,
    пока жив наш сервер. Одно другому не мешает — записи разные.
    """
    site = await _get_site(session, site_id, user)
    if site.status != SiteStatus.published:
        raise BadRequest("Site is not published yet", code="SITE_NOT_PUBLISHED")
    tx = build_set_site_transaction(site.dns_item_address or "", settings.TON_SITE_ADNL)
    return DnsBindResponse(transaction=TonConnectTransaction(**tx.to_tonconnect()))


@router.get("/{site_id}/render", response_class=HTMLResponse, include_in_schema=False)
async def render_published(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID
) -> HTMLResponse:
    """Сырой HTML сайта — удобно для отладки рендера и http-зеркала."""
    site = await _get_site(session, site_id, user)
    return HTMLResponse(build_site_html(site))


# ------------------------------------------------- проект «Свой код»
@router.get("/{site_id}/custom-code/price", response_model=CustomCodePriceResponse)
async def custom_code_price(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID
) -> CustomCodePriceResponse:
    """Сколько стоит свой код для этого сайта и оплачен ли он уже."""
    site = await _get_site(session, site_id, user)
    tariff = await _custom_code_tariff(session)
    return CustomCodePriceResponse(price_ton=tariff.price_ton, paid=site.custom_code_paid)


@router.post("/{site_id}/custom-code/purchase", response_model=PurchaseResponse)
async def purchase_custom_code(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID
) -> PurchaseResponse:
    """Разовая оплата своего кода: цена берётся из тарифа kind=custom_code."""
    site = await _get_site(session, site_id, user)
    _ensure_custom_code_site(site)
    if site.custom_code_paid:
        raise Conflict("Custom code is already paid for this site", code="CUSTOM_CODE_PAID")

    # Прошлая оплата могла дойти, но не подтвердиться. Засчитываем её обычным
    # ответом, а не ошибкой: при исключении сессия откатится вместе с засчётом.
    if await payments_service.recover_paid_pending(
        session, user=user, purpose=PaymentPurpose.custom_code, related_id=site.id
    ):
        site.custom_code_paid = True
        await session.flush()
        return PurchaseResponse(already_paid=True)

    tariff = await _custom_code_tariff(session)
    payment = await payments_service.create_payment(
        session,
        user=user,
        amount=tariff.price_ton,
        purpose=PaymentPurpose.custom_code,
        related_id=site.id,
    )
    tx = payments_service.build_payment_transaction(payment)
    return PurchaseResponse(
        transaction=TonConnectTransaction(**tx.to_tonconnect()), payment_id=payment.id
    )


@router.post("/{site_id}/custom-code/confirm", response_model=SuccessResponse)
async def confirm_custom_code(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID, body: ConfirmPaymentRequest
) -> SuccessResponse:
    """Подтверждение оплаты — только после проверки транзакции в блокчейне."""
    site = await _get_site(session, site_id, user)
    payment = await payments_service.get_payment_for_update(session, body.payment_id, user)
    if payment.purpose != PaymentPurpose.custom_code or payment.related_id != site.id:
        raise BadRequest("Payment does not belong to this site", code="PAYMENT_MISMATCH")

    await payments_service.confirm_payment(session, payment, body.tx_hash)
    site.custom_code_paid = True
    await session.flush()
    return SuccessResponse()


@router.post("/{site_id}/custom-code", response_model=SuccessResponse)
async def set_custom_code(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID, body: CustomCodeRequest
) -> SuccessResponse:
    """Загрузка HTML/CSS/JS в проект «Свой код». Нужна разовая оплата этого сайта."""
    site = await _get_site(session, site_id, user)
    _ensure_custom_code_site(site)
    _ensure_custom_code_paid(site)

    total = len(body.html.encode()) + len(body.css.encode()) + len(body.js.encode())
    if total > settings.MAX_CUSTOM_CODE_BYTES:
        raise BadRequest(
            f"Custom code is too large (limit {settings.MAX_CUSTOM_CODE_BYTES} bytes)",
            code="CUSTOM_CODE_TOO_LARGE",
        )

    site.custom_code = body.model_dump()
    site.updated_at = utcnow()
    await session.flush()
    return SuccessResponse()
