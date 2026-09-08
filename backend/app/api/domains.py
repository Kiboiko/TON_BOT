"""Субдомены и привязка их к сайтам.

Роутер не знает ничего о внутренностях subdom — только про наш интерфейс
`DomainService`. Это и есть та изоляция, ради которой сделан subdom_client.

Флоу пользователя (зонная модель, см. app/services/zone.py):

    1. проверить, свободно ли `имя` в зоне платформы  — GET  /domains/check
    2. получить транзакцию на получение субдомена     — POST /domains/claim
    3. подписать её кошельком и сообщить об отправке  — POST /domains/confirm

Разворот самой зоны — разовая операция администратора, она в /api/admin/zone.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SessionDep, require_wallet
from app.core.errors import BadRequest, Conflict, NotFound
from app.models import Site, SiteStatus
from app.schemas import (
    DomainAttachRequest,
    DomainAttachResponse,
    DomainCheckResponse,
    DomainClaimRequest,
    DomainClaimResponse,
    DomainConfirmRequest,
    DomainConfirmResponse,
    TonConnectTransaction,
)
from app.services.dns_resolver import get_resolver, is_valid_name
from app.services.publishing import enqueue_publish, publish_is_stale
from app.services.subdom_client import get_domain_service
from app.services.ton import same_address
from app.services.zone import full_domain, get_zone

log = logging.getLogger(__name__)

router = APIRouter(prefix="/domains", tags=["domains"])


def _validate_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not is_valid_name(name):
        raise BadRequest(
            "Domain must be 3-126 chars: latin letters, digits and hyphen",
            code="INVALID_DOMAIN_NAME",
        )
    return name


@router.get("/check", response_model=DomainCheckResponse)
async def check_domain(
    session: SessionDep,
    _: CurrentUser,
    name: str = Query(min_length=1, max_length=126),
) -> DomainCheckResponse:
    """Свободно ли имя в зоне платформы. Проверяется резолвом в блокчейне."""
    zone = await get_zone(session)
    if not zone.configured:
        raise BadRequest("Subdomain zone is not configured yet", code="ZONE_NOT_CONFIGURED")

    domain = full_domain(_validate_name(name), zone)
    info = await get_resolver().resolve(domain)
    return DomainCheckResponse(
        available=info.available,
        status=info.status,
        domain=domain,
        zone=zone.domain,
        item_address=info.item_address,
        owner=info.owner,
    )


@router.post("/claim", response_model=DomainClaimResponse)
async def claim_domain(
    session: SessionDep, user: CurrentUser, body: DomainClaimRequest
) -> DomainClaimResponse:
    """Транзакция на получение субдомена — подписывает кошелёк пользователя."""
    wallet = require_wallet(user)
    zone = await get_zone(session)
    if not zone.configured:
        raise BadRequest("Subdomain zone is not configured yet", code="ZONE_NOT_CONFIGURED")

    site = await session.get(Site, body.site_id)
    if site is None or site.user_id != user.id:
        raise NotFound("Site not found", code="SITE_NOT_FOUND")

    name = _validate_name(body.name)
    domain = full_domain(name, zone)

    info = await get_resolver().resolve(domain)
    if not info.available and not same_address(info.owner, wallet):
        raise Conflict("Subdomain is already taken", code="DOMAIN_TAKEN")

    service = get_domain_service()
    if zone.mode == "sbt":
        tx = await service.mint_sbt_subdomain(zone.collection_address, name)
    else:
        # в proxy-зоне субдомен разыгрывается аукционом, как и домены верхнего уровня
        tx = await service.start_auction(zone.collection_address, name)

    # Домен НЕ сохраняем: транзакция ещё не подписана. Раньше он записывался
    # здесь же, и сайт показывал «текущий домен» даже когда пользователь
    # отменял оплату — а привязать такой домен было нечем, потому что DNS-item
    # у него так и не появлялся. Владение подтверждает /domains/confirm.
    return DomainClaimResponse(
        transaction=TonConnectTransaction(**tx.to_tonconnect()), domain=domain
    )


@router.post("/attach", response_model=DomainAttachResponse)
async def attach_domain(
    session: SessionDep, user: CurrentUser, body: DomainAttachRequest
) -> DomainAttachResponse:
    """Привязывает к сайту домен, которым пользователь уже владеет.

    Зона платформы здесь не нужна: домен существует, разворачивать нечего.
    Достаточно убедиться, что кошелёк пользователя действительно им владеет,
    и запомнить адрес DNS-item — по нему потом собирается транзакция
    DNS-записи (/api/sites/{id}/dns-bind), которая направит домен на сайт.
    """
    wallet = require_wallet(user)
    site = await session.get(Site, body.site_id)
    if site is None or site.user_id != user.id:
        raise NotFound("Site not found", code="SITE_NOT_FOUND")

    domain = body.domain
    if "." not in domain:
        raise BadRequest("Enter the full domain, for example mysite.ton", code="INVALID_DOMAIN_NAME")

    info = await get_resolver().resolve(domain)
    if info.available:
        raise BadRequest(
            "This domain is not registered yet — buy it first", code="DOMAIN_NOT_REGISTERED"
        )
    if info.status == "unknown":
        raise BadRequest("Cannot check the domain right now, try again", code="DOMAIN_CHECK_FAILED")
    if not same_address(info.owner, wallet):
        raise Conflict("This domain belongs to another wallet", code="DOMAIN_NOT_OWNED")

    site.domain = domain
    site.tld = domain.split(".")[-1]
    site.dns_item_address = info.item_address
    await session.flush()
    log.info("domain %s attached to site %s", domain, site.id)

    return DomainAttachResponse(
        domain=domain,
        item_address=info.item_address,
        needs_publish=site.status != SiteStatus.published,
    )


@router.post("/confirm", response_model=DomainConfirmResponse)
async def confirm_domain(
    session: SessionDep, user: CurrentUser, body: DomainConfirmRequest
) -> DomainConfirmResponse:
    """Фронт сообщает, что транзакция отправлена; проверяем состояние в сети.

    Фронту на слово не верим: субдомен считается полученным, только если резолвер
    видит его в блокчейне и владелец — кошелёк пользователя.
    """
    wallet = require_wallet(user)
    site = await session.get(Site, body.site_id)
    if site is None or site.user_id != user.id:
        raise NotFound("Site not found", code="SITE_NOT_FOUND")
    domain = (body.domain or site.domain or "").strip().lower()
    if not domain:
        raise BadRequest("No domain is attached to this site", code="DOMAIN_NOT_ATTACHED")

    info = await get_resolver().resolve(domain)
    owned = (not info.available) and (info.owner is None or same_address(info.owner, wallet))
    if not owned:
        # транзакция ещё не долетела до сети — фронт повторит опрос
        return DomainConfirmResponse(status="pending", domain=domain)

    zone = await get_zone(session)
    site.domain = domain
    site.tld = zone.domain if domain.endswith("." + zone.domain) else domain.split(".")[-1]
    if domain.endswith("." + zone.domain):
        site.collection_address = zone.collection_address
    if info.item_address:
        site.dns_item_address = info.item_address
    # если предыдущая задача потерялась, сайт так и висит в publishing —
    # отвечать «публикуется» и не ставить новую значило бы обречь фронт на
    # бесконечный поллинг
    if site.status != SiteStatus.publishing or publish_is_stale(site):
        await enqueue_publish(session, site)
    return DomainConfirmResponse(status=SiteStatus.publishing.value, domain=domain)
