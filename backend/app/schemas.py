"""Pydantic-схемы = формальная запись API-контракта из раздела 4 ТЗ.

Именно эти схемы попадают в OpenAPI (/api/openapi.json), по которому Разработчик B
поднимает мок-сервер и генерирует типы клиента.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.models import (
    Language,
    PaymentPurpose,
    PaymentStatus,
    SiteStatus,
    SiteType,
    SubscriptionStatus,
    TariffDuration,
    TariffKind,
    Theme,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def format_ton(value: Decimal | None) -> str | None:
    """Сумма в TON без хвостовых нулей: 9.500000000 -> "9.5", 7 -> "7"."""
    if value is None:
        return None
    normalized = Decimal(str(value)).normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


# --------------------------------------------------------------------- errors
class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# --------------------------------------------------------------------- user
class UserOut(ORMModel):
    id: uuid.UUID
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    wallet_address: str | None = None
    language: Language
    theme: Theme
    is_admin: bool
    created_at: datetime


class AuthRequest(BaseModel):
    # initData можно передать телом (по контракту) или заголовком X-Telegram-Init-Data
    init_data: str | None = None


class AuthResponse(BaseModel):
    user: UserOut
    is_admin: bool


class TonProofDomain(BaseModel):
    lengthBytes: int
    value: str


class TonProof(BaseModel):
    timestamp: int
    domain: TonProofDomain
    signature: str
    payload: str
    state_init: str | None = None


class ConnectWalletRequest(BaseModel):
    wallet_address: str = Field(min_length=10, max_length=128)
    ton_proof: TonProof
    public_key: str | None = None


class ConnectWalletResponse(BaseModel):
    success: bool
    wallet_address: str


class TonProofPayloadResponse(BaseModel):
    payload: str
    expires_at: datetime


class UserSettingsRequest(BaseModel):
    language: Language | None = None
    theme: Theme | None = None


class SuccessResponse(BaseModel):
    success: bool = True


# --------------------------------------------------------------------- sites
class SiteOut(ORMModel):
    id: uuid.UUID
    type: SiteType
    title: str
    content_json: dict[str, Any]
    custom_code: dict[str, Any] | None = None
    custom_code_paid: bool = False
    domain: str | None = None
    dns_item_address: str | None = None
    collection_address: str | None = None
    status: SiteStatus
    storage_bag_id: str | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SiteListItem(ORMModel):
    id: uuid.UUID
    type: SiteType
    title: str
    domain: str | None = None
    status: SiteStatus
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SiteCreateRequest(BaseModel):
    type: SiteType
    title: str = Field(min_length=1, max_length=255)
    content_json: dict[str, Any] = Field(default_factory=dict)


class SiteUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content_json: dict[str, Any] | None = None
    custom_code: CustomCodeRequest | None = None


class SiteResponse(BaseModel):
    site: SiteOut


class PreviewResponse(BaseModel):
    preview_html: str
    preview_url: str | None = None


# --------------------------------------------------------------- domains
class DomainCheckResponse(BaseModel):
    available: bool
    status: str          # free / taken / unknown
    domain: str          # полный адрес: имя.зона.ton
    zone: str            # домен зоны платформы
    item_address: str | None = None
    owner: str | None = None


class TonConnectMessage(BaseModel):
    address: str
    amount: str
    payload: str | None = None
    stateInit: str | None = None


class TonConnectTransaction(BaseModel):
    validUntil: int
    messages: list[TonConnectMessage]
    network: str | None = None
    from_: str | None = Field(default=None, alias="from")

    model_config = ConfigDict(populate_by_name=True)


class DomainClaimRequest(BaseModel):
    site_id: uuid.UUID
    name: str = Field(min_length=3, max_length=126)

    @field_validator("name")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return v.strip().lower().rstrip(".")


class DomainClaimResponse(BaseModel):
    transaction: TonConnectTransaction
    domain: str


class DomainAttachRequest(BaseModel):
    """Привязка домена .ton, которым пользователь уже владеет."""

    site_id: uuid.UUID
    domain: str = Field(min_length=3, max_length=255)

    @field_validator("domain")
    @classmethod
    def _normalize_domain(cls, v: str) -> str:
        return v.strip().lower().rstrip(".")


class DomainAttachResponse(BaseModel):
    domain: str
    item_address: str | None = None
    # транзакция DNS-записи приходит отдельно: /api/sites/{id}/dns-bind
    needs_publish: bool = True


# --- зона субдоменов (админ) ---
class ZoneOut(BaseModel):
    domain: str
    dns_item_address: str
    collection_address: str
    mode: Literal["proxy", "sbt"]
    configured: bool     # можно выдавать субдомены
    deployable: bool     # можно разворачивать зону


class ZoneUpdateRequest(BaseModel):
    domain: str | None = None
    dns_item_address: str | None = None
    collection_address: str | None = None
    mode: Literal["proxy", "sbt"] | None = None


class ZoneDeployResponse(BaseModel):
    transaction: TonConnectTransaction
    domain: str


class DomainConfirmRequest(BaseModel):
    site_id: uuid.UUID
    tx_hash: str = Field(min_length=8, max_length=8192)


class DomainConfirmResponse(BaseModel):
    status: str
    domain: str | None = None


class PublishResponse(BaseModel):
    status: str
    job_id: str


class PublishStatusResponse(BaseModel):
    status: SiteStatus
    storage_bag_id: str | None = None
    published_at: datetime | None = None
    error: str | None = None
    # http-ссылка на опубликованный сайт: домен .ton открывается TON-браузером,
    # а эта ссылка работает в любом браузере и до привязки домена
    public_url: str | None = None


class DnsBindResponse(BaseModel):
    transaction: TonConnectTransaction


# --------------------------------------------------------- tariffs / subscriptions
class TariffOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    sites_limit: int
    duration: TariffDuration
    price_ton: Decimal
    kind: TariffKind
    is_active: bool

    @field_serializer("price_ton")
    def _price(self, value: Decimal) -> str:
        return format_ton(value) or "0"


class PurchaseRequest(BaseModel):
    tariff_id: uuid.UUID
    site_id: uuid.UUID | None = None


class PurchaseResponse(BaseModel):
    transaction: TonConnectTransaction
    payment_id: uuid.UUID


class ConfirmPaymentRequest(BaseModel):
    payment_id: uuid.UUID
    # TON Connect возвращает фронту BOC подписанного сообщения (сотни символов),
    # а не хэш транзакции: принимаем и то и другое, платёж всё равно ищется
    # в блокчейне по комментарию-нонсу
    tx_hash: str = Field(min_length=8, max_length=8192)


class SubscriptionOut(ORMModel):
    id: uuid.UUID
    tariff: TariffOut | None = None
    site_id: uuid.UUID | None = None
    starts_at: datetime
    expires_at: datetime | None = None
    is_forever: bool
    is_trial: bool
    status: SubscriptionStatus
    granted_by_admin: bool


class SubscriptionResponse(BaseModel):
    subscription: SubscriptionOut


# --------------------------------------------------------------- custom code
class CustomCodeRequest(BaseModel):
    html: str = ""
    css: str = ""
    js: str = ""


class UploadResponse(BaseModel):
    url: str
    size: int
    mime: str


# --------------------------------------------------------------------- payments
class PaymentOut(ORMModel):
    id: uuid.UUID
    tx_hash: str | None = None
    amount: Decimal
    purpose: PaymentPurpose
    related_id: uuid.UUID | None = None
    status: PaymentStatus
    created_at: datetime
    confirmed_at: datetime | None = None

    @field_serializer("amount")
    def _amount(self, value: Decimal) -> str:
        return format_ton(value) or "0"


# --------------------------------------------------------------------- admin
class AdminUserListItem(ORMModel):
    id: uuid.UUID
    telegram_id: int
    username: str | None = None
    wallet_address: str | None = None
    is_admin: bool
    is_blocked: bool
    created_at: datetime
    sites_count: int = 0
    active_subscriptions: int = 0


class AdminUsersResponse(BaseModel):
    users: list[AdminUserListItem]
    total: int
    page: int
    per_page: int


class AdminUserDetail(BaseModel):
    user: UserOut
    sites: list[SiteListItem]
    subscriptions: list[SubscriptionOut]
    payments: list[PaymentOut]


class GrantAccessRequest(BaseModel):
    tariff_id: uuid.UUID | None = None
    duration: TariffDuration | None = None
    site_id: uuid.UUID | None = None
    sites_limit: int | None = None
    comment: str | None = None


class RevokeAccessRequest(BaseModel):
    subscription_id: uuid.UUID


class TariffCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    sites_limit: int = Field(default=1, ge=1, le=1000)
    duration: TariffDuration
    price_ton: Decimal = Field(ge=0)
    kind: TariffKind = TariffKind.base
    is_active: bool = True


class TariffUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    sites_limit: int | None = Field(default=None, ge=1, le=1000)
    duration: TariffDuration | None = None
    price_ton: Decimal | None = Field(default=None, ge=0)
    kind: TariffKind | None = None
    is_active: bool | None = None


class AdminDomainItem(BaseModel):
    domain: str
    status: SiteStatus
    site_id: uuid.UUID
    site_title: str
    user_id: uuid.UUID
    telegram_id: int
    published_at: datetime | None = None


class AdminStatsResponse(BaseModel):
    total_users: int
    total_sites: int
    published_sites: int
    active_subscriptions: int
    revenue: Decimal
    revenue_last_30d: Decimal
    payments_confirmed: int

    @field_serializer("revenue", "revenue_last_30d")
    def _money(self, value: Decimal) -> str:
        return format_ton(value) or "0"


# SiteUpdateRequest ссылается на CustomCodeRequest, объявленный ниже
SiteUpdateRequest.model_rebuild()
