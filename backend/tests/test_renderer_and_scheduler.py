"""A4/A5: безопасность рендера, проект «Свой код» и планировщик подписок."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.db import SessionLocal
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
from app.services.dns import build_set_storage_payload
from app.services.renderer import default_content_for, render_site, safe_url
from app.services.subscriptions import refresh_statuses
from tests.conftest import headers_for


def test_user_text_is_escaped():
    html = render_site(
        {
            "meta": {"title": "<script>alert(1)</script>"},
            "blocks": [
                {"type": "hero", "props": {"title": "<img src=x onerror=alert(1)>", "subtitle": "ok"}}
            ],
        }
    )
    # разметка пользователя обезврежена: тегов нет, остался только escaped-текст
    assert "<script>alert(1)</script>" not in html
    assert "<img" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "&lt;script&gt;" in html


def test_javascript_urls_are_dropped():
    assert safe_url("javascript:alert(1)") == ""
    assert safe_url("data:text/html;base64,PHNjcmlwdD4=") == ""
    assert safe_url("https://ton.org") == "https://ton.org"
    assert safe_url("t.me/durov") == "https://t.me/durov"

    html = render_site(
        {"blocks": [{"type": "links", "props": {"items": [
            {"title": "bad", "url": "javascript:alert(1)"},
            {"title": "good", "url": "https://ton.org"},
        ]}}]}
    )
    assert "javascript:" not in html
    assert "https://ton.org" in html


def test_custom_code_is_sandboxed():
    html = render_site(
        {"blocks": []},
        custom_code={"html": "<b>hi</b>", "css": "b{color:red}", "js": "alert(1)"},
    )
    assert "<iframe" in html
    assert 'sandbox="allow-scripts"' in html
    # код пользователя не попадает в основной документ как исполняемый скрипт
    assert "<script>alert(1)</script>" not in html


def test_css_background_injection_is_blocked():
    html = render_site({"theme": {"background": "url(javascript:alert(1))"}, "blocks": []})
    assert "javascript:" not in html
    ok = render_site({"theme": {"background": "linear-gradient(#fff, #000)"}, "blocks": []})
    assert "linear-gradient(#fff, #000)" in ok


def test_all_six_templates_render():
    for site_type in ("visitka", "links", "landing", "portfolio", "events", "ton_project"):
        content = default_content_for(site_type, "Тест")
        html = render_site(content, title="Тест", site_type=site_type)
        assert html.startswith("<!DOCTYPE html>")
        assert "Тест" in html


def test_dns_payload_is_valid_boc():
    payload = build_set_storage_payload("A" * 64)
    import base64

    from pytoniq_core import Cell

    cell = Cell.one_from_boc(base64.b64decode(payload))
    slice_ = cell.begin_parse()
    assert slice_.load_uint(32) == 0x4EB1F0F9  # op change_dns_record


async def _give_subscription(telegram_id: int, *, trial: bool = False) -> None:
    """Активная подписка пользователю: платная (с тарифом) либо пробная."""
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        tariff_id = None
        if not trial:
            tariff = Tariff(
                name="Pro",
                sites_limit=5,
                duration=TariffDuration.month,
                price_ton=Decimal("7"),
                kind=TariffKind.pro,
            )
            session.add(tariff)
            await session.flush()
            tariff_id = tariff.id
        session.add(
            Subscription(
                user_id=user.id,
                tariff_id=tariff_id,
                expires_at=utcnow() + timedelta(days=30),
                is_trial=trial,
            )
        )
        await session.commit()


async def test_custom_code_project_requires_subscription(client):
    """«Свой код» — отдельный тип проекта, и открывает его только подписка."""
    h = headers_for(4001)
    await client.post("/api/user/auth", headers=h, json={})

    denied = await client.post(
        "/api/sites", headers=h, json={"type": "custom_code", "title": "CC"}
    )
    assert denied.status_code == 402
    assert denied.json()["error"]["code"] == "SUBSCRIPTION_REQUIRED"

    await _give_subscription(4001)

    created = await client.post(
        "/api/sites", headers=h, json={"type": "custom_code", "title": "CC"}
    )
    assert created.status_code == 201
    site = created.json()["site"]
    site_id = site["id"]
    # у такого проекта нет блоков: страница — это код пользователя
    assert site["content_json"]["blocks"] == []

    allowed = await client.post(
        f"/api/sites/{site_id}/custom-code",
        headers=h,
        json={"html": "<b>x</b>", "css": "", "js": "console.log(1)"},
    )
    assert allowed.status_code == 200

    preview = await client.post(f"/api/sites/{site_id}/preview", headers=h)
    assert "<iframe" in preview.json()["preview_html"]


async def test_trial_does_not_open_custom_code(client):
    """Пробный период — это бесплатная публикация, а не доступ к платному типу."""
    h = headers_for(4005)
    await client.post("/api/user/auth", headers=h, json={})
    await _give_subscription(4005, trial=True)

    denied = await client.post(
        "/api/sites", headers=h, json={"type": "custom_code", "title": "CC"}
    )
    assert denied.status_code == 402


async def test_custom_code_is_rejected_inside_regular_project(client):
    """Внутри визитки или лендинга блока со своим кодом больше нет."""
    h = headers_for(4004)
    await client.post("/api/user/auth", headers=h, json={})
    await _give_subscription(4004)

    created = await client.post("/api/sites", headers=h, json={"type": "links", "title": "L"})
    site_id = created.json()["site"]["id"]

    for path, payload in (
        (f"/api/sites/{site_id}/custom-code", {"html": "<b>x</b>", "css": "", "js": ""}),
    ):
        resp = await client.post(path, headers=h, json=payload)
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "NOT_A_CUSTOM_CODE_SITE"

    patched = await client.patch(
        f"/api/sites/{site_id}",
        headers=h,
        json={"custom_code": {"html": "<b>x</b>", "css": "", "js": ""}},
    )
    assert patched.status_code == 400
    assert patched.json()["error"]["code"] == "NOT_A_CUSTOM_CODE_SITE"


async def test_custom_code_size_limit(client):
    h = headers_for(4002)
    await client.post("/api/user/auth", headers=h, json={})
    await _give_subscription(4002)

    created = await client.post(
        "/api/sites", headers=h, json={"type": "custom_code", "title": "big"}
    )
    site_id = created.json()["site"]["id"]

    resp = await client.post(
        f"/api/sites/{site_id}/custom-code",
        headers=h,
        json={"html": "x" * 300_000, "css": "", "js": ""},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CUSTOM_CODE_TOO_LARGE"


async def test_scheduler_marks_expiring_and_expired(client, notifier):
    h = headers_for(4003)
    await client.post("/api/user/auth", headers=h, json={})

    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == 4003))
        tariff = Tariff(
            name="PRO",
            sites_limit=5,
            duration=TariffDuration.month,
            price_ton=Decimal("7"),
            kind=TariffKind.pro,
        )
        session.add(tariff)
        await session.flush()

        soon = Subscription(
            user_id=user.id, tariff_id=tariff.id, expires_at=utcnow() + timedelta(days=1)
        )
        session.add(soon)
        site = Site(
            user_id=user.id,
            type="links",
            title="Published",
            content_json={},
            status=SiteStatus.published,
        )
        session.add(site)
        await session.commit()
        soon_id, site_id = soon.id, site.id

    # первый прогон: подписка помечается как истекающая, уведомление уходит
    async with SessionLocal() as session:
        stats = await refresh_statuses(session)
        await session.commit()
    assert stats["expiring_soon"] == 1
    assert any("заканчивается" in text for _, text in notifier.sent)

    async with SessionLocal() as session:
        sub = await session.get(Subscription, soon_id)
        assert sub.status == SubscriptionStatus.expiring_soon
        sub.expires_at = utcnow() - timedelta(minutes=1)  # срок вышел
        await session.commit()

    # второй прогон: подписка истекла, сайт снят с публикации
    async with SessionLocal() as session:
        stats = await refresh_statuses(session)
        await session.commit()
    assert stats["expired"] == 1
    assert stats["unpublished"] == 1

    async with SessionLocal() as session:
        assert (await session.get(Subscription, soon_id)).status == SubscriptionStatus.expired
        assert (await session.get(Site, site_id)).status == SiteStatus.expired
    assert any("закончилась" in text for _, text in notifier.sent)


async def test_forever_subscription_never_expires(client):
    h = headers_for(4004)
    await client.post("/api/user/auth", headers=h, json={})
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == 4004))
        tariff = Tariff(
            name="Вечный",
            sites_limit=5,
            duration=TariffDuration.forever,
            price_ton=Decimal("100"),
            kind=TariffKind.pro,
        )
        session.add(tariff)
        await session.flush()
        session.add(
            Subscription(user_id=user.id, tariff_id=tariff.id, is_forever=True, expires_at=None)
        )
        await session.commit()

    async with SessionLocal() as session:
        stats = await refresh_statuses(session)
        await session.commit()
    assert stats == {"expiring_soon": 0, "expired": 0, "unpublished": 0}

    subs = await client.get("/api/subscriptions", headers=h)
    assert subs.json()[0]["is_forever"] is True
    assert subs.json()[0]["status"] == "active"


async def test_image_upload(client):
    """Картинка принимается по сигнатуре файла, а не по присланному типу."""
    import struct, zlib

    def png(width: int = 1) -> bytes:
        raw = b"\x00" + b"\xff\x00\x00" * width

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )

    h = headers_for(4010)
    resp = await client.post("/api/uploads", headers=h, files={"file": ("photo.png", png(), "image/png")})
    assert resp.status_code == 200, resp.text
    url = resp.json()["url"]
    assert resp.json()["mime"] == "image/png"

    # файл отдаётся по ссылке без авторизации — он нужен опубликованному сайту
    served = await client.get(url[url.index("/u/"):])
    assert served.status_code == 200
    assert served.content.startswith(b"\x89PNG")

    # подделанный content-type не помогает: смотрим на содержимое
    bad = await client.post(
        "/api/uploads", headers=h, files={"file": ("evil.svg", b"<svg onload=alert(1)>", "image/png")}
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "UNSUPPORTED_IMAGE"

    # без авторизации загрузка недоступна
    anon = await client.post("/api/uploads", files={"file": ("photo.png", png(), "image/png")})
    assert anon.status_code == 401
