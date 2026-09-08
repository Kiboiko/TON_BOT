"""Блок «Об авторе проекта» — публичная часть (ТЗ, раздел про автора)."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.schemas import AboutOut
from app.services.about import get_about

router = APIRouter(tags=["about"])


@router.get("/about", response_model=AboutOut)
async def about(session: SessionDep, user: CurrentUser) -> AboutOut:
    """Текст и ссылка автора. Значения задаёт админ, поэтому они не в коде."""
    return AboutOut(**(await get_about(session)).as_dict())
