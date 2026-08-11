"""Canonical provider-neutral financial account contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import validate_currency_code

_NAME_MAX_LENGTH = 96
_CUSTOM_TYPE_MAX_LENGTH = 96


class FinancialAccountType(StrEnum):
    """Canonical account classifications independent from provider taxonomy."""

    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    CASH = "CASH"
    DIGITAL_WALLET = "DIGITAL_WALLET"
    INVESTMENT = "INVESTMENT"
    BENEFIT = "BENEFIT"
    CUSTOM = "CUSTOM"


class FinancialAccountStatus(StrEnum):
    """Lifecycle state of a canonical financial account."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialAccountDraft:
    """Trusted account creation intent before local identity/scope assignment."""

    name: str
    currency: str
    account_type: FinancialAccountType
    visibility_scope: FinancialVisibilityScope
    custom_type_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _clean_text(self.name, "name", _NAME_MAX_LENGTH))
        object.__setattr__(self, "currency", validate_currency_code(self.currency))
        if not isinstance(self.account_type, FinancialAccountType):
            raise TypeError("account_type must be FinancialAccountType")
        if not isinstance(self.visibility_scope, FinancialVisibilityScope):
            raise TypeError("visibility_scope must be FinancialVisibilityScope")

        custom_type_name = _clean_optional_text(
            self.custom_type_name,
            "custom_type_name",
            _CUSTOM_TYPE_MAX_LENGTH,
        )
        if self.account_type is FinancialAccountType.CUSTOM:
            if custom_type_name is None:
                raise ValueError("custom_type_name is required for CUSTOM account")
        elif custom_type_name is not None:
            raise ValueError("custom_type_name is valid only for CUSTOM account")
        object.__setattr__(self, "custom_type_name", custom_type_name)

    def __repr__(self) -> str:
        return (
            "FinancialAccountDraft("
            f"account_type={self.account_type.value!r}, "
            f"visibility_scope={self.visibility_scope.value!r}, "
            f"currency={self.currency!r}, <name-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialAccountRecord:
    """Canonical persisted financial account without any balance field."""

    id: UUID
    residence_id: UUID
    owner_operator_id: UUID
    visibility_scope: FinancialVisibilityScope
    account_type: FinancialAccountType
    custom_type_name: str | None
    name: str
    currency: str
    status: FinancialAccountStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        _require_uuid(self.residence_id, "residence_id")
        _require_uuid(self.owner_operator_id, "owner_operator_id")
        if not isinstance(self.visibility_scope, FinancialVisibilityScope):
            raise TypeError("visibility_scope must be FinancialVisibilityScope")
        if not isinstance(self.account_type, FinancialAccountType):
            raise TypeError("account_type must be FinancialAccountType")
        if not isinstance(self.status, FinancialAccountStatus):
            raise TypeError("status must be FinancialAccountStatus")
        object.__setattr__(self, "name", _clean_text(self.name, "name", _NAME_MAX_LENGTH))
        object.__setattr__(self, "currency", validate_currency_code(self.currency))
        custom_type_name = _clean_optional_text(
            self.custom_type_name,
            "custom_type_name",
            _CUSTOM_TYPE_MAX_LENGTH,
        )
        if self.account_type is FinancialAccountType.CUSTOM:
            if custom_type_name is None:
                raise ValueError("custom_type_name is required for CUSTOM account")
        elif custom_type_name is not None:
            raise ValueError("custom_type_name is valid only for CUSTOM account")
        object.__setattr__(self, "custom_type_name", custom_type_name)
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.status is FinancialAccountStatus.ACTIVE:
            if self.archived_at is not None:
                raise ValueError("active account must not have archived_at")
        else:
            _require_aware(self.archived_at, "archived_at")
            if self.archived_at is not None and self.archived_at < self.created_at:
                raise ValueError("archived_at must not precede created_at")

    def __repr__(self) -> str:
        return (
            "FinancialAccountRecord("
            f"account_type={self.account_type.value!r}, "
            f"visibility_scope={self.visibility_scope.value!r}, "
            f"status={self.status.value!r}, currency={self.currency!r}, "
            "<identity-and-name-redacted>)"
        )


def _clean_text(value: str, field_name: str, max_length: int) -> str:
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


def _clean_optional_text(
    value: str | None,
    field_name: str,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    return _clean_text(value, field_name, max_length)


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


def _require_aware(value: datetime | None, field_name: str) -> None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "FinancialAccountDraft",
    "FinancialAccountRecord",
    "FinancialAccountStatus",
    "FinancialAccountType",
]
