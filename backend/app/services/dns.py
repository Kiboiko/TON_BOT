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

OP_CHANGE_DNS_RECORD = 0x4EB1F0F9
DNS_STORAGE_PREFIX = 0x7473  # "ts" — dns_storage_address
CATEGORY_STORAGE = "storage"
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
        raise BadRequest("Site has no DNS item address", code="DNS_ITEM_MISSING")
    return TransactionResponse(
        valid_until=int(time.time()) + valid_for,
        messages=[
            TransactionMessage(
                address=dns_item_address,
                amount=amount_nano,
                payload=build_set_storage_payload(bag_id),
            )
        ],
    )
