"""Provider-neutral manual monthly recurrence contracts (planning, never a ledger).

A recurrence *rule* is a model; an *occurrence* is one persisted instance of that
model for one calendar month. Neither is a financial fact: a PENDING, SKIPPED or
SUPERSEDED occurrence never reaches a balance or a statement. Only an explicit
realization turns one occurrence into exactly one canonical ``STANDARD`` Movement
(ADR-0027); the Movement stays the single realized authority.

Every date here is a plain ``date`` and the calendar is pure: nothing in this
module reads a clock or a timezone. Callers inject ``today`` where a rule needs it.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.manual_entries import (
    FinancialManualEntryDraft,
    FinancialManualEntryType,
)
from meufinanceiro_finance.money import Money, validate_currency_code
from meufinanceiro_finance.movements import FinancialResultEffect

RECURRENCE_DESCRIPTION_MAX_LENGTH = 256
RECURRENCE_LIST_MAX = 200
RECURRENCE_OCCURRENCE_LIST_MAX = 1000
RECURRENCE_GENERATION_MAX_MONTHS = 12
RECURRENCE_GENERATION_HORIZON_MONTHS = 24
RECURRENCE_WINDOW_MAX_MONTHS = 12

_RECURRENCE_EFFECTS = frozenset(
    (FinancialResultEffect.INCOME, FinancialResultEffect.EXPENSE)
)


class FinancialRecurrenceFrequency(StrEnum):
    """Only monthly exists in v1."""

    MONTHLY = "MONTHLY"


class FinancialRecurrenceStatus(StrEnum):
    """A PAUSED rule never generates new occurrences; history is kept."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class FinancialOccurrenceStatus(StrEnum):
    """Lifecycle of one occurrence. Only PENDING can move."""

    PENDING = "PENDING"
    REALIZED = "REALIZED"
    SKIPPED = "SKIPPED"
    SUPERSEDED = "SUPERSEDED"


class FinancialOccurrenceMovementState(StrEnum):
    """Derived state of the linked Movement. Never reopens the occurrence."""

    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"


_OCCURRENCE_TRANSITIONS: dict[
    FinancialOccurrenceStatus, frozenset[FinancialOccurrenceStatus]
] = {
    FinancialOccurrenceStatus.PENDING: frozenset(
        (
            FinancialOccurrenceStatus.REALIZED,
            FinancialOccurrenceStatus.SKIPPED,
            FinancialOccurrenceStatus.SUPERSEDED,
        )
    ),
    FinancialOccurrenceStatus.REALIZED: frozenset(),
    FinancialOccurrenceStatus.SKIPPED: frozenset(),
    FinancialOccurrenceStatus.SUPERSEDED: frozenset(),
}


def can_transition_occurrence(
    current: FinancialOccurrenceStatus, target: FinancialOccurrenceStatus
) -> bool:
    """REALIZED, SKIPPED and SUPERSEDED are terminal and immutable."""
    return target in _OCCURRENCE_TRANSITIONS[current]


# --- pure calendar ----------------------------------------------------------------


def _require_plain_date(value: date, field_name: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{field_name} must be date")
    return value


def validate_recurrence_period_start(value: date) -> date:
    _require_plain_date(value, "period_start")
    if value.day != 1:
        raise ValueError("period_start must be the first day of a month")
    return value


def parse_recurrence_period(value: str) -> date:
    """Parse a strict ``YYYY-MM`` month into its first day."""
    if not isinstance(value, str):
        raise TypeError("period must be a string")
    if len(value) != 7 or value[4] != "-" or not (value[:4] + value[5:]).isdigit():
        raise ValueError("period must be YYYY-MM")
    year, month = int(value[:4]), int(value[5:])
    if not 1 <= month <= 12 or year < 1:
        raise ValueError("period must be YYYY-MM")
    return date(year, month, 1)


def add_months(period_start: date, months: int) -> date:
    """First day of the month ``months`` after ``period_start`` (may be negative)."""
    validate_recurrence_period_start(period_start)
    index = period_start.year * 12 + (period_start.month - 1) + months
    year, month = divmod(index, 12)
    if not 1 <= year <= 9999:
        raise ValueError("period is out of range")
    return date(year, month + 1, 1)


def month_start(value: date) -> date:
    return _require_plain_date(value, "date").replace(day=1)


def months_between(first: date, last: date) -> int:
    """Number of calendar months from ``first`` to ``last`` inclusive."""
    validate_recurrence_period_start(first)
    validate_recurrence_period_start(last)
    return (last.year - first.year) * 12 + (last.month - first.month) + 1


def validate_day_of_month(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("day_of_month must be an integer")
    if not 1 <= value <= 31:
        raise ValueError("day_of_month must be between 1 and 31")
    return value


def monthly_occurrence_date(period_start: date, day_of_month: int) -> date:
    """The scheduled date inside one month.

    The anchor is the day of the month. A day that does not exist in the month
    falls on that month's last day (31 -> 28/29 in February, 30 -> 28/29 in
    February but 30 in April). Plain ``date`` arithmetic, no timezone.
    """
    validate_recurrence_period_start(period_start)
    validate_day_of_month(day_of_month)
    last_day = calendar.monthrange(period_start.year, period_start.month)[1]
    return date(period_start.year, period_start.month, min(day_of_month, last_day))


@dataclass(frozen=True, slots=True)
class FinancialRecurrenceWindow:
    """An inclusive month window ``[from_period, through_period]``."""

    from_period: date
    through_period: date

    def __post_init__(self) -> None:
        validate_recurrence_period_start(self.from_period)
        validate_recurrence_period_start(self.through_period)
        if self.through_period < self.from_period:
            raise ValueError("through_period must not precede from_period")

    @property
    def months(self) -> int:
        return months_between(self.from_period, self.through_period)


def generation_window(
    *, from_period: date, through_period: date, today: date
) -> FinancialRecurrenceWindow:
    """Validate an explicit, bounded generation request.

    At most ``RECURRENCE_GENERATION_MAX_MONTHS`` months, and never further than
    ``RECURRENCE_GENERATION_HORIZON_MONTHS`` months after the month of ``today``
    (the injected clock). Generation is never open-ended.
    """
    window = FinancialRecurrenceWindow(from_period, through_period)
    if window.months > RECURRENCE_GENERATION_MAX_MONTHS:
        raise ValueError(
            f"generation window must not exceed {RECURRENCE_GENERATION_MAX_MONTHS} months"
        )
    horizon = add_months(month_start(today), RECURRENCE_GENERATION_HORIZON_MONTHS)
    if window.through_period > horizon:
        raise ValueError("generation window is beyond the allowed horizon")
    return window


def read_window(
    *, from_period: date, through_period: date
) -> FinancialRecurrenceWindow:
    window = FinancialRecurrenceWindow(from_period, through_period)
    if window.months > RECURRENCE_WINDOW_MAX_MONTHS:
        raise ValueError(
            f"occurrence window must not exceed {RECURRENCE_WINDOW_MAX_MONTHS} months"
        )
    return window


@dataclass(frozen=True, slots=True)
class FinancialScheduledOccurrence:
    """One due month of a rule: the competence month and its scheduled date."""

    period_start: date
    scheduled_date: date


def scheduled_occurrences(
    *,
    start_date: date,
    day_of_month: int,
    end_date: date | None,
    window: FinancialRecurrenceWindow,
) -> tuple[FinancialScheduledOccurrence, ...]:
    """Months of the window whose scheduled date is within ``[start, end]``.

    ``start_date`` and ``end_date`` are inclusive and compared with the *scheduled*
    date, so a rule starting on the 15th does not produce a due date on the 10th of
    that same month, and an end date on the 9th drops the 10th.
    """
    _require_plain_date(start_date, "start_date")
    validate_day_of_month(day_of_month)
    if end_date is not None:
        _require_plain_date(end_date, "end_date")
    due: list[FinancialScheduledOccurrence] = []
    period = window.from_period
    while period <= window.through_period:
        scheduled = monthly_occurrence_date(period, day_of_month)
        if scheduled >= start_date and (end_date is None or scheduled <= end_date):
            due.append(FinancialScheduledOccurrence(period, scheduled))
        period = add_months(period, 1)
    return tuple(due)


# --- validation helpers -------------------------------------------------------------


def _clean_description(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("description must be a string")
    cleaned = value.strip()
    if not 1 <= len(cleaned) <= RECURRENCE_DESCRIPTION_MAX_LENGTH:
        raise ValueError(
            "description must contain between 1 and "
            f"{RECURRENCE_DESCRIPTION_MAX_LENGTH} characters"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise ValueError("description contains control characters")
    return cleaned


def _require_effect(value: FinancialResultEffect) -> FinancialResultEffect:
    if not isinstance(value, FinancialResultEffect):
        raise TypeError("result_effect must be FinancialResultEffect")
    if value not in _RECURRENCE_EFFECTS:
        raise ValueError("result_effect must be INCOME or EXPENSE")
    return value


def _require_positive_money(value: Money, field_name: str) -> Money:
    if not isinstance(value, Money):
        raise TypeError(f"{field_name} must be Money")
    if value.amount <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _require_version(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 1:
        raise ValueError(f"{field_name} must be positive")
    return value


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _validate_rule_shape(
    *, start_date: date, day_of_month: int, end_date: date | None
) -> None:
    _require_plain_date(start_date, "start_date")
    validate_day_of_month(day_of_month)
    if end_date is not None:
        _require_plain_date(end_date, "end_date")
        if end_date < start_date:
            raise ValueError("end_date must not precede start_date")


# --- rule ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, repr=False)
class FinancialRecurrenceDraft:
    """Trusted rule creation intent. Owner and residence come from the session."""

    account_id: UUID
    description: str
    result_effect: FinancialResultEffect
    expected: Money
    start_date: date
    day_of_month: int
    end_date: date | None = None

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.account_id)
        object.__setattr__(self, "description", _clean_description(self.description))
        _require_effect(self.result_effect)
        _require_positive_money(self.expected, "expected")
        _validate_rule_shape(
            start_date=self.start_date,
            day_of_month=self.day_of_month,
            end_date=self.end_date,
        )

    def canonical_material(self) -> tuple[object, ...]:
        """Stable material for the create idempotency digest."""
        return (
            str(self.account_id),
            self.description,
            self.result_effect.value,
            self.expected.currency,
            self.expected.canonical_amount,
            FinancialRecurrenceFrequency.MONTHLY.value,
            self.start_date.isoformat(),
            self.day_of_month,
            self.end_date.isoformat() if self.end_date is not None else None,
        )

    def __repr__(self) -> str:
        return (
            "FinancialRecurrenceDraft("
            f"result_effect={self.result_effect.value!r}, "
            f"currency={self.expected.currency!r}, "
            "<account-description-amount-dates-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialRecurrenceReplacement:
    """Full replacement of the mutable part under CAS.

    Account, effect, currency and ``start_date`` are the rule's identity and stay
    immutable: changing them would re-aim the plan at other ledger facts.
    """

    expected_version: int
    description: str
    expected_amount: Decimal
    day_of_month: int
    end_date: date | None

    def __post_init__(self) -> None:
        _require_version(self.expected_version, "expected_version")
        object.__setattr__(self, "description", _clean_description(self.description))
        if not isinstance(self.expected_amount, Decimal):
            raise TypeError("expected_amount must be Decimal")
        if not self.expected_amount.is_finite() or self.expected_amount <= 0:
            raise ValueError("expected_amount must be positive")
        validate_day_of_month(self.day_of_month)
        if self.end_date is not None:
            _require_plain_date(self.end_date, "end_date")

    def __repr__(self) -> str:
        return (
            "FinancialRecurrenceReplacement("
            f"expected_version={self.expected_version}, "
            "<description-amount-dates-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialRecurrenceRecord:
    """Canonical persisted rule at its current ``version``."""

    id: UUID
    residence_id: UUID
    account_id: UUID
    owner_operator_id: UUID
    description: str
    result_effect: FinancialResultEffect
    expected: Money
    frequency: FinancialRecurrenceFrequency
    start_date: date
    day_of_month: int
    end_date: date | None
    status: FinancialRecurrenceStatus
    version: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        _require_uuid(self.residence_id, "residence_id")
        validate_financial_resource_id(self.account_id)
        _require_uuid(self.owner_operator_id, "owner_operator_id")
        object.__setattr__(self, "description", _clean_description(self.description))
        _require_effect(self.result_effect)
        _require_positive_money(self.expected, "expected")
        validate_currency_code(self.expected.currency)
        if self.frequency is not FinancialRecurrenceFrequency.MONTHLY:
            raise ValueError("frequency must be MONTHLY")
        _validate_rule_shape(
            start_date=self.start_date,
            day_of_month=self.day_of_month,
            end_date=self.end_date,
        )
        if not isinstance(self.status, FinancialRecurrenceStatus):
            raise TypeError("status must be FinancialRecurrenceStatus")
        _require_version(self.version, "version")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")

    def __repr__(self) -> str:
        return (
            "FinancialRecurrenceRecord("
            f"status={self.status.value!r}, version={self.version}, "
            "<identity-and-amounts-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialRecurrenceEditOutcome:
    """A CAS edit and the future PENDING occurrences it explicitly superseded."""

    recurrence: FinancialRecurrenceRecord
    superseded_count: int

    def __post_init__(self) -> None:
        if isinstance(self.superseded_count, bool) or not isinstance(
            self.superseded_count, int
        ):
            raise TypeError("superseded_count must be an integer")
        if self.superseded_count < 0:
            raise ValueError("superseded_count must not be negative")

    def __repr__(self) -> str:
        return (
            f"FinancialRecurrenceEditOutcome(superseded_count={self.superseded_count})"
        )


def can_edit_recurrence(
    *, recurrence: FinancialRecurrenceRecord, operator_id: UUID
) -> bool:
    """Write authority is the rule owner's (the account owner). Reading is wider."""
    return recurrence.owner_operator_id == operator_id


def can_generate_occurrences(recurrence: FinancialRecurrenceRecord) -> bool:
    """A PAUSED rule never generates."""
    return recurrence.status is FinancialRecurrenceStatus.ACTIVE


# --- occurrence -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True, repr=False)
class FinancialRecurrenceRealizationDraft:
    """The explicit user decision that turns one PENDING occurrence into a fact."""

    actual: Money
    effective_date: date
    competence_date: date

    def __post_init__(self) -> None:
        _require_positive_money(self.actual, "actual")
        _require_plain_date(self.effective_date, "effective_date")
        _require_plain_date(self.competence_date, "competence_date")

    def canonical_material(self) -> tuple[str, str, str, str]:
        return (
            self.actual.currency,
            self.actual.canonical_amount,
            self.effective_date.isoformat(),
            self.competence_date.isoformat(),
        )

    def __repr__(self) -> str:
        return "FinancialRecurrenceRealizationDraft(<amount-and-dates-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialRecurrenceRealization:
    """The stable link from a REALIZED occurrence to its one Movement."""

    movement_id: UUID
    actual: Money
    effective_date: date
    competence_date: date
    realized_at: datetime
    movement_state: FinancialOccurrenceMovementState

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.movement_id)
        _require_positive_money(self.actual, "actual")
        _require_plain_date(self.effective_date, "effective_date")
        _require_plain_date(self.competence_date, "competence_date")
        _require_aware(self.realized_at, "realized_at")
        if not isinstance(self.movement_state, FinancialOccurrenceMovementState):
            raise TypeError("movement_state must be FinancialOccurrenceMovementState")

    def __repr__(self) -> str:
        return (
            "FinancialRecurrenceRealization("
            f"movement_state={self.movement_state.value!r}, <identity-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialRecurrenceOccurrenceRecord:
    """One persisted occurrence with the snapshot of the revision that made it."""

    id: UUID
    residence_id: UUID
    recurrence_id: UUID
    account_id: UUID
    owner_operator_id: UUID
    period_start: date
    scheduled_date: date
    rule_version: int
    result_effect: FinancialResultEffect
    expected: Money
    description: str
    status: FinancialOccurrenceStatus
    created_at: datetime
    updated_at: datetime
    realization: FinancialRecurrenceRealization | None = None

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        _require_uuid(self.residence_id, "residence_id")
        validate_financial_resource_id(self.recurrence_id)
        validate_financial_resource_id(self.account_id)
        _require_uuid(self.owner_operator_id, "owner_operator_id")
        validate_recurrence_period_start(self.period_start)
        _require_plain_date(self.scheduled_date, "scheduled_date")
        if month_start(self.scheduled_date) != self.period_start:
            raise ValueError("scheduled_date must fall inside period_start month")
        _require_version(self.rule_version, "rule_version")
        _require_effect(self.result_effect)
        _require_positive_money(self.expected, "expected")
        object.__setattr__(self, "description", _clean_description(self.description))
        if not isinstance(self.status, FinancialOccurrenceStatus):
            raise TypeError("status must be FinancialOccurrenceStatus")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if (self.status is FinancialOccurrenceStatus.REALIZED) != (
            self.realization is not None
        ):
            raise ValueError("only a REALIZED occurrence carries a realization")

    def __repr__(self) -> str:
        return (
            "FinancialRecurrenceOccurrenceRecord("
            f"status={self.status.value!r}, <identity-and-amounts-redacted>)"
        )


def is_occurrence_compatible_with_revision(
    *,
    occurrence: FinancialRecurrenceOccurrenceRecord,
    description: str,
    expected_amount: Decimal,
    day_of_month: int,
    end_date: date | None,
) -> bool:
    """Whether a PENDING occurrence still describes what the new revision plans.

    Compared on what the occurrence would show the user: description, expected
    amount, the scheduled date the new day-of-month implies for its month, and the
    end date. An incompatible future PENDING is SUPERSEDED, never reinterpreted.
    """
    if occurrence.description != description:
        return False
    if occurrence.expected.amount != expected_amount:
        return False
    scheduled = monthly_occurrence_date(occurrence.period_start, day_of_month)
    if scheduled != occurrence.scheduled_date:
        return False
    return end_date is None or scheduled <= end_date


def occurrences_to_supersede(
    *,
    pending: Iterable[FinancialRecurrenceOccurrenceRecord],
    today: date,
    description: str,
    expected_amount: Decimal,
    day_of_month: int,
    end_date: date | None,
) -> tuple[FinancialRecurrenceOccurrenceRecord, ...]:
    """Future PENDING occurrences a rule edit makes stale.

    "Future" is ``scheduled_date >= today`` on the injected clock. An overdue
    PENDING is history the user has not acted on yet and keeps its snapshot.
    """
    _require_plain_date(today, "today")
    return tuple(
        occurrence
        for occurrence in pending
        if occurrence.status is FinancialOccurrenceStatus.PENDING
        and occurrence.scheduled_date >= today
        and not is_occurrence_compatible_with_revision(
            occurrence=occurrence,
            description=description,
            expected_amount=expected_amount,
            day_of_month=day_of_month,
            end_date=end_date,
        )
    )


def recurrence_replacement_changes_rule(
    *,
    recurrence: FinancialRecurrenceRecord,
    replacement: FinancialRecurrenceReplacement,
) -> bool:
    return (
        recurrence.description != replacement.description
        or recurrence.expected.amount != replacement.expected_amount
        or recurrence.day_of_month != replacement.day_of_month
        or recurrence.end_date != replacement.end_date
    )


def occurrence_manual_entry(
    *,
    occurrence: FinancialRecurrenceOccurrenceRecord,
    draft: FinancialRecurrenceRealizationDraft,
) -> FinancialManualEntryDraft:
    """The canonical manual-entry intent for realizing one occurrence.

    The Movement description is the occurrence snapshot; no category, rule or
    allocation is decided here (classification stays a separate, explicit act).
    """
    if occurrence.status is not FinancialOccurrenceStatus.PENDING:
        raise ValueError("only a PENDING occurrence can be realized")
    if draft.actual.currency != occurrence.expected.currency:
        raise ValueError("actual currency must match the occurrence currency")
    entry_type = (
        FinancialManualEntryType.INCOME
        if occurrence.result_effect is FinancialResultEffect.INCOME
        else FinancialManualEntryType.EXPENSE
    )
    return FinancialManualEntryDraft(
        account_id=occurrence.account_id,
        magnitude=draft.actual,
        entry_type=entry_type,
        effective_date=draft.effective_date,
        competence_date=draft.competence_date,
        description=occurrence.description,
    )


__all__ = [
    "RECURRENCE_DESCRIPTION_MAX_LENGTH",
    "RECURRENCE_GENERATION_HORIZON_MONTHS",
    "RECURRENCE_GENERATION_MAX_MONTHS",
    "RECURRENCE_LIST_MAX",
    "RECURRENCE_OCCURRENCE_LIST_MAX",
    "RECURRENCE_WINDOW_MAX_MONTHS",
    "FinancialOccurrenceMovementState",
    "FinancialOccurrenceStatus",
    "FinancialRecurrenceDraft",
    "FinancialRecurrenceEditOutcome",
    "FinancialRecurrenceFrequency",
    "FinancialRecurrenceOccurrenceRecord",
    "FinancialRecurrenceRealization",
    "FinancialRecurrenceRealizationDraft",
    "FinancialRecurrenceRecord",
    "FinancialRecurrenceReplacement",
    "FinancialRecurrenceStatus",
    "FinancialRecurrenceWindow",
    "FinancialScheduledOccurrence",
    "add_months",
    "can_edit_recurrence",
    "can_generate_occurrences",
    "can_transition_occurrence",
    "generation_window",
    "is_occurrence_compatible_with_revision",
    "month_start",
    "monthly_occurrence_date",
    "months_between",
    "occurrence_manual_entry",
    "occurrences_to_supersede",
    "parse_recurrence_period",
    "read_window",
    "recurrence_replacement_changes_rule",
    "scheduled_occurrences",
    "validate_day_of_month",
    "validate_recurrence_period_start",
]
