"""Provider-neutral projects: planning and append-only links to real expenses.

A project is an analytic dimension of the canonical ledger, not a new balance,
Movement, category, budget, or cash-flow authority (ADR-0030, issue #262).
Only one current link exists for a Movement; persistence must enforce the
linear revision chain under concurrency. Reversals follow their original.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum
from collections.abc import Iterable
from uuid import UUID

from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.accounts import (
    FinancialAccountRecord,
    FinancialAccountStatus,
)
from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.movements import FinancialMovementRole, FinancialResultEffect

PROJECT_TITLE_MAX_LENGTH = 96
PROJECT_DESCRIPTION_MAX_LENGTH = 280
PROJECT_PERCENT_SCALE = 2
PROJECTS_PER_OWNER_MAX = 200

_ALLOWED_SCOPES = frozenset(
    (FinancialVisibilityScope.PERSONAL, FinancialVisibilityScope.HOUSEHOLD)
)


def _text(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    cleaned = value.strip()
    if not 1 <= len(cleaned) <= maximum:
        raise ValueError(f"{field} length is invalid")
    if any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise ValueError(f"{field} contains control characters")
    return cleaned


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("description must be a string")
    if not value.strip():
        return None
    return _text(value, "description", PROJECT_DESCRIPTION_MAX_LENGTH)


def _scope(value: FinancialVisibilityScope) -> None:
    if not isinstance(value, FinancialVisibilityScope) or value not in _ALLOWED_SCOPES:
        raise ValueError("project audience must be PERSONAL or HOUSEHOLD")


def _positive_money(value: Money) -> None:
    if not isinstance(value, Money):
        raise TypeError("planned must be Money")
    if value.amount <= 0:
        raise ValueError("planned must be positive")


def _date(value: date | None) -> None:
    if value is not None and (
        isinstance(value, datetime) or not isinstance(value, date)
    ):
        raise TypeError("target_date must be a plain date")


def _version(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("version must be a positive integer")


def _aware(value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("timestamp must be timezone-aware")


class FinancialProjectProgressStatus(StrEnum):
    UNDER = "UNDER"
    AT = "AT"
    OVER = "OVER"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialProjectDraft:
    title: str
    description: str | None
    visibility_scope: FinancialVisibilityScope
    planned: Money
    target_date: date | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "title", _text(self.title, "title", PROJECT_TITLE_MAX_LENGTH)
        )
        object.__setattr__(self, "description", _optional_text(self.description))
        _scope(self.visibility_scope)
        _positive_money(self.planned)
        _date(self.target_date)

    def canonical_material(self) -> tuple[str | None, ...]:
        return (
            self.title,
            self.description,
            self.visibility_scope.value,
            self.planned.currency,
            self.planned.canonical_amount,
            self.target_date.isoformat() if self.target_date is not None else None,
        )

    def __repr__(self) -> str:
        return "FinancialProjectDraft(<financial-planning-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialProjectReplacement:
    expected_version: int
    title: str
    description: str | None
    planned: Money
    target_date: date | None

    def __post_init__(self) -> None:
        _version(self.expected_version)
        object.__setattr__(
            self, "title", _text(self.title, "title", PROJECT_TITLE_MAX_LENGTH)
        )
        object.__setattr__(self, "description", _optional_text(self.description))
        _positive_money(self.planned)
        _date(self.target_date)

    def __repr__(self) -> str:
        return "FinancialProjectReplacement(<financial-planning-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialProjectRecord:
    id: UUID
    residence_id: UUID
    owner_operator_id: UUID
    visibility_scope: FinancialVisibilityScope
    title: str
    description: str | None
    planned: Money
    target_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        # Membership and residence identifiers are UUIDs, not required UUIDv4.
        for value in (self.residence_id, self.owner_operator_id):
            if not isinstance(value, UUID):
                raise TypeError("residence and owner must be UUID")
        _scope(self.visibility_scope)
        object.__setattr__(
            self, "title", _text(self.title, "title", PROJECT_TITLE_MAX_LENGTH)
        )
        object.__setattr__(self, "description", _optional_text(self.description))
        _positive_money(self.planned)
        _date(self.target_date)
        _version(self.version)
        _aware(self.created_at)
        _aware(self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at precedes created_at")

    def __repr__(self) -> str:
        return "FinancialProjectRecord(<identity-and-planning-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialProjectLinkRevisionDraft:
    """One desired current link, or None to unlink; CAS is predecessor ID."""

    movement_id: UUID
    project_id: UUID | None
    expected_predecessor_id: UUID | None

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.movement_id)
        if self.project_id is not None:
            validate_financial_resource_id(self.project_id)
        if self.expected_predecessor_id is not None:
            validate_financial_resource_id(self.expected_predecessor_id)
        if self.project_id is None and self.expected_predecessor_id is None:
            raise ValueError("cannot unlink an unlinked movement")

    def canonical_material(self) -> tuple[str | None, ...]:
        return (
            str(self.movement_id),
            str(self.project_id) if self.project_id is not None else None,
            str(self.expected_predecessor_id)
            if self.expected_predecessor_id is not None
            else None,
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialProjectLinkRevisionRecord:
    """Immutable member of a linear chain keyed by original Movement ID."""

    id: UUID
    movement_id: UUID
    project_id: UUID | None
    supersedes_id: UUID | None
    revision: int
    actor_operator_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        validate_financial_resource_id(self.movement_id)
        if not isinstance(self.actor_operator_id, UUID):
            raise TypeError("actor_operator_id must be UUID")
        if self.project_id is not None:
            validate_financial_resource_id(self.project_id)
        if self.supersedes_id is not None:
            validate_financial_resource_id(self.supersedes_id)
        _version(self.revision)
        _aware(self.created_at)
        if self.revision == 1 and (
            self.supersedes_id is not None or self.project_id is None
        ):
            raise ValueError("first link must select one project without predecessor")
        if self.revision > 1 and self.supersedes_id is None:
            raise ValueError("link revision must refer to predecessor")
        if self.supersedes_id == self.id:
            raise ValueError("link cannot supersede itself")

    def __repr__(self) -> str:
        return (
            f"FinancialProjectLinkRevisionRecord(revision={self.revision}, "
            "<ids-redacted>)"
        )


def is_project_expense_eligible(
    *,
    project: FinancialProjectRecord,
    account: FinancialAccountRecord,
    movement: FinancialMovementRecord,
    for_new_link: bool,
) -> bool:
    """Fail-closed v1 audience and ledger eligibility; database rechecks it."""
    return (
        project.residence_id == account.residence_id
        and project.owner_operator_id == account.owner_operator_id
        and project.visibility_scope is account.visibility_scope
        and project.planned.currency == account.currency == movement.amount.currency
        and project.visibility_scope in _ALLOWED_SCOPES
        and movement.account_id == account.id
        and movement.role is FinancialMovementRole.STANDARD
        and movement.result_effect is FinancialResultEffect.EXPENSE
        and movement.amount.amount < 0
        and (not for_new_link or account.status is FinancialAccountStatus.ACTIVE)
    )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialProjectExpenseFact:
    """Only a linked original expense and its optional canonical full reversal."""

    project_id: UUID
    original: FinancialMovementRecord
    reversal: FinancialMovementRecord | None = None

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.project_id)
        original = self.original
        if (
            not isinstance(original, FinancialMovementRecord)
            or original.role is not FinancialMovementRole.STANDARD
            or original.result_effect is not FinancialResultEffect.EXPENSE
            or original.amount.amount >= 0
        ):
            raise ValueError("project fact needs a STANDARD EXPENSE original")
        reversed_by = self.reversal
        if reversed_by is None:
            return
        if not isinstance(reversed_by, FinancialMovementRecord) or (
            reversed_by.role is not FinancialMovementRole.REVERSAL
            or reversed_by.reversal_of_id != original.id
            or reversed_by.account_id != original.account_id
            or reversed_by.amount.currency != original.amount.currency
            or reversed_by.amount.amount != -original.amount.amount
        ):
            raise ValueError("project reversal must fully reverse the same original")

    @property
    def realized(self) -> Money:
        value = -self.original.amount.amount
        if self.reversal is not None:
            value -= self.reversal.amount.amount
        return Money(value, self.original.amount.currency)


@dataclass(frozen=True, slots=True, repr=False)
class FinancialProjectSummary:
    project: FinancialProjectRecord
    realized: Money
    remaining: Money
    excess: Money
    progress_percent: Decimal
    progress_status: FinancialProjectProgressStatus
    expense_count: int

    def __repr__(self) -> str:
        return "FinancialProjectSummary(<financials-redacted>)"


def summarize_project(
    project: FinancialProjectRecord,
    expenses: Iterable[FinancialProjectExpenseFact],
) -> FinancialProjectSummary:
    """Derive result from the unique current links, never from cached money."""
    total = Decimal(0)
    seen: set[UUID] = set()
    count = 0
    for fact in expenses:
        if not isinstance(fact, FinancialProjectExpenseFact):
            raise TypeError("expenses must contain FinancialProjectExpenseFact")
        if fact.project_id != project.id:
            raise ValueError("expense linked to another project")
        if fact.original.id in seen:
            raise ValueError("the same Movement cannot be counted twice")
        if fact.original.amount.currency != project.planned.currency:
            raise ValueError("expense currency differs from project")
        seen.add(fact.original.id)
        count += 1
        total += fact.realized.amount
    planned = project.planned.amount
    with localcontext() as context:
        context.prec = 60
        percent = (total * Decimal(100) / planned).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    status = (
        FinancialProjectProgressStatus.UNDER
        if total < planned
        else FinancialProjectProgressStatus.AT
        if total == planned
        else FinancialProjectProgressStatus.OVER
    )
    return FinancialProjectSummary(
        project=project,
        realized=Money(total, project.planned.currency),
        remaining=Money(max(planned - total, Decimal(0)), project.planned.currency),
        excess=Money(max(total - planned, Decimal(0)), project.planned.currency),
        progress_percent=percent,
        progress_status=status,
        expense_count=count,
    )


__all__ = [
    "PROJECT_TITLE_MAX_LENGTH",
    "PROJECT_DESCRIPTION_MAX_LENGTH",
    "PROJECTS_PER_OWNER_MAX",
    "FinancialProjectDraft",
    "FinancialProjectReplacement",
    "FinancialProjectRecord",
    "FinancialProjectLinkRevisionDraft",
    "FinancialProjectLinkRevisionRecord",
    "FinancialProjectExpenseFact",
    "FinancialProjectSummary",
    "FinancialProjectProgressStatus",
    "is_project_expense_eligible",
    "summarize_project",
]
