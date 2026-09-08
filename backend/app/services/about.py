"""Блок «Об авторе проекта» (требование ТЗ).

Текст и ссылку задаёт администратор из админки, поэтому они живут в
`app_settings`, а не в коде: у автора проекта может смениться контакт, и ради
этого не должно требоваться пересобирать приложение.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting, utcnow

KEY_TITLE = "about_title"
KEY_TEXT = "about_text"
KEY_LINK_URL = "about_link_url"
KEY_LINK_LABEL = "about_link_label"

DEFAULT_TITLE = "TON Site Builder"
DEFAULT_TEXT = (
    "Конструктор мини-сайтов на доменах .ton прямо в Telegram. "
    "Соберите страницу из блоков, оплатите подписку в TON и опубликуйте её "
    "на собственном домене — без хостинга и вёрстки."
)
DEFAULT_LINK_LABEL = "Написать автору"


@dataclass(slots=True)
class About:
    title: str
    text: str
    link_url: str
    link_label: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


async def _get(session: AsyncSession, key: str, fallback: str) -> str:
    value = await session.scalar(select(AppSetting.value).where(AppSetting.key == key))
    return value if value else fallback


async def get_about(session: AsyncSession) -> About:
    return About(
        title=await _get(session, KEY_TITLE, DEFAULT_TITLE),
        text=await _get(session, KEY_TEXT, DEFAULT_TEXT),
        link_url=await _get(session, KEY_LINK_URL, ""),
        link_label=await _get(session, KEY_LINK_LABEL, DEFAULT_LINK_LABEL),
    )


async def set_about(
    session: AsyncSession,
    *,
    title: str | None = None,
    text: str | None = None,
    link_url: str | None = None,
    link_label: str | None = None,
) -> About:
    updates = {
        KEY_TITLE: title,
        KEY_TEXT: text,
        KEY_LINK_URL: link_url,
        KEY_LINK_LABEL: link_label,
    }
    for key, value in updates.items():
        if value is None:
            continue
        row = await session.get(AppSetting, key)
        if row is None:
            session.add(AppSetting(key=key, value=value))
        else:
            row.value = value
            row.updated_at = utcnow()
    await session.flush()
    return await get_about(session)
