"""A6. Уведомления пользователю в Telegram.

Сервис знает только события домена (сайт опубликован, подписка истекает и т.д.),
а как именно доставляется сообщение — забота транспорта. В боевом режиме это
aiogram-бот, в тестах — заглушка, собирающая отправленное в список.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from app.core.config import settings
from app.models import Language

log = logging.getLogger(__name__)

# Telegram может не ответить; задача публикации ждать его не обязана
SEND_TIMEOUT = 15.0


MESSAGES: dict[str, dict[str, str]] = {
    "site_published": {
        "ru": "✅ Сайт «{title}» опубликован{domain}.",
        "en": "✅ Site “{title}” is published{domain}.",
    },
    "publish_error": {
        "ru": "⚠️ Не удалось опубликовать сайт «{title}».\nПричина: {error}\nПопробуйте ещё раз или напишите в поддержку.",
        "en": "⚠️ Failed to publish site “{title}”.\nReason: {error}\nPlease try again or contact support.",
    },
    "dns_bind_required": {
        "ru": "🔗 Сайт «{title}» загружен в TON Storage. Осталось подписать привязку домена в приложении.",
        "en": "🔗 Site “{title}” is uploaded to TON Storage. One signature left to bind the domain.",
    },
    "subscription_activated": {
        "ru": "🎉 Подписка «{tariff}» активна{until}.",
        "en": "🎉 Subscription “{tariff}” is active{until}.",
    },
    "subscription_expiring": {
        "ru": "⏳ Подписка «{tariff}» заканчивается {date}. Продлите её, чтобы сайт остался опубликованным.",
        "en": "⏳ Subscription “{tariff}” expires on {date}. Renew it to keep your site online.",
    },
    "subscription_expired": {
        "ru": "🔕 Подписка «{tariff}» закончилась. Сайты сняты с публикации до продления.",
        "en": "🔕 Subscription “{tariff}” has expired. Your sites are unpublished until renewal.",
    },
    "trial_started": {
        "ru": "🎁 Первый сайт опубликован бесплатно на {days} дней. Дальше — по подписке.",
        "en": "🎁 Your first site is free for {days} days. After that a subscription is required.",
    },
    "access_granted": {
        "ru": "🔓 Администратор выдал вам доступ: «{tariff}»{until}.",
        "en": "🔓 An admin granted you access: “{tariff}”{until}.",
    },
    "access_revoked": {
        "ru": "🔒 Администратор отозвал доступ «{tariff}».",
        "en": "🔒 An admin revoked access “{tariff}”.",
    },
}


class NotificationTransport(Protocol):
    async def send(self, telegram_id: int, text: str) -> bool: ...

    async def close(self) -> None: ...


class AiogramTransport:
    def __init__(self, token: str | None = None) -> None:
        self._token = token if token is not None else settings.TELEGRAM_BOT_TOKEN
        self._bot: Any = None

    async def _get_bot(self) -> Any:
        if self._bot is None:
            from aiogram import Bot
            from aiogram.client.default import DefaultBotProperties
            from aiogram.enums import ParseMode

            self._bot = Bot(
                token=self._token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
        return self._bot

    async def send(self, telegram_id: int, text: str) -> bool:
        if not self._token:
            log.warning("notification skipped: TELEGRAM_BOT_TOKEN is empty")
            return False

        try:
            bot = await self._get_bot()
            # без таймаута зависшее соединение с Telegram останавливает воркер:
            # публикация уже сделана, но задача не завершается
            await asyncio.wait_for(
                bot.send_message(chat_id=telegram_id, text=text), timeout=SEND_TIMEOUT
            )
            return True
        except asyncio.TimeoutError:
            log.warning("cannot notify %s: Telegram did not answer in %ss", telegram_id, SEND_TIMEOUT)
            return False
        except Exception as exc:  # noqa: BLE001 - уведомление никогда не важнее самой задачи
            # пользователь мог не запускать бота или заблокировать его — это не ошибка системы
            log.warning("cannot notify %s: %s", telegram_id, exc)
            return False

    async def close(self) -> None:
        if self._bot is not None:
            await self._bot.session.close()
            self._bot = None


class NullTransport:
    """Заглушка: копит отправленное, ничего не шлёт (тесты, окружение без бота)."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send(self, telegram_id: int, text: str) -> bool:
        self.sent.append((telegram_id, text))
        return True

    async def close(self) -> None:
        return None


_transport: NotificationTransport | None = None


def get_transport() -> NotificationTransport:
    global _transport
    if _transport is None:
        _transport = AiogramTransport() if settings.TELEGRAM_BOT_TOKEN else NullTransport()
    return _transport


def set_transport(transport: NotificationTransport | None) -> None:
    global _transport
    _transport = transport


async def close_transport() -> None:
    global _transport
    if _transport is not None:
        await _transport.close()
        _transport = None


def render(event: str, language: Language | str = Language.ru, **params: Any) -> str:
    lang = language.value if isinstance(language, Language) else str(language or "ru")
    template = MESSAGES.get(event, {}).get(lang) or MESSAGES.get(event, {}).get("ru") or event
    try:
        return template.format(**params)
    except KeyError:
        return template


async def notify(
    telegram_id: int, event: str, language: Language | str = Language.ru, **params: Any
) -> bool:
    """Отправляет пользователю уведомление о событии системы."""
    text = render(event, language, **params)
    return await get_transport().send(telegram_id, text)
