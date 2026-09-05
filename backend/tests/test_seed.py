"""Тарифная сетка: полный набор сроков, идемпотентность и переезд старых названий."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models import Subscription, Tariff, TariffDuration, TariffKind, User
from app.seed import TIERS, default_tariffs, seed
from tests.conftest import headers_for

ALL_DURATIONS = {
    TariffDuration.month,
    TariffDuration.month3,
    TariffDuration.month6,
    TariffDuration.month12,
    TariffDuration.forever,
}


def test_every_tier_has_all_durations_from_tz() -> None:
    """ТЗ: подписки на 1, 3, 6, 12 месяцев и навсегда — у каждого тарифа."""
    rows = default_tariffs()
    for tier in TIERS:
        durations = {r["duration"] for r in rows if r["name"] == tier["name"]}
        assert durations == ALL_DURATIONS, tier["name"]

    assert len(rows) == len(TIERS) * len(ALL_DURATIONS) + 1  # + «Свой код»


def test_longer_terms_are_cheaper_per_month() -> None:
    """Скидка за длинный срок — иначе переключатель срока теряет смысл."""
    months = {TariffDuration.month: 1, TariffDuration.month3: 3, TariffDuration.month6: 6,
              TariffDuration.month12: 12}
    for tier in TIERS:
        monthly = Decimal(tier["prices"][TariffDuration.month])
        for duration, count in months.items():
            if duration == TariffDuration.month:
                continue
            per_month = Decimal(tier["prices"][duration]) / count
            assert per_month < monthly, f"{tier['name']} / {duration}"


@pytest.mark.asyncio
async def test_seed_is_idempotent(db) -> None:
    await seed()
    await seed()

    async with SessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(Tariff))
        assert total == len(default_tariffs())

        # витрина: у каждого тарифа ровно пять вариантов оплаты
        for tier in TIERS:
            rows = await session.scalars(select(Tariff).where(Tariff.name == tier["name"]))
            assert {t.duration for t in rows.all()} == ALL_DURATIONS


@pytest.mark.asyncio
async def test_legacy_tariffs_are_renamed_not_recreated(db) -> None:
    """Старые строки переименовываются: оплаченные подписки на них не должны отвязаться."""
    async with SessionLocal() as session:
        user = User(telegram_id=42, username="legacy")
        old_month = Tariff(
            name="PRO 5",
            description="До 5 сайтов",
            sites_limit=5,
            duration=TariffDuration.month,
            price_ton=Decimal("7"),
            kind=TariffKind.pro,
        )
        old_year = Tariff(
            name="PRO 5 — год",
            description="До 5 сайтов, оплата за 12 месяцев",
            sites_limit=5,
            duration=TariffDuration.month12,
            price_ton=Decimal("60"),
            kind=TariffKind.pro,
        )
        session.add_all([user, old_month, old_year])
        await session.flush()
        subscription = Subscription(user_id=user.id, tariff_id=old_month.id)
        session.add(subscription)
        await session.commit()
        old_month_id, old_year_id, sub_id = old_month.id, old_year.id, subscription.id

    await seed()

    async with SessionLocal() as session:
        # те же строки, новое имя — id не поменялись
        assert (await session.get(Tariff, old_month_id)).name == "Pro"
        assert (await session.get(Tariff, old_year_id)).name == "Pro"

        sub = await session.get(Subscription, sub_id)
        assert sub is not None and sub.tariff_id == old_month_id

        # дубликатов не появилось: у «Pro» по одной строке на срок
        rows = await session.scalars(select(Tariff).where(Tariff.name == "Pro"))
        durations = [t.duration for t in rows.all()]
        assert sorted(durations, key=str) == sorted(ALL_DURATIONS, key=str)

        assert await session.scalar(select(func.count()).select_from(Tariff)) == len(
            default_tariffs()
        )


@pytest.mark.asyncio
async def test_storefront_shows_grid_without_custom_code(client) -> None:
    await seed()
    response = await client.get("/api/tariffs", headers=headers_for(500100))
    assert response.status_code == 200
    tariffs = response.json()

    assert all(t["kind"] != "custom_code" for t in tariffs)
    assert len(tariffs) == len(TIERS) * len(ALL_DURATIONS)
    # порядок: сначала младшие тарифы — витрина строит карточки в этом порядке
    assert [t["sites_limit"] for t in tariffs] == sorted(t["sites_limit"] for t in tariffs)
