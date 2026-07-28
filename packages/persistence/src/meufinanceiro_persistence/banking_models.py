"""Immutable records and validation for banking persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_REASON_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
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


def clean_reason_code(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _REASON_PATTERN.fullmatch(value):
        raise ValueError("provider reason code is invalid")
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
