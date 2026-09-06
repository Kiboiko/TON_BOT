"""Проверка занятости домена и субдомена в сети TON.

У subdom API проверки доступности имени нет — она делается резолвом домена в
блокчейне. Модуль изолирован так же, как subdom_client: наружу торчит интерфейс
`DomainResolver` в наших типах, поэтому смена провайдера правит один файл.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

# 3–126 символов: латиница в нижнем регистре, цифры и дефис (правила TON DNS)
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,125}$")


@dataclass(slots=True)
class DomainInfo:
    domain: str
    available: bool
    status: str
    item_address: str | None = None
    owner: str | None = None
    expires_at: int | None = None


def is_valid_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch((name or "").strip().lower()))


class DomainResolver(Protocol):
    async def resolve(self, domain: str) -> DomainInfo: ...

    async def contract_deployed(self, address: str) -> bool | None: ...

    async def close(self) -> None: ...


class TonApiResolver:
    """Резолвер поверх tonapi.io.

    Домен, которого нет в блокчейне, отдаётся ответом 404 — это и означает,
    что имя свободно. Ошибку сети наверх не превращаем в «свободно»: лучше
    честно сказать, что проверить не удалось, чем позволить занять чужое имя.
    """

    def __init__(self, base_url: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = (base_url or settings.TON_DNS_API).rstrip("/")
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=20.0)
        return self._client

    async def resolve(self, domain: str) -> DomainInfo:
        domain = domain.strip().lower()
        client = await self._get_client()
        try:
            resp = await client.get(f"/v2/dns/{domain}")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            log.warning("dns resolve %s failed: %s", domain, exc)
            return DomainInfo(domain=domain, available=False, status="unknown")

        if resp.status_code == 404:
            return DomainInfo(domain=domain, available=True, status="free")
        if resp.status_code >= 400:
            log.warning("dns resolve %s -> %s", domain, resp.status_code)
            return DomainInfo(domain=domain, available=False, status="unknown")

        try:
            data = resp.json()
        except ValueError:
            return DomainInfo(domain=domain, available=False, status="unknown")

        item = data.get("item") or {}
        owner = (item.get("owner") or {}).get("address")
        return DomainInfo(
            domain=domain,
            available=False,
            status="taken",
            item_address=item.get("address"),
            owner=owner,
            expires_at=data.get("expiring_at"),
        )

    async def contract_deployed(self, address: str) -> bool | None:
        """Есть ли контракт по адресу. None — проверить не удалось.

        Нужна перед включением зоны: адрес коллекции известен заранее (он
        выводится из транзакции разворота), но пока она не развёрнута, включать
        зону нельзя — пользователи получили бы субдомены в пустоту.
        """
        client = await self._get_client()
        try:
            resp = await client.get(f"/v2/accounts/{address}")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            log.warning("account check %s failed: %s", address, exc)
            return None
        if resp.status_code >= 400:
            log.warning("account check %s -> %s", address, resp.status_code)
            return None
        try:
            status = str(resp.json().get("status") or "")
        except ValueError:
            return None
        return status not in {"nonexist", "uninit"}

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class FakeResolver:
    """Заглушка для dev и тестов: занятыми считаются имена, начинающиеся на `taken`."""

    FAKE_ITEM = "0:" + "11" * 32

    def __init__(self) -> None:
        self.calls: list[str] = []
        # домены, «купленные» в тесте: адрес -> владелец
        self.owned: dict[str, str] = {}
        # контракты: адрес -> есть ли он в сети. По умолчанию считаем, что есть,
        # а тесты про неразвёрнутую зону выставляют False явно
        self.deployed: dict[str, bool | None] = {}

    def own(self, domain: str, owner: str, item_address: str | None = None) -> None:
        self.owned[domain.strip().lower()] = owner
        if item_address:
            self.FAKE_ITEM = item_address

    async def resolve(self, domain: str) -> DomainInfo:
        domain = domain.strip().lower()
        self.calls.append(domain)
        if domain in self.owned:
            return DomainInfo(
                domain=domain,
                available=False,
                status="taken",
                item_address=self.FAKE_ITEM,
                owner=self.owned[domain],
            )
        taken = domain.split(".")[0].startswith("taken")
        return DomainInfo(
            domain=domain,
            available=not taken,
            status="taken" if taken else "free",
            item_address=self.FAKE_ITEM if taken else None,
            owner=self.FAKE_ITEM if taken else None,
        )

    async def contract_deployed(self, address: str) -> bool | None:
        return self.deployed.get(address, True)

    async def close(self) -> None:
        return None


_resolver: DomainResolver | None = None


def get_resolver() -> DomainResolver:
    global _resolver
    if _resolver is None:
        _resolver = FakeResolver() if settings.SUBDOM_MODE == "fake" else TonApiResolver()
    return _resolver


def set_resolver(resolver: DomainResolver | None) -> None:
    global _resolver
    _resolver = resolver


async def close_resolver() -> None:
    global _resolver
    if _resolver is not None:
        await _resolver.close()
        _resolver = None
