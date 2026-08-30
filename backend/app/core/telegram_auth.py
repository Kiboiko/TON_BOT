"""Валидация Telegram initData (A1).

Подпись initData проверяется по bot token по алгоритму Telegram Web Apps:

    secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    hash       = HMAC_SHA256(key=secret_key, msg=data_check_string)

data_check_string — все поля кроме `hash`, отсортированные по ключу,
склеенные как "k=v" через перевод строки.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl

from app.core.config import settings
from app.core.errors import Unauthorized


@dataclass(slots=True)
class TelegramUser:
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _data_check_string(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"{k}={v}" for k, v in sorted(pairs, key=lambda kv: kv[0]) if k != "hash")


def verify_init_data(
    init_data: str,
    *,
    bot_token: str | None = None,
    ttl: int | None = None,
    allow_insecure: bool | None = None,
) -> TelegramUser:
    """Проверяет подпись initData и возвращает пользователя Telegram.

    Бросает Unauthorized при любой проблеме: пустая строка, битая подпись,
    отсутствие поля user, протухший auth_date.
    """
    bot_token = bot_token if bot_token is not None else settings.TELEGRAM_BOT_TOKEN
    ttl = ttl if ttl is not None else settings.TELEGRAM_INITDATA_TTL
    allow_insecure = (
        allow_insecure if allow_insecure is not None else settings.ALLOW_INSECURE_AUTH
    )

    if not init_data:
        raise Unauthorized("Missing Telegram initData", code="INIT_DATA_MISSING")

    pairs = parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)

    if not allow_insecure:
        if not bot_token:
            raise Unauthorized("Bot token is not configured", code="INIT_DATA_INVALID")
        received_hash = data.get("hash", "")
        if not received_hash:
            raise Unauthorized("initData has no hash", code="INIT_DATA_INVALID")

        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(
            secret_key, _data_check_string(pairs).encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            raise Unauthorized("Invalid initData signature", code="INIT_DATA_INVALID")

        auth_date = data.get("auth_date")
        if ttl > 0:
            if not auth_date or not auth_date.isdigit():
                raise Unauthorized("initData has no auth_date", code="INIT_DATA_INVALID")
            if time.time() - int(auth_date) > ttl:
                raise Unauthorized("initData is expired", code="INIT_DATA_EXPIRED")

    raw_user = data.get("user")
    if not raw_user:
        raise Unauthorized("initData has no user", code="INIT_DATA_INVALID")
    try:
        user = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise Unauthorized("initData user is malformed", code="INIT_DATA_INVALID") from exc

    tg_id = user.get("id")
    if not isinstance(tg_id, int):
        raise Unauthorized("initData user has no id", code="INIT_DATA_INVALID")

    return TelegramUser(
        id=tg_id,
        username=user.get("username"),
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        language_code=user.get("language_code"),
        raw=user,
    )


def build_init_data(bot_token: str, user: dict[str, Any], auth_date: int | None = None) -> str:
    """Собирает подписанную строку initData — используется в тестах и мок-режиме."""
    from urllib.parse import urlencode

    payload = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAAAAAAAAAAAAAAA",
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    }
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    dcs = _data_check_string(list(payload.items()))
    payload["hash"] = hmac.new(secret_key, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)
