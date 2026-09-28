"""Immutable records and validation for banking persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_REASON_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DIAGNOSTIC_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$")
_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_MAX_EXTERNAL_ID = 512
_MAX_SECRET_LENGTH = 16_384


class ProviderConfigurationState(StrEnum):
    DISABLED = "disabled"
    CONFIGURED = "configured"
    ENABLED = "enabled"


class StoredConnectionStatus(StrEnum):
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


class StoredCapability(StrEnum):
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


class StoredCapabilityState(StrEnum):
    SUPPORTED = "SUPPORTED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    REQUIRES_USER_ACTION = "REQUIRES_USER_ACTION"
    NOT_OBSERVED = "NOT_OBSERVED"
    UNKNOWN = "UNKNOWN"


class StoredCapabilitySource(StrEnum):
    CONTRACT = "CONTRACT"
    OBSERVATION = "OBSERVATION"
    OPERATION = "OPERATION"


class StoredSyncTrigger(StrEnum):
    MANUAL = "manual"


class StoredSyncStatus(StrEnum):
    REQUESTED = "requested"
    RUNNING = "running"
    PARTIAL = "partial"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            StoredSyncStatus.PARTIAL,
            StoredSyncStatus.SUCCEEDED,
            StoredSyncStatus.FAILED,
            StoredSyncStatus.CANCELLED,
        }


class StoredSyncErrorCategory(StrEnum):
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    NOT_FOUND = "NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    REQUIRES_USER_ACTION = "REQUIRES_USER_ACTION"
    RATE_LIMITED = "RATE_LIMITED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    CONFLICT = "CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"
    INTERNAL = "INTERNAL"


class StoredExternalAccountType(StrEnum):
    BANK = "BANK"
    CREDIT = "CREDIT"
    INVESTMENT = "INVESTMENT"
    LOAN = "LOAN"
    OTHER = "OTHER"


class StoredExternalAccountStatus(StrEnum):
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"
    DISCONNECTED = "disconnected"


class StoredSyncResource(StrEnum):
    TRANSACTIONS = "transactions"


class BankingPersistenceError(RuntimeError):
    """Base error that never includes credentials or external identifiers."""


class ConfigurationNotFoundError(BankingPersistenceError):
    pass


class ConfigurationConflictError(BankingPersistenceError):
    pass


class ProviderNotEnabledError(BankingPersistenceError):
    pass


class ConnectionNotFoundError(BankingPersistenceError):
    pass


class ConnectionConflictError(BankingPersistenceError):
    pass


class SyncConflictError(BankingPersistenceError):
    pass


class SyncRunNotFoundError(BankingPersistenceError):
    pass


class SyncTransitionError(BankingPersistenceError):
    pass


class ExternalAccountNotFoundError(BankingPersistenceError):
    pass


class SyncCursorNotFoundError(BankingPersistenceError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderConfigurationRecord:
    id: UUID
    installation_id: UUID
    provider: str
    state: ProviderConfigurationState
    configuration_revision: int
    created_at: datetime
    updated_at: datetime
    enabled_at: datetime | None
    disabled_at: datetime | None


@dataclass(frozen=True, slots=True)
class BankingConnectionRecord:
    id: UUID
    installation_id: UUID
    residence_id: UUID
    provider: str
    external_connection_id: str
    status: StoredConnectionStatus
    requires_user_action: bool
    last_successful_sync_at: datetime | None
    last_attempt_at: datetime | None
    next_refresh_allowed_at: datetime | None
    consent_expires_at: datetime | None
    provider_reason_code: str | None
    disconnected_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    capability: StoredCapability
    state: StoredCapabilityState
    source: StoredCapabilitySource
    observed_at: datetime
    provider_reason_code: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        clean_reason_code(self.provider_reason_code)


@dataclass(frozen=True, slots=True)
class ConnectionCapabilityRecord:
    id: UUID
    residence_id: UUID
    connection_id: UUID
    capability: StoredCapability
    state: StoredCapabilityState
    source: StoredCapabilitySource
    provider_reason_code: str | None
    observed_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class ExternalAccountSnapshot:
    external_account_id: str
    account_type: StoredExternalAccountType
    subtype: str
    currency: str
    status: StoredExternalAccountStatus
    observed_at: datetime
    name: str | None = None
    number_mask: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.account_type, StoredExternalAccountType):
            raise TypeError("account_type must be StoredExternalAccountType")
        if not isinstance(self.status, StoredExternalAccountStatus):
            raise TypeError("status must be StoredExternalAccountStatus")
        object.__setattr__(
            self,
            "external_account_id",
            clean_external_account_id(self.external_account_id),
        )
        object.__setattr__(
            self,
            "subtype",
            clean_bounded_text(self.subtype, "subtype", 128),
        )
        object.__setattr__(self, "currency", clean_currency(self.currency))
        object.__setattr__(
            self,
            "name",
            clean_optional_text(self.name, "name", 512),
        )
        object.__setattr__(
            self,
            "number_mask",
            clean_number_mask(self.number_mask),
        )
        require_aware(self.observed_at, "observed_at")

    def __repr__(self) -> str:
        return (
            "ExternalAccountSnapshot("
            f"account_type={self.account_type.value!r}, currency={self.currency!r}, "
            f"status={self.status.value!r}, <external-id-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class SyncRunRecord:
    id: UUID
    residence_id: UUID
    connection_id: UUID
    idempotency_key: str
    trigger: StoredSyncTrigger
    status: StoredSyncStatus
    started_at: datetime | None
    finished_at: datetime | None
    attempt_count: int
    error_category: StoredSyncErrorCategory | None
    provider_reason_code: str | None
    http_status: int | None
    retry_window_bucket: str | None
    records_seen: int
    records_applied: int
    created_at: datetime
    updated_at: datetime

    def __repr__(self) -> str:
        return (
            "SyncRunRecord("
            f"status={self.status.value!r}, attempt_count={self.attempt_count}, "
            f"records_seen={self.records_seen}, records_applied={self.records_applied}, "
            "<scope-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ExternalAccountRecord:
    id: UUID
    residence_id: UUID
    connection_id: UUID
    external_account_id: str
    account_type: StoredExternalAccountType
    subtype: str
    currency: str
    name: str | None
    number_mask: str | None
    status: StoredExternalAccountStatus
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime

    def __repr__(self) -> str:
        return (
            "ExternalAccountRecord("
            f"account_type={self.account_type.value!r}, currency={self.currency!r}, "
            f"status={self.status.value!r}, <external-id-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class SyncCursorRecord:
    id: UUID
    residence_id: UUID
    connection_id: UUID
    external_account_id: str
    resource: StoredSyncResource
    cursor: str
    source_window: str
    committed_at: datetime
    updated_at: datetime

    def __repr__(self) -> str:
        return (
            "SyncCursorRecord("
            f"resource={self.resource.value!r}, committed_at={self.committed_at!r}, "
            "<cursor-redacted>)"
        )


def credential_aad(
    installation_id: UUID,
    provider: str,
    configuration_id: UUID,
    field_name: str,
) -> str:
    normalized_provider = clean_provider(provider)
    if field_name not in {"client_id", "client_secret"}:
        raise ValueError("credential field is not supported")
    return (
        f"meufinanceiro:v1:installation:{installation_id}:"
        f"provider:{normalized_provider}:configuration:{configuration_id}:"
        f"field:{field_name}"
    )


def clean_provider(provider: str) -> str:
    if not isinstance(provider, str) or not _PROVIDER_PATTERN.fullmatch(provider):
        raise ValueError("provider slug is invalid")
    return provider


def clean_secret(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > _MAX_SECRET_LENGTH:
        raise ValueError(f"{field_name} exceeds the supported size")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} contains control characters")
    return value


def clean_external_id(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("external connection id must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_EXTERNAL_ID:
        raise ValueError("external connection id size is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError("external connection id contains control characters")
    return normalized


def clean_external_account_id(value: str) -> str:
    return clean_opaque_text(value, "external account id", _MAX_EXTERNAL_ID)


def clean_idempotency_key(value: str) -> str:
    if not isinstance(value, str) or not _IDEMPOTENCY_PATTERN.fullmatch(value):
        raise ValueError("sync idempotency key is invalid")
    return value


def clean_cursor(value: str) -> str:
    return clean_opaque_text(value, "sync cursor", 512)


def clean_source_window(value: str) -> str:
    return clean_opaque_text(value, "sync source window", 256)


def clean_currency(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or value != value.upper()
    ):
        raise ValueError("currency must be a three-letter uppercase ASCII code")
    return value


def clean_bounded_text(value: str, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise ValueError(f"{field_name} size is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


def clean_opaque_text(value: str, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if (
        not value
        or len(value) > max_length
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} is invalid")
    return value


def clean_optional_text(
    value: str | None,
    field_name: str,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    return clean_bounded_text(value, field_name, max_length)


def clean_number_mask(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = clean_bounded_text(value, "number_mask", 32)
    digit_count = sum(character.isdigit() for character in normalized)
    if digit_count > 4:
        raise ValueError("number_mask must not contain a full numeric account number")
    return normalized


def clean_reason_code(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _REASON_PATTERN.fullmatch(value):
        raise ValueError("provider reason code is invalid")
    return value


def clean_retry_window_bucket(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _DIAGNOSTIC_PATTERN.fullmatch(value):
        raise ValueError("retry window bucket is invalid")
    return value


def clean_http_status(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        raise ValueError("HTTP status is invalid")
    return value


def require_aware(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must be timezone-aware")


def validate_connection_state(
    *,
    status: StoredConnectionStatus,
    requires_user_action: bool,
    disconnected_at: datetime | None,
) -> None:
    expected_user_action = status in {
        StoredConnectionStatus.PENDING_USER_ACTION,
        StoredConnectionStatus.REAUTHENTICATION_REQUIRED,
    }
    if expected_user_action and not requires_user_action:
        raise ValueError("connection status requires user action")
    if status is StoredConnectionStatus.DISCONNECTED:
        if requires_user_action or disconnected_at is None:
            raise ValueError("disconnected connection state is invalid")


def validate_sync_completion(
    *,
    status: StoredSyncStatus,
    error_category: StoredSyncErrorCategory | None,
    provider_reason_code: str | None,
    http_status: int | None,
    retry_window_bucket: str | None,
    records_seen: int,
    records_applied: int,
) -> None:
    if not isinstance(status, StoredSyncStatus) or not status.is_terminal:
        raise ValueError("sync completion status must be terminal")
    if error_category is not None and not isinstance(
        error_category,
        StoredSyncErrorCategory,
    ):
        raise TypeError("error_category must be StoredSyncErrorCategory")
    if (
        isinstance(records_seen, bool)
        or not isinstance(records_seen, int)
        or isinstance(records_applied, bool)
        or not isinstance(records_applied, int)
        or records_seen < 0
        or records_applied < 0
        or records_applied > records_seen
    ):
        raise ValueError("sync record counts are invalid")
    clean_reason_code(provider_reason_code)
    clean_http_status(http_status)
    clean_retry_window_bucket(retry_window_bucket)
    if status is StoredSyncStatus.SUCCEEDED and any(
        value is not None
        for value in (
            error_category,
            provider_reason_code,
            http_status,
            retry_window_bucket,
        )
    ):
        raise ValueError("successful sync cannot contain error diagnostics")
