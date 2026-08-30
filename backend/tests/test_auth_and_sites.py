"""Авторизация по initData, настройки, CRUD сайтов, превью и лимиты."""
from __future__ import annotations

import pytest

from app.core.errors import Unauthorized
from app.core.telegram_auth import build_init_data, verify_init_data
from tests.conftest import BOT_TOKEN, headers_for


def test_init_data_signature_is_verified():
    good = build_init_data(BOT_TOKEN, {"id": 1, "username": "u"})
    assert verify_init_data(good, bot_token=BOT_TOKEN).id == 1

    with pytest.raises(Unauthorized):
        verify_init_data(good, bot_token="another:token")
    with pytest.raises(Unauthorized):
        verify_init_data(good.replace("hash=", "hash=0"), bot_token=BOT_TOKEN)
    with pytest.raises(Unauthorized):
        verify_init_data("", bot_token=BOT_TOKEN)


def test_init_data_expires():
    stale = build_init_data(BOT_TOKEN, {"id": 1}, auth_date=1)
    with pytest.raises(Unauthorized):
        verify_init_data(stale, bot_token=BOT_TOKEN, ttl=3600)


async def test_auth_creates_user_and_flags_admin(client):
    resp = await client.post("/api/user/auth", headers=headers_for(1001), json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["telegram_id"] == 1001
    assert body["is_admin"] is False

    admin = await client.post("/api/user/auth", headers=headers_for(777000, "boss"), json={})
    assert admin.json()["is_admin"] is True


async def test_requests_without_init_data_are_rejected(client):
    resp = await client.get("/api/sites")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INIT_DATA_MISSING"


async def test_error_format_is_uniform(client):
    resp = await client.get("/api/sites/not-a-uuid", headers=headers_for(1002))
    assert resp.status_code == 422
    assert set(resp.json()["error"]) >= {"code", "message"}


async def test_site_crud_and_preview(client):
    h = headers_for(1003)
    created = await client.post(
        "/api/sites", headers=h, json={"type": "visitka", "title": "Моя визитка"}
    )
    assert created.status_code == 201
    site = created.json()["site"]
    assert site["status"] == "draft"
    assert site["content_json"]["blocks"]  # скелет шаблона проставлен

    patched = await client.patch(
        f"/api/sites/{site['id']}",
        headers=h,
        json={
            "title": "Визитка v2",
            "content_json": {
                "version": 1,
                "meta": {"title": "Ирина", "lang": "ru"},
                "theme": {"preset": "aurora", "accent": "#ff6600"},
                "blocks": [
                    {"id": "1", "type": "hero", "props": {"title": "Ирина", "subtitle": "Дизайнер"}},
                    {
                        "id": "2",
                        "type": "links",
                        "props": {"items": [{"title": "Telegram", "url": "https://t.me/ton"}]},
                    },
                ],
            },
        },
    )
    assert patched.status_code == 200
    assert patched.json()["site"]["title"] == "Визитка v2"

    preview = await client.post(f"/api/sites/{site['id']}/preview", headers=h)
    html = preview.json()["preview_html"]
    assert "Ирина" in html and "https://t.me/ton" in html
    assert "<!DOCTYPE html>" in html

    listed = await client.get("/api/sites", headers=h)
    assert len(listed.json()) == 1

    deleted = await client.delete(f"/api/sites/{site['id']}", headers=h)
    assert deleted.json() == {"success": True}
    assert (await client.get("/api/sites", headers=h)).json() == []


async def test_foreign_site_is_not_accessible(client):
    created = await client.post(
        "/api/sites", headers=headers_for(1004), json={"type": "links", "title": "Мой"}
    )
    site_id = created.json()["site"]["id"]
    resp = await client.get(f"/api/sites/{site_id}", headers=headers_for(1005))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SITE_NOT_FOUND"


async def test_site_limit_without_subscription(client):
    h = headers_for(1006)
    first = await client.post("/api/sites", headers=h, json={"type": "links", "title": "A"})
    assert first.status_code == 201
    second = await client.post("/api/sites", headers=h, json={"type": "links", "title": "B"})
    assert second.status_code == 403
    assert second.json()["error"]["code"] == "LIMIT_EXCEEDED"


async def test_settings_update(client):
    h = headers_for(1007)
    await client.post("/api/user/auth", headers=h, json={})
    resp = await client.patch("/api/user/settings", headers=h, json={"language": "en", "theme": "dark"})
    assert resp.json() == {"success": True}
    me = await client.get("/api/user/me", headers=h)
    assert me.json()["language"] == "en" and me.json()["theme"] == "dark"
