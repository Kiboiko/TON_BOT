"""A7: права, ручная выдача/отзыв доступа, тарифы, домены, статистика, аудит."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import AdminAction, AdminActionType
from tests.conftest import headers_for

ADMIN = headers_for(777000, "boss")


async def test_admin_endpoints_require_admin(client):
    user = headers_for(3001)
    for method, path in (
        ("get", "/api/admin/users"),
        ("get", "/api/admin/stats"),
        ("get", "/api/admin/tariffs"),
        ("get", "/api/admin/domains"),
    ):
        resp = await getattr(client, method)(path, headers=user)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "ADMIN_REQUIRED"


async def test_tariff_crud_and_price_change_is_audited(client):
    created = await client.post(
        "/api/admin/tariffs",
        headers=ADMIN,
        json={"name": "PRO 5", "sites_limit": 5, "duration": "month", "price_ton": "7", "kind": "pro"},
    )
    assert created.status_code == 201
    tariff_id = created.json()["id"]

    updated = await client.patch(
        f"/api/admin/tariffs/{tariff_id}", headers=ADMIN, json={"price_ton": "9.5"}
    )
    assert updated.json()["price_ton"] == "9.5"

    # витрина для пользователя отдаёт новую цену
    shop = await client.get("/api/tariffs", headers=headers_for(3002))
    assert shop.json()[0]["price_ton"] == "9.5"

    hidden = await client.patch(
        f"/api/admin/tariffs/{tariff_id}", headers=ADMIN, json={"is_active": False}
    )
    assert hidden.json()["is_active"] is False
    assert (await client.get("/api/tariffs", headers=headers_for(3002))).json() == []

    async with SessionLocal() as session:
        actions = (await session.scalars(select(AdminAction))).all()
    kinds = {a.action for a in actions}
    assert AdminActionType.create_tariff in kinds
    assert AdminActionType.change_price in kinds

    deleted = await client.delete(f"/api/admin/tariffs/{tariff_id}", headers=ADMIN)
    assert deleted.json() == {"success": True}


async def test_grant_and_revoke_access(client, notifier):
    tariff = await client.post(
        "/api/admin/tariffs",
        headers=ADMIN,
        json={"name": "PRO 25", "sites_limit": 25, "duration": "3month", "price_ton": "25", "kind": "pro"},
    )
    tariff_id = tariff.json()["id"]

    user_headers = headers_for(3003, "client")
    await client.post("/api/user/auth", headers=user_headers, json={})
    users = await client.get("/api/admin/users", headers=ADMIN, params={"search": "client"})
    assert users.json()["total"] == 1
    user_id = users.json()["users"][0]["id"]

    granted = await client.post(
        f"/api/admin/users/{user_id}/grant-access",
        headers=ADMIN,
        json={"tariff_id": tariff_id, "duration": "3month", "comment": "промо"},
    )
    assert granted.status_code == 200
    sub = granted.json()["subscription"]
    assert sub["granted_by_admin"] is True
    assert sub["status"] == "manual"
    assert any("выдал вам доступ" in text for _, text in notifier.sent)

    # доступ работает: лимит вырос до 25 сайтов
    for i in range(3):
        created = await client.post(
            "/api/sites", headers=user_headers, json={"type": "links", "title": f"s{i}"}
        )
        assert created.status_code == 201

    detail = await client.get(f"/api/admin/users/{user_id}", headers=ADMIN)
    assert len(detail.json()["sites"]) == 3
    assert len(detail.json()["subscriptions"]) == 1

    revoked = await client.post(
        f"/api/admin/users/{user_id}/revoke-access",
        headers=ADMIN,
        json={"subscription_id": sub["id"]},
    )
    assert revoked.json() == {"success": True}
    assert any("отозвал доступ" in text for _, text in notifier.sent)

    # после отзыва лимит вернулся к одному сайту
    blocked = await client.post(
        "/api/sites", headers=user_headers, json={"type": "links", "title": "x"}
    )
    assert blocked.status_code == 403


async def test_grant_access_without_tariff_requires_params(client):
    await client.post("/api/user/auth", headers=headers_for(3004), json={})
    users = await client.get("/api/admin/users", headers=ADMIN, params={"search": "3004"})
    user_id = users.json()["users"][0]["id"]

    bad = await client.post(f"/api/admin/users/{user_id}/grant-access", headers=ADMIN, json={})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "GRANT_PARAMS_REQUIRED"

    ok = await client.post(
        f"/api/admin/users/{user_id}/grant-access",
        headers=ADMIN,
        json={"sites_limit": 10, "duration": "forever"},
    )
    assert ok.status_code == 200
    assert ok.json()["subscription"]["is_forever"] is True


async def test_users_pagination_and_stats(client, ton):
    for tg in range(3100, 3110):
        await client.post("/api/user/auth", headers=headers_for(tg), json={})

    page1 = await client.get("/api/admin/users", headers=ADMIN, params={"page": 1, "per_page": 4})
    assert len(page1.json()["users"]) == 4
    assert page1.json()["total"] >= 10

    stats = await client.get("/api/admin/stats", headers=ADMIN)
    body = stats.json()
    assert body["total_users"] >= 10
    assert set(body) == {
        "total_users",
        "total_sites",
        "published_sites",
        "active_subscriptions",
        "revenue",
        "revenue_last_30d",
        "payments_confirmed",
    }


async def test_admin_domains_list(client, domain_service):
    h = headers_for(3200, "domainer")
    created = await client.post("/api/sites", headers=h, json={"type": "links", "title": "D"})
    site_id = created.json()["site"]["id"]

    async with SessionLocal() as session:
        from app.models import Site, User

        user = await session.scalar(select(User).where(User.telegram_id == 3200))
        user.wallet_address = "0:" + "2" * 64
        site = await session.get(Site, uuid.UUID(site_id))
        site.domain = "cool.ton"
        await session.commit()

    domains = await client.get("/api/admin/domains", headers=ADMIN)
    assert any(d["domain"] == "cool.ton" and d["telegram_id"] == 3200 for d in domains.json())
