"""Identity persistence models with sanitized failures."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

_LOGIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_TOKEN_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class IdentityPersistenceError(RuntimeError):
    """Base identity persistence error with stable diagnostics."""


class IdentityBootstrapConflictError(IdentityPersistenceError):
    pass


class OperatorRole(StrEnum):
    INSTALLATION_ADMIN = "installation_admin"


class OperatorStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


def normalize_operator_login(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("operator login must be a string")
    normalized = value.strip().lower()
    if not _LOGIN_PATTERN.fullmatch(normalized):
        raise ValueError("operator login is invalid")
    return normalized


def validate_token_hash(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("token hash must be a string")
    if not _TOKEN_HASH_PATTERN.fullmatch(value):
        raise ValueError("token hash is invalid")
    return value


def require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class InstallationOperatorRecord:
    installation_id: UUID
    operator_id: UUID
    login_name: str
    role: OperatorRole
    status: OperatorStatus
    created_at: datetime
    primary_residence_id: UUID | None = None
    primary_residence_name: str | None = None

    def __post_init__(self) -> None:
        normalize_operator_login(self.login_name)
        require_aware(self.created_at, "created_at")
        if (self.primary_residence_id is None) != (self.primary_residence_name is None):
            raise ValueError("primary residence context is incomplete")


@dataclass(frozen=True, slots=True, repr=False)
class OperatorAuthenticationMaterial:
    installation_id: UUID
    operator_id: UUID
    login_name: str
    password_hash: str
    role: OperatorRole
    status: OperatorStatus
    failed_attempts: int
    locked_until: datetime | None

    def __post_init__(self) -> None:
        normalize_operator_login(self.login_name)
        if not isinstance(self.password_hash, str) or not self.password_hash:
            raise ValueError("password hash is invalid")
        if self.failed_attempts < 0:
            raise ValueError("failed_attempts must not be negative")
        if self.locked_until is not None:
            require_aware(self.locked_until, "locked_until")

    def __repr__(self) -> str:
        return (
            "OperatorAuthenticationMaterial("
            f"login_name={self.login_name!r}, role={self.role!r}, "
            f"status={self.status!r}, failed_attempts={self.failed_attempts}, "
            "<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class OperatorSessionPrincipal:
    session_id: UUID
    installation_id: UUID
    operator_id: UUID
    login_name: str
    role: OperatorRole
    expires_at: datetime
    primary_residence_id: UUID | None = None

    def __post_init__(self) -> None:
        normalize_operator_login(self.login_name)
        require_aware(self.expires_at, "expires_at")
