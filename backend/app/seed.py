"""Начальные тарифы и назначение админов.

Запуск: python -m app.seed
Идемпотентно: повторный запуск ничего не дублирует и не перетирает цены,
изменённые через админку.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Tariff, TariffDuration, TariffKind, User

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("seed")

DEFAULT_TARIFFS = [
    {
        "name": "Базовый",
        "description": "1 сайт, публикация на домене .ton",
        "sites_limit": 1,
        "duration": TariffDuration.month,
        "price_ton": Decimal("2"),
        "kind": TariffKind.base,
    },
    {
        "name": "PRO 5",
        "description": "До 5 сайтов",
        "sites_limit": 5,
        "duration": TariffDuration.month,
        "price_ton": Decimal("7"),
        "kind": TariffKind.pro,
    },
    {
        "name": "PRO 25",
        "description": "До 25 сайтов",
        "sites_limit": 25,
        "duration": TariffDuration.month,
        "price_ton": Decimal("25"),
        "kind": TariffKind.pro,
    },
    {
        "name": "PRO 5 — год",
        "description": "До 5 сайтов, оплата за 12 месяцев",
        "sites_limit": 5,
        "duration": TariffDuration.month12,
        "price_ton": Decimal("60"),
        "kind": TariffKind.pro,
    },
    {
        "name": "Свой код",
        "description": "Премиум-блок HTML/CSS/JS для одного сайта, бессрочно",
        "sites_limit": 1,
        "duration": TariffDuration.forever,
        "price_ton": Decimal("5"),
        "kind": TariffKind.custom_code,
    },
]


async def seed() -> None:
    async with SessionLocal() as session:
        created = 0
        for data in DEFAULT_TARIFFS:
            exists = await session.scalar(select(Tariff).where(Tariff.name == data["name"]))
            if exists is not None:
                continue
            session.add(Tariff(**data))
            created += 1

        promoted = 0
        for telegram_id in settings.admin_telegram_ids:
            user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is not None and not user.is_admin:
                user.is_admin = True
                promoted += 1

        await session.commit()
        log.info("tariffs created: %s, admins promoted: %s", created, promoted)


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
