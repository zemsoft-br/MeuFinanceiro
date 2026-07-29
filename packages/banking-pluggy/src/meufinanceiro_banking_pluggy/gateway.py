"""Sanitized provider-specific snapshots consumed by the Pluggy adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

_IDENTIFIER_MAX_LENGTH = 512
_TEXT_MAX_LENGTH = 512
_REASON_CODE_MAX_LENGTH = 128


def _clean_text(
    value: str,
    field_name: str,
    *,
    max_length: int = _TEXT_MAX_LENGTH,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


def _clean_identifier(value: str, field_name: str) -> str:
    return _clean_text(value, field_name, max_length=_IDENTIFIER_MAX_LENGTH)


def _clean_optional_text(
    value: str | None,
    field_name: str,
    *,
    max_length: int = _TEXT_MAX_LENGTH,
) -> str | None:
    if value is None:
        return None
    return _clean_text(value, field_name, max_length=max_length)


def _clean_currency(value: str) -> str:
    currency = _clean_text(value, "currency", max_length=3).upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise ValueError("currency must be a three-letter ASCII code")
    return currency


def _require_aware(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


class PluggyGatewayErrorCategory(StrEnum):
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    NOT_FOUND = "NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    REQUIRES_USER_ACTION = "REQUIRES_USER_ACTION"
    RATE_LIMITED = "RATE_LIMITED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    CONFLICT = "CONFLICT"
    INTERNAL = "INTERNAL"


class PluggyGatewayError(RuntimeError):
    """Sanitized gateway failure without raw transport diagnostics."""

    __slots__ = ("category", "provider_reason_code", "retryable")

    def __init__(
        self,
        category: PluggyGatewayErrorCategory,
        *,
        retryable: bool,
        provider_reason_code: str | None = None,
    ) -> None:
        reason = _clean_optional_text(
            provider_reason_code,
            "provider_reason_code",
            max_length=_REASON_CODE_MAX_LENGTH,
        )
        super().__init__("pluggy gateway operation failed")
        self.category = category
        self.retryable = retryable
        self.provider_reason_code = reason


class PluggyConnectionPhase(StrEnum):
    CONNECTING = "CONNECTING"
    SYNCING = "SYNCING"
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
    REAUTHENTICATION_REQUIRED = "REAUTHENTICATION_REQUIRED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    DISCONNECTED = "DISCONNECTED"
    FAILED = "FAILED"


class PluggyCapability(StrEnum):
    IDENTITY = "IDENTITY"
    BANK_ACCOUNTS = "BANK_ACCOUNTS"
    CREDIT_ACCOUNTS = "CREDIT_ACCOUNTS"
    TRANSACTIONS = "TRANSACTIONS"


class PluggyCapabilityAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
    NOT_OBSERVED = "NOT_OBSERVED"
    UNKNOWN = "UNKNOWN"


class PluggyCapabilityEvidence(StrEnum):
    CONTRACT = "CONTRACT"
    OBSERVATION = "OBSERVATION"
    OPERATION = "OPERATION"


class PluggyAccountKind(StrEnum):
    BANK = "BANK"
    CREDIT = "CREDIT"
    OTHER = "OTHER"


class PluggyTransactionState(StrEnum):
    POSTED = "POSTED"
    PENDING = "PENDING"


@dataclass(frozen=True, slots=True)
class PluggyCapabilitySnapshot:
    capability: PluggyCapability
    availability: PluggyCapabilityAvailability
    observed_at: datetime
    evidence: PluggyCapabilityEvidence
    provider_reason_code: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
        object.__setattr__(
            self,
            "provider_reason_code",
            _clean_optional_text(
                self.provider_reason_code,
                "provider_reason_code",
                max_length=_REASON_CODE_MAX_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class PluggyItemSnapshot:
    item_id: str
    phase: PluggyConnectionPhase
    capabilities: tuple[PluggyCapabilitySnapshot, ...]
    last_successful_update_at: datetime | None = None
    last_attempt_at: datetime | None = None
    next_refresh_allowed_at: datetime | None = None
    consent_expires_at: datetime | None = None
    provider_reason_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _clean_identifier(self.item_id, "item_id"))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        names = [snapshot.capability for snapshot in self.capabilities]
        if len(names) != len(set(names)):
            raise ValueError("capabilities must not contain duplicates")
        for field_name in (
            "last_successful_update_at",
            "last_attempt_at",
            "next_refresh_allowed_at",
            "consent_expires_at",
        ):
            _require_aware(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "provider_reason_code",
            _clean_optional_text(
                self.provider_reason_code,
                "provider_reason_code",
                max_length=_REASON_CODE_MAX_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class PluggyAccountSnapshot:
    account_id: str
    item_id: str
    kind: PluggyAccountKind
    subtype: str
    currency: str
    name: str | None = None
    number_mask: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "account_id",
            _clean_identifier(self.account_id, "account_id"),
        )
        object.__setattr__(self, "item_id", _clean_identifier(self.item_id, "item_id"))
        object.__setattr__(self, "subtype", _clean_text(self.subtype, "subtype"))
        object.__setattr__(self, "currency", _clean_currency(self.currency))
        object.__setattr__(self, "name", _clean_optional_text(self.name, "name"))
        object.__setattr__(
            self,
            "number_mask",
            _clean_optional_text(self.number_mask, "number_mask", max_length=32),
        )


@dataclass(frozen=True, slots=True)
class PluggyInstallmentSnapshot:
    number: int
    count: int
    total_amount: Decimal | None = None

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("number must be at least one")
        if self.count < self.number:
            raise ValueError("count must be greater than or equal to number")
        if self.total_amount is not None:
            total = _require_decimal(self.total_amount, "total_amount")
            if total < 0:
                raise ValueError("total_amount must not be negative")


@dataclass(frozen=True, slots=True)
class PluggyTransactionSnapshot:
    account_id: str
    state: PluggyTransactionState
    effective_date: date
    amount: Decimal
    currency: str
    transaction_id: str | None = None
    updated_at: datetime | None = None
    description: str | None = None
    category: str | None = None
    bill_reference: str | None = None
    installment: PluggyInstallmentSnapshot | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "account_id",
            _clean_identifier(self.account_id, "account_id"),
        )
        object.__setattr__(
            self,
            "transaction_id",
            _clean_optional_text(
                self.transaction_id,
                "transaction_id",
                max_length=_IDENTIFIER_MAX_LENGTH,
            ),
        )
        _require_decimal(self.amount, "amount")
        object.__setattr__(self, "currency", _clean_currency(self.currency))
        _require_aware(self.updated_at, "updated_at")
        for field_name in ("description", "category", "bill_reference"):
            object.__setattr__(
                self,
                field_name,
                _clean_optional_text(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class PluggyTransactionPageSnapshot:
    records: tuple[PluggyTransactionSnapshot, ...]
    next_cursor: str | None
    source_window: str
    retrieved_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(
            self,
            "next_cursor",
            _clean_optional_text(
                self.next_cursor,
                "next_cursor",
                max_length=_IDENTIFIER_MAX_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "source_window",
            _clean_text(self.source_window, "source_window"),
        )
        _require_aware(self.retrieved_at, "retrieved_at")


@runtime_checkable
class PluggyReadOnlyGateway(Protocol):
    """Provider-specific read contract with no transport or credential surface."""

    def get_item(self, item_id: str) -> PluggyItemSnapshot: ...

    def list_accounts(self, item_id: str) -> tuple[PluggyAccountSnapshot, ...]: ...

    def list_transactions(
        self,
        account_id: str,
        cursor: str | None,
        changed_since: datetime | None,
    ) -> PluggyTransactionPageSnapshot: ...
