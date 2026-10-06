"""Provider-neutral monthly category budget contracts.

A budget is *planning*: a persisted intent per category and result effect for one
calendar month, one currency and one date basis. It is never a second ledger. It
holds no Movement, no balance and no realized amount; realized values are always
derived at read time from the canonical ledger and the current allocation set
(ADR-0026), so reclassifying a Movement changes the next summary without touching
the budget or the ledger.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.categories import (
    FinancialCategoryRecord,
    FinancialCategoryStatus,
)
from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import Money, validate_currency_code
from meufinanceiro_finance.movements import FinancialResultEffect

BUDGET_NAME_MAX_LENGTH = 96
BUDGET_LINES_MAX = 100
BUDGET_PERCENT_SCALE = 2

_BUDGET_EFFECTS = frozenset(
    (FinancialResultEffect.INCOME, FinancialResultEffect.EXPENSE)
)
_BUDGET_SCOPES = frozenset(
    (FinancialVisibilityScope.PERSONAL, FinancialVisibilityScope.HOUSEHOLD)
)


class FinancialBudgetPeriodKind(StrEnum):
    """Only calendar months exist in v1."""

    MONTHLY = "MONTHLY"


class FinancialBudgetRealizationAccountScope(StrEnum):
    """Which accounts feed the realized and the coverage of a budget (v1).

    Decided by the server from the budget audience and exposed on the wire so no
    client has to infer it. It is deliberately narrower than what the
    classification matrix allows: a PERSONAL or SHARED account may classify a
    Movement under a HOUSEHOLD category, and that Movement is *not* counted in a
    HOUSEHOLD budget (nor flagged in its coverage), because a shared figure must
    never carry one member's personal spending.
    """

    OWNER_PERSONAL_ONLY = "OWNER_PERSONAL_ONLY"  # the owner's PERSONAL accounts
    HOUSEHOLD_ONLY = "HOUSEHOLD_ONLY"  # accounts whose audience is HOUSEHOLD


def budget_realization_account_scope(
    visibility_scope: FinancialVisibilityScope,
) -> FinancialBudgetRealizationAccountScope:
    """The one mapping from budget audience to the accounts it realizes from."""
    if visibility_scope is FinancialVisibilityScope.PERSONAL:
        return FinancialBudgetRealizationAccountScope.OWNER_PERSONAL_ONLY
    if visibility_scope is FinancialVisibilityScope.HOUSEHOLD:
        return FinancialBudgetRealizationAccountScope.HOUSEHOLD_ONLY
    raise ValueError("budget visibility_scope must be PERSONAL or HOUSEHOLD")


class FinancialBudgetDateBasis(StrEnum):
    """Which Movement date places an amount in the budget month."""

    CASH = "CASH"  # effective_date
    COMPETENCE = "COMPETENCE"  # competence_date


class FinancialBudgetLineStatus(StrEnum):
    """Realized compared with planned. Not a judgement: INCOME OVER is good news."""

    UNDER = "UNDER"
    AT = "AT"
    OVER = "OVER"


def budget_period_end(period_start: date) -> date:
    """Return the exclusive end of the month that starts at ``period_start``."""
    validate_budget_period_start(period_start)
    last_day = calendar.monthrange(period_start.year, period_start.month)[1]
    return period_start + timedelta(days=last_day)


def validate_budget_period_start(value: date) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError("period_start must be date")
    if value.day != 1:
        raise ValueError("period_start must be the first day of a month")
    return value


def parse_budget_period(value: str) -> date:
    """Parse a strict ``YYYY-MM`` month into its first day."""
    if not isinstance(value, str):
        raise TypeError("period must be a string")
    if len(value) != 7 or value[4] != "-" or not (value[:4] + value[5:]).isdigit():
        raise ValueError("period must be YYYY-MM")
    year, month = int(value[:4]), int(value[5:])
    if not 1 <= month <= 12 or year < 1:
        raise ValueError("period must be YYYY-MM")
    return date(year, month, 1)


def _clean_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("name must be a string")
    cleaned = value.strip()
    if not 1 <= len(cleaned) <= BUDGET_NAME_MAX_LENGTH:
        raise ValueError(
            f"name must contain between 1 and {BUDGET_NAME_MAX_LENGTH} characters"
        )
    return cleaned


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_effect(value: FinancialResultEffect) -> FinancialResultEffect:
    if not isinstance(value, FinancialResultEffect):
        raise TypeError("result_effect must be FinancialResultEffect")
    if value not in _BUDGET_EFFECTS:
        raise ValueError("result_effect must be INCOME or EXPENSE")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class FinancialBudgetLineDraft:
    """One planned amount for the exact category and effect (no subtree)."""

    category_id: UUID
    result_effect: FinancialResultEffect
    planned: Money

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.category_id)
        _require_effect(self.result_effect)
        if not isinstance(self.planned, Money):
            raise TypeError("planned must be Money")
        if self.planned.amount <= 0:
            raise ValueError("planned amount must be positive")

    @property
    def key(self) -> tuple[UUID, FinancialResultEffect]:
        return (self.category_id, self.result_effect)

    def canonical_material(self) -> tuple[str, str, str, str]:
        return (
            str(self.category_id),
            self.result_effect.value,
            self.planned.currency,
            self.planned.canonical_amount,
        )

    def __repr__(self) -> str:
        return (
            "FinancialBudgetLineDraft("
            f"result_effect={self.result_effect.value!r}, "
            "<category-and-amount-redacted>)"
        )


def _validate_lines(
    lines: Sequence[FinancialBudgetLineDraft], currency: str
) -> tuple[FinancialBudgetLineDraft, ...]:
    if isinstance(lines, (str, bytes)) or not isinstance(lines, Iterable):
        raise TypeError("lines must be a sequence")
    ordered = tuple(lines)
    if not 1 <= len(ordered) <= BUDGET_LINES_MAX:
        raise ValueError(f"a budget needs between 1 and {BUDGET_LINES_MAX} lines")
    seen: set[tuple[UUID, FinancialResultEffect]] = set()
    for line in ordered:
        if not isinstance(line, FinancialBudgetLineDraft):
            raise TypeError("lines must contain FinancialBudgetLineDraft")
        if line.planned.currency != currency:
            raise ValueError("line currency must match the budget currency")
        if line.key in seen:
            raise ValueError("budget lines must be unique per category and effect")
        seen.add(line.key)
    # Digest material must not depend on the order the client sent.
    return tuple(
        sorted(ordered, key=lambda line: (str(line.category_id), line.result_effect))
    )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialBudgetDraft:
    """Trusted budget creation intent. Owner and residence come from the session."""

    name: str
    visibility_scope: FinancialVisibilityScope
    currency: str
    period_start: date
    date_basis: FinancialBudgetDateBasis
    lines: tuple[FinancialBudgetLineDraft, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _clean_name(self.name))
        if (
            not isinstance(self.visibility_scope, FinancialVisibilityScope)
            or self.visibility_scope not in _BUDGET_SCOPES
        ):
            raise ValueError("budget visibility_scope must be PERSONAL or HOUSEHOLD")
        validate_currency_code(self.currency)
        validate_budget_period_start(self.period_start)
        if not isinstance(self.date_basis, FinancialBudgetDateBasis):
            raise TypeError("date_basis must be FinancialBudgetDateBasis")
        object.__setattr__(self, "lines", _validate_lines(self.lines, self.currency))

    @property
    def period_end(self) -> date:
        return budget_period_end(self.period_start)

    def canonical_material(self) -> tuple[object, ...]:
        """Stable material for the create idempotency digest (order-independent)."""
        return (
            self.name,
            self.visibility_scope.value,
            self.currency,
            FinancialBudgetPeriodKind.MONTHLY.value,
            self.period_start.isoformat(),
            self.date_basis.value,
            tuple(line.canonical_material() for line in self.lines),
        )

    def __repr__(self) -> str:
        return (
            "FinancialBudgetDraft("
            f"visibility_scope={self.visibility_scope.value!r}, "
            f"currency={self.currency!r}, date_basis={self.date_basis.value!r}, "
            f"lines={len(self.lines)}, <name-and-period-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialBudgetReplacement:
    """Full replacement of the mutable part (name and lines) under CAS.

    Scope, owner, currency, period and date basis are the budget's identity and
    are immutable: changing them would re-aim the plan at other ledger facts.
    """

    expected_version: int
    name: str
    lines: tuple[FinancialBudgetLineDraft, ...]

    def __post_init__(self) -> None:
        if isinstance(self.expected_version, bool) or not isinstance(
            self.expected_version, int
        ):
            raise TypeError("expected_version must be an integer")
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        object.__setattr__(self, "name", _clean_name(self.name))
        if isinstance(self.lines, (str, bytes)) or not isinstance(self.lines, Iterable):
            raise TypeError("lines must be a sequence")
        ordered = tuple(self.lines)
        if not ordered:
            raise ValueError(f"a budget needs between 1 and {BUDGET_LINES_MAX} lines")
        object.__setattr__(
            self, "lines", _validate_lines(ordered, ordered[0].planned.currency)
        )

    def __repr__(self) -> str:
        return (
            "FinancialBudgetReplacement("
            f"expected_version={self.expected_version}, lines={len(self.lines)}, "
            "<name-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialBudgetLineRecord:
    """One persisted planned line of the current revision."""

    category_id: UUID
    result_effect: FinancialResultEffect
    planned: Money

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.category_id)
        _require_effect(self.result_effect)
        if not isinstance(self.planned, Money) or self.planned.amount <= 0:
            raise ValueError("planned must be positive Money")

    def __repr__(self) -> str:
        return (
            "FinancialBudgetLineRecord("
            f"result_effect={self.result_effect.value!r}, "
            "<category-and-amount-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialBudgetRecord:
    """Canonical persisted budget at its current ``version``."""

    id: UUID
    residence_id: UUID
    owner_operator_id: UUID
    visibility_scope: FinancialVisibilityScope
    name: str
    currency: str
    period_kind: FinancialBudgetPeriodKind
    period_start: date
    date_basis: FinancialBudgetDateBasis
    version: int
    created_at: datetime
    updated_at: datetime
    lines: tuple[FinancialBudgetLineRecord, ...]

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        _require_uuid(self.residence_id, "residence_id")
        _require_uuid(self.owner_operator_id, "owner_operator_id")
        if self.visibility_scope not in _BUDGET_SCOPES:
            raise ValueError("budget visibility_scope must be PERSONAL or HOUSEHOLD")
        object.__setattr__(self, "name", _clean_name(self.name))
        validate_currency_code(self.currency)
        if self.period_kind is not FinancialBudgetPeriodKind.MONTHLY:
            raise ValueError("period_kind must be MONTHLY")
        validate_budget_period_start(self.period_start)
        if not isinstance(self.date_basis, FinancialBudgetDateBasis):
            raise TypeError("date_basis must be FinancialBudgetDateBasis")
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise TypeError("version must be an integer")
        if self.version < 1:
            raise ValueError("version must be positive")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if not 1 <= len(self.lines) <= BUDGET_LINES_MAX:
            raise ValueError("budget record needs between 1 and 100 lines")
        seen: set[tuple[UUID, FinancialResultEffect]] = set()
        for line in self.lines:
            if line.planned.currency != self.currency:
                raise ValueError("line currency must match the budget currency")
            key = (line.category_id, line.result_effect)
            if key in seen:
                raise ValueError("budget lines must be unique per category and effect")
            seen.add(key)

    @property
    def period_end(self) -> date:
        """Exclusive end of the month, derived server-side."""
        return budget_period_end(self.period_start)

    @property
    def realization_account_scope(self) -> FinancialBudgetRealizationAccountScope:
        """Accounts that feed this budget's realized and coverage (server-decided)."""
        return budget_realization_account_scope(self.visibility_scope)

    def __repr__(self) -> str:
        return (
            "FinancialBudgetRecord("
            f"visibility_scope={self.visibility_scope.value!r}, "
            f"version={self.version}, lines={len(self.lines)}, "
            "<identity-and-name-redacted>)"
        )


def is_budget_category_compatible(
    *,
    budget_visibility_scope: FinancialVisibilityScope,
    budget_owner_operator_id: UUID,
    category: FinancialCategoryRecord,
) -> bool:
    """A line category must be ACTIVE and match the budget audience exactly.

    ``PERSONAL`` budget -> ``PERSONAL`` category of the same owner.
    ``HOUSEHOLD`` budget -> ``HOUSEHOLD`` category. Nothing else is valid in v1
    (``SHARED`` budgets do not exist). Knowing a category id proves nothing.
    """
    if category.status is not FinancialCategoryStatus.ACTIVE:
        return False
    if budget_visibility_scope is FinancialVisibilityScope.HOUSEHOLD:
        return category.visibility_scope is FinancialVisibilityScope.HOUSEHOLD
    if budget_visibility_scope is FinancialVisibilityScope.PERSONAL:
        return (
            category.visibility_scope is FinancialVisibilityScope.PERSONAL
            and category.owner_operator_id == budget_owner_operator_id
        )
    return False


def can_edit_budget(*, budget: FinancialBudgetRecord, operator_id: UUID) -> bool:
    """Write authority is the owner's. Reading a HOUSEHOLD budget never implies it."""
    return budget.owner_operator_id == operator_id


@dataclass(frozen=True, slots=True, repr=False)
class FinancialBudgetRealizedRow:
    """Realized magnitude for one exact (category, effect), already netted."""

    category_id: UUID
    result_effect: FinancialResultEffect
    amount: Decimal

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.category_id)
        _require_effect(self.result_effect)
        if not isinstance(self.amount, Decimal):
            raise TypeError("amount must be Decimal")

    def __repr__(self) -> str:
        return (
            "FinancialBudgetRealizedRow("
            f"result_effect={self.result_effect.value!r}, <amount-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialBudgetCoverageSlice:
    """Unclassified economic impact of one effect in the budget window.

    ``amount`` is a net magnitude: a STANDARD Movement without classification
    contributes ``+|amount|``; a REVERSAL of a Movement without classification
    contributes ``-|amount|``; a pair that both fall inside the window cancels.
    ``count`` is the number of such uncancelled items.
    """

    count: int
    amount: Decimal

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise TypeError("count must be an integer")
        if self.count < 0:
            raise ValueError("count must not be negative")
        if not isinstance(self.amount, Decimal):
            raise TypeError("amount must be Decimal")

    def __repr__(self) -> str:
        return f"FinancialBudgetCoverageSlice(count={self.count}, <amount-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialBudgetRealization:
    """Store output: derived realized rows plus the unclassified coverage."""

    rows: tuple[FinancialBudgetRealizedRow, ...]
    unclassified_expense: FinancialBudgetCoverageSlice
    unclassified_income: FinancialBudgetCoverageSlice

    def __repr__(self) -> str:
        return f"FinancialBudgetRealization(rows={len(self.rows)})"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialBudgetLineSummary:
    category_id: UUID
    result_effect: FinancialResultEffect
    planned: Money
    realized: Money
    remaining: Money
    status: FinancialBudgetLineStatus
    progress_percent: Decimal

    def __repr__(self) -> str:
        return (
            "FinancialBudgetLineSummary("
            f"result_effect={self.result_effect.value!r}, "
            f"status={self.status.value!r}, <amounts-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialBudgetCoverage:
    unclassified_expense_count: int
    unclassified_expense: Money
    unclassified_income_count: int
    unclassified_income: Money

    def __repr__(self) -> str:
        return (
            "FinancialBudgetCoverage("
            f"expense_count={self.unclassified_expense_count}, "
            f"income_count={self.unclassified_income_count}, <amounts-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialBudgetSummary:
    budget: FinancialBudgetRecord
    lines: tuple[FinancialBudgetLineSummary, ...]
    coverage: FinancialBudgetCoverage

    def __repr__(self) -> str:
        return f"FinancialBudgetSummary(lines={len(self.lines)})"


def budget_line_status(
    planned: Decimal, realized: Decimal
) -> FinancialBudgetLineStatus:
    if realized < planned:
        return FinancialBudgetLineStatus.UNDER
    if realized == planned:
        return FinancialBudgetLineStatus.AT
    return FinancialBudgetLineStatus.OVER


def budget_progress_percent(planned: Decimal, realized: Decimal) -> Decimal:
    """``realized / planned * 100`` as Decimal, half-up at 2 places.

    Planned is strictly positive by contract (a zero line is invalid), so there
    is no division policy to invent; a non-positive planned fails closed.
    """
    if planned <= 0:
        raise ValueError("planned must be positive")
    with localcontext() as context:
        context.prec = 60
        value = realized * Decimal(100) / planned
        return value.quantize(
            Decimal(1).scaleb(-BUDGET_PERCENT_SCALE), rounding=ROUND_HALF_UP
        )


def summarize_budget(
    budget: FinancialBudgetRecord, realization: FinancialBudgetRealization
) -> FinancialBudgetSummary:
    """Combine planned lines with the derived realization. Pure, no I/O.

    A line with no realized row has realized zero. Realized rows for
    categories/effects without a budget line are ignored (they are not planned);
    only the classified-by-category aggregate is line-scoped, so they never leak
    into coverage either.
    """
    realized_by_key = {
        (r.category_id, r.result_effect): r.amount for r in realization.rows
    }
    summaries = []
    currency = budget.currency
    for line in sorted(
        budget.lines, key=lambda line: (line.result_effect.value, str(line.category_id))
    ):
        planned = line.planned.amount
        realized = realized_by_key.get(
            (line.category_id, line.result_effect), Decimal(0)
        )
        summaries.append(
            FinancialBudgetLineSummary(
                category_id=line.category_id,
                result_effect=line.result_effect,
                planned=Money(planned, currency),
                realized=Money(realized, currency),
                remaining=Money(planned - realized, currency),
                status=budget_line_status(planned, realized),
                progress_percent=budget_progress_percent(planned, realized),
            )
        )
    return FinancialBudgetSummary(
        budget=budget,
        lines=tuple(summaries),
        coverage=FinancialBudgetCoverage(
            unclassified_expense_count=realization.unclassified_expense.count,
            unclassified_expense=Money(
                realization.unclassified_expense.amount, currency
            ),
            unclassified_income_count=realization.unclassified_income.count,
            unclassified_income=Money(realization.unclassified_income.amount, currency),
        ),
    )


__all__ = [
    "BUDGET_LINES_MAX",
    "BUDGET_NAME_MAX_LENGTH",
    "BUDGET_PERCENT_SCALE",
    "FinancialBudgetCoverage",
    "FinancialBudgetCoverageSlice",
    "FinancialBudgetDateBasis",
    "FinancialBudgetDraft",
    "FinancialBudgetLineDraft",
    "FinancialBudgetLineRecord",
    "FinancialBudgetLineStatus",
    "FinancialBudgetLineSummary",
    "FinancialBudgetPeriodKind",
    "FinancialBudgetRealization",
    "FinancialBudgetRealizationAccountScope",
    "FinancialBudgetRealizedRow",
    "FinancialBudgetRecord",
    "FinancialBudgetReplacement",
    "FinancialBudgetSummary",
    "budget_line_status",
    "budget_period_end",
    "budget_progress_percent",
    "budget_realization_account_scope",
    "can_edit_budget",
    "is_budget_category_compatible",
    "parse_budget_period",
    "summarize_budget",
    "validate_budget_period_start",
]
