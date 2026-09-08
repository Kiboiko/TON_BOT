"""Начальные тарифы и назначение админов.

Запуск: python -m app.seed
Идемпотентно: повторный запуск ничего не дублирует и не перетирает цены,
изменённые через админку.

Тарифная сетка = тариф × срок. Сроки по ТЗ: 1, 3, 6, 12 месяцев и навсегда.
На витрине срок вынесен в переключатель, поэтому строки с одним и тем же
именем — это один тариф с разными вариантами оплаты.
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

# Цены за срок, TON. Чем длиннее срок, тем дешевле месяц:
# 3 месяца ≈ −10%, 6 месяцев ≈ −17%, год ≈ −30%.
TIERS: list[dict] = [
    {
        "name": "Basic",
        "description": "Для одного проекта",
        "sites_limit": 1,
        "kind": TariffKind.base,
        "prices": {
            TariffDuration.month: "2",
            TariffDuration.month3: "5",
            TariffDuration.month6: "10",
            TariffDuration.month12: "17",
            TariffDuration.forever: "50",
        },
    },
    {
        "name": "Pro",
        "description": "Для нескольких проектов",
        "sites_limit": 5,
        "kind": TariffKind.pro,
        "prices": {
            TariffDuration.month: "7",
            TariffDuration.month3: "19",
            TariffDuration.month6: "35",
            TariffDuration.month12: "60",
            TariffDuration.forever: "175",
        },
    },
    {
        "name": "Business",
        "description": "Для агентства и команды",
        "sites_limit": 25,
        "kind": TariffKind.pro,
        "prices": {
            TariffDuration.month: "25",
            TariffDuration.month3: "67",
            TariffDuration.month6: "125",
            TariffDuration.month12: "210",
            TariffDuration.forever: "600",
        },
    },
    {
        "name": "Max",
        "description": "Максимальный лимит сайтов",
        "sites_limit": 100,
        "kind": TariffKind.pro,
        "prices": {
            TariffDuration.month: "60",
            TariffDuration.month3: "160",
            TariffDuration.month6: "300",
            TariffDuration.month12: "500",
            TariffDuration.forever: "1500",
        },
    },
]

# Разовая покупка возможности «Свой код» — по ТЗ это не подписка, а фиксированная
# плата за один сайт. Цена по умолчанию; дальше её меняет админ в тарифах.
CUSTOM_CODE_TARIFF: dict = {
    "name": "Свой код",
    "description": "Разовая оплата своего HTML, CSS и JS для одного сайта",
    "sites_limit": 1,
    "kind": TariffKind.custom_code,
    "duration": TariffDuration.forever,
    "price_ton": Decimal("5"),
}

# Старые названия тарифов до перехода на сетку Basic/Pro/Business/Max.
# Переименовываем, а не пересоздаём: на эти строки ссылаются оплаченные подписки.
LEGACY_RENAMES: dict[str, str] = {
    "Базовый": "Basic",
    "PRO 5": "Pro",
    "PRO 5 — год": "Pro",
    "PRO 25": "Business",
}


def default_tariffs() -> list[dict]:
    """Разворачивает сетку тариф × срок в плоский список строк таблицы."""
    rows: list[dict] = []
    for tier in TIERS:
        for duration, price in tier["prices"].items():
            rows.append(
                {
                    "name": tier["name"],
                    "description": tier["description"],
                    "sites_limit": tier["sites_limit"],
                    "kind": tier["kind"],
                    "duration": duration,
                    "price_ton": Decimal(price),
                }
            )
    return rows


async def seed() -> None:
    async with SessionLocal() as session:
        descriptions = {tier["name"]: tier["description"] for tier in TIERS}

        # 1. Переименование старых тарифов: подписки и платежи остаются привязанными.
        renamed = 0
        for old_name, new_name in LEGACY_RENAMES.items():
            rows = await session.scalars(select(Tariff).where(Tariff.name == old_name))
            for tariff in rows.all():
                tariff.name = new_name
                tariff.description = descriptions.get(new_name, tariff.description)
                renamed += 1

        # 2. Разовая покупка «Своего кода». Цену задаёт админ, поэтому строку
        #    только создаём — существующую не трогаем, иначе изменённая цена
        #    возвращалась бы к дефолтной при каждом запуске.
        custom = await session.scalar(
            select(Tariff).where(Tariff.kind == TariffKind.custom_code)
        )
        if custom is None:
            session.add(Tariff(**CUSTOM_CODE_TARIFF))
            custom_created = True
        else:
            # строка могла быть погашена, пока доступ давала подписка
            custom_created = False
            custom.is_active = True

        await session.flush()

        # 3. Досоздание недостающих вариантов. Ключ — пара «название + срок»,
        #    иначе сроки одного тарифа считались бы дубликатами.
        created = 0
        for data in default_tariffs():
            exists = await session.scalar(
                select(Tariff).where(
                    Tariff.name == data["name"], Tariff.duration == data["duration"]
                )
            )
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
        log.info(
            "tariffs renamed: %s, custom code created: %s, created: %s, admins promoted: %s",
            renamed,
            custom_created,
            created,
            promoted,
        )


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
