"""A3. Работа с блокчейном TON: проверка транзакций и ton_proof.

Главный принцип ТЗ (раздел 8): backend не активирует подписку и не публикует сайт
по слову фронта. Фронт присылает tx_hash, а мы идём в блокчейн и проверяем, что
транзакция реально прошла, на наш адрес и на нужную сумму.

Платёж связывается с записью в БД через комментарий-нонс (`Payment.comment`),
который мы кладём в тело исходящего сообщения при формировании транзакции.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.core.errors import BadRequest, TonApiError

log = logging.getLogger(__name__)

NANO = Decimal(10) ** 9
TON_PROOF_PREFIX = b"ton-proof-item-v2/"
TON_CONNECT_PREFIX = b"\xff\xff" + b"ton-connect"


def to_nano(amount: Decimal | float | str) -> int:
    return int((Decimal(str(amount)) * NANO).to_integral_value())


def from_nano(amount: int | str) -> Decimal:
    return Decimal(int(amount)) / NANO


def to_user_friendly(address: str, *, bounceable: bool = True) -> str:
    """Адрес в виде EQ…/UQ… — именно его требует TON Connect.

    Кошельки отвергают сырой `0:hex` с ошибкой «Wrong 'address' format»,
    а из блокчейн-API адреса приходят как раз в сыром виде.
    """
    from pytoniq_core import Address

    address = (address or "").strip()
    if not address:
        return ""
    try:
        return Address(address).to_str(
            is_user_friendly=True, is_bounceable=bounceable, is_url_safe=True
        )
    except Exception:  # noqa: BLE001 - не наш адрес: отдаём как есть, провалидирует кошелёк
        return address


ADNL_ADDRESS_LEN = 55


def decode_adnl_address(address: str) -> bytes:
    """user-friendly ADNL адрес (55 символов) → 32 байта.

    Формат тот же, что у `.adnl`-хостов: base32 от 35 байт `0x2d | id | crc16`,
    у которых отброшен первый символ. Проверяем и длину, и контрольную сумму —
    опечатка в адресе иначе уехала бы в DNS-запись домена.
    """
    from pytoniq_core.crypto.crc import crc16

    value = (address or "").strip().lower()
    if len(value) != ADNL_ADDRESS_LEN:
        raise BadRequest("Invalid ADNL address", code="INVALID_ADNL_ADDRESS")
    padded = ("f" + value).upper()
    try:
        raw = base64.b32decode(padded + "=" * (-len(padded) % 8))
    except (ValueError, binascii.Error) as exc:
        raise BadRequest("Invalid ADNL address", code="INVALID_ADNL_ADDRESS") from exc
    if len(raw) != 35 or raw[0] != 0x2D:
        raise BadRequest("Invalid ADNL address", code="INVALID_ADNL_ADDRESS")
    if crc16(raw[:33]) != raw[33:]:
        raise BadRequest("Invalid ADNL address", code="INVALID_ADNL_ADDRESS")
    return raw[1:33]


def normalize_address(address: str) -> str:
    """Приводит адрес к каноничной форме `workchain:hex` для сравнения.

    TON-адрес встречается в raw и в нескольких user-friendly кодировках; сравнивать
    строки «как есть» нельзя — один и тот же кошелёк даст разные строки.
    """
    address = (address or "").strip()
    if not address:
        return ""
    if ":" in address:
        wc, _, tail = address.partition(":")
        try:
            return f"{int(wc)}:{tail.lower().rjust(64, '0')}"
        except ValueError:
            return address.lower()
    try:
        raw = base64.urlsafe_b64decode(address + "=" * (-len(address) % 4))
        if len(raw) != 36:
            return address.lower()
        wc_byte = raw[1]
        workchain = wc_byte - 256 if wc_byte > 127 else wc_byte
        return f"{workchain}:{raw[2:34].hex()}"
    except (binascii.Error, ValueError):
        return address.lower()


def looks_like_tx_hash(value: str | None) -> bool:
    """Хэш транзакции — 64 hex-символа или 44 символа base64 (32 байта)."""
    if not value:
        return False
    value = value.strip()
    if len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
        return True
    return len(value) == 44 and value.endswith("=")


def same_address(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return normalize_address(a) == normalize_address(b)


@dataclass(slots=True)
class TxInfo:
    """Нормализованное входящее сообщение (то, что нам реально нужно от блокчейна)."""

    tx_hash: str
    source: str | None
    destination: str | None
    value_nano: int
    comment: str | None
    utime: int
    success: bool = True

    @property
    def value_ton(self) -> Decimal:
        return from_nano(self.value_nano)


class TonClient(Protocol):
    async def get_transaction_by_hash(self, tx_hash: str, address: str | None = None) -> TxInfo | None: ...

    async def find_incoming(
        self, address: str, *, comment: str | None = None, since: int | None = None, limit: int = 50
    ) -> list[TxInfo]: ...

    async def get_public_key(self, address: str) -> bytes | None: ...

    async def close(self) -> None: ...


class ToncenterClient:
    """Клиент toncenter v2 (совместим с self-hosted нодой того же API)."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (base_url or settings.TON_API_BASE).rstrip("/")
        self._api_key = api_key if api_key is not None else settings.TON_API_KEY
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Accept": "application/json"}
            if self._api_key:
                headers["X-API-Key"] = self._api_key
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=20.0, headers=headers)
        return self._client

    async def _call(self, path: str, params: dict[str, Any] | None = None) -> Any:
        client = await self._get_client()
        for attempt in range(3):
            try:
                resp = await client.get(path, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == 2:
                    raise TonApiError(f"TON API unreachable: {exc}") from exc
                await asyncio.sleep(1 + attempt)
                continue
            if resp.status_code == 429:
                await asyncio.sleep(1 + attempt)
                continue
            if resp.status_code >= 400:
                raise TonApiError(f"TON API responded {resp.status_code}")
            data = resp.json()
            if isinstance(data, dict) and data.get("ok") is False:
                raise TonApiError(str(data.get("error") or "TON API error"))
            return data.get("result") if isinstance(data, dict) else data
        raise TonApiError("TON API rate limited")

    @staticmethod
    def _extract_comment(msg: dict[str, Any]) -> str | None:
        msg_data = msg.get("msg_data") or {}
        text = msg.get("message") or msg_data.get("text")
        if isinstance(text, str) and text:
            # toncenter отдаёт комментарий уже декодированным либо base64
            try:
                decoded = base64.b64decode(text, validate=True)
                if decoded[:4] == b"\x00\x00\x00\x00":
                    return decoded[4:].decode("utf-8", "ignore").strip("\x00") or None
                return text
            except (binascii.Error, ValueError):
                return text
        body = msg_data.get("body")
        if isinstance(body, str) and body:
            try:
                raw = base64.b64decode(body)
                idx = raw.find(b"\x00\x00\x00\x00")
                if idx != -1:
                    return raw[idx + 4 :].decode("utf-8", "ignore").strip("\x00") or None
            except (binascii.Error, ValueError):
                return None
        return None

    def _to_txinfo(self, tx: dict[str, Any]) -> TxInfo | None:
        in_msg = tx.get("in_msg") or {}
        if not in_msg:
            return None
        return TxInfo(
            tx_hash=str(tx.get("transaction_id", {}).get("hash") or tx.get("hash") or ""),
            source=in_msg.get("source") or None,
            destination=in_msg.get("destination") or None,
            value_nano=int(in_msg.get("value") or 0),
            comment=self._extract_comment(in_msg),
            utime=int(tx.get("utime") or 0),
            success=True,
        )

    async def find_incoming(
        self, address: str, *, comment: str | None = None, since: int | None = None, limit: int = 50
    ) -> list[TxInfo]:
        # без archival: ищем свежий платёж, а архивные ноды отстают от сети
        result = await self._call("/getTransactions", {"address": address, "limit": limit})
        out: list[TxInfo] = []
        for tx in result or []:
            info = self._to_txinfo(tx)
            if info is None or info.value_nano <= 0:
                continue
            if since and info.utime < since:
                continue
            if comment and (info.comment or "") != comment:
                continue
            out.append(info)
        return out

    async def get_transaction_by_hash(
        self, tx_hash: str, address: str | None = None
    ) -> TxInfo | None:
        """Ищет транзакцию по хэшу. Не найдено или хэш не распознан — None.

        Фронт присылает то, что вернул TON Connect, а это BOC внешнего сообщения,
        а не хэш транзакции. Для такой строки TON API отвечает 422 — это не сбой
        сервиса, а «искать нечего», поэтому наверх уходит None, и основной путь
        поиска (по комментарию-нонсу) отрабатывает как обычно.
        """
        if not address or not looks_like_tx_hash(tx_hash):
            return None
        try:
            result = await self._call(
                "/getTransactions",
                {"address": address, "limit": 100, "hash": tx_hash, "archival": "true"},
            )
        except TonApiError as exc:
            log.warning("lookup by hash failed: %s", exc)
            return None
        for tx in result or []:
            info = self._to_txinfo(tx)
            if info and (not tx_hash or info.tx_hash == tx_hash):
                return info
        return None

    async def get_public_key(self, address: str) -> bytes | None:
        """Публичный ключ кошелька через get-метод контракта (get_public_key)."""
        client = await self._get_client()
        try:
            resp = await client.post(
                "/runGetMethod",
                json={"address": address, "method": "get_public_key", "stack": []},
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TonApiError(f"TON API unreachable: {exc}") from exc
        if resp.status_code >= 400:
            return None
        data = resp.json()
        result = data.get("result") if isinstance(data, dict) else None
        if not result or result.get("exit_code") not in (0, None):
            return None
        stack = result.get("stack") or []
        if not stack:
            return None
        entry = stack[0]
        value = entry[1] if isinstance(entry, list) and len(entry) > 1 else entry
        if isinstance(value, dict):
            value = value.get("value") or value.get("number", {}).get("number")
        if not isinstance(value, str):
            return None
        try:
            return int(value, 16 if value.startswith("0x") else 10).to_bytes(32, "big")
        except (ValueError, OverflowError):
            return None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class MockTonClient:
    """Заглушка для dev/тестов: транзакции, которые «как будто» прошли."""

    def __init__(self) -> None:
        self.transactions: list[TxInfo] = []
        self.public_keys: dict[str, bytes] = {}
        self.accept_any = True

    def add(self, tx: TxInfo) -> None:
        self.transactions.append(tx)

    async def find_incoming(
        self, address: str, *, comment: str | None = None, since: int | None = None, limit: int = 50
    ) -> list[TxInfo]:
        out = [
            t
            for t in self.transactions
            if same_address(t.destination, address)
            and (comment is None or t.comment == comment)
            and (since is None or t.utime >= since)
        ]
        return out[:limit]

    async def get_transaction_by_hash(
        self, tx_hash: str, address: str | None = None
    ) -> TxInfo | None:
        for t in self.transactions:
            if t.tx_hash == tx_hash:
                return t
        return None

    async def get_public_key(self, address: str) -> bytes | None:
        return self.public_keys.get(normalize_address(address))

    async def close(self) -> None:
        return None


_ton_client: TonClient | None = None


def get_ton_client() -> TonClient:
    global _ton_client
    if _ton_client is None:
        _ton_client = MockTonClient() if settings.TON_VERIFY_MODE == "mock" else ToncenterClient()
    return _ton_client


def set_ton_client(client: TonClient | None) -> None:
    global _ton_client
    _ton_client = client


async def close_ton_client() -> None:
    global _ton_client
    if _ton_client is not None:
        await _ton_client.close()
        _ton_client = None


# ------------------------------------------------------------------ ton_proof
def build_ton_proof_message(
    address: str, domain: str, timestamp: int, payload: str
) -> bytes:
    """Дайджест, который кошелёк подписывает при ton_proof (TON Connect v2).

    По спецификации подпись ставится на ДВОЙНОЙ хэш:

        message = "ton-proof-item-v2/" ++ Address ++ AppDomain ++ Timestamp ++ Payload
        digest  = sha256(0xffff ++ "ton-connect" ++ sha256(message))

    Внешний sha256 обязателен: без него подпись настоящего кошелька не сойдётся.
    """
    wc_str, _, hex_hash = normalize_address(address).partition(":")
    workchain = int(wc_str)
    addr_hash = bytes.fromhex(hex_hash)
    domain_bytes = domain.encode()

    message = (
        TON_PROOF_PREFIX
        + workchain.to_bytes(4, "big", signed=True)
        + addr_hash
        + len(domain_bytes).to_bytes(4, "little")
        + domain_bytes
        + timestamp.to_bytes(8, "little")
        + payload.encode()
    )
    return hashlib.sha256(TON_CONNECT_PREFIX + hashlib.sha256(message).digest()).digest()


def pubkeys_from_state_init(state_init_b64: str, address: str) -> list[bytes]:
    """Кандидаты публичных ключей из state_init кошелька.

    Нужно кошелькам, ещё не задеплоенным в сети: get-метода `get_public_key`
    у них нет. Раскладка данных зависит от версии кошелька:

        v3 / v4:  seqno:32, wallet_id:32, public_key:256
        v5 (W5):  is_signature_allowed:1, seqno:32, wallet_id:32, public_key:256

    Определять версию по коду не нужно: возвращаем оба варианта, а какой верен —
    покажет проверка подписи. Подделать это нельзя, потому что хэш state_init
    обязан совпадать с адресом кошелька, а он проверяется здесь же.
    """
    try:
        from pytoniq_core import Cell
    except ImportError:  # pragma: no cover - библиотека есть в requirements
        return []
    try:
        cell = Cell.one_from_boc(base64.b64decode(state_init_b64))
    except Exception:  # noqa: BLE001 - любой битый BOC = отказ
        log.warning("ton_proof: state_init не разобрался")
        return []

    _, _, hex_hash = normalize_address(address).partition(":")
    if cell.hash.hex() != hex_hash:
        log.warning("ton_proof: state_init не соответствует адресу кошелька")
        return []

    # StateInit хранит ссылки в порядке code, data — нужна вторая
    data_cell = cell.refs[1] if len(cell.refs) >= 2 else (cell.refs[0] if cell.refs else None)
    if data_cell is None:
        return []

    keys: list[bytes] = []
    for offset in (64, 65):  # v3/v4 и v5
        try:
            slice_ = data_cell.begin_parse()
            slice_.skip_bits(offset)
            key = slice_.load_bytes(32)
        except Exception:  # noqa: BLE001 - не хватило бит: вариант не подходит
            continue
        if key not in keys:
            keys.append(key)
    return keys


async def verify_ton_proof(
    address: str,
    proof_timestamp: int,
    proof_domain: str,
    signature_b64: str,
    payload: str,
    *,
    state_init: str | None = None,
    allowed_domain: str | None = None,
    ttl: int | None = None,
    client: TonClient | None = None,
) -> bool:
    """Проверяет владение кошельком: домен, срок, подпись ed25519 публичным ключом."""
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey

    allowed_domain = allowed_domain or settings.TONCONNECT_DOMAIN
    ttl = ttl if ttl is not None else settings.TONPROOF_PAYLOAD_TTL

    if allowed_domain and proof_domain != allowed_domain:
        log.warning("ton_proof: domain mismatch %s != %s", proof_domain, allowed_domain)
        return False
    now = int(time.time())
    if proof_timestamp > now + 300 or now - proof_timestamp > max(ttl, 900):
        log.warning("ton_proof: stale timestamp %s (now %s)", proof_timestamp, now)
        return False

    client = client or get_ton_client()

    # ключ берём из сети, а для незадеплоенного кошелька — из state_init
    candidates: list[bytes] = []
    try:
        onchain_key = await client.get_public_key(address)
    except TonApiError as exc:
        log.warning("ton_proof: публичный ключ из сети недоступен: %s", exc)
        onchain_key = None
    if onchain_key:
        candidates.append(onchain_key)
    if state_init:
        candidates.extend(k for k in pubkeys_from_state_init(state_init, address) if k not in candidates)

    if not candidates:
        log.warning("ton_proof: публичный ключ кошелька %s не найден", address[:12])
        return False

    try:
        signature = base64.b64decode(signature_b64)
    except (binascii.Error, ValueError):
        log.warning("ton_proof: подпись не декодируется")
        return False

    message = build_ton_proof_message(address, proof_domain, proof_timestamp, payload)
    for key in candidates:
        try:
            VerifyKey(key).verify(message, signature)
        except (BadSignatureError, ValueError):
            continue
        return True

    log.warning("ton_proof: подпись не сошлась ни с одним из %s ключей", len(candidates))
    return False


# ------------------------------------------------------------------ платежи
@dataclass(slots=True)
class PaymentCheck:
    ok: bool
    tx: TxInfo | None = None
    reason: str | None = None


async def verify_payment(
    *,
    tx_hash: str | None,
    destination: str,
    min_amount: Decimal,
    comment: str | None = None,
    since: int | None = None,
    client: TonClient | None = None,
    tolerance: Decimal | None = None,
) -> PaymentCheck:
    """Проверяет, что платёж действительно пришёл на наш адрес нужной суммой.

    Основной путь поиска — комментарий-нонс среди входящих транзакций казначейского
    адреса: он устойчив к тому, что TON Connect возвращает фронту хэш внешнего
    сообщения, а не хэш транзакции. Хэш используется как дополнительная сверка.
    """
    if settings.TON_VERIFY_MODE == "mock":
        return PaymentCheck(ok=True, tx=None, reason="mock-mode")

    if not destination:
        return PaymentCheck(ok=False, reason="Treasury address is not configured")

    client = client or get_ton_client()
    tolerance = tolerance if tolerance is not None else Decimal(str(settings.PAYMENT_AMOUNT_TOLERANCE))

    # Недоступность TON API трактуем как «платёж пока не виден», а не как отказ:
    # фронт продолжит опрашивать, и временный сбой или лимит запросов не выбьет
    # пользователя из оплаты.
    candidates: list[TxInfo] = []
    try:
        if comment:
            candidates = await client.find_incoming(destination, comment=comment, since=since)
        if not candidates and tx_hash:
            found = await client.get_transaction_by_hash(tx_hash, destination)
            if found:
                candidates = [found]
    except TonApiError as exc:
        log.warning("payment check postponed: %s", exc)
        return PaymentCheck(ok=False, reason="Transaction is not found on-chain yet")

    if not candidates:
        return PaymentCheck(ok=False, reason="Transaction not found on-chain")

    for tx in candidates:
        if not same_address(tx.destination, destination):
            continue
        if tx.value_ton + tolerance < min_amount:
            continue
        return PaymentCheck(ok=True, tx=tx)

    return PaymentCheck(ok=False, reason="Transaction amount or destination mismatch")
