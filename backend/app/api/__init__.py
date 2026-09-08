"""Сборка API-роутера. Пути ровно те, что зафиксированы в разделе 4 ТЗ."""
from fastapi import APIRouter

from app.api import about, admin, domains, sites, subscriptions, user

api_router = APIRouter()
api_router.include_router(user.router)
api_router.include_router(about.router)
api_router.include_router(sites.router)
api_router.include_router(domains.router)
api_router.include_router(subscriptions.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]
