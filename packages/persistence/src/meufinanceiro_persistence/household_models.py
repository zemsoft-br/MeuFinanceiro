"""Household persistence models and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

_RESIDENCE_WHITESPACE = re.compile(r"\s+")


class HouseholdPersistenceError(RuntimeError):
    """Base household persistence error with stable diagnostics."""


class HouseholdBootstrapConflictError(HouseholdPersistenceError):
    pass


class ResidenceStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMINISTRATOR = "administrator"
    MEMBER = "member"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


def normalize_residence_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("residence name must be a string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("residence name contains control characters")
    normalized = _RESIDENCE_WHITESPACE.sub(" ", value.strip())
    if not 1 <= len(normalized) <= 96:
        raise ValueError("residence name length is invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class PrimaryResidenceRecord:
    installation_id: UUID
    residence_id: UUID
    membership_id: UUID
    operator_id: UUID
    residence_name: str
    membership_role: MembershipRole
    residence_status: ResidenceStatus
    membership_status: MembershipStatus
    created_at: datetime

    def __post_init__(self) -> None:
        normalize_residence_name(self.residence_name)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
