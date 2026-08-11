"""Provider-neutral audience rules for residence-scoped financial resources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class FinancialVisibilityScope(StrEnum):
    """Audience model for one canonical financial resource."""

    PERSONAL = "PERSONAL"
    SHARED = "SHARED"
    HOUSEHOLD = "HOUSEHOLD"


class FinancialAccessDeniedError(PermissionError):
    """Stable fail-closed error for resources outside the actor audience."""


@dataclass(frozen=True, slots=True, repr=False)
class FinancialActorContext:
    """Trusted membership context derived server-side from authentication."""

    residence_id: UUID
    operator_id: UUID
    membership_active: bool

    def __post_init__(self) -> None:
        _require_uuid(self.residence_id, "residence_id")
        _require_uuid(self.operator_id, "operator_id")
        if not isinstance(self.membership_active, bool):
            raise TypeError("membership_active must be bool")

    def __repr__(self) -> str:
        return (
            "FinancialActorContext("
            f"membership_active={self.membership_active}, <scope-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialResourceAudience:
    """Immutable owner, residence and visibility contract for one resource."""

    residence_id: UUID
    owner_operator_id: UUID
    visibility_scope: FinancialVisibilityScope
    shared_operator_ids: frozenset[UUID] = frozenset()

    def __post_init__(self) -> None:
        _require_uuid(self.residence_id, "residence_id")
        _require_uuid(self.owner_operator_id, "owner_operator_id")
        if not isinstance(self.visibility_scope, FinancialVisibilityScope):
            raise TypeError("visibility_scope must be FinancialVisibilityScope")
        if not isinstance(self.shared_operator_ids, frozenset):
            raise TypeError("shared_operator_ids must be frozenset")
        for operator_id in self.shared_operator_ids:
            _require_uuid(operator_id, "shared_operator_id")

        if self.visibility_scope is not FinancialVisibilityScope.SHARED:
            if self.shared_operator_ids:
                raise ValueError(
                    "explicit grants are valid only for SHARED resources"
                )
        elif self.owner_operator_id in self.shared_operator_ids:
            raise ValueError("resource owner must not have a redundant shared grant")

    def __repr__(self) -> str:
        return (
            "FinancialResourceAudience("
            f"visibility_scope={self.visibility_scope.value!r}, "
            f"shared_count={len(self.shared_operator_ids)}, <scope-redacted>)"
        )


def can_access_financial_resource(
    actor: FinancialActorContext,
    audience: FinancialResourceAudience,
) -> bool:
    """Return whether an active same-residence member belongs to the audience."""

    if not isinstance(actor, FinancialActorContext):
        raise TypeError("actor must be FinancialActorContext")
    if not isinstance(audience, FinancialResourceAudience):
        raise TypeError("audience must be FinancialResourceAudience")

    if not actor.membership_active:
        return False
    if actor.residence_id != audience.residence_id:
        return False

    if audience.visibility_scope is FinancialVisibilityScope.PERSONAL:
        return actor.operator_id == audience.owner_operator_id
    if audience.visibility_scope is FinancialVisibilityScope.SHARED:
        return (
            actor.operator_id == audience.owner_operator_id
            or actor.operator_id in audience.shared_operator_ids
        )
    if audience.visibility_scope is FinancialVisibilityScope.HOUSEHOLD:
        return True

    return False  # pragma: no cover - enum exhaustiveness defense


def require_financial_resource_access(
    actor: FinancialActorContext,
    audience: FinancialResourceAudience,
) -> None:
    """Raise a sanitized error when the actor is outside the resource audience."""

    if not can_access_financial_resource(actor, audience):
        raise FinancialAccessDeniedError("financial resource access denied")


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialAccessDeniedError",
    "FinancialActorContext",
    "FinancialResourceAudience",
    "FinancialVisibilityScope",
    "can_access_financial_resource",
    "require_financial_resource_access",
]
