"""A4 (часть 2). Заливка готового сайта в TON Storage.

Зона неопределённости из ТЗ: subdom API закрывает только операции с доменами,
публикацию контента делаем сами. Поэтому здесь — интерфейс `SiteStorage` и две
реализации:

* `StorageDaemonBackend` — боевой путь: локальный `ton-storage-daemon` c HTTP API,
  которому мы отдаём каталог с отрендеренным сайтом и получаем bag id (torrent hash).
* `LocalBackend` — dev-режим: сайт складывается в каталог, bag id считается
  детерминированно от содержимого. Позволяет гонять весь флоу без демона.

Переключение — переменной окружения TON_STORAGE_MODE, код выше не меняется.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.core.errors import StorageError

log = logging.getLogger(__name__)


@dataclass(slots=True)
class BagInfo:
    bag_id: str
    size: int
    files: int
    path: str | None = None


class SiteStorage(Protocol):
    async def upload_directory(self, path: Path, description: str = "") -> BagInfo: ...

    async def remove_bag(self, bag_id: str) -> None: ...

    async def close(self) -> None: ...


def write_site_files(build_dir: Path, html: str, assets: dict[str, bytes] | None = None) -> Path:
    """Готовит каталог сайта: index.html + опциональные ассеты."""
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "index.html").write_text(html, encoding="utf-8")
    for name, blob in (assets or {}).items():
        safe_name = Path(name).name  # никаких путей наружу каталога
        if not safe_name or safe_name.startswith("."):
            continue
        (build_dir / safe_name).write_bytes(blob)
    return build_dir


def _dir_stats(path: Path) -> tuple[int, int]:
    size = files = 0
    for f in path.rglob("*"):
        if f.is_file():
            size += f.stat().st_size
            files += 1
    return size, files


class StorageDaemonBackend:
    """HTTP-клиент ton-storage-daemon.

    Демон должен видеть тот же каталог, что и backend (общий volume), поэтому
    ему передаётся путь, а не содержимое.
    """

    def __init__(
        self,
        api_base: str | None = None,
        login: str | None = None,
        password: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_base = (api_base or settings.TON_STORAGE_API).rstrip("/")
        self._login = login if login is not None else settings.TON_STORAGE_LOGIN
        self._password = password if password is not None else settings.TON_STORAGE_PASSWORD
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            auth = (self._login, self._password) if self._login else None
            self._client = httpx.AsyncClient(base_url=self._api_base, timeout=120.0, auth=auth)
        return self._client

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        try:
            resp = await client.post(path, json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise StorageError(f"Storage daemon unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise StorageError(f"Storage daemon responded {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise StorageError("Malformed response from storage daemon") from exc
        if isinstance(data, dict) and data.get("ok") is False:
            raise StorageError(str(data.get("error") or "Storage daemon error"))
        return data if isinstance(data, dict) else {"result": data}

    @staticmethod
    def _extract_bag_id(data: dict[str, Any]) -> str:
        for key in ("bag_id", "hash", "torrent_hash", "bagId"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        for key in ("torrent", "result"):
            inner = data.get(key)
            if isinstance(inner, dict):
                found = StorageDaemonBackend._extract_bag_id(inner)
                if found:
                    return found
        raise StorageError("Storage daemon did not return bag id")

    async def upload_directory(self, path: Path, description: str = "") -> BagInfo:
        data = await self._post(
            "/api/v1/create",
            {"path": str(path), "description": description or path.name, "copy": False},
        )
        bag_id = self._extract_bag_id(data)
        size, files = _dir_stats(path)
        log.info("site uploaded to TON Storage: bag=%s files=%s size=%s", bag_id, files, size)
        return BagInfo(bag_id=bag_id, size=size, files=files, path=str(path))

    async def remove_bag(self, bag_id: str) -> None:
        try:
            await self._post("/api/v1/remove", {"bag_id": bag_id, "remove_files": False})
        except StorageError as exc:
            log.warning("cannot remove bag %s: %s", bag_id, exc)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class LocalBackend:
    """Dev-режим: без демона. Bag id детерминирован по содержимому каталога."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.SITES_BUILD_DIR)

    async def upload_directory(self, path: Path, description: str = "") -> BagInfo:
        digest = hashlib.sha256()
        for f in sorted(p for p in path.rglob("*") if p.is_file()):
            digest.update(f.name.encode())
            digest.update(f.read_bytes())
        size, files = _dir_stats(path)
        return BagInfo(bag_id=digest.hexdigest().upper(), size=size, files=files, path=str(path))

    async def remove_bag(self, bag_id: str) -> None:
        return None

    async def close(self) -> None:
        return None


def cleanup_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


_storage: SiteStorage | None = None


def get_storage() -> SiteStorage:
    global _storage
    if _storage is None:
        _storage = StorageDaemonBackend() if settings.TON_STORAGE_MODE == "daemon" else LocalBackend()
    return _storage


def set_storage(storage: SiteStorage | None) -> None:
    global _storage
    _storage = storage


async def close_storage() -> None:
    global _storage
    if _storage is not None:
        await _storage.close()
        _storage = None
