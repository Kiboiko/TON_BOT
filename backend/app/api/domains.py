"""Домены и публикация: тонкая обёртка над subdom_client + запуск публикации.

Роутер не знает ничего о внутренностях subdom — только про наш интерфейс
`DomainService`. Это и есть та изоляция, ради которой сделан subdom_client.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SessionDep, require_wallet
from app.core.errors import BadRequest, Conflict, NotFound
from app.models import Site, SiteStatus
from app.schemas import (
    DeployZoneRequest,
    DeployZoneResponse,
    DomainCheckResponse,
    DomainConfirmRequest,
    DomainConfirmResponse,
    TonConnectTransaction,
)
from app.services.publishing import enqueue_publish
from app.services.subdom_client import get_domain_service
from app.services.ton import same_address

log = logging.getLogger(__name__)

router = APIRouter(prefix="/domains", tags=["domains"])

DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,124}$")


def _validate_name(name: str) -> str:
    name = name.strip().lower()
    if not DOMAIN_RE.fullmatch(name):
        raise BadRequest(
            "Domain must be 3-125 chars: latin letters, digits and hyphen",
            code="INVALID_DOMAIN_NAME",
        )
    return name


@router.get("/check", response_model=DomainCheckResponse)
async def check_domain(
    _: CurrentUser,
    name: str = Query(min_length=1, max_length=126),
    tld: str = Query(default="ton", max_length=32),
) -> DomainCheckResponse:
    info = await get_domain_service().check_domain(_validate_name(name), tld)
    return DomainCheckResponse(
        available=info.available,
        status=info.status,
        domain=info.domain,
        dns_item_address=info.dns_item_address,
        collection_address=info.collection_address,
        owner=info.owner,
    )


@router.post("/deploy-zone", response_model=DeployZoneResponse)
async def deploy_zone(
    session: SessionDep, user: CurrentUser, body: DeployZoneRequest
) -> DeployZoneResponse:
    """Готовит транзакцию деплоя зоны — подписывает её кошелёк пользователя."""
    wallet = require_wallet(user)
    name = _validate_name(body.domain.removesuffix(f".{body.tld}"))

    site = await session.get(Site, body.site_id)
    if site is None or site.user_id != user.id:
        raise NotFound("Site not found", code="SITE_NOT_FOUND")

    service = get_domain_service()
    info = await service.check_domain(name, body.tld)
    if not info.dns_item_address:
        raise BadRequest("Domain service returned no DNS item address", code="DNS_ITEM_MISSING")
    if not info.available and not same_address(info.owner, wallet):
        raise Conflict("Domain is already taken", code="DOMAIN_TAKEN")

    full_domain = f"{name}.{body.tld}"
    if body.mode == "sbt":
        tx = await service.deploy_sbt_zone(info.dns_item_address, full_domain, wallet, body.tld)
    else:
        tx = await service.deploy_proxy_zone(info.dns_item_address, name, wallet, body.tld)

    # запоминаем домен ещё до подтверждения: данные о сайте живут у нас
    site.domain = full_domain
    site.tld = body.tld
    site.dns_item_address = info.dns_item_address
    site.collection_address = info.collection_address
    await session.flush()

    return DeployZoneResponse(transaction=TonConnectTransaction(**tx.to_tonconnect()))


@router.post("/confirm", response_model=DomainConfirmResponse)
async def confirm_domain(
    session: SessionDep, user: CurrentUser, body: DomainConfirmRequest
) -> DomainConfirmResponse:
    """Фронт сообщает, что транзакция отправлена; проверяем состояние домена в сети.

    Фронту на слово не верим: домен считается привязанным только если доменный
    сервис подтверждает, что он больше не свободен и принадлежит кошельку.
    """
    wallet = require_wallet(user)
    site = await session.get(Site, body.site_id)
    if site is None or site.user_id != user.id:
        raise NotFound("Site not found", code="SITE_NOT_FOUND")
    if not site.domain:
        raise BadRequest("No domain is attached to this site", code="DOMAIN_NOT_ATTACHED")

    name, _, tld = site.domain.partition(".")
    info = await get_domain_service().check_domain(name, tld or "ton")

    owned = (not info.available) and (info.owner is None or same_address(info.owner, wallet))
    if not owned:
        # транзакция ещё не долетела до сети — фронт повторит поллинг
        return DomainConfirmResponse(status="pending")

    if info.dns_item_address:
        site.dns_item_address = info.dns_item_address
    if info.collection_address:
        site.collection_address = info.collection_address

    if site.status not in (SiteStatus.publishing,):
        await enqueue_publish(session, site)
    return DomainConfirmResponse(status=SiteStatus.publishing.value)


@router.get("/my", response_model=list[DomainCheckResponse], include_in_schema=False)
async def my_domains(session: SessionDep, user: CurrentUser) -> list[DomainCheckResponse]:
    from sqlalchemy import select

    rows = await session.scalars(
        select(Site).where(Site.user_id == user.id, Site.domain.is_not(None))
    )
    return [
        DomainCheckResponse(
            available=False,
            status=s.status.value,
            domain=s.domain or "",
            dns_item_address=s.dns_item_address,
            collection_address=s.collection_address,
            owner=user.wallet_address,
        )
        for s in rows.all()
    ]
