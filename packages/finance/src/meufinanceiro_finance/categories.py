"""Canonical provider-neutral financial category contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.ids import validate_financial_resource_id

_NAME_MAX_LENGTH = 96


class FinancialCategoryStatus(StrEnum):
    """Lifecycle state for one canonical financial category."""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCategoryDraft:
    """Trusted category creation intent before local scope assignment."""

    name: str
    visibility_scope: FinancialVisibilityScope
    parent_id: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _clean_name(self.name))
        _require_supported_visibility(self.visibility_scope)
        if self.parent_id is not None:
            validate_financial_resource_id(self.parent_id)

    def __repr__(self) -> str:
        return (
            "FinancialCategoryDraft("
            f"visibility_scope={self.visibility_scope.value!r}, "
            f"has_parent={self.parent_id is not None}, <name-and-parent-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCategoryRecord:
    """Canonical persisted category node without Movement semantics."""

    id: UUID
    residence_id: UUID
    owner_operator_id: UUID
    visibility_scope: FinancialVisibilityScope
    parent_id: UUID | None
    name: str
    status: FinancialCategoryStatus
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        _require_uuid(self.residence_id, "residence_id")
        _require_uuid(self.owner_operator_id, "owner_operator_id")
        _require_supported_visibility(self.visibility_scope)
        if self.parent_id is not None:
            validate_financial_resource_id(self.parent_id)
            if self.parent_id == self.id:
                raise ValueError("category must not be its own parent")
        object.__setattr__(self, "name", _clean_name(self.name))
        if not isinstance(self.status, FinancialCategoryStatus):
            raise TypeError("status must be FinancialCategoryStatus")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.status is FinancialCategoryStatus.ACTIVE:
            if self.disabled_at is not None:
                raise ValueError("active category must not have disabled_at")
        else:
            _require_aware(self.disabled_at, "disabled_at")
            if self.disabled_at is not None and self.disabled_at < self.created_at:
                raise ValueError("disabled_at must not precede created_at")

    def __repr__(self) -> str:
        return (
            "FinancialCategoryRecord("
            f"visibility_scope={self.visibility_scope.value!r}, "
            f"status={self.status.value!r}, has_parent={self.parent_id is not None}, "
            "<identity-and-name-redacted>)"
        )


def _require_supported_visibility(value: FinancialVisibilityScope) -> None:
    if not isinstance(value, FinancialVisibilityScope):
        raise TypeError("visibility_scope must be FinancialVisibilityScope")
    if value is FinancialVisibilityScope.SHARED:
        raise ValueError("SHARED category visibility is not supported yet")


def _clean_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("name must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("name must not be empty")
    if len(normalized) > _NAME_MAX_LENGTH:
        raise ValueError(f"name exceeds {_NAME_MAX_LENGTH} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError("name contains control characters")
    return normalized


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


def _require_aware(value: datetime | None, field_name: str) -> None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "FinancialCategoryDraft",
    "FinancialCategoryRecord",
    "FinancialCategoryStatus",
]
