"""A2/A3: изоляция subdom API и блокчейн-проверки."""
from __future__ import annotations

import base64
import time
from decimal import Decimal

import httpx
import pytest
from nacl.signing import SigningKey

from app.core.errors import SubdomError
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

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transaction": {
                    "validUntil": 1900000000,
                    "messages": [
                        {"address": "EQAbc", "amount": "50000000", "payload": "te6ccg"},
                    ],
                }
            },
        )

    transport = httpx.MockTransport(handler)
    client = SubdomHttpClient(client=httpx.AsyncClient(transport=transport, base_url="http://x"))
    tx = await client.deploy_proxy_zone("EQDns", "mysite", "EQWallet", "ton")

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
