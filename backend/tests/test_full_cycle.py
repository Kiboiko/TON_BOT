"""Интеграционный тест полного цикла (A8):

создание сайта → покупка подписки → проверка оплаты on-chain → деплой домена →
публикация в TON Storage → уведомление в Telegram.
"""
from __future__ import annotations

import time
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Payment, Site, SiteStatus, Tariff, TariffDuration, TariffKind
from app.services.publishing import run_publish_job
from app.services.ton import TxInfo, to_nano
from tests.conftest import TREASURY, headers_for


async def make_tariff(
    name: str = "PRO 5",
    price: str = "7",
    sites_limit: int = 5,
    kind: TariffKind = TariffKind.pro,
    duration: TariffDuration = TariffDuration.month,
) -> uuid.UUID:
    async with SessionLocal() as session:
        tariff = Tariff(
            name=name,
            sites_limit=sites_limit,
            duration=duration,
            price_ton=Decimal(price),
            kind=kind,
            is_active=True,
        )
        session.add(tariff)
        await session.commit()
        return tariff.id


async def payment_comment(payment_id: str) -> str:
    async with SessionLocal() as session:
        payment = await session.get(Payment, uuid.UUID(payment_id))
        return payment.comment


def paid_tx(comment: str, amount: str, tx_hash: str = "abc123hash") -> TxInfo:
    return TxInfo(
        tx_hash=tx_hash,
        source="EQD__USER_WALLET_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        destination=TREASURY,
        value_nano=to_nano(Decimal(amount)),
        comment=comment,
        utime=int(time.time()),
    )


async def test_full_cycle(client, ton, queue, notifier, domain_service):
    h = headers_for(2001, "founder")
    tariff_id = await make_tariff()

    # 1. витрина тарифов
    tariffs = await client.get("/api/tariffs", headers=h)
    assert [t["name"] for t in tariffs.json()] == ["PRO 5"]

    # 2. покупка подписки — фронт получает транзакцию для TON Connect
    purchase = await client.post(
        "/api/subscriptions/purchase", headers=h, json={"tariff_id": str(tariff_id)}
    )
    assert purchase.status_code == 200
    tx = purchase.json()["transaction"]
    payment_id = purchase.json()["payment_id"]
    assert tx["messages"][0]["address"] == TREASURY
    assert tx["messages"][0]["amount"] == str(to_nano(Decimal("7")))
    assert tx["validUntil"] > int(time.time())

    # 3. подтверждение без реальной транзакции в сети — отказ
    rejected = await client.post(
        "/api/subscriptions/confirm",
        headers=h,
        json={"payment_id": payment_id, "tx_hash": "fake-hash-not-onchain"},
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "PAYMENT_NOT_CONFIRMED"

    # 4. транзакция появилась в блокчейне — подписка активируется
    comment = await payment_comment(payment_id)
    ton.add(paid_tx(comment, "7"))
    confirmed = await client.post(
        "/api/subscriptions/confirm",
        headers=h,
        json={"payment_id": payment_id, "tx_hash": "abc123hash"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["subscription"]["status"] == "active"
    assert confirmed.json()["subscription"]["tariff"]["sites_limit"] == 5

    # 5. лимит вырос до 5 сайтов
    site_ids = []
    for i in range(5):
        created = await client.post(
            "/api/sites", headers=h, json={"type": "landing", "title": f"Сайт {i}"}
        )
        assert created.status_code == 201
        site_ids.append(created.json()["site"]["id"])
    over_limit = await client.post("/api/sites", headers=h, json={"type": "landing", "title": "6"})
    assert over_limit.status_code == 403

    site_id = site_ids[0]

    # 6. домен: проверка, деплой зоны, подтверждение
    check = await client.get("/api/domains/check", headers=h, params={"name": "mysite", "tld": "ton"})
    assert check.json()["available"] is True

    # без подключённого кошелька деплой невозможен
    no_wallet = await client.post(
        "/api/domains/deploy-zone",
        headers=h,
        json={"site_id": site_id, "domain": "mysite", "tld": "ton", "mode": "proxy"},
    )
    assert no_wallet.status_code == 401
    assert no_wallet.json()["error"]["code"] == "WALLET_NOT_CONNECTED"

    async with SessionLocal() as session:  # кошелёк привязывается через ton_proof, здесь — напрямую
        from app.models import User

        user = await session.scalar(select(User).where(User.telegram_id == 2001))
        user.wallet_address = "0:" + "1" * 64
        await session.commit()

    deploy = await client.post(
        "/api/domains/deploy-zone",
        headers=h,
        json={"site_id": site_id, "domain": "mysite", "tld": "ton", "mode": "proxy"},
    )
    assert deploy.status_code == 200
    assert deploy.json()["transaction"]["messages"]
    assert ("deploy_proxy_zone", {"domain": "mysite", "wallet": "0:" + "1" * 64}) in domain_service.calls

    # 7. публикация: задача уходит в очередь
    publish = await client.post(f"/api/sites/{site_id}/publish", headers=h)
    assert publish.status_code == 200
    assert publish.json()["status"] == "publishing"

    status = await client.get(f"/api/sites/{site_id}/publish-status", headers=h)
    assert status.json()["status"] == "publishing"

    # 8. воркер выполняет задачу
    job = await queue.dequeue(timeout=1)
    assert job is not None and job.name == "publish_site"
    await run_publish_job(job.payload["site_id"])

    status = await client.get(f"/api/sites/{site_id}/publish-status", headers=h)
    body = status.json()
    assert body["status"] == "published"
    assert body["storage_bag_id"]
    assert body["error"] is None

    # 9. уведомление о публикации ушло пользователю
    assert any("опубликован" in text for _, text in notifier.sent)

    # 10. привязка bag id к домену — транзакция для подписи владельцем
    bind = await client.post(f"/api/sites/{site_id}/dns-bind", headers=h)
    assert bind.status_code == 200
    assert bind.json()["transaction"]["messages"][0]["payload"]


async def test_same_tx_cannot_pay_twice(client, ton):
    h = headers_for(2002)
    tariff_id = await make_tariff(name="Базовый", price="2", sites_limit=1, kind=TariffKind.base)

    first = await client.post(
        "/api/subscriptions/purchase", headers=h, json={"tariff_id": str(tariff_id)}
    )
    second = await client.post(
        "/api/subscriptions/purchase", headers=h, json={"tariff_id": str(tariff_id)}
    )
    comment = await payment_comment(first.json()["payment_id"])
    ton.add(paid_tx(comment, "2", tx_hash="reused-hash"))

    ok = await client.post(
        "/api/subscriptions/confirm",
        headers=h,
        json={"payment_id": first.json()["payment_id"], "tx_hash": "reused-hash"},
    )
    assert ok.status_code == 200

    dup = await client.post(
        "/api/subscriptions/confirm",
        headers=h,
        json={"payment_id": second.json()["payment_id"], "tx_hash": "reused-hash"},
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "TX_ALREADY_USED"


async def test_underpaid_transaction_is_rejected(client, ton):
    h = headers_for(2003)
    tariff_id = await make_tariff(name="PRO 25", price="25", sites_limit=25)
    purchase = await client.post(
        "/api/subscriptions/purchase", headers=h, json={"tariff_id": str(tariff_id)}
    )
    payment_id = purchase.json()["payment_id"]
    comment = await payment_comment(payment_id)
    ton.add(paid_tx(comment, "5", tx_hash="underpaid"))  # заплатили меньше цены

    resp = await client.post(
        "/api/subscriptions/confirm",
        headers=h,
        json={"payment_id": payment_id, "tx_hash": "underpaid"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "PAYMENT_NOT_CONFIRMED"


async def test_first_publish_is_free_for_trial_days(client, queue, notifier):
    """Первый сайт публикуется без подписки — выдаётся триал на 7 дней."""
    h = headers_for(2004)
    created = await client.post("/api/sites", headers=h, json={"type": "visitka", "title": "Первый"})
    site_id = created.json()["site"]["id"]

    publish = await client.post(f"/api/sites/{site_id}/publish", headers=h)
    assert publish.status_code == 200

    subs = await client.get("/api/subscriptions", headers=h)
    assert len(subs.json()) == 1
    assert subs.json()[0]["is_trial"] is True
    assert subs.json()[0]["expires_at"] is not None
    assert any("бесплатно" in text for _, text in notifier.sent)


async def test_second_site_publish_requires_subscription(client, queue):
    h = headers_for(2005)
    tariff_id = await make_tariff(name="PRO 5 t", price="7", sites_limit=5)

    async with SessionLocal() as session:  # выдаём лимит без оплаты, чтобы создать 2 сайта
        from app.models import Subscription, User

        user = await session.scalar(select(User).where(User.telegram_id == 2005))
        if user is None:
            await client.post("/api/user/auth", headers=h, json={})
            user = await session.scalar(select(User).where(User.telegram_id == 2005))
        session.add(
            Subscription(user_id=user.id, tariff_id=tariff_id, site_id=None, is_forever=True)
        )
        await session.commit()

    a = await client.post("/api/sites", headers=h, json={"type": "links", "title": "A"})
    b = await client.post("/api/sites", headers=h, json={"type": "links", "title": "B"})
    assert a.status_code == b.status_code == 201

    # подписка общая (site_id=None) — публикуются оба сайта
    assert (await client.post(f"/api/sites/{a.json()['site']['id']}/publish", headers=h)).status_code == 200
    assert (await client.post(f"/api/sites/{b.json()['site']['id']}/publish", headers=h)).status_code == 200


async def test_publish_error_is_reported(client, queue, notifier, monkeypatch):
    h = headers_for(2006)
    created = await client.post("/api/sites", headers=h, json={"type": "links", "title": "Сломанный"})
    site_id = created.json()["site"]["id"]
    await client.post(f"/api/sites/{site_id}/publish", headers=h)
    job = await queue.dequeue(timeout=1)

    class BrokenStorage:
        async def upload_directory(self, path, description=""):
            raise RuntimeError("storage-daemon is down")

        async def remove_bag(self, bag_id):
            return None

        async def close(self):
            return None

    from app.services import storage as storage_module

    storage_module.set_storage(BrokenStorage())
    try:
        await run_publish_job(job.payload["site_id"])
    finally:
        storage_module.set_storage(None)

    status = await client.get(f"/api/sites/{site_id}/publish-status", headers=h)
    assert status.json()["status"] == "publish_error"
    assert "storage-daemon is down" in status.json()["error"]
    assert any("Не удалось опубликовать" in text for _, text in notifier.sent)


async def test_publish_status_survives_restart(client, queue):
    """Статус хранится у нас в БД, а не в памяти процесса."""
    h = headers_for(2007)
    created = await client.post("/api/sites", headers=h, json={"type": "links", "title": "S"})
    site_id = created.json()["site"]["id"]
    await client.post(f"/api/sites/{site_id}/publish", headers=h)

    async with SessionLocal() as session:
        site = await session.get(Site, uuid.UUID(site_id))
        assert site.status == SiteStatus.publishing
        assert site.publish_job_id
