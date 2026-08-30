"""Тестовое окружение: SQLite в файле, очередь в памяти, заглушки внешних сервисов."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

BOT_TOKEN = "123456:TEST-BOT-TOKEN"
TREASURY = "EQD__TREASURY_ADDRESS_FOR_TESTS_AAAAAAAAAAAAAAAA"

_tmp = Path(tempfile.mkdtemp(prefix="tsb-tests-"))
os.environ.update(
    ENV="test",
    DATABASE_URL=f"sqlite+aiosqlite:///{(_tmp / 'test.db').as_posix()}",
    QUEUE_MODE="memory",
    SUBDOM_MODE="fake",
    TON_VERIFY_MODE="onchain",  # проверка платежей включена: её и тестируем
    TON_STORAGE_MODE="local",
    SITES_BUILD_DIR=str(_tmp / "sites"),
    TELEGRAM_BOT_TOKEN=BOT_TOKEN,
    TREASURY_ADDRESS=TREASURY,
    TONCONNECT_DOMAIN="test.local",
    ADMIN_TELEGRAM_IDS="777000",
    TRIAL_DAYS="7",
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.db import Base, engine  # noqa: E402
from app.core.telegram_auth import build_init_data  # noqa: E402
from app.main import app  # noqa: E402
from app.services import notifications  # noqa: E402
from app.services.storage import LocalBackend, set_storage  # noqa: E402
from app.services.subdom_client import FakeDomainService, set_domain_service  # noqa: E402
from app.services.ton import MockTonClient, set_ton_client  # noqa: E402
from app.workers.queue import MemoryQueue, set_queue  # noqa: E402


def init_data_for(telegram_id: int, username: str = "tester") -> str:
    return build_init_data(
        BOT_TOKEN,
        {"id": telegram_id, "username": username, "first_name": "Test", "language_code": "ru"},
    )


def headers_for(telegram_id: int, username: str = "tester") -> dict[str, str]:
    return {"X-Telegram-Init-Data": init_data_for(telegram_id, username)}


@pytest_asyncio.fixture
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def domain_service() -> FakeDomainService:
    service = FakeDomainService()
    set_domain_service(service)
    yield service
    set_domain_service(None)


@pytest.fixture
def ton() -> MockTonClient:
    client = MockTonClient()
    set_ton_client(client)
    yield client
    set_ton_client(None)


@pytest.fixture
def queue() -> MemoryQueue:
    q = MemoryQueue()
    set_queue(q)
    yield q
    set_queue(None)


@pytest.fixture
def storage() -> LocalBackend:
    backend = LocalBackend(_tmp / "sites")
    set_storage(backend)
    yield backend
    set_storage(None)


@pytest.fixture
def notifier() -> notifications.NullTransport:
    transport = notifications.NullTransport()
    notifications.set_transport(transport)
    yield transport
    notifications.set_transport(None)


@pytest_asyncio.fixture
async def client(db, domain_service, ton, queue, storage, notifier):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
