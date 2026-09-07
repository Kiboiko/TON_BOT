"""A4 (часть 2). Заливка готового сайта в TON Storage.

Зона неопределённости из ТЗ: subdom API закрывает только операции с доменами,
публикацию контента делаем сами. Здесь — интерфейс `SiteStorage` и две реализации:

* `StorageDaemonBackend` — боевой путь. У `ton-storage-daemon` нет HTTP API, он
  управляется утилитой `storage-daemon-cli` по управляющему порту, поэтому backend вызывает
  её как подпроцесс. Демон и backend делят том с готовыми сайтами: путь, который
  мы передаём в команду `create`, разрешает демон, а не мы.
* `LocalBackend` — dev-режим: сайт складывается в каталог, bag id считается
  детерминированно от содержимого. Позволяет гонять весь флоу без демона.

Переключение — переменной окружения TON_STORAGE_MODE, код выше не меняется.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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


def parse_bag_id(raw: str) -> str:
    """Приводит bag id к hex-виду.

    CLI отдаёт хэш в base64 (`--json`) или в hex (текстовый вывод), а для
    DNS-записи нужен ровно 256-битный hex.
    """
    raw = (raw or "").strip()
    if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
        return raw.upper()
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise StorageError(f"Unexpected bag id from storage daemon: {raw[:32]}") from exc
    if len(decoded) != 32:
        raise StorageError("Storage daemon returned bag id of wrong length")
    return decoded.hex().upper()


def parse_create_output(stdout: str) -> dict[str, Any]:
    """Достаёт JSON из вывода CLI: перед ним идут строки лога подключения."""
    start = stdout.find("{")
    if start == -1:
        raise StorageError(f"Storage daemon returned no data: {stdout.strip()[:200]}")
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError as exc:
        raise StorageError("Cannot parse storage daemon response") from exc


# строки лога самой утилиты: [ 3][t 0][2026-09-07 ...][storage-daemon-cli.cpp:229][!extclient] Connected
_ANSI_RE = re.compile("\\x1b\\[[0-9;]*m")
_CLI_LOG_RE = re.compile(r"^\[\s*\d+\]\[t\s*\d+\]\[")
# демон отказывается добавлять бэг, который у него уже есть
_DUPLICATE_RE = re.compile(r"duplicate hash ([0-9A-Fa-f]{64})")


def clean_cli_output(text: str) -> str:
    """Оставляет от вывода CLI только осмысленные строки.

    Утилита пишет в stderr цветной служебный лог («Connected»), а настоящую
    ошибку — в stdout. Без чистки пользователь получал в уведомлении именно
    служебную строку вместо причины.
    """
    text = _ANSI_RE.sub("", text or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(line for line in lines if not _CLI_LOG_RE.match(line))


def run_cli(args: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    """Синхронный запуск CLI в отдельном потоке.

    Намеренно не asyncio.create_subprocess_exec: aiogram при импорте подменяет
    политику asyncio на uvloop (aiogram/__init__.py), а цикл к этому моменту уже
    создан обычным asyncio. После такой подмены create_subprocess_exec идёт за
    child watcher в чужую политику и падает с пустым NotImplementedError.
    На практике это выглядело так: первая публикация проходила, отправляла
    уведомление через aiogram — и все следующие публикации в этом процессе
    ломались. subprocess.run про политику asyncio ничего не знает.
    """
    return subprocess.run(args, capture_output=True, timeout=timeout, check=False)


class StorageDaemonBackend:
    """Клиент ton-storage-daemon через storage-daemon-cli.

    Ключи для подключения демон генерирует сам при первом старте в
    `<db>/cli-keys/{client,server.pub}` — этот каталог общий с backend.
    """

    def __init__(
        self,
        cli: str | None = None,
        control: str | None = None,
        key: str | None = None,
        pub: str | None = None,
        timeout: float = 180.0,
    ) -> None:
        self._cli = cli or settings.TON_STORAGE_CLI
        self._control = control or settings.TON_STORAGE_CONTROL
        self._key = key or settings.TON_STORAGE_CLI_KEY
        self._pub = pub or settings.TON_STORAGE_CLI_PUB
        self._timeout = timeout

    async def _run(self, command: str) -> str:
        args = [
            self._cli,
            "-I", self._control,
            "-k", self._key,
            "-p", self._pub,
            "-c", command,
            "-c", "exit",
        ]
        try:
            completed = await asyncio.to_thread(run_cli, args, self._timeout)
        except FileNotFoundError as exc:
            raise StorageError(f"storage-daemon-cli not found: {self._cli}") from exc
        except subprocess.TimeoutExpired as exc:
            raise StorageError("Storage daemon did not respond in time") from exc

        out = completed.stdout.decode("utf-8", "replace")
        err = completed.stderr.decode("utf-8", "replace")
        if completed.returncode != 0:
            reason = clean_cli_output(out) or clean_cli_output(err) or "no output"
            raise StorageError(f"storage-daemon-cli failed: {reason[:300]}")
        if "Unknown command" in out or "Error" in err:
            log.warning("storage-daemon-cli: %s", (err or out).strip()[:200])
        return out

    async def upload_directory(self, path: Path, description: str = "") -> BagInfo:
        # путь разрешает демон, поэтому каталог обязан быть в общем томе
        try:
            out = await self._run(f"create {path.as_posix()} --json")
        except StorageError as exc:
            # bag id считается от содержимого, поэтому публикация сайта без
            # изменений даёт тот же хэш, а демон отказывается добавлять его
            # второй раз. Для пользователя это не ошибка: контент уже в сети.
            duplicate = _DUPLICATE_RE.search(str(exc))
            if duplicate is None:
                raise
            bag_id = duplicate.group(1).upper()
            size, files = _dir_stats(path)
            log.info("site already in TON Storage: bag=%s files=%s size=%s", bag_id, files, size)
            return BagInfo(bag_id=bag_id, size=size, files=files, path=str(path))
        data = parse_create_output(out)
        torrent = data.get("torrent") or {}
        bag_id = parse_bag_id(str(torrent.get("hash", "")))
        size, files = _dir_stats(path)
        log.info("site uploaded to TON Storage: bag=%s files=%s size=%s", bag_id, files, size)
        return BagInfo(
            bag_id=bag_id,
            size=int(torrent.get("total_size") or size),
            files=int(torrent.get("files_count") or files),
            path=str(path),
        )

    async def remove_bag(self, bag_id: str) -> None:
        try:
            await self._run(f"remove {bag_id}")
        except StorageError as exc:
            log.warning("cannot remove bag %s: %s", bag_id, exc)

    async def close(self) -> None:
        return None


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
