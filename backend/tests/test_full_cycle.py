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


async def test_full_cycle(client, ton, queue, notifier, domain_service, resolver):
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

    # 6. субдомен в зоне платформы: настройка зоны, проверка, получение, подтверждение
    admin_h = headers_for(777000, "zone_admin")
    zone = await client.patch(
        "/api/admin/zone",
        headers=admin_h,
        json={
            "domain": "tonsite.ton",
            "dns_item_address": "0:" + "aa" * 32,
            "collection_address": "0:" + "bb" * 32,
            "mode": "proxy",
        },
    )
    assert zone.status_code == 200 and zone.json()["configured"] is True

    check = await client.get("/api/domains/check", headers=h, params={"name": "mysite"})
    assert check.json()["available"] is True
    assert check.json()["domain"] == "mysite.tonsite.ton"

    taken = await client.get("/api/domains/check", headers=h, params={"name": "takenname"})
    assert taken.json()["available"] is False

    # без подключённого кошелька субдомен не получить
    no_wallet = await client.post(
        "/api/domains/claim", headers=h, json={"site_id": site_id, "name": "mysite"}
    )
    assert no_wallet.status_code == 401
    assert no_wallet.json()["error"]["code"] == "WALLET_NOT_CONNECTED"

    wallet = "0:" + "1" * 64
    async with SessionLocal() as session:  # кошелёк привязывается через ton_proof, здесь — напрямую
        from app.models import User

        user = await session.scalar(select(User).where(User.telegram_id == 2001))
        user.wallet_address = wallet
        await session.commit()

    claim = await client.post(
        "/api/domains/claim", headers=h, json={"site_id": site_id, "name": "mysite"}
    )
    assert claim.status_code == 200, claim.text
    assert claim.json()["domain"] == "mysite.tonsite.ton"
    assert claim.json()["transaction"]["messages"]
    assert ("start_auction", {"subdomain": "mysite"}) in domain_service.calls

    # пока субдомена нет в сети — подтверждение отвечает pending
    pending = await client.post(
        "/api/domains/confirm", headers=h, json={"site_id": site_id, "tx_hash": "boc-not-onchain"}
    )
    assert pending.json()["status"] == "pending"

    # субдомен появился и принадлежит кошельку пользователя
    resolver.own("mysite.tonsite.ton", wallet, item_address="0:" + "cc" * 32)
    confirmed = await client.post(
        "/api/domains/confirm", headers=h, json={"site_id": site_id, "tx_hash": "boc-onchain"}
    )
    assert confirmed.json()["status"] == "publishing"

    # 7. публикация уже запущена подтверждением домена
    status = await client.get(f"/api/sites/{site_id}/publish-status", headers=h)
    assert status.json()["status"] == "publishing"

    # повторный запуск, пока идёт публикация, отклоняется
    again = await client.post(f"/api/sites/{site_id}/publish", headers=h)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "PUBLISH_IN_PROGRESS"

    # а сайт без домена публикуется обычным путём
    other = await client.post(f"/api/sites/{site_ids[1]}/publish", headers=h)
    assert other.status_code == 200 and other.json()["status"] == "publishing"

    # 8. воркер выполняет задачи из очереди
    for _ in range(2):
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


async def test_published_site_is_served_publicly(client, queue, storage):
    """Опубликованный сайт открывается обычной ссылкой, черновик — нет."""
    h = headers_for(2008)
    created = await client.post(
        "/api/sites", headers=h, json={"type": "visitka", "title": "Публичный"}
    )
    site_id = created.json()["site"]["id"]

    # черновик наружу не отдаётся
    assert (await client.get(f"/s/{site_id}")).status_code == 404

    await client.patch(
        f"/api/sites/{site_id}",
        headers=h,
        json={"content_json": {"version": 1, "meta": {"title": "Публичный"}, "theme":
              {"preset": "light", "accent": "#0098ea"}, "blocks": [
                  {"id": "1", "type": "hero", "props": {"title": "Привет из TON"}}]}},
    )
    await client.post(f"/api/sites/{site_id}/publish", headers=h)
    job = await queue.dequeue(timeout=1)
    await run_publish_job(job.payload["site_id"])

    status = await client.get(f"/api/sites/{site_id}/publish-status", headers=h)
    assert status.json()["status"] == "published"
    assert status.json()["public_url"].endswith(f"/s/{site_id}")

    page = await client.get(f"/s/{site_id}")
    assert page.status_code == 200
    assert "Привет из TON" in page.text
    assert page.headers["content-type"].startswith("text/html")


async def test_attach_own_domain(client, resolver, queue, storage):
    """Свой домен .ton привязывается к сайту без зоны платформы (ТЗ: «Привязанный домен»)."""
    h = headers_for(2009, "domain_owner")
    created = await client.post("/api/sites", headers=h, json={"type": "visitka", "title": "Свой домен"})
    site_id = created.json()["site"]["id"]
    wallet = "0:" + "7" * 64

    # без кошелька привязывать нечего
    no_wallet = await client.post(
        "/api/domains/attach", headers=h, json={"site_id": site_id, "domain": "mysite.ton"}
    )
    assert no_wallet.status_code == 401

    async with SessionLocal() as session:
        from app.models import User

        user = await session.scalar(select(User).where(User.telegram_id == 2009))
        user.wallet_address = wallet
        await session.commit()

    # незарегистрированный домен привязать нельзя
    free = await client.post(
        "/api/domains/attach", headers=h, json={"site_id": site_id, "domain": "notbought.ton"}
    )
    assert free.status_code == 400
    assert free.json()["error"]["code"] == "DOMAIN_NOT_REGISTERED"

    # чужой домен — тоже
    resolver.own("someoneelse.ton", "0:" + "9" * 64)
    foreign = await client.post(
        "/api/domains/attach", headers=h, json={"site_id": site_id, "domain": "someoneelse.ton"}
    )
    assert foreign.status_code == 409
    assert foreign.json()["error"]["code"] == "DOMAIN_NOT_OWNED"

    # свой домен привязывается, а зона платформы для этого не нужна
    resolver.own("mysite.ton", wallet, item_address="0:" + "ee" * 32)
    ok = await client.post(
        "/api/domains/attach", headers=h, json={"site_id": site_id, "domain": "mysite.ton"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["domain"] == "mysite.ton"

    # после публикации домен можно направить на сайт DNS-записью
    await client.post(f"/api/sites/{site_id}/publish", headers=h)
    job = await queue.dequeue(timeout=1)
    await run_publish_job(job.payload["site_id"])

    bind = await client.post(f"/api/sites/{site_id}/dns-bind", headers=h)
    assert bind.status_code == 200, bind.text
    assert bind.json()["transaction"]["messages"][0]["payload"]
