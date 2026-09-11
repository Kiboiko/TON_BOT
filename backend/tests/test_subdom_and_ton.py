"""A2/A3: изоляция subdom API и блокчейн-проверки."""
from __future__ import annotations

import base64
import time
from decimal import Decimal

import httpx
import pytest
from nacl.signing import SigningKey

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.errors import SubdomError
from app.models import User
from app.services.zone import set_zone
from app.services.subdom_client import DomainService, FakeDomainService, SubdomHttpClient
from app.services.ton import (
    MockTonClient,
    TxInfo,
    build_ton_proof_message,
    from_nano,
    normalize_address,
    same_address,
    to_nano,
    verify_payment,
    verify_ton_proof,
)


def test_fake_service_satisfies_interface():
    assert isinstance(FakeDomainService(), DomainService)
    assert isinstance(SubdomHttpClient(), DomainService)


async def test_subdom_client_normalizes_transaction():
    """Тело транзакции пробрасывается наверх без изменений, поля — нормализуются."""

    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["query"] = str(request.url.query.decode())
        # реальный ответ subdom: объект без обёртки
        return httpx.Response(
            200,
            json={
                "validUntil": 1900000000,
                "messages": [{"address": "EQAbc", "amount": "50000000", "payload": "te6ccg"}],
            },
        )

    transport = httpx.MockTransport(handler)
    client = SubdomHttpClient(client=httpx.AsyncClient(transport=transport, base_url="http://x"))
    tx = await client.deploy_proxy_zone("EQDns", "mysite", "EQWallet", "ton")

    # путь и имена параметров — как в схеме сервиса
    assert seen["path"] == "/api/v1/deploy-proxy-zone"
    assert "dns_item_address=EQDns" in seen["query"]
    assert "user_wallet_address=EQWallet" in seen["query"]

    assert tx.valid_until == 1900000000
    assert tx.to_tonconnect() == {
        "validUntil": 1900000000,
        "messages": [{"address": "EQAbc", "amount": "50000000", "payload": "te6ccg"}],
    }


async def test_subdom_client_retries_on_5xx_then_succeeds():
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(
            200, json={"validUntil": 123, "messages": [{"address": "EQ", "amount": "1"}]}
        )

    client = SubdomHttpClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x"),
        retries=3,
    )
    tx = await client.start_auction("EQColl", "name")
    assert calls["n"] == 3
    assert tx.messages[0].address == "EQ"


async def test_subdom_client_raises_domain_error_on_persistent_failure():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = SubdomHttpClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x"),
        retries=2,
    )
    with pytest.raises(SubdomError) as exc:
        await client.claim_subdomain("EQItem")
    assert exc.value.status_code == 502
    assert exc.value.to_dict()["error"]["code"] == "SUBDOM_ERROR"


async def test_subdom_bad_response_is_reported():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"something": "else"})

    client = SubdomHttpClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    )
    with pytest.raises(SubdomError):
        await client.mint_sbt_subdomain("EQColl", "name")


def test_address_normalization():
    raw = "0:" + "ab" * 32
    assert normalize_address(raw) == raw
    assert same_address(raw, raw.upper().replace("0:", "0:"))
    assert not same_address(raw, "0:" + "cd" * 32)
    assert not same_address(None, raw)


def test_nano_conversion():
    assert to_nano(Decimal("1.5")) == 1_500_000_000
    assert from_nano(2_000_000_000) == Decimal("2")


async def test_verify_payment_checks_amount_and_destination():
    treasury = "0:" + "11" * 32
    client = MockTonClient()
    client.add(
        TxInfo(
            tx_hash="h1",
            source="0:" + "22" * 32,
            destination=treasury,
            value_nano=to_nano("5"),
            comment="tsb-1",
            utime=int(time.time()),
        )
    )

    ok = await verify_payment(
        tx_hash="h1", destination=treasury, min_amount=Decimal("5"), comment="tsb-1", client=client
    )
    assert ok.ok

    low = await verify_payment(
        tx_hash="h1", destination=treasury, min_amount=Decimal("6"), comment="tsb-1", client=client
    )
    assert not low.ok

    wrong_dest = await verify_payment(
        tx_hash="h1",
        destination="0:" + "99" * 32,
        min_amount=Decimal("5"),
        comment="tsb-1",
        client=client,
    )
    assert not wrong_dest.ok

    missing = await verify_payment(
        tx_hash="nope", destination=treasury, min_amount=Decimal("5"), comment="tsb-x", client=client
    )
    assert not missing.ok
    assert "not found" in (missing.reason or "")


def test_ton_proof_digest_matches_spec():
    """Дайджест считается независимо по формуле из спецификации TON Connect.

    Раньше тест подписывал той же функцией, которую и проверял, поэтому не заметил
    пропущенный внешний sha256 — настоящие кошельки при этом не проходили.
    """
    import hashlib

    address = "0:" + "5c" * 32
    domain, payload, ts = "example.com", "nonce-1", 1700000000

    message = (
        b"ton-proof-item-v2/"
        + (0).to_bytes(4, "big", signed=True)
        + bytes.fromhex("5c" * 32)
        + len(domain.encode()).to_bytes(4, "little")
        + domain.encode()
        + ts.to_bytes(8, "little")
        + payload.encode()
    )
    expected = hashlib.sha256(
        bytes([0xFF, 0xFF]) + b"ton-connect" + hashlib.sha256(message).digest()
    ).digest()

    assert build_ton_proof_message(address, domain, ts, payload) == expected
    assert len(expected) == 32


async def test_ton_proof_signature_roundtrip():
    """Валидная подпись принимается, любая подмена — отвергается."""
    key = SigningKey.generate()
    address = "0:" + "33" * 32
    domain = "test.local"
    payload = "nonce-123"
    ts = int(time.time())

    client = MockTonClient()
    client.public_keys[normalize_address(address)] = bytes(key.verify_key)

    message = build_ton_proof_message(address, domain, ts, payload)
    signature = base64.b64encode(key.sign(message).signature).decode()

    assert await verify_ton_proof(
        address, ts, domain, signature, payload, allowed_domain=domain, client=client
    )
    # чужой домен
    assert not await verify_ton_proof(
        address, ts, "evil.local", signature, payload, allowed_domain=domain, client=client
    )
    # другой payload — подпись перестаёт совпадать
    assert not await verify_ton_proof(
        address, ts, domain, signature, "other-nonce", allowed_domain=domain, client=client
    )
    # протухший timestamp
    assert not await verify_ton_proof(
        address, ts - 100000, domain, signature, payload, allowed_domain=domain, client=client
    )
    # неизвестный кошелёк (публичный ключ недоступен)
    assert not await verify_ton_proof(
        "0:" + "44" * 32, ts, domain, signature, payload, allowed_domain=domain, client=client
    )


def test_boc_is_not_mistaken_for_tx_hash():
    """TON Connect возвращает BOC, а не хэш: по нему в блокчейн ходить нельзя."""
    from app.services.ton import looks_like_tx_hash

    assert looks_like_tx_hash("a" * 64)
    assert looks_like_tx_hash("hR1n8/1XCJ8mFo2xzKQ5eTLRPaOBBk1J5xQZLBGm0Uo=")
    assert not looks_like_tx_hash("te6cckEBAQEAAgAAAA==")  # короткий BOC
    assert not looks_like_tx_hash("te6cckEBAgEA" + "A" * 400)  # длинный BOC
    assert not looks_like_tx_hash("")
    assert not looks_like_tx_hash(None)


async def test_lookup_by_boc_does_not_break_verification():
    """422 от TON API на непохожую на хэш строку не должен ронять проверку платежа."""
    import httpx as _httpx
    from decimal import Decimal as _D
    from app.services.ton import ToncenterClient, verify_payment

    async def handler(request):
        return _httpx.Response(422, json={"error": "invalid hash"})

    client = ToncenterClient(
        client=_httpx.AsyncClient(transport=_httpx.MockTransport(handler), base_url="http://x")
    )
    treasury = "0:" + "11" * 32
    result = await verify_payment(
        tx_hash="te6cckEBAQEAAgAAAA==" + "A" * 300,
        destination=treasury,
        min_amount=_D("1"),
        comment="tsb-none",
        client=client,
    )
    assert result.ok is False
    assert "not found" in (result.reason or "")


async def test_ton_api_outage_is_retryable_not_fatal():
    """Сбой TON API — «пока не подтверждено», а не 502: фронт продолжит опрашивать."""
    import httpx as _httpx
    from decimal import Decimal as _D
    from app.services.ton import ToncenterClient, verify_payment

    async def handler(request):
        return _httpx.Response(500, json={"error": "upstream is down"})

    client = ToncenterClient(
        client=_httpx.AsyncClient(transport=_httpx.MockTransport(handler), base_url="http://x")
    )
    result = await verify_payment(
        tx_hash="a" * 64,
        destination="0:" + "11" * 32,
        min_amount=_D("1"),
        comment="tsb-none",
        client=client,
    )
    assert result.ok is False
    assert "yet" in (result.reason or "")


def _wallet_state_init(public_key: bytes, v5: bool) -> str:
    """Собирает state_init кошелька: code + data в раскладке v3/v4 или W5."""
    from pytoniq_core import begin_cell

    code = begin_cell().store_uint(0xDEAD, 16).end_cell()  # содержимое кода не важно
    data = begin_cell()
    if v5:
        data = data.store_bit_int(1)  # is_signature_allowed у W5
    data = data.store_uint(0, 32).store_uint(698983191, 32).store_bytes(public_key)
    state_init = (
        begin_cell()
        .store_uint(0, 2)          # split_depth, special — оба отсутствуют
        .store_bit_int(1)          # есть code
        .store_bit_int(1)          # есть data
        .store_bit_int(0)          # library отсутствует
        .store_ref(code)
        .store_ref(data.end_cell())
        .end_cell()
    )
    return base64.b64encode(state_init.to_boc()).decode(), state_init.hash.hex()


@pytest.mark.parametrize("v5", [False, True], ids=["кошелёк v4", "кошелёк W5"])
async def test_ton_proof_works_for_undeployed_wallet(v5: bool):
    """Незадеплоенный кошелёк: ключ берётся из state_init, обе раскладки данных."""
    from app.services.ton import pubkeys_from_state_init

    key = SigningKey.generate()
    state_init, addr_hash = _wallet_state_init(bytes(key.verify_key), v5)
    address = f"0:{addr_hash}"
    domain, payload, ts = "test.local", "nonce-xyz", int(time.time())

    assert bytes(key.verify_key) in pubkeys_from_state_init(state_init, address)

    signature = base64.b64encode(
        key.sign(build_ton_proof_message(address, domain, ts, payload)).signature
    ).decode()

    client = MockTonClient()  # в сети кошелька нет — get_public_key вернёт None
    assert await verify_ton_proof(
        address, ts, domain, signature, payload,
        state_init=state_init, allowed_domain=domain, client=client,
    )

    # чужая подпись не проходит даже с валидным state_init
    other = SigningKey.generate()
    bad = base64.b64encode(
        other.sign(build_ton_proof_message(address, domain, ts, payload)).signature
    ).decode()
    assert not await verify_ton_proof(
        address, ts, domain, bad, payload,
        state_init=state_init, allowed_domain=domain, client=client,
    )


def test_dns_bind_address_is_user_friendly():
    """TON Connect принимает только EQ…/UQ…: сырой адрес кошелёк отвергает.

    Из tonapi адрес DNS-item приходит сырым, и на проде кошелёк отвечал
    «Wrong 'address' format in message at index 0».
    """
    from app.services.dns import build_set_storage_transaction

    raw = "0:dd3a6b455eeb887660a43bee729f5337733c6d051c0466402618b73ed86e3b05"
    tx = build_set_storage_transaction(raw, "A" * 64)
    address = tx.messages[0].address

    assert address.startswith("EQ")
    assert len(address) == 48
    assert ":" not in address

    # уже user-friendly адрес не портим
    same = build_set_storage_transaction(address, "A" * 64)
    assert same.messages[0].address == address


def test_storage_cli_error_shows_real_reason():
    """Настоящая ошибка демона лежит в stdout, а stderr забит служебным логом."""
    from app.services.storage import clean_cli_output

    noise = (
        "\x1b[1;36m[ 3][t 0][2026-09-07 19:22:15][storage-daemon-cli.cpp:229]"
        "[!extclient]\tConnected\x1b[0m"
    )
    assert clean_cli_output(noise) == ""

    real = noise + "\nQuery error: Cannot add torrent: duplicate hash " + "A" * 64
    assert clean_cli_output(real) == "Query error: Cannot add torrent: duplicate hash " + "A" * 64


async def test_republish_without_changes_is_not_an_error(tmp_path):
    """Публикация сайта без изменений даёт тот же bag: демон отказывает, мы — нет."""
    from app.core.errors import StorageError
    from app.services.storage import StorageDaemonBackend

    bag = "890C67A47046D99A993B1B1237FF6FF47B5E15C86CBFA70B26DB08E62CB93F5C"
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text("<html></html>", encoding="utf-8")

    backend = StorageDaemonBackend()

    async def duplicate(_command: str) -> str:
        raise StorageError(
            f"storage-daemon-cli failed: Query error: Cannot add torrent: duplicate hash {bag}"
        )

    backend._run = duplicate  # noqa: SLF001 - подменяем вызов CLI
    info = await backend.upload_directory(site_dir)
    assert info.bag_id == bag
    assert info.files == 1


# ---------------------------------------------------- TON Site (запись `site`)
def test_adnl_address_roundtrip():
    """Адрес .adnl декодируется в те же 32 байта, что печатает generate-random-id."""
    from app.services.ton import decode_adnl_address

    addr = "wi22d76kj67rstlzgihzurd5y4x2fmm5ymzsweteizwn7ty7xwwuhqm"
    assert (
        decode_adnl_address(addr).hex().upper()
        == "91AD0FFE527DF8CA6BC9907CD223EE397D158CEE19995893223366FE78FDED6A"
    )


def test_adnl_address_rejects_broken_checksum():
    """Опечатка в адресе не должна уехать в DNS-запись домена."""
    from app.core.errors import BadRequest
    from app.services.ton import decode_adnl_address

    for bad in ("", "short", "wi22d76kj67rstlzgihzurd5y4x2fmm5ymzsweteizwn7ty7xwwuhq0"):
        with pytest.raises(BadRequest):
            decode_adnl_address(bad)


def test_site_record_matches_tep81():
    """dns_adnl_address#ad01 adnl_addr:bits256 flags:(## 8) proto_list:flags . 0?ProtoList."""
    import base64

    from pytoniq_core import Cell

    from app.services.dns import CATEGORY_SITE, build_set_site_payload, dns_category_key

    addr = "wi22d76kj67rstlzgihzurd5y4x2fmm5ymzsweteizwn7ty7xwwuhqm"
    body = Cell.one_from_boc(base64.b64decode(build_set_site_payload(addr))).begin_parse()
    assert body.load_uint(32) == 0x4EB1F0F9      # change_dns_record
    assert body.load_uint(64) == 0
    assert body.load_uint(256) == dns_category_key(CATEGORY_SITE)

    value = body.load_maybe_ref().begin_parse()
    assert value.load_uint(16) == 0xAD01         # dns_adnl_address
    assert value.load_uint(256) == int.from_bytes(
        bytes.fromhex("91AD0FFE527DF8CA6BC9907CD223EE397D158CEE19995893223366FE78FDED6A"), "big"
    )
    assert value.load_uint(8) == 1               # flags: дальше proto_list
    assert value.load_bit() == 1                 # proto_list_next
    assert value.load_uint(16) == 0x4854         # proto_http
    assert value.load_bit() == 0                 # proto_list_nil


async def test_site_bind_needs_published_site(client):
    """Пока сайт не опубликован, направлять на него домен нечем."""
    from tests.conftest import headers_for

    h = headers_for(7701)
    await client.post("/api/user/auth", headers=h, json={})
    site_id = (
        await client.post("/api/sites", headers=h, json={"type": "visitka", "title": "S"})
    ).json()["site"]["id"]

    resp = await client.post(f"/api/sites/{site_id}/site-bind", headers=h)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SITE_NOT_PUBLISHED"


async def test_subdomain_confirmed_via_collection_when_dns_index_blind(client, resolver):
    """Оплаченный субдомен подтверждается, даже если DNS-индекс его не видит.

    tonapi не индексирует субдомены сторонних коллекций: свежий субдомен там
    отвечает 404 и выглядит свободным, хотя NFT уже выпущен и оплачен. Раньше
    из-за этого подтверждение вечно отвечало pending, домен не закреплялся, а
    вместе с ним не появлялся адрес DNS-item — и привязать домен было нечем.
    """
    from tests.conftest import headers_for

    h = headers_for(7801)
    await client.post("/api/user/auth", headers=h, json={})
    wallet = "0:" + "7" * 64
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == 7801))
        user.wallet_address = wallet
        await session.commit()
        await set_zone(
            session,
            domain="tonsite.ton",
            dns_item_address="0:" + "ab" * 32,
            collection_address="0:" + "cd" * 32,
            mode="sbt",
        )
        await session.commit()

    site_id = (
        await client.post("/api/sites", headers=h, json={"type": "visitka", "title": "S"})
    ).json()["site"]["id"]

    claim = await client.post(
        "/api/domains/claim", headers=h, json={"site_id": site_id, "name": "shop"}
    )
    assert claim.status_code == 200, claim.text

    # NFT выпущен и принадлежит пользователю, но DNS-индекс его «не видит»
    resolver.own("shop.tonsite.ton", wallet, item_address="0:" + "ef" * 32)
    resolver.dns_index_blind = True

    confirmed = await client.post(
        "/api/domains/confirm",
        headers=h,
        json={"site_id": site_id, "tx_hash": "boc-onchain", "domain": "shop.tonsite.ton"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "publishing"

    site = (await client.get(f"/api/sites/{site_id}", headers=h)).json()["site"]
    assert site["domain"] == "shop.tonsite.ton"
    assert site["dns_item_address"] == "0:" + "ef" * 32


def test_real_resolver_implements_full_interface():
    """Боевой резолвер обязан уметь всё, что объявлено в интерфейсе.

    Тесты гоняют заглушку, поэтому метод, забытый в TonApiResolver, всплыл бы
    только на боевом — как и случилось с find_subdomain.
    """
    from app.services.dns_resolver import DomainResolver, FakeResolver, TonApiResolver

    required = [n for n in dir(DomainResolver) if not n.startswith("_")]
    assert required, "интерфейс не должен быть пустым"
    for impl in (TonApiResolver, FakeResolver):
        missing = [n for n in required if not callable(getattr(impl, n, None))]
        assert not missing, f"{impl.__name__} не реализует: {missing}"


async def test_claim_does_not_charge_twice_for_owned_subdomain(client, resolver):
    """Повторное «получить» не берёт денег, если субдомен уже выпущен.

    Кошелёк отдаёт ошибку и после успешной отправки транзакции, поэтому
    пользователь жмёт кнопку ещё раз. Раньше это упиралось в 409 DOMAIN_TAKEN:
    имя занято, а чьё — резолвер не знает. Домен оставался неприкреплённым,
    хотя NFT уже оплачен.
    """
    from tests.conftest import headers_for

    h = headers_for(7901)
    await client.post("/api/user/auth", headers=h, json={})
    wallet = "0:" + "9" * 64
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == 7901))
        user.wallet_address = wallet
        await session.commit()
        await set_zone(
            session,
            domain="tonsite.ton",
            dns_item_address="0:" + "ab" * 32,
            collection_address="0:" + "cd" * 32,
            mode="sbt",
        )
        await session.commit()

    site_id = (
        await client.post("/api/sites", headers=h, json={"type": "landing", "title": "L"})
    ).json()["site"]["id"]

    # NFT выпущен на кошелёк пользователя, но DNS-индекс имя не показывает
    resolver.own("promo.tonsite.ton", wallet, item_address="0:" + "ee" * 32)
    resolver.dns_index_blind = True

    # проверка имени говорит «занято», но владельцем показывает самого пользователя
    check = await client.get("/api/domains/check?name=promo", headers=h)
    assert check.status_code == 200
    assert check.json()["available"] is False
    assert check.json()["owner"] == wallet

    again = await client.post(
        "/api/domains/claim", headers=h, json={"site_id": site_id, "name": "promo"}
    )
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["already_owned"] is True
    assert body["transaction"] is None, "второй раз платить не за что"

    site = (await client.get(f"/api/sites/{site_id}", headers=h)).json()["site"]
    assert site["domain"] == "promo.tonsite.ton"
    assert site["dns_item_address"] == "0:" + "ee" * 32


async def test_broken_utf8_in_toncenter_response_does_not_break_payments():
    """Зашифрованный комментарий в истории кошелька не должен ронять проверку платежей.

    toncenter кладёт сырые байты такого комментария в поле message, и ответ
    перестаёт быть корректным UTF-8. Раньше разбор падал с UnicodeDecodeError,
    и на этот кошелёк не подтверждался ни один платёж — ни подписка, ни свой код.
    """
    import httpx as _httpx
    import json as _json
    from decimal import Decimal as _D
    from app.services.ton import ToncenterClient, verify_payment

    treasury = "0:" + "11" * 32
    now = int(time.time())
    payload = {
        "ok": True,
        "result": [
            {
                "utime": now,
                "transaction_id": {"hash": "encrypted-hash"},
                "in_msg": {
                    "source": "0:" + "22" * 32,
                    "destination": treasury,
                    "value": "20000000",
                    "message": "BROKEN_BYTES",
                    "msg_data": {"@type": "msg.dataEncryptedText"},
                },
            },
            {
                "utime": now,
                "transaction_id": {"hash": "paid-hash"},
                "in_msg": {
                    "source": "0:" + "33" * 32,
                    "destination": treasury,
                    "value": "200000000",
                    "message": "tsb-paid",
                    "msg_data": {"@type": "msg.dataText"},
                },
            },
        ],
    }
    # байты не из UTF-8 — ровно то, что приходит в ответе на зашифрованный комментарий
    body = _json.dumps(payload).encode().replace(b"BROKEN_BYTES", bytes([0x95, 0xFA, 0x0C, 0xFF]))

    async def handler(request):
        return _httpx.Response(200, content=body, headers={"Content-Type": "application/json"})

    client = ToncenterClient(
        client=_httpx.AsyncClient(transport=_httpx.MockTransport(handler), base_url="http://x")
    )
    result = await verify_payment(
        tx_hash="a" * 64,
        destination=treasury,
        min_amount=_D("0.2"),
        comment="tsb-paid",
        client=client,
    )
    assert result.ok is True
    assert result.tx is not None and result.tx.tx_hash == "paid-hash"
