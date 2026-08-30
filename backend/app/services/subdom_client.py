"""A2. subdom_client — единственная точка контакта с внешним доменным сервисом.

Архитектурное требование ТЗ (раздел 8): вся работа с `subdom.zone` живёт здесь.
Наружу торчит только чистый интерфейс `DomainService` в наших собственных типах
(`TransactionResponse`, `DomainInfo`). Ни один вызывающий модуль не знает ни про
URL-ы subdom, ни про формат его JSON, ни про его коды ошибок — поэтому замена
сервиса на альтернативу правит только этот файл.

Единственное, что пробрасывается «как есть» — тело транзакции TON Connect
(validUntil + messages): его подписывает кошелёк пользователя, и любое наше
вмешательство в него сломало бы подпись.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import httpx

from app.core.config import settings
from app.core.errors import SubdomError

log = logging.getLogger(__name__)

ZoneMode = Literal["proxy", "sbt"]


# --------------------------------------------------------------------- наши типы
@dataclass(slots=True)
class TransactionMessage:
    address: str
    amount: str
    payload: str | None = None
    state_init: str | None = None

    def to_tonconnect(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"address": self.address, "amount": self.amount}
        if self.payload:
            msg["payload"] = self.payload
        if self.state_init:
            msg["stateInit"] = self.state_init
        return msg


@dataclass(slots=True)
class TransactionResponse:
    """Готовая к подписи транзакция TON Connect."""

    valid_until: int
    messages: list[TransactionMessage]
    network: str | None = None

    def to_tonconnect(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "validUntil": self.valid_until,
            "messages": [m.to_tonconnect() for m in self.messages],
        }
        if self.network:
            out["network"] = self.network
        return out


@dataclass(slots=True)
class DomainInfo:
    domain: str
    available: bool
    status: str
    dns_item_address: str | None = None
    collection_address: str | None = None
    owner: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DomainService(Protocol):
    """Интерфейс доменного сервиса. Меняется сервис — меняется только реализация."""

    async def check_domain(self, name: str, tld: str = "ton") -> DomainInfo: ...

    async def deploy_proxy_zone(
        self, dns_item_address: str, dns_item_name: str, user_wallet: str, tld: str = "ton"
    ) -> TransactionResponse: ...

    async def deploy_sbt_zone(
        self, dns_item_address: str, domain: str, user_wallet: str, tld: str = "ton"
    ) -> TransactionResponse: ...

    async def start_auction(
        self, collection_address: str, subdomain_name: str
    ) -> TransactionResponse: ...

    async def mint_sbt_subdomain(
        self, collection_address: str, subdomain_name: str
    ) -> TransactionResponse: ...

    async def claim_subdomain(self, subdomain_item_address: str) -> TransactionResponse: ...

    async def close(self) -> None: ...


# --------------------------------------------------------------------- HTTP-реализация
class SubdomHttpClient:
    """Реализация поверх HTTP API subdom.zone: ретраи, таймауты, маппинг ошибок."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (base_url or settings.SUBDOM_API_BASE).rstrip("/")
        self._api_key = api_key if api_key is not None else settings.SUBDOM_API_KEY
        self._timeout = timeout or settings.SUBDOM_TIMEOUT
        self._retries = retries if retries is not None else settings.SUBDOM_RETRIES
        self._client = client
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    headers = {"Accept": "application/json"}
                    if self._api_key:
                        headers["Authorization"] = f"Bearer {self._api_key}"
                    self._client = httpx.AsyncClient(
                        base_url=self._base_url,
                        timeout=self._timeout,
                        headers=headers,
                    )
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        client = await self._get_client()
        last_exc: Exception | None = None

        for attempt in range(1, self._retries + 1):
            try:
                resp = await client.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                log.warning("subdom %s %s network error (try %s): %s", method, path, attempt, exc)
            else:
                # 5xx и 429 — временные, ретраим; 4xx — ошибка запроса, отдаём сразу
                if resp.status_code >= 500 or resp.status_code == 429:
                    last_exc = SubdomError(
                        f"subdom responded {resp.status_code}",
                        details={"status": resp.status_code},
                    )
                    log.warning("subdom %s %s -> %s (try %s)", method, path, resp.status_code, attempt)
                elif resp.status_code >= 400:
                    raise SubdomError(
                        self._error_message(resp),
                        code="SUBDOM_BAD_REQUEST",
                        status_code=400 if resp.status_code < 500 else 502,
                        details={"status": resp.status_code},
                    )
                else:
                    return self._parse_json(resp)

            if attempt < self._retries:
                await asyncio.sleep(min(2 ** (attempt - 1), 5))

        raise SubdomError("Domain service is unavailable", details={"cause": str(last_exc)})

    @staticmethod
    def _parse_json(resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError as exc:
            raise SubdomError("Malformed response from domain service") from exc
        if not isinstance(data, dict):
            return {"result": data}
        return data

    @staticmethod
    def _error_message(resp: httpx.Response) -> str:
        try:
            data = resp.json()
        except ValueError:
            return f"Domain service error ({resp.status_code})"
        if isinstance(data, dict):
            for key in ("message", "error", "detail", "description"):
                val = data.get(key)
                if isinstance(val, str) and val:
                    return val
        return f"Domain service error ({resp.status_code})"

    # --- нормализация ответов внешнего API в наши типы ---
    @staticmethod
    def _to_transaction(data: dict[str, Any]) -> TransactionResponse:
        payload = data
        for key in ("transaction", "result", "data"):
            inner = payload.get(key)
            if isinstance(inner, dict) and ("messages" in inner or "validUntil" in inner):
                payload = inner
                break

        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            raise SubdomError(
                "Domain service returned no transaction messages", code="SUBDOM_BAD_RESPONSE"
            )

        messages: list[TransactionMessage] = []
        for m in raw_messages:
            if not isinstance(m, dict) or "address" not in m or "amount" not in m:
                raise SubdomError(
                    "Domain service returned malformed message", code="SUBDOM_BAD_RESPONSE"
                )
            messages.append(
                TransactionMessage(
                    address=str(m["address"]),
                    amount=str(m["amount"]),
                    payload=m.get("payload") or m.get("body"),
                    state_init=m.get("stateInit") or m.get("state_init"),
                )
            )

        valid_until = payload.get("validUntil") or payload.get("valid_until")
        if not isinstance(valid_until, int):
            import time

            valid_until = int(time.time()) + 600

        return TransactionResponse(
            valid_until=int(valid_until),
            messages=messages,
            network=payload.get("network"),
        )

    # --- публичный интерфейс ---
    async def check_domain(self, name: str, tld: str = "ton") -> DomainInfo:
        data = await self._request("GET", "/domains/check", params={"name": name, "tld": tld})
        result = data.get("result") if isinstance(data.get("result"), dict) else data
        available = bool(result.get("available", result.get("is_available", False)))
        return DomainInfo(
            domain=f"{name}.{tld}",
            available=available,
            status=str(result.get("status") or ("free" if available else "taken")),
            dns_item_address=result.get("dns_item_address") or result.get("dnsItemAddress"),
            collection_address=result.get("collection_address") or result.get("collectionAddress"),
            owner=result.get("owner") or result.get("owner_address"),
            extra={k: v for k, v in result.items() if k not in {"available", "status"}},
        )

    async def deploy_proxy_zone(
        self, dns_item_address: str, dns_item_name: str, user_wallet: str, tld: str = "ton"
    ) -> TransactionResponse:
        data = await self._request(
            "POST",
            "/zones/deploy-proxy",
            json={
                "dns_item_address": dns_item_address,
                "dns_item_name": dns_item_name,
                "user_wallet": user_wallet,
                "tld": tld,
            },
        )
        return self._to_transaction(data)

    async def deploy_sbt_zone(
        self, dns_item_address: str, domain: str, user_wallet: str, tld: str = "ton"
    ) -> TransactionResponse:
        data = await self._request(
            "POST",
            "/zones/deploy-sbt",
            json={
                "dns_item_address": dns_item_address,
                "domain": domain,
                "user_wallet": user_wallet,
                "tld": tld,
            },
        )
        return self._to_transaction(data)

    async def start_auction(
        self, collection_address: str, subdomain_name: str
    ) -> TransactionResponse:
        data = await self._request(
            "POST",
            "/subdomains/auction",
            json={"collection_address": collection_address, "subdomain_name": subdomain_name},
        )
        return self._to_transaction(data)

    async def mint_sbt_subdomain(
        self, collection_address: str, subdomain_name: str
    ) -> TransactionResponse:
        data = await self._request(
            "POST",
            "/subdomains/mint-sbt",
            json={"collection_address": collection_address, "subdomain_name": subdomain_name},
        )
        return self._to_transaction(data)

    async def claim_subdomain(self, subdomain_item_address: str) -> TransactionResponse:
        data = await self._request(
            "POST",
            "/subdomains/claim",
            json={"subdomain_item_address": subdomain_item_address},
        )
        return self._to_transaction(data)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# --------------------------------------------------------------------- заглушка
class FakeDomainService:
    """Детерминированная заглушка для локальной разработки и тестов.

    Позволяет фронту и интеграционным тестам проходить весь флоу без внешнего
    сервиса. Домены, начинающиеся на `taken`, считаются занятыми.
    """

    FAKE_ADDRESS = "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _tx(self, amount: str = "50000000") -> TransactionResponse:
        import time

        return TransactionResponse(
            valid_until=int(time.time()) + 600,
            messages=[TransactionMessage(address=self.FAKE_ADDRESS, amount=amount, payload="te6cc")],
        )

    async def check_domain(self, name: str, tld: str = "ton") -> DomainInfo:
        self.calls.append(("check_domain", {"name": name, "tld": tld}))
        available = not name.lower().startswith("taken")
        return DomainInfo(
            domain=f"{name}.{tld}",
            available=available,
            status="free" if available else "taken",
            dns_item_address=self.FAKE_ADDRESS,
            collection_address=self.FAKE_ADDRESS,
        )

    async def deploy_proxy_zone(
        self, dns_item_address: str, dns_item_name: str, user_wallet: str, tld: str = "ton"
    ) -> TransactionResponse:
        self.calls.append(("deploy_proxy_zone", {"domain": dns_item_name, "wallet": user_wallet}))
        return self._tx()

    async def deploy_sbt_zone(
        self, dns_item_address: str, domain: str, user_wallet: str, tld: str = "ton"
    ) -> TransactionResponse:
        self.calls.append(("deploy_sbt_zone", {"domain": domain, "wallet": user_wallet}))
        return self._tx()

    async def start_auction(
        self, collection_address: str, subdomain_name: str
    ) -> TransactionResponse:
        self.calls.append(("start_auction", {"subdomain": subdomain_name}))
        return self._tx()

    async def mint_sbt_subdomain(
        self, collection_address: str, subdomain_name: str
    ) -> TransactionResponse:
        self.calls.append(("mint_sbt_subdomain", {"subdomain": subdomain_name}))
        return self._tx()

    async def claim_subdomain(self, subdomain_item_address: str) -> TransactionResponse:
        self.calls.append(("claim_subdomain", {"address": subdomain_item_address}))
        return self._tx()

    async def close(self) -> None:
        return None


_service: DomainService | None = None


def get_domain_service() -> DomainService:
    """Фабрика: единственное место, где выбирается реализация доменного сервиса."""
    global _service
    if _service is None:
        _service = FakeDomainService() if settings.SUBDOM_MODE == "fake" else SubdomHttpClient()
    return _service


def set_domain_service(service: DomainService | None) -> None:
    """Подмена реализации (тесты, ручной прогон)."""
    global _service
    _service = service


async def close_domain_service() -> None:
    global _service
    if _service is not None:
        await _service.close()
        _service = None
