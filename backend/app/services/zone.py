"""Зона субдоменов платформы.

Модель работы subdom: платформа владеет доменом `.ton`, один раз разворачивает
на нём зону субдоменов, а пользователи получают адреса вида `имя.домен.ton`
внутри этой коллекции. Собственный домен каждому пользователю не нужен.

Настройки зоны хранятся в БД, а не только в .env: адрес коллекции становится
известен лишь после того, как владелец домена подпишет транзакцию разворота,
и админ должен иметь возможность вписать его без передеплоя.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AppSetting, utcnow

log = logging.getLogger(__name__)

KEY_DOMAIN = "zone_domain"
KEY_DNS_ITEM = "zone_dns_item_address"
KEY_COLLECTION = "zone_collection_address"
KEY_MODE = "zone_mode"


@dataclass(slots=True)
class ZoneConfig:
    domain: str
    dns_item_address: str
    collection_address: str
    mode: str

    @property
    def configured(self) -> bool:
        """Зона готова принимать субдомены, когда известна её коллекция."""
        return bool(self.domain and self.collection_address)

    @property
    def deployable(self) -> bool:
        """Зону можно разворачивать, когда известен домен и его DNS-item."""
        return bool(self.domain and self.dns_item_address)


async def _get(session: AsyncSession, key: str, fallback: str) -> str:
    value = await session.scalar(select(AppSetting.value).where(AppSetting.key == key))
    return value if value else fallback


async def get_zone(session: AsyncSession) -> ZoneConfig:
    """Настройки зоны: значения из БД перекрывают значения из .env."""
    return ZoneConfig(
        domain=(await _get(session, KEY_DOMAIN, settings.ZONE_DOMAIN)).strip().lower(),
        dns_item_address=await _get(session, KEY_DNS_ITEM, settings.ZONE_DNS_ITEM_ADDRESS),
        collection_address=await _get(session, KEY_COLLECTION, settings.ZONE_COLLECTION_ADDRESS),
        mode=await _get(session, KEY_MODE, settings.ZONE_MODE),
    )


async def set_zone(
    session: AsyncSession,
    *,
    domain: str | None = None,
    dns_item_address: str | None = None,
    collection_address: str | None = None,
    mode: str | None = None,
) -> ZoneConfig:
    updates = {
        KEY_DOMAIN: domain.strip().lower() if domain is not None else None,
        KEY_DNS_ITEM: dns_item_address,
        KEY_COLLECTION: collection_address,
        KEY_MODE: mode,
    }
    for key, value in updates.items():
        if value is None:
            continue
        row = await session.get(AppSetting, key)
        if row is None:
            session.add(AppSetting(key=key, value=value))
        else:
            row.value = value
            row.updated_at = utcnow()
    await session.flush()
    zone = await get_zone(session)
    log.info("zone updated: domain=%s collection=%s", zone.domain, zone.collection_address[:12])
    return zone


def full_domain(name: str, zone: ZoneConfig) -> str:
    """`имя` + зона -> полный адрес субдомена."""
    return f"{name.strip().lower()}.{zone.domain}" if zone.domain else name.strip().lower()
