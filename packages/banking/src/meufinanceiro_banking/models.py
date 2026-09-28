"""Provider-neutral immutable models for banking integrations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Generic, TypeVar

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
    return _clean_text(
        value,
        field_name,
        max_length=_IDENTIFIER_MAX_LENGTH,
    )


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


def _require_non_negative(value: Decimal, field_name: str) -> Decimal:
    amount = _require_decimal(value, field_name)
    if amount < 0:
        raise ValueError(f"{field_name} must not be negative")
    return amount


class Capability(StrEnum):
    """Capabilities observed for one external connection."""

    IDENTITY = "identity"
    BANK_ACCOUNTS = "bank_accounts"
    CREDIT_ACCOUNTS = "credit_accounts"
    TRANSACTIONS = "transactions"
    CREDIT_CARD_BILLS = "credit_card_bills"
    INVESTMENTS = "investments"
    LOANS = "loans"
    MANUAL_REFRESH = "manual_refresh"
    CONSENT_RENEWAL = "consent_renewal"
    DISCONNECT = "disconnect"
    WEBHOOKS = "webhooks"


class CapabilityState(StrEnum):
    """Neutral evidence state for one capability."""

    SUPPORTED = "SUPPORTED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    REQUIRES_USER_ACTION = "REQUIRES_USER_ACTION"
    NOT_OBSERVED = "NOT_OBSERVED"
    UNKNOWN = "UNKNOWN"


class CapabilitySource(StrEnum):
    """Origin of a capability assertion."""

    CONTRACT = "CONTRACT"
    OBSERVATION = "OBSERVATION"
    OPERATION = "OPERATION"


class ConnectionStatus(StrEnum):
    """Provider-neutral lifecycle state for an external connection."""

    PENDING_USER_ACTION = "PENDING_USER_ACTION"
    SYNC_REQUESTED = "SYNC_REQUESTED"
    SYNCING = "SYNCING"
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    REAUTHENTICATION_REQUIRED = "REAUTHENTICATION_REQUIRED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    DISCONNECTED = "DISCONNECTED"
    FAILED = "FAILED"


class TransactionStatus(StrEnum):
    """Neutral transaction reconciliation state."""

    CONFIRMED = "CONFIRMED"
    PENDING = "PENDING"
    INFERRED = "INFERRED"
    DELETED = "DELETED"


class AccountType(StrEnum):
    """Broad account classification independent from a provider."""

    BANK = "BANK"
    CREDIT = "CREDIT"
    INVESTMENT = "INVESTMENT"
    LOAN = "LOAN"
    OTHER = "OTHER"


class ConnectionIntentKind(StrEnum):
    """Purpose of a short-lived connection intent."""

    CONNECT = "CONNECT"
    REAUTHENTICATE = "REAUTHENTICATE"


class RefreshStatus(StrEnum):
    """Outcome of a manual refresh request."""

    REQUESTED = "REQUESTED"
    RATE_LIMITED = "RATE_LIMITED"
    REQUIRES_USER_ACTION = "REQUIRES_USER_ACTION"
    REJECTED = "REJECTED"


class CreditCardBillStatus(StrEnum):
    """Neutral status for a credit-card bill."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ConnectionCapability:
    capability: Capability
    state: CapabilityState
    observed_at: datetime
    source: CapabilitySource
    provider_reason_code: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
        reason = _clean_optional_text(
            self.provider_reason_code,
            "provider_reason_code",
            max_length=_REASON_CODE_MAX_LENGTH,
        )
        object.__setattr__(self, "provider_reason_code", reason)


@dataclass(frozen=True, slots=True)
class ConnectionIntent:
    intent_id: str
    kind: ConnectionIntentKind
    residence_id: str
    actor_id: str
    expires_at: datetime
    external_connection_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "intent_id",
            _clean_identifier(self.intent_id, "intent_id"),
        )
        object.__setattr__(
            self,
            "residence_id",
            _clean_identifier(self.residence_id, "residence_id"),
        )
        object.__setattr__(
            self,
            "actor_id",
            _clean_identifier(self.actor_id, "actor_id"),
        )
        external_connection_id = _clean_optional_text(
            self.external_connection_id,
            "external_connection_id",
            max_length=_IDENTIFIER_MAX_LENGTH,
        )
        object.__setattr__(
            self,
            "external_connection_id",
            external_connection_id,
        )
        _require_aware(self.expires_at, "expires_at")
        if (
            self.kind is ConnectionIntentKind.REAUTHENTICATE
            and external_connection_id is None
        ):
            raise ValueError("external_connection_id is required for reauthentication")


@dataclass(frozen=True, slots=True)
class ConnectionState:
    external_connection_id: str
    status: ConnectionStatus
    capabilities: tuple[ConnectionCapability, ...]
    last_successful_sync_at: datetime | None = None
    last_attempt_at: datetime | None = None
    next_refresh_allowed_at: datetime | None = None
    consent_expires_at: datetime | None = None
    requires_user_action: bool = False
    provider_reason_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "external_connection_id",
            _clean_identifier(
                self.external_connection_id,
                "external_connection_id",
            ),
        )
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        capability_names = [item.capability for item in self.capabilities]
        if len(capability_names) != len(set(capability_names)):
            raise ValueError("capabilities must not contain duplicates")
        for field_name in (
            "last_successful_sync_at",
            "last_attempt_at",
            "next_refresh_allowed_at",
            "consent_expires_at",
        ):
            _require_aware(getattr(self, field_name), field_name)
        reason = _clean_optional_text(
            self.provider_reason_code,
            "provider_reason_code",
            max_length=_REASON_CODE_MAX_LENGTH,
        )
        object.__setattr__(self, "provider_reason_code", reason)
        expected_user_action = self.status in {
            ConnectionStatus.PENDING_USER_ACTION,
            ConnectionStatus.REAUTHENTICATION_REQUIRED,
        }
        if expected_user_action and not self.requires_user_action:
            raise ValueError("requires_user_action must be true for the current status")
        if self.status is ConnectionStatus.DISCONNECTED and self.requires_user_action:
            raise ValueError("a disconnected connection cannot require user action")


@dataclass(frozen=True, slots=True)
class ExternalAccount:
    external_account_id: str
    external_connection_id: str
    account_type: AccountType
    subtype: str
    currency: str
    name: str | None = None
    number_mask: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "external_account_id",
            _clean_identifier(self.external_account_id, "external_account_id"),
        )
        object.__setattr__(
            self,
            "external_connection_id",
            _clean_identifier(
                self.external_connection_id,
                "external_connection_id",
            ),
        )
        object.__setattr__(self, "subtype", _clean_text(self.subtype, "subtype"))
        object.__setattr__(self, "currency", _clean_currency(self.currency))
        object.__setattr__(
            self,
            "name",
            _clean_optional_text(self.name, "name"),
        )
        object.__setattr__(
            self,
            "number_mask",
            _clean_optional_text(
                self.number_mask,
                "number_mask",
                max_length=32,
            ),
        )


@dataclass(frozen=True, slots=True)
class InstallmentMetadata:
    installment_number: int
    installment_count: int
    total_amount: Decimal | None = None

    def __post_init__(self) -> None:
        if self.installment_number < 1:
            raise ValueError("installment_number must be at least one")
        if self.installment_count < self.installment_number:
            raise ValueError(
                "installment_count must be greater than or equal to installment_number"
            )
        if self.total_amount is not None:
            _require_non_negative(self.total_amount, "total_amount")


@dataclass(frozen=True, slots=True)
class ExternalTransaction:
    external_account_id: str
    status: TransactionStatus
    effective_date: date
    amount: Decimal
    currency: str
    external_transaction_id: str | None = None
    provider_updated_at: datetime | None = None
    description: str | None = None
    category: str | None = None
    bill_reference: str | None = None
    installment_metadata: InstallmentMetadata | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "external_account_id",
            _clean_identifier(self.external_account_id, "external_account_id"),
        )
        external_transaction_id = _clean_optional_text(
            self.external_transaction_id,
            "external_transaction_id",
            max_length=_IDENTIFIER_MAX_LENGTH,
        )
        object.__setattr__(
            self,
            "external_transaction_id",
            external_transaction_id,
        )
        _require_decimal(self.amount, "amount")
        object.__setattr__(self, "currency", _clean_currency(self.currency))
        _require_aware(self.provider_updated_at, "provider_updated_at")
        for field_name in ("description", "category", "bill_reference"):
            object.__setattr__(
                self,
                field_name,
                _clean_optional_text(getattr(self, field_name), field_name),
            )
        if self.status is TransactionStatus.INFERRED and external_transaction_id:
            raise ValueError(
                "an inferred transaction cannot claim a provider transaction ID"
            )


PageRecord = TypeVar("PageRecord")


@dataclass(frozen=True, slots=True)
class ExternalPage(Generic[PageRecord]):
    records: tuple[PageRecord, ...]
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
            _clean_text(self.source_window, "source_window", max_length=256),
        )
        _require_aware(self.retrieved_at, "retrieved_at")


@dataclass(frozen=True, slots=True)
class ExternalCreditCardBill:
    external_bill_id: str
    external_account_id: str
    status: CreditCardBillStatus
    due_date: date
    total_amount: Decimal
    currency: str
    close_date: date | None = None
    minimum_payment: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "external_bill_id",
            _clean_identifier(self.external_bill_id, "external_bill_id"),
        )
        object.__setattr__(
            self,
            "external_account_id",
            _clean_identifier(self.external_account_id, "external_account_id"),
        )
        _require_non_negative(self.total_amount, "total_amount")
        if self.minimum_payment is not None:
            _require_non_negative(self.minimum_payment, "minimum_payment")
            if self.minimum_payment > self.total_amount:
                raise ValueError("minimum_payment must not exceed total_amount")
        object.__setattr__(self, "currency", _clean_currency(self.currency))


@dataclass(frozen=True, slots=True)
class ExternalInvestment:
    external_investment_id: str
    external_connection_id: str
    name: str
    kind: str
    balance: Decimal
    currency: str
    as_of: datetime
    external_account_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "external_investment_id",
            _clean_identifier(
                self.external_investment_id,
                "external_investment_id",
            ),
        )
        object.__setattr__(
            self,
            "external_connection_id",
            _clean_identifier(
                self.external_connection_id,
                "external_connection_id",
            ),
        )
        object.__setattr__(self, "name", _clean_text(self.name, "name"))
        object.__setattr__(self, "kind", _clean_text(self.kind, "kind"))
        _require_non_negative(self.balance, "balance")
        object.__setattr__(self, "currency", _clean_currency(self.currency))
        _require_aware(self.as_of, "as_of")
        account_id = _clean_optional_text(
            self.external_account_id,
            "external_account_id",
            max_length=_IDENTIFIER_MAX_LENGTH,
        )
        object.__setattr__(self, "external_account_id", account_id)


@dataclass(frozen=True, slots=True)
class ExternalLoan:
    external_loan_id: str
    external_connection_id: str
    kind: str
    outstanding_balance: Decimal
    currency: str
    as_of: datetime
    contracted_at: date | None = None
    due_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "external_loan_id",
            _clean_identifier(self.external_loan_id, "external_loan_id"),
        )
        object.__setattr__(
            self,
            "external_connection_id",
            _clean_identifier(
                self.external_connection_id,
                "external_connection_id",
            ),
        )
        object.__setattr__(self, "kind", _clean_text(self.kind, "kind"))
        _require_non_negative(self.outstanding_balance, "outstanding_balance")
        object.__setattr__(self, "currency", _clean_currency(self.currency))
        _require_aware(self.as_of, "as_of")
        if (
            self.contracted_at is not None
            and self.due_date is not None
            and self.due_date < self.contracted_at
        ):
            raise ValueError("due_date must not be before contracted_at")


@dataclass(frozen=True, slots=True)
class RefreshRequest:
    request_id: str
    external_connection_id: str
    status: RefreshStatus
    requested_at: datetime
    next_poll_at: datetime | None = None
    next_refresh_allowed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_id",
            _clean_identifier(self.request_id, "request_id"),
        )
        object.__setattr__(
            self,
            "external_connection_id",
            _clean_identifier(
                self.external_connection_id,
                "external_connection_id",
            ),
        )
        _require_aware(self.requested_at, "requested_at")
        _require_aware(self.next_poll_at, "next_poll_at")
        _require_aware(
            self.next_refresh_allowed_at,
            "next_refresh_allowed_at",
        )
        if (
            self.status is RefreshStatus.RATE_LIMITED
            and self.next_refresh_allowed_at is None
        ):
            raise ValueError("next_refresh_allowed_at is required when rate limited")
