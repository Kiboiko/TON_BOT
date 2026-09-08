"""A4 (часть 3). Привязка опубликованного контента к домену через DNS-резолвер.

Опубликованный сайт живёт в TON Storage под bag id. Чтобы домен `example.ton`
начал его отдавать, в DNS-item нужно записать категорию `storage` со значением
bag id. Запись меняет владелец домена, то есть пользователь — значит backend
только собирает тело транзакции, а подписывает её кошелёк через TON Connect.

Формат сообщения (TEP-81 / dns-item):
    change_dns_record#4eb1f0f9 query_id:uint64 key:uint256 value:(Maybe ^Cell)
    value = dns_storage_address#7473 bag_id:uint256
"""
from __future__ import annotations

import base64
import hashlib
import time

from app.core.errors import BadRequest
from app.services.subdom_client import TransactionMessage, TransactionResponse
from app.services.ton import decode_adnl_address, to_user_friendly

OP_CHANGE_DNS_RECORD = 0x4EB1F0F9
DNS_STORAGE_PREFIX = 0x7473  # "ts" — dns_storage_address
DNS_ADNL_PREFIX = 0xAD01  # dns_adnl_address
PROTO_HTTP = 0x4854  # proto_http
CATEGORY_STORAGE = "storage"
CATEGORY_SITE = "site"
# Стоимость операции: газ + возврат остатка отправителю
DEFAULT_DNS_FEE_NANO = "50000000"  # 0.05 TON


def dns_category_key(category: str) -> int:
    return int.from_bytes(hashlib.sha256(category.encode()).digest(), "big")


def build_set_storage_payload(bag_id: str, query_id: int = 0) -> str:
    """Собирает BOC тела change_dns_record с bag id, base64 для TON Connect."""
    try:
        from pytoniq_core import begin_cell
    except ImportError as exc:  # pragma: no cover - есть в requirements
        raise BadRequest(
            "pytoniq-core is required to build DNS transaction", code="DNS_BUILD_UNAVAILABLE"
        ) from exc

    bag = bag_id.strip().lower().removeprefix("0x")
    try:
        bag_int = int(bag, 16)
    except ValueError as exc:
        raise BadRequest("Invalid storage bag id", code="INVALID_BAG_ID") from exc
    if bag_int.bit_length() > 256:
        raise BadRequest("Invalid storage bag id", code="INVALID_BAG_ID")

    value_cell = begin_cell().store_uint(DNS_STORAGE_PREFIX, 16).store_uint(bag_int, 256).end_cell()
    body = (
        begin_cell()
        .store_uint(OP_CHANGE_DNS_RECORD, 32)
        .store_uint(query_id, 64)
        .store_uint(dns_category_key(CATEGORY_STORAGE), 256)
        .store_maybe_ref(value_cell)
        .end_cell()
    )
    return base64.b64encode(body.to_boc()).decode()


def build_set_storage_transaction(
    dns_item_address: str,
    bag_id: str,
    *,
    amount_nano: str = DEFAULT_DNS_FEE_NANO,
    valid_for: int = 600,
) -> TransactionResponse:
    """Транзакция «привязать bag id к домену», готовая к подписи в TON Connect."""
    if not dns_item_address:
        raise BadRequest(
            "Domain ownership is not confirmed yet: finish getting the domain first",
            code="DNS_ITEM_MISSING",
        )
    return TransactionResponse(
        valid_until=int(time.time()) + valid_for,
        messages=[
            TransactionMessage(
                # из tonapi адрес приходит сырым, а кошелёк примет только EQ…
                address=to_user_friendly(dns_item_address),
                amount=amount_nano,
                payload=build_set_storage_payload(bag_id),
            )
        ],
    )


def build_set_site_payload(adnl_address: str, query_id: int = 0) -> str:
    """BOC записи `site` — ADNL-адрес нашего rldp-http-proxy.

    Формат (TEP-81):
        dns_adnl_address#ad01 adnl_addr:bits256 flags:(## 8) proto_list:flags . 0?ProtoList
        proto_http#4854 = Protocol
    flags=1 и явный proto_http: так резолверы точно знают, что по адресу живёт
    http-сайт, а не произвольный ADNL-сервис.
    """
    try:
        from pytoniq_core import begin_cell
    except ImportError as exc:  # pragma: no cover - есть в requirements
        raise BadRequest(
            "pytoniq-core is required to build DNS transaction", code="DNS_BUILD_UNAVAILABLE"
        ) from exc

    adnl = int.from_bytes(decode_adnl_address(adnl_address), "big")
    value_cell = (
        begin_cell()
        .store_uint(DNS_ADNL_PREFIX, 16)
        .store_uint(adnl, 256)
        .store_uint(1, 8)          # flags: дальше идёт proto_list
        .store_bit(1)              # proto_list_next
        .store_uint(PROTO_HTTP, 16)
        .store_bit(0)              # proto_list_nil
        .end_cell()
    )
    body = (
        begin_cell()
        .store_uint(OP_CHANGE_DNS_RECORD, 32)
        .store_uint(query_id, 64)
        .store_uint(dns_category_key(CATEGORY_SITE), 256)
        .store_maybe_ref(value_cell)
        .end_cell()
    )
    return base64.b64encode(body.to_boc()).decode()


def build_set_site_transaction(
    dns_item_address: str,
    adnl_address: str,
    *,
    amount_nano: str = DEFAULT_DNS_FEE_NANO,
    valid_for: int = 600,
) -> TransactionResponse:
    """Транзакция «направить домен на наш TON-сайт», готовая к подписи."""
    if not dns_item_address:
        raise BadRequest(
            "Domain ownership is not confirmed yet: finish getting the domain first",
            code="DNS_ITEM_MISSING",
        )
    if not adnl_address:
        raise BadRequest("TON Site is not configured on the server", code="TON_SITE_NOT_CONFIGURED")
    return TransactionResponse(
        valid_until=int(time.time()) + valid_for,
        messages=[
            TransactionMessage(
                address=to_user_friendly(dns_item_address),
                amount=amount_nano,
                payload=build_set_site_payload(adnl_address),
            )
        ],
    )


async def direct_delivery_ready(domain: str | None) -> bool | None:
    """Указывает ли домен на наш TON-сайт. None — проверить не удалось.

    Адрес прокси не меняется от публикации к публикации, поэтому запись
    подписывается один раз на домен: повторно дёргать владельца незачем.
    """
    from app.core.config import settings
    from app.services.dns_resolver import get_resolver

    if not domain or not settings.TON_SITE_ADNL:
        return None
    try:
        ours = decode_adnl_address(settings.TON_SITE_ADNL).hex()
    except BadRequest:
        return None
    current = await get_resolver().site_adnl(domain)
    if current is None:
        return None
    return current == ours
