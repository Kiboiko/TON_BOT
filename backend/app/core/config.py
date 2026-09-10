"""Конфигурация приложения. Все значения — из .env (см. .env.example).

Чёткое разделение тестовых/боевых значений достигается заменой одного файла .env:
никаких хардкодов адресов, токенов и ключей в коде быть не должно.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- окружение ---
    ENV: Literal["dev", "test", "prod"] = "dev"
    DEBUG: bool = False
    API_PREFIX: str = "/api"
    CORS_ORIGINS: str = "*"

    # --- база ---
    DATABASE_URL: str = "postgresql+asyncpg://ton:ton@postgres:5432/ton_builder"
    DB_ECHO: bool = False

    # --- redis / очередь фоновых задач ---
    REDIS_URL: str = "redis://redis:6379/0"
    # redis — боевая очередь, memory — очередь в памяти процесса (dev/тесты)
    QUEUE_MODE: Literal["redis", "memory"] = "redis"
    QUEUE_NAME: str = "ton_builder:jobs"

    # --- telegram ---
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_INITDATA_TTL: int = 86400  # сек, максимальный возраст auth_date
    MINI_APP_URL: str = ""  # https-URL Mini App для кнопки в боте
    # Разрешить вход без валидной подписи initData (ТОЛЬКО для локальной разработки)
    ALLOW_INSECURE_AUTH: bool = False

    # --- админы ---
    # список telegram_id через запятую — эти пользователи получают is_admin при первом входе
    ADMIN_TELEGRAM_IDS: str = ""

    # --- TON ---
    TON_NETWORK: Literal["mainnet", "testnet"] = "testnet"
    TON_API_BASE: str = "https://testnet.toncenter.com/api/v2"
    TON_API_KEY: str = ""
    # Кошелёк проекта — на него приходят платежи за подписки и премиум-блок
    TREASURY_ADDRESS: str = ""
    # Режим проверки транзакций: onchain — реальная проверка, mock — принимать любой хэш (dev)
    TON_VERIFY_MODE: Literal["onchain", "mock"] = "onchain"
    # Допуск по сумме платежа (в TON), чтобы комиссия/округление не ломали проверку
    PAYMENT_AMOUNT_TOLERANCE: float = 0.005
    # Сколько ждать появления транзакции в блокчейне (сек) и интервал опроса
    TX_CONFIRM_TIMEOUT: int = 180
    TX_CONFIRM_INTERVAL: int = 6

    # --- TON Connect (ton_proof) ---
    TONCONNECT_DOMAIN: str = "localhost"
    TONPROOF_PAYLOAD_TTL: int = 600  # сек
    TONPROOF_SECRET: str = "change-me"

    # --- subdom.zone ---
    SUBDOM_API_BASE: str = "https://api.subdom.zone"
    SUBDOM_API_KEY: str = ""
    SUBDOM_TIMEOUT: float = 20.0
    SUBDOM_RETRIES: int = 3
    # http — реальный сервис, fake — встроенная заглушка (dev/тесты)
    SUBDOM_MODE: Literal["http", "fake"] = "http"

    # --- зона субдоменов ---
    # Платформа владеет одним доменом .ton и один раз разворачивает на нём зону;
    # пользователи получают субдомены внутри неё: имя.ZONE_DOMAIN
    ZONE_DOMAIN: str = ""              # например tonsite.ton
    ZONE_DNS_ITEM_ADDRESS: str = ""    # адрес DNS-item этого домена
    ZONE_COLLECTION_ADDRESS: str = ""  # адрес коллекции после разворота зоны
    ZONE_MODE: Literal["proxy", "sbt"] = "proxy"
    # Резолвер TON DNS для проверки занятости имени
    TON_DNS_API: str = "https://tonapi.io"

    # --- TON Storage ---
    # daemon — настоящий ton-storage-daemon, local — выкладка в каталог (dev)
    # ADNL-адрес нашего rldp-http-proxy (55 символов, как у .adnl-хостов).
    # Домен .ton с DNS-записью `site` на этот адрес открывается TON-браузерами
    # напрямую с нашего сервера — без публичных шлюзов.
    TON_SITE_ADNL: str = ""

    TON_STORAGE_MODE: Literal["daemon", "local"] = "local"
    # У демона нет HTTP API: управление идёт утилитой storage-daemon-cli
    # по управляющему порту, ключи демон генерирует сам при первом старте.
    TON_STORAGE_CLI: str = "storage-daemon-cli"
    # демон в сети хоста: имя сервиса storage-daemon из контейнера не резолвится
    TON_STORAGE_CONTROL: str = "host.docker.internal:5555"
    TON_STORAGE_CLI_KEY: str = "/var/ton-work/db/cli-keys/client"
    TON_STORAGE_CLI_PUB: str = "/var/ton-work/db/cli-keys/server.pub"
    # Директория, куда рендерятся сайты перед заливкой (общий volume с storage-daemon)
    SITES_BUILD_DIR: str = "/data/sites"
    PUBLIC_SITE_BASE_URL: str = ""  # опционально: http-зеркало для превью

    # --- подписки ---
    TRIAL_DAYS: int = 7
    # через сколько секунд «публикуется» считается зависшим и публикацию можно повторить
    PUBLISH_STALE_SECONDS: int = 180
    EXPIRING_SOON_DAYS: int = 3
    SCHEDULER_INTERVAL: int = 300  # сек между прогонами планировщика

    # --- загрузка изображений ---
    UPLOADS_DIR: str = "/data/uploads"
    MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024

    # --- лимиты пользовательского контента ---
    MAX_CONTENT_JSON_BYTES: int = 512_000
    MAX_CUSTOM_CODE_BYTES: int = 256_000

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origins(self) -> list[str]:
        if self.CORS_ORIGINS.strip() in ("*", ""):
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def admin_telegram_ids(self) -> set[int]:
        out: set[int] = set()
        for chunk in self.ADMIN_TELEGRAM_IDS.split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                out.add(int(chunk))
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
