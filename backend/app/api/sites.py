"""Эндпоинты конструктора сайтов, превью, публикации и премиум-блока «Свой код»."""
from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.errors import BadRequest, Conflict, NotFound, PaymentRequired
from app.models import (
    PaymentPurpose,
    Site,
    SiteStatus,
    Tariff,
    TariffKind,
    utcnow,
)
from app.schemas import (
    ConfirmPaymentRequest,
    CustomCodeRequest,
    DnsBindResponse,
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
from app.services.dns import build_set_storage_transaction
from app.services.publishing import build_site_html, enqueue_publish
from app.services.renderer import content_size, default_content_for, render_site

router = APIRouter(prefix="/sites", tags=["sites"])


async def _get_site(session: SessionDep, site_id: uuid.UUID, user) -> Site:
    site = await session.get(Site, site_id)
    if site is None or site.user_id != user.id:
        raise NotFound("Site not found", code="SITE_NOT_FOUND")
    return site


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
        if not site.custom_code_paid:
            raise PaymentRequired(
                "Custom code block is not paid for this site", code="CUSTOM_CODE_NOT_PAID"
            )
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
        custom_code=site.custom_code if site.custom_code_paid else None,
        domain=site.domain,
        site_type=site.type.value,
    )
    return PreviewResponse(preview_html=html)


@router.post("/{site_id}/publish", response_model=PublishResponse)
async def publish(session: SessionDep, user: CurrentUser, site_id: uuid.UUID) -> PublishResponse:
    site = await _get_site(session, site_id, user)
    if site.status == SiteStatus.publishing:
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


@router.get("/{site_id}/render", response_class=HTMLResponse, include_in_schema=False)
async def render_published(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID
) -> HTMLResponse:
    """Сырой HTML сайта — удобно для отладки рендера и http-зеркала."""
    site = await _get_site(session, site_id, user)
    return HTMLResponse(build_site_html(site))


# ------------------------------------------------- премиум-блок «Свой код»
@router.post("/{site_id}/custom-code/purchase", response_model=PurchaseResponse)
async def purchase_custom_code(
    session: SessionDep, user: CurrentUser, site_id: uuid.UUID
) -> PurchaseResponse:
    """Оплата премиум-блока: цена берётся из активного тарифа kind=custom_code (админка)."""
    site = await _get_site(session, site_id, user)
    if site.custom_code_paid:
        raise Conflict("Custom code is already paid for this site", code="CUSTOM_CODE_PAID")

    tariff = await session.scalar(
        select(Tariff)
        .where(Tariff.kind == TariffKind.custom_code, Tariff.is_active.is_(True))
        .order_by(Tariff.price_ton.asc())
    )
    if tariff is None:
        raise NotFound("Custom code tariff is not configured", code="TARIFF_NOT_FOUND")

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
    """Подтверждение оплаты премиум-блока — только после проверки транзакции on-chain."""
    site = await _get_site(session, site_id, user)
    payment = await payments_service.get_payment_for_user(session, body.payment_id, user)
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
    """Загрузка HTML/CSS/JS. Доступна только после подтверждённой оплаты."""
    site = await _get_site(session, site_id, user)
    if not site.custom_code_paid:
        raise PaymentRequired(
            "Custom code block is not paid for this site", code="CUSTOM_CODE_NOT_PAID"
        )

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
