"""A7. Админ-API: пользователи, доступы, тарифы, домены, статистика, аудит.

Права проверяются зависимостью `AdminUser` на каждом эндпоинте, любое ручное
действие пишется в AdminAction — по ТЗ это аудит, а не опциональный лог.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import String, func, or_, select

from app.api.deps import AdminUser, SessionDep
from app.core.errors import BadRequest, NotFound
from app.models import (
    AdminAction,
    AdminActionType,
    Payment,
    PaymentStatus,
    Site,
    SiteStatus,
    Subscription,
    SubscriptionStatus,
    Tariff,
    User,
    utcnow,
)
from app.schemas import (
    AdminDomainItem,
    AdminStatsResponse,
    AdminUserDetail,
    AdminUserListItem,
    AdminUsersResponse,
    GrantAccessRequest,
    PaymentOut,
    RevokeAccessRequest,
    SiteListItem,
    SubscriptionOut,
    SubscriptionResponse,
    SuccessResponse,
    TariffCreateRequest,
    TariffOut,
    TariffUpdateRequest,
    TonConnectTransaction,
    UserOut,
    ZoneDeployResponse,
    ZoneOut,
    ZoneUpdateRequest,
)
from app.api.deps import require_wallet
from app.services import notifications
from app.services import subscriptions as subs_service
from app.services.dns_resolver import get_resolver
from app.services.subdom_client import get_domain_service
from app.services.zone import get_zone, set_zone

router = APIRouter(prefix="/admin", tags=["admin"])


async def _audit(
    session: SessionDep,
    admin: User,
    action: AdminActionType,
    target_user_id: uuid.UUID | None = None,
    **details,
) -> None:
    session.add(
        AdminAction(
            admin_id=admin.id,
            action=action,
            target_user_id=target_user_id,
            details={k: str(v) for k, v in details.items() if v is not None},
        )
    )
    await session.flush()


# --------------------------------------------------------------------- users
@router.get("/users", response_model=AdminUsersResponse)
async def list_users(
    session: SessionDep,
    admin: AdminUser,
    search: str = Query(default="", max_length=128),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> AdminUsersResponse:
    stmt = select(User)
    if search:
        like = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.username).like(like),
                func.lower(User.first_name).like(like),
                func.lower(User.wallet_address).like(like),
                func.cast(User.telegram_id, String).like(like),
            )
        )

    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await session.scalars(
        stmt.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    users = rows.all()

    items: list[AdminUserListItem] = []
    now = utcnow()
    for user in users:
        sites_count = await session.scalar(
            select(func.count()).select_from(Site).where(Site.user_id == user.id)
        )
        active = await session.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(
                Subscription.user_id == user.id,
                Subscription.status != SubscriptionStatus.expired,
                or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
            )
        )
        item = AdminUserListItem.model_validate(user)
        item.sites_count = sites_count or 0
        item.active_subscriptions = active or 0
        items.append(item)

    return AdminUsersResponse(users=items, total=total, page=page, per_page=per_page)


@router.get("/users/{user_id}", response_model=AdminUserDetail)
async def user_detail(
    session: SessionDep, admin: AdminUser, user_id: uuid.UUID
) -> AdminUserDetail:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("User not found", code="USER_NOT_FOUND")

    sites = (await session.scalars(select(Site).where(Site.user_id == user_id))).all()
    subs = (
        await session.scalars(
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
        )
    ).all()
    pays = (
        await session.scalars(
            select(Payment).where(Payment.user_id == user_id).order_by(Payment.created_at.desc())
        )
    ).all()

    return AdminUserDetail(
        user=UserOut.model_validate(user),
        sites=[SiteListItem.model_validate(s) for s in sites],
        subscriptions=[SubscriptionOut.model_validate(s) for s in subs],
        payments=[PaymentOut.model_validate(p) for p in pays],
    )


@router.post("/users/{user_id}/grant-access", response_model=SubscriptionResponse)
async def grant_access(
    session: SessionDep, admin: AdminUser, user_id: uuid.UUID, body: GrantAccessRequest
) -> SubscriptionResponse:
    """Ручная выдача доступа: подписка с granted_by_admin=true, без оплаты."""
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("User not found", code="USER_NOT_FOUND")

    tariff: Tariff | None = None
    if body.tariff_id is not None:
        tariff = await session.get(Tariff, body.tariff_id)
        if tariff is None:
            raise NotFound("Tariff not found", code="TARIFF_NOT_FOUND")
    else:
        # доступ без привязки к витрине: служебный тариф под нужный лимит
        if body.sites_limit is None or body.duration is None:
            raise BadRequest(
                "Either tariff_id or (sites_limit + duration) is required",
                code="GRANT_PARAMS_REQUIRED",
            )
        tariff = Tariff(
            name=f"Manual {body.sites_limit} sites",
            description="Выдан администратором вручную",
            sites_limit=body.sites_limit,
            duration=body.duration,
            price_ton=Decimal("0"),
            is_active=False,
        )
        session.add(tariff)
        await session.flush()

    subscription = await subs_service.activate_subscription(
        session,
        user=user,
        tariff=tariff,
        site_id=body.site_id,
        granted_by_admin=True,
        duration=body.duration or tariff.duration,
    )
    await _audit(
        session,
        admin,
        AdminActionType.grant_access,
        user_id,
        tariff=tariff.name,
        duration=(body.duration or tariff.duration).value,
        subscription_id=subscription.id,
        comment=body.comment,
    )
    return SubscriptionResponse(subscription=SubscriptionOut.model_validate(subscription))


@router.post("/users/{user_id}/revoke-access", response_model=SuccessResponse)
async def revoke_access(
    session: SessionDep, admin: AdminUser, user_id: uuid.UUID, body: RevokeAccessRequest
) -> SuccessResponse:
    subscription = await session.get(Subscription, body.subscription_id)
    if subscription is None or subscription.user_id != user_id:
        raise NotFound("Subscription not found", code="SUBSCRIPTION_NOT_FOUND")

    tariff_name = subscription.tariff.name if subscription.tariff else "—"
    await subs_service.revoke_subscription(session, subscription)

    user = await session.get(User, user_id)
    if user is not None:
        await notifications.notify(
            user.telegram_id, "access_revoked", user.language, tariff=tariff_name
        )
    await _audit(
        session,
        admin,
        AdminActionType.revoke_access,
        user_id,
        subscription_id=subscription.id,
        tariff=tariff_name,
    )
    return SuccessResponse()


@router.post("/users/{user_id}/block", response_model=SuccessResponse, include_in_schema=False)
async def block_user(
    session: SessionDep, admin: AdminUser, user_id: uuid.UUID, blocked: bool = True
) -> SuccessResponse:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("User not found", code="USER_NOT_FOUND")
    user.is_blocked = blocked
    await session.flush()
    return SuccessResponse()


# --------------------------------------------------------------------- tariffs
@router.get("/tariffs", response_model=list[TariffOut])
async def admin_list_tariffs(session: SessionDep, admin: AdminUser) -> list[TariffOut]:
    rows = await session.scalars(select(Tariff).order_by(Tariff.created_at.desc()))
    return [TariffOut.model_validate(t) for t in rows.all()]


@router.post("/tariffs", response_model=TariffOut, status_code=201)
async def create_tariff(
    session: SessionDep, admin: AdminUser, body: TariffCreateRequest
) -> TariffOut:
    tariff = Tariff(**body.model_dump())
    session.add(tariff)
    await session.flush()
    await _audit(
        session, admin, AdminActionType.create_tariff, None, tariff=tariff.name, price=tariff.price_ton
    )
    return TariffOut.model_validate(tariff)


@router.patch("/tariffs/{tariff_id}", response_model=TariffOut)
async def update_tariff(
    session: SessionDep, admin: AdminUser, tariff_id: uuid.UUID, body: TariffUpdateRequest
) -> TariffOut:
    tariff = await session.get(Tariff, tariff_id)
    if tariff is None:
        raise NotFound("Tariff not found", code="TARIFF_NOT_FOUND")

    old_price = tariff.price_ton
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(tariff, field, value)
    await session.flush()

    if body.price_ton is not None and body.price_ton != old_price:
        await _audit(
            session,
            admin,
            AdminActionType.change_price,
            None,
            tariff=tariff.name,
            old_price=old_price,
            new_price=tariff.price_ton,
        )
    return TariffOut.model_validate(tariff)


@router.delete("/tariffs/{tariff_id}", response_model=SuccessResponse)
async def delete_tariff(
    session: SessionDep, admin: AdminUser, tariff_id: uuid.UUID
) -> SuccessResponse:
    tariff = await session.get(Tariff, tariff_id)
    if tariff is None:
        raise NotFound("Tariff not found", code="TARIFF_NOT_FOUND")

    in_use = await session.scalar(
        select(func.count()).select_from(Subscription).where(Subscription.tariff_id == tariff_id)
    )
    name = tariff.name
    if in_use:
        # тариф с историей подписок не удаляем — иначе потеряем связь в аудите
        tariff.is_active = False
    else:
        await session.delete(tariff)
    await session.flush()
    await _audit(session, admin, AdminActionType.delete_tariff, None, tariff=name, soft=bool(in_use))
    return SuccessResponse()


# --------------------------------------------------------------------- domains
@router.get("/domains", response_model=list[AdminDomainItem])
async def list_domains(session: SessionDep, admin: AdminUser) -> list[AdminDomainItem]:
    rows = await session.execute(
        select(Site, User).join(User, Site.user_id == User.id).where(Site.domain.is_not(None))
    )
    return [
        AdminDomainItem(
            domain=site.domain or "",
            status=site.status,
            site_id=site.id,
            site_title=site.title,
            user_id=user.id,
            telegram_id=user.telegram_id,
            published_at=site.published_at,
        )
        for site, user in rows.all()
    ]


# --------------------------------------------------------------------- зона
@router.get("/zone", response_model=ZoneOut)
async def zone_config(session: SessionDep, admin: AdminUser) -> ZoneOut:
    """Настройки зоны субдоменов платформы."""
    zone = await get_zone(session)
    return ZoneOut(
        domain=zone.domain,
        dns_item_address=zone.dns_item_address,
        collection_address=zone.collection_address,
        mode=zone.mode,
        configured=zone.configured,
        deployable=zone.deployable,
    )


@router.patch("/zone", response_model=ZoneOut)
async def update_zone(
    session: SessionDep, admin: AdminUser, body: ZoneUpdateRequest
) -> ZoneOut:
    """Правка настроек зоны: домен, его DNS-item и адрес коллекции после разворота."""
    # Адрес коллекции известен ещё до разворота, поэтому его легко вписать рано.
    # Зона с невыстроенной коллекцией выглядела бы рабочей, а субдомены уходили
    # бы в никуда — поэтому проверяем, что контракт действительно в сети.
    if body.collection_address:
        deployed = await get_resolver().contract_deployed(body.collection_address)
        if deployed is False:
            raise BadRequest(
                "Collection contract is not deployed yet: sign the zone deploy transaction first",
                code="ZONE_NOT_DEPLOYED",
            )

    zone = await set_zone(
        session,
        domain=body.domain,
        dns_item_address=body.dns_item_address,
        collection_address=body.collection_address,
        mode=body.mode,
    )
    return ZoneOut(
        domain=zone.domain,
        dns_item_address=zone.dns_item_address,
        collection_address=zone.collection_address,
        mode=zone.mode,
        configured=zone.configured,
        deployable=zone.deployable,
    )


@router.post("/zone/deploy", response_model=ZoneDeployResponse)
async def deploy_zone(session: SessionDep, admin: AdminUser) -> ZoneDeployResponse:
    """Транзакция разворота зоны субдоменов на домене платформы.

    Операция разовая и подписывается кошельком владельца домена — то есть
    администратором. После неё в сети появляется коллекция, адрес которой
    нужно вписать в настройки зоны.
    """
    wallet = require_wallet(admin)
    zone = await get_zone(session)
    if not zone.deployable:
        raise BadRequest(
            "Set zone domain and its DNS item address first", code="ZONE_NOT_CONFIGURED"
        )

    name, _, tld = zone.domain.partition(".")
    service = get_domain_service()
    if zone.mode == "sbt":
        tx = await service.deploy_sbt_zone(zone.dns_item_address, zone.domain, wallet, tld or "ton")
    else:
        tx = await service.deploy_proxy_zone(zone.dns_item_address, name, wallet, tld or "ton")

    await _audit(session, admin, AdminActionType.deploy_zone, None, zone=zone.domain, mode=zone.mode)
    return ZoneDeployResponse(
        transaction=TonConnectTransaction(**tx.to_tonconnect()),
        domain=zone.domain,
        collection_address=_collection_from(tx),
    )


def _collection_from(tx) -> str | None:
    """Адрес коллекции — назначение сообщения, которое разворачивает контракт."""
    for message in tx.messages:
        if message.state_init:
            return message.address
    return None


# --------------------------------------------------------------------- stats
@router.get("/stats", response_model=AdminStatsResponse)
async def stats(session: SessionDep, admin: AdminUser) -> AdminStatsResponse:
    now = utcnow()
    total_users = await session.scalar(select(func.count()).select_from(User)) or 0
    total_sites = await session.scalar(select(func.count()).select_from(Site)) or 0
    published = (
        await session.scalar(
            select(func.count()).select_from(Site).where(Site.status == SiteStatus.published)
        )
        or 0
    )
    active_subs = (
        await session.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(
                Subscription.status != SubscriptionStatus.expired,
                or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
            )
        )
        or 0
    )
    revenue = (
        await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.status == PaymentStatus.confirmed
            )
        )
        or 0
    )
    revenue_30d = (
        await session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.status == PaymentStatus.confirmed,
                Payment.confirmed_at >= now - timedelta(days=30),
            )
        )
        or 0
    )
    payments_confirmed = (
        await session.scalar(
            select(func.count()).select_from(Payment).where(Payment.status == PaymentStatus.confirmed)
        )
        or 0
    )

    return AdminStatsResponse(
        total_users=total_users,
        total_sites=total_sites,
        published_sites=published,
        active_subscriptions=active_subs,
        revenue=Decimal(str(revenue)),
        revenue_last_30d=Decimal(str(revenue_30d)),
        payments_confirmed=payments_confirmed,
    )


@router.get("/actions", include_in_schema=False)
async def admin_actions(
    session: SessionDep, admin: AdminUser, limit: int = Query(default=100, ge=1, le=500)
) -> list[dict]:
    rows = await session.scalars(
        select(AdminAction).order_by(AdminAction.created_at.desc()).limit(limit)
    )
    return [
        {
            "id": str(a.id),
            "admin_id": str(a.admin_id) if a.admin_id else None,
            "action": a.action.value,
            "target_user_id": str(a.target_user_id) if a.target_user_id else None,
            "details": a.details,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows.all()
    ]
