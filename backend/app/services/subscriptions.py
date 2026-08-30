"""A5 (часть 2). Подписки: сроки, лимиты, триал, планировщик статусов.

Правила из ТЗ:
* лимиты сайтов берутся из тарифа (base = 1, PRO = 5 / 25);
* сроки: month / 3month / 6month / 12month / forever;
* первый сайт публикуется бесплатно на 7 дней (подписка типа trial);
* по истечении подписка становится expiring_soon → expired, а сайт снимается
  с публикации.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import LimitExceeded
from app.models import (
    Site,
    SiteStatus,
    Subscription,
    SubscriptionStatus,
    Tariff,
    TariffDuration,
    TariffKind,
    User,
    utcnow,
)
from app.services import notifications

log = logging.getLogger(__name__)

DURATION_DAYS: dict[TariffDuration, int | None] = {
    TariffDuration.month: 30,
    TariffDuration.month3: 90,
    TariffDuration.month6: 180,
    TariffDuration.month12: 365,
    TariffDuration.forever: None,
}


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite отдаёт naive datetime — приводим к UTC, чтобы сравнения не падали."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def compute_expires_at(
    duration: TariffDuration, starts_at: datetime | None = None
) -> datetime | None:
    days = DURATION_DAYS.get(duration)
    if days is None:
        return None
    return (starts_at or utcnow()) + timedelta(days=days)


def is_active(sub: Subscription, now: datetime | None = None) -> bool:
    now = now or utcnow()
    if sub.status == SubscriptionStatus.expired:
        return False
    if sub.is_forever or sub.expires_at is None:
        return True
    return _aware(sub.expires_at) > now


async def active_subscriptions(session: AsyncSession, user_id: uuid.UUID) -> list[Subscription]:
    now = utcnow()
    rows = await session.scalars(
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status != SubscriptionStatus.expired,
            or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
        )
        .order_by(Subscription.created_at.desc())
    )
    return [s for s in rows.all() if s.tariff is None or s.tariff.kind != TariffKind.custom_code]


async def sites_limit_for(session: AsyncSession, user: User) -> int:
    """Действующий лимит сайтов: максимум по активным подпискам, минимум 1 (черновик)."""
    subs = await active_subscriptions(session, user.id)
    limits = [s.tariff.sites_limit for s in subs if s.tariff is not None]
    limits.append(1)  # без подписки можно вести один черновик
    return max(limits)


async def ensure_can_create_site(session: AsyncSession, user: User) -> None:
    limit = await sites_limit_for(session, user)
    count = await session.scalar(
        select(func.count()).select_from(Site).where(Site.user_id == user.id)
    )
    if (count or 0) >= limit:
        raise LimitExceeded(
            f"Sites limit reached ({limit}). Upgrade your plan to add more.",
            details={"limit": limit, "used": count or 0},
        )


async def has_publish_right(session: AsyncSession, user: User, site: Site) -> bool:
    """Есть ли право публиковать конкретный сайт (общая или посайтовая подписка)."""
    for sub in await active_subscriptions(session, user.id):
        if sub.site_id is None or sub.site_id == site.id:
            return True
    return False


async def grant_trial_if_first_publish(
    session: AsyncSession, user: User, site: Site
) -> Subscription | None:
    """Бесплатная публикация первого сайта на TRIAL_DAYS дней.

    Триал выдаётся один раз на пользователя — повторно только по подписке.
    """
    used = await session.scalar(
        select(func.count()).select_from(Subscription).where(
            Subscription.user_id == user.id, Subscription.is_trial.is_(True)
        )
    )
    if used:
        return None

    now = utcnow()
    sub = Subscription(
        user_id=user.id,
        tariff_id=None,
        site_id=site.id,
        starts_at=now,
        expires_at=now + timedelta(days=settings.TRIAL_DAYS),
        is_forever=False,
        is_trial=True,
        status=SubscriptionStatus.active,
    )
    session.add(sub)
    await session.flush()
    log.info("trial subscription granted to user %s for site %s", user.id, site.id)
    await notifications.notify(
        user.telegram_id, "trial_started", user.language, days=settings.TRIAL_DAYS
    )
    return sub


async def ensure_can_publish(session: AsyncSession, user: User, site: Site) -> Subscription | None:
    """Право на публикацию: активная подписка либо разовый бесплатный триал."""
    if await has_publish_right(session, user, site):
        return None
    trial = await grant_trial_if_first_publish(session, user, site)
    if trial is not None:
        return trial
    raise LimitExceeded(
        "An active subscription is required to publish this site",
        code="SUBSCRIPTION_REQUIRED",
        status_code=402,
    )


async def activate_subscription(
    session: AsyncSession,
    *,
    user: User,
    tariff: Tariff,
    site_id: uuid.UUID | None = None,
    granted_by_admin: bool = False,
    duration: TariffDuration | None = None,
    notify: bool = True,
) -> Subscription:
    """Создаёт активную подписку. Продление того же тарифа наращивает срок."""
    duration = duration or tariff.duration
    now = utcnow()

    existing = await session.scalar(
        select(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.tariff_id == tariff.id,
            Subscription.site_id.is_(None) if site_id is None else Subscription.site_id == site_id,
            Subscription.status != SubscriptionStatus.expired,
        )
        .order_by(Subscription.expires_at.desc().nullsfirst())
    )

    if existing is not None and is_active(existing, now):
        if existing.is_forever or duration == TariffDuration.forever:
            existing.is_forever = True
            existing.expires_at = None
        else:
            base = _aware(existing.expires_at) or now
            existing.expires_at = compute_expires_at(duration, max(base, now))
        existing.status = SubscriptionStatus.active
        existing.notified_expiring = False
        existing.notified_expired = False
        subscription = existing
    else:
        subscription = Subscription(
            user_id=user.id,
            tariff_id=tariff.id,
            site_id=site_id,
            starts_at=now,
            expires_at=compute_expires_at(duration, now),
            is_forever=duration == TariffDuration.forever,
            status=SubscriptionStatus.manual if granted_by_admin else SubscriptionStatus.active,
            granted_by_admin=granted_by_admin,
        )
        session.add(subscription)

    await session.flush()

    if notify:
        until = ""
        if subscription.expires_at:
            until = f" до {_aware(subscription.expires_at):%d.%m.%Y}"
        elif subscription.is_forever:
            until = " бессрочно"
        event = "access_granted" if granted_by_admin else "subscription_activated"
        await notifications.notify(
            user.telegram_id, event, user.language, tariff=tariff.name, until=until
        )
    return subscription


async def revoke_subscription(session: AsyncSession, subscription: Subscription) -> None:
    subscription.status = SubscriptionStatus.expired
    subscription.expires_at = utcnow()
    subscription.is_forever = False
    await session.flush()
    await unpublish_sites_without_subscription(session, subscription.user_id)


async def unpublish_sites_without_subscription(
    session: AsyncSession, user_id: uuid.UUID
) -> list[Site]:
    """Снимает с публикации сайты, которые больше не покрыты подпиской."""
    user = await session.get(User, user_id)
    if user is None:
        return []
    subs = await active_subscriptions(session, user_id)
    covers_all = any(s.site_id is None for s in subs)
    covered_ids = {s.site_id for s in subs if s.site_id is not None}

    sites = (
        await session.scalars(
            select(Site).where(
                Site.user_id == user_id,
                Site.status.in_([SiteStatus.published, SiteStatus.publishing]),
            )
        )
    ).all()

    expired: list[Site] = []
    for site in sites:
        if covers_all or site.id in covered_ids:
            continue
        site.status = SiteStatus.expired
        expired.append(site)
    if expired:
        await session.flush()
        log.info("unpublished %s site(s) of user %s", len(expired), user_id)
    return expired


async def refresh_statuses(session: AsyncSession) -> dict[str, int]:
    """Прогон планировщика: expiring_soon / expired + снятие сайтов и уведомления."""
    now = utcnow()
    soon_border = now + timedelta(days=settings.EXPIRING_SOON_DAYS)
    stats = {"expiring_soon": 0, "expired": 0, "unpublished": 0}

    rows = await session.scalars(
        select(Subscription).where(
            Subscription.expires_at.is_not(None),
            Subscription.status != SubscriptionStatus.expired,
        )
    )
    for sub in rows.all():
        expires_at = _aware(sub.expires_at)
        user = await session.get(User, sub.user_id)
        tariff_name = sub.tariff.name if sub.tariff else ("Trial" if sub.is_trial else "—")

        if expires_at is not None and expires_at <= now:
            sub.status = SubscriptionStatus.expired
            stats["expired"] += 1
            if user and not sub.notified_expired:
                await notifications.notify(
                    user.telegram_id, "subscription_expired", user.language, tariff=tariff_name
                )
                sub.notified_expired = True
            unpublished = await unpublish_sites_without_subscription(session, sub.user_id)
            stats["unpublished"] += len(unpublished)
        elif expires_at is not None and expires_at <= soon_border:
            if sub.status != SubscriptionStatus.expiring_soon:
                sub.status = SubscriptionStatus.expiring_soon
                stats["expiring_soon"] += 1
            if user and not sub.notified_expiring:
                await notifications.notify(
                    user.telegram_id,
                    "subscription_expiring",
                    user.language,
                    tariff=tariff_name,
                    date=f"{expires_at:%d.%m.%Y}",
                )
                sub.notified_expiring = True

    await session.flush()
    return stats
