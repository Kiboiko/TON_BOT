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

    # запрос транзакции ничего не присваивает: пользователь мог её и не подписать
    not_yet = await client.get(f"/api/sites/{site_id}", headers=h)
    assert not_yet.json()["site"]["domain"] is None

    # пока субдомена нет в сети — подтверждение отвечает pending
    pending = await client.post(
        "/api/domains/confirm",
        headers=h,
        json={"site_id": site_id, "tx_hash": "boc-not-onchain", "domain": "mysite.tonsite.ton"},
    )
    assert pending.json()["status"] == "pending"
    still_empty = await client.get(f"/api/sites/{site_id}", headers=h)
    assert still_empty.json()["site"]["domain"] is None

    # субдомен появился и принадлежит кошельку пользователя
    resolver.own("mysite.tonsite.ton", wallet, item_address="0:" + "cc" * 32)
    confirmed = await client.post(
        "/api/domains/confirm",
        headers=h,
        json={"site_id": site_id, "tx_hash": "boc-onchain", "domain": "mysite.tonsite.ton"},
    )
    assert confirmed.json()["status"] == "publishing"

    # только теперь домен закреплён — и вместе с ним адрес DNS-item,
    # без которого нечем подписать запись домена
    bound = (await client.get(f"/api/sites/{site_id}", headers=h)).json()["site"]
    assert bound["domain"] == "mysite.tonsite.ton"
    assert bound["dns_item_address"] == "0:" + "cc" * 32

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


async def test_stuck_publishing_can_be_retried(client, queue):
    """Из зависшего «публикуется» должен быть выход: иначе кнопка вечно даёт 409."""
    from datetime import timedelta

    from app.core.config import settings
    from app.models import SiteStatus, utcnow

    h = headers_for(6001)
    created = await client.post("/api/sites", headers=h, json={"type": "links", "title": "Stuck"})
    site_id = created.json()["site"]["id"]

    async with SessionLocal() as session:
        site = await session.get(Site, uuid.UUID(site_id))
        site.status = SiteStatus.publishing
        await session.commit()

    # свежая публикация: повтор запрещён, задача действительно выполняется
    busy = await client.post(f"/api/sites/{site_id}/publish", headers=h)
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "PUBLISH_IN_PROGRESS"

    # задача потеряна: статус висит дольше порога
    async with SessionLocal() as session:
        site = await session.get(Site, uuid.UUID(site_id))
        site.updated_at = utcnow() - timedelta(seconds=settings.PUBLISH_STALE_SECONDS + 60)
        await session.commit()

    retry = await client.post(f"/api/sites/{site_id}/publish", headers=h)
    assert retry.status_code == 200
    assert retry.json()["status"] == "publishing"


async def test_publish_result_is_committed_before_notifying(client, queue, storage, notifier):
    """Telegram не должен решать, опубликован ли сайт.

    Раньше уведомления отправлялись внутри транзакции: зависший запрос к
    Telegram оставлял сайт навсегда в статусе «публикуется».
    """
    import asyncio

    from app.services import notifications
    from app.services.publishing import run_publish_job

    h = headers_for(6002)
    created = await client.post("/api/sites", headers=h, json={"type": "links", "title": "Notify"})
    site_id = created.json()["site"]["id"]
    await client.post(f"/api/sites/{site_id}/publish", headers=h)

    class HangingTransport:
        """Транспорт, который никогда не отвечает."""

        async def send(self, telegram_id: int, text: str) -> bool:
            await asyncio.sleep(3600)
            return True

    notifications.set_transport(HangingTransport())
    try:
        # задача не должна зависнуть вместе с уведомлением
        await asyncio.wait_for(run_publish_job(site_id), timeout=10)
    except asyncio.TimeoutError:
        pass  # уведомление зависло — проверяем, что публикация всё равно сохранена
    finally:
        notifications.set_transport(notifier)

    async with SessionLocal() as session:
        site = await session.get(Site, uuid.UUID(site_id))
        assert site.status == SiteStatus.published
        assert site.storage_bag_id


async def test_subscription_purchase_credits_payment_that_already_arrived(client, ton):
    """Подписка: дошедшую, но неподтверждённую оплату засчитываем вместо новой."""
    h = headers_for(2050)
    tariff_id = await make_tariff(name="Recovered", price="2")

    first = await client.post(
        "/api/subscriptions/purchase", headers=h, json={"tariff_id": str(tariff_id)}
    )
    comment = await payment_comment(first.json()["payment_id"])
    ton.add(paid_tx(comment, "2", tx_hash="sub-arrived"))

    again = await client.post(
        "/api/subscriptions/purchase", headers=h, json={"tariff_id": str(tariff_id)}
    )
    assert again.status_code == 200
    body = again.json()
    assert body["already_paid"] is True
    assert body["recovered_tariffs"] == ["Recovered"]
    assert body["transaction"] is None

    subs = (await client.get("/api/subscriptions", headers=h)).json()
    assert len(subs) == 1


async def test_confirming_same_payment_twice_does_not_extend_twice(client, ton):
    """Повтор подтверждения той же оплаты не продлевает подписку второй раз."""
    from datetime import datetime, timezone

    h = headers_for(2051)
    tariff_id = await make_tariff(name="Once", price="2")
    bought = await client.post(
        "/api/subscriptions/purchase", headers=h, json={"tariff_id": str(tariff_id)}
    )
    payment_id = bought.json()["payment_id"]
    ton.add(paid_tx(await payment_comment(payment_id), "2", tx_hash="sub-once"))

    body = {"payment_id": payment_id, "tx_hash": "sub-once-boc-0001"}
    first = await client.post("/api/subscriptions/confirm", headers=h, json=body)
    second = await client.post("/api/subscriptions/confirm", headers=h, json=body)
    assert first.status_code == 200 and second.status_code == 200

    # Один и тот же момент приходит в разной записи: только что созданная
    # подписка сериализуется с поясом, прочитанная из SQLite — без него.
    def instant(value: str) -> datetime:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

    assert instant(first.json()["subscription"]["expires_at"]) == instant(
        second.json()["subscription"]["expires_at"]
    ), "одна оплата — одно продление"
    subs = (await client.get("/api/subscriptions", headers=h)).json()
    assert len(subs) == 1


async def test_published_site_can_be_updated(client, queue, storage, notifier):
    """Опубликованный сайт обновляется повторной публикацией по той же ссылке.

    После правки приложение видит неопубликованные изменения, наружу по-прежнему
    отдаётся прошлая версия, а после обновления — новая. Домен и подпись в
    кошельке для этого не нужны.
    """
    h = headers_for(2052)
    created = await client.post(
        "/api/sites", headers=h, json={"type": "visitka", "title": "Обновляемый"}
    )
    site_id = created.json()["site"]["id"]

    def content(title: str) -> dict:
        return {"content_json": {
            "version": 1,
            "meta": {"title": "Обновляемый"},
            "theme": {"preset": "light", "accent": "#0098ea"},
            "blocks": [{"id": "1", "type": "hero", "props": {"title": title}}],
        }}

    async def publish() -> None:
        started = await client.post(f"/api/sites/{site_id}/publish", headers=h)
        assert started.status_code == 200
        job = await queue.dequeue(timeout=1)
        await run_publish_job(job.payload["site_id"])

    await client.patch(f"/api/sites/{site_id}", headers=h, json=content("Первая версия"))
    await publish()
    site = (await client.get(f"/api/sites/{site_id}", headers=h)).json()["site"]
    assert site["status"] == "published"
    assert site["has_unpublished_changes"] is False

    await client.patch(f"/api/sites/{site_id}", headers=h, json=content("Вторая версия"))
    site = (await client.get(f"/api/sites/{site_id}", headers=h)).json()["site"]
    assert site["has_unpublished_changes"] is True
    listed = (await client.get("/api/sites", headers=h)).json()
    assert next(s for s in listed if s["id"] == site_id)["has_unpublished_changes"] is True
    # правка не уходит наружу, пока сайт не обновили
    page = await client.get(f"/s/{site_id}")
    assert "Первая версия" in page.text and "Вторая версия" not in page.text

    await publish()
    status = (await client.get(f"/api/sites/{site_id}/publish-status", headers=h)).json()
    assert status["status"] == "published"
    assert status["has_unpublished_changes"] is False
    page = await client.get(f"/s/{site_id}")
    assert "Вторая версия" in page.text
    # первое сообщение — о публикации, второе — об обновлении
    texts = [text for _, text in notifier.sent]
    assert any("опубликован" in text for text in texts)
    assert any("обновлён" in text for text in texts)
