"""A6. Telegram-бот (aiogram 3.x).

Две задачи:
* точка входа в Mini App (/start с кнопкой запуска);
* транспорт уведомлений — их шлёт `app.services.notifications`, бот лишь держит
  сессию и обрабатывает команды.

Запуск: python -m app.bot.main
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Site, SiteStatus, User

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("bot")

dp = Dispatcher()

TEXTS = {
    "ru": {
        "start": (
            "<b>TON Site Builder</b>\n\n"
            "Соберите мини-сайт и опубликуйте его на домене .ton — прямо из Telegram.\n"
            "Первый сайт бесплатно на {days} дней."
        ),
        "open": "🚀 Открыть конструктор",
        "help": (
            "Команды:\n"
            "/start — открыть конструктор\n"
            "/sites — мои сайты\n"
            "/help — эта справка"
        ),
        "no_sites": "У вас пока нет сайтов. Откройте конструктор и создайте первый.",
        "sites": "Ваши сайты:",
    },
    "en": {
        "start": (
            "<b>TON Site Builder</b>\n\n"
            "Build a mini-site and publish it on a .ton domain — right from Telegram.\n"
            "The first site is free for {days} days."
        ),
        "open": "🚀 Open builder",
        "help": "Commands:\n/start — open builder\n/sites — my sites\n/help — this help",
        "no_sites": "You have no sites yet. Open the builder and create your first one.",
        "sites": "Your sites:",
    },
}

STATUS_ICON = {
    SiteStatus.draft: "📝",
    SiteStatus.publishing: "⏳",
    SiteStatus.published: "✅",
    SiteStatus.publish_error: "⚠️",
    SiteStatus.expired: "🔕",
}


def _kb(lang: str) -> InlineKeyboardMarkup | None:
    if not settings.MINI_APP_URL:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=TEXTS[lang]["open"], web_app=WebAppInfo(url=settings.MINI_APP_URL)
                )
            ]
        ]
    )


async def _lang(telegram_id: int, fallback: str | None) -> str:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is not None:
            return user.language.value
    return "ru" if (fallback or "ru").startswith("ru") else "en"


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    lang = await _lang(message.from_user.id, message.from_user.language_code)
    await message.answer(
        TEXTS[lang]["start"].format(days=settings.TRIAL_DAYS), reply_markup=_kb(lang)
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    lang = await _lang(message.from_user.id, message.from_user.language_code)
    await message.answer(TEXTS[lang]["help"], reply_markup=_kb(lang))


@dp.message(Command("sites"))
async def cmd_sites(message: Message) -> None:
    lang = await _lang(message.from_user.id, message.from_user.language_code)
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        sites = []
        if user is not None:
            rows = await session.scalars(
                select(Site).where(Site.user_id == user.id).order_by(Site.created_at.desc())
            )
            sites = rows.all()

    if not sites:
        await message.answer(TEXTS[lang]["no_sites"], reply_markup=_kb(lang))
        return

    lines = [TEXTS[lang]["sites"]]
    for site in sites:
        domain = f" — <code>{site.domain}</code>" if site.domain else ""
        lines.append(f"{STATUS_ICON.get(site.status, '•')} {site.title}{domain}")
    await message.answer("\n".join(lines), reply_markup=_kb(lang))


@dp.message(F.text)
async def fallback(message: Message) -> None:
    lang = await _lang(message.from_user.id, message.from_user.language_code)
    await message.answer(TEXTS[lang]["help"], reply_markup=_kb(lang))


async def run() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    log.info("bot polling started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
