"""Модели данных — раздел 3 ТЗ.

Все сущности хранятся у нас, а не у стороннего сервиса: при недоступности subdom
API теряется только возможность создать новый домен, данные остаются на месте.
"""
from __future__ import annotations

import hashlib
import json

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.core.db import Base

# jsonb в Postgres, обычный JSON в SQLite (тесты)
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Language(str, enum.Enum):
    ru = "ru"
    en = "en"


class Theme(str, enum.Enum):
    light = "light"
    dark = "dark"


class SiteType(str, enum.Enum):
    visitka = "visitka"
    links = "links"
    landing = "landing"
    portfolio = "portfolio"
    events = "events"
    ton_project = "ton_project"
    # отдельный тип проекта: страница целиком из своего HTML/CSS/JS, блоков нет
    custom_code = "custom_code"


class SiteStatus(str, enum.Enum):
    draft = "draft"
    publishing = "publishing"
    published = "published"
    publish_error = "publish_error"
    expired = "expired"


class TariffDuration(str, enum.Enum):
    month = "month"
    month3 = "3month"
    month6 = "6month"
    month12 = "12month"
    forever = "forever"


class TariffKind(str, enum.Enum):
    base = "base"
    pro = "pro"
    custom_code = "custom_code"


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    expiring_soon = "expiring_soon"
    expired = "expired"
    manual = "manual"


class PaymentPurpose(str, enum.Enum):
    subscription = "subscription"
    custom_code = "custom_code"
    domain = "domain"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    failed = "failed"


class AdminActionType(str, enum.Enum):
    grant_access = "grant_access"
    revoke_access = "revoke_access"
    change_price = "change_price"
    create_tariff = "create_tariff"
    delete_tariff = "delete_tariff"
    deploy_zone = "deploy_zone"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(128))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    wallet_address: Mapped[str | None] = mapped_column(String(128), index=True)
    language: Mapped[Language] = mapped_column(
        SAEnum(Language, name="language_enum"), default=Language.ru, nullable=False
    )
    theme: Mapped[Theme] = mapped_column(
        SAEnum(Theme, name="theme_enum"), default=Theme.light, nullable=False
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sites: Mapped[list["Site"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[SiteType] = mapped_column(SAEnum(SiteType, name="site_type_enum"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    # заполняется только у сайтов типа custom_code
    custom_code: Mapped[dict | None] = mapped_column(JSONType)
    # Разовая оплата возможности своего кода — на каждый сайт отдельно.
    # Не подписка: заплатив один раз, пользователь владеет ею бессрочно.
    custom_code_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    tld: Mapped[str | None] = mapped_column(String(32))
    dns_item_address: Mapped[str | None] = mapped_column(String(128))
    collection_address: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[SiteStatus] = mapped_column(
        SAEnum(SiteStatus, name="site_status_enum"), default=SiteStatus.draft, nullable=False
    )
    storage_bag_id: Mapped[str | None] = mapped_column(String(128))
    publish_error: Mapped[str | None] = mapped_column(Text)
    publish_job_id: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Отпечаток содержимого, которое сейчас опубликовано. По нему видно, что
    # сайт правили после публикации и опубликованную версию пора обновить.
    published_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="sites")

    __table_args__ = (Index("ix_sites_user_status", "user_id", "status"),)

    @property
    def content_hash(self) -> str:
        """Отпечаток всего, что попадает на опубликованную страницу.

        Хэшируем исходные данные, а не готовый HTML: иначе любое изменение
        шаблонов в новой версии приложения помечало бы все сайты изменёнными.
        """
        payload = {
            "title": self.title,
            "type": self.type.value if self.type else None,
            # домен выводится в подвале страницы
            "domain": self.domain,
            "content": self.content_json,
            "custom_code": self.custom_code if self.custom_code_paid else None,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def has_unpublished_changes(self) -> bool:
        """Сайт опубликован, но с тех пор его содержимое менялось."""
        if self.status != SiteStatus.published:
            return False
        if self.published_hash:
            return self.published_hash != self.content_hash
        # Опубликованные до появления отпечатка: судим по времени последней
        # правки. Сама публикация тоже трогает updated_at, отсюда допуск.
        if self.published_at is None or self.updated_at is None:
            return False
        published = self.published_at.replace(tzinfo=None)
        updated = self.updated_at.replace(tzinfo=None)
        return (updated - published).total_seconds() > 5


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sites_limit: Mapped[int] = mapped_column(default=1, nullable=False)
    duration: Mapped[TariffDuration] = mapped_column(
        SAEnum(TariffDuration, name="tariff_duration_enum"), nullable=False
    )
    price_ton: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    kind: Mapped[TariffKind] = mapped_column(
        SAEnum(TariffKind, name="tariff_kind_enum"), default=TariffKind.base, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tariff_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tariffs.id", ondelete="SET NULL"), index=True
    )
    # SET NULL, а не CASCADE: удаление сайта не должно стирать оплаченный срок
    # и отметку «пробный период уже использован»
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_forever: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        SAEnum(SubscriptionStatus, name="subscription_status_enum"),
        default=SubscriptionStatus.active,
        nullable=False,
    )
    granted_by_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notified_expiring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notified_expired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="subscriptions")
    tariff: Mapped[Tariff | None] = relationship(lazy="selectin")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tx_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)
    purpose: Mapped[PaymentPurpose] = mapped_column(
        SAEnum(PaymentPurpose, name="payment_purpose_enum"), nullable=False
    )
    related_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    # комментарий-нонс в транзакции: связывает on-chain платёж с записью в БД
    comment: Mapped[str | None] = mapped_column(String(64), index=True)
    destination: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus, name="payment_status_enum"),
        default=PaymentStatus.pending,
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="payments")

    __table_args__ = (UniqueConstraint("tx_hash", name="uq_payments_tx_hash"),)


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[AdminActionType] = mapped_column(
        SAEnum(AdminActionType, name="admin_action_enum"), nullable=False
    )
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    details: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TonProofPayload(Base):
    """Одноразовый nonce для ton_proof: защита от повторного использования подписи."""

    __tablename__ = "ton_proof_payloads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payload: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AppSetting(Base):
    """Настройки, которые меняет администратор без передеплоя.

    Адрес коллекции субдоменов известен только после того, как владелец домена
    подпишет транзакцию разворота зоны, — держать его в .env неудобно.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow, nullable=False
    )
