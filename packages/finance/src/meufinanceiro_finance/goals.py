"""Provider-neutral financial goal contracts (virtual destination of existing balance).

A goal is *planning*: a title, a currency, a positive target and an optional target
date. The only thing that ties it to money is an append-only history of explicit
virtual ``ALLOCATE`` / ``RELEASE`` events against an account. An allocation is not a
Movement, a transfer, a budget line, a bank balance or blocked money: ``finance.movements``
stays the single realized ledger and every account balance is derived from it
(ADR-0018/0019). The goal never becomes a second monetary authority: "allocated" is
only what was explicitly allocated, and a later expense lowers the bank balance without
rewriting any event (the summary then flags the account as lacking backing, ADR-0029).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.accounts import (
    FinancialAccountRecord,
    FinancialAccountStatus,
)
from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import Money, validate_currency_code

GOAL_TITLE_MAX_LENGTH = 96
GOAL_DESCRIPTION_MAX_LENGTH = 280
GOAL_PERCENT_SCALE = 2
GOALS_PER_OWNER_MAX = 200
GOAL_ACCOUNTS_MAX = 25
GOAL_EVENTS_MAX = 500
# New ALLOCATE events stop earlier so RELEASE always has room (one per account).
GOAL_ALLOCATE_EVENTS_MAX = GOAL_EVENTS_MAX - GOAL_ACCOUNTS_MAX
GOAL_TARGET_DATE_PAST_TOLERANCE_DAYS = 1
GOAL_TARGET_DATE_HORIZON_YEARS = 100

_GOAL_SCOPES = frozenset(
    (FinancialVisibilityScope.PERSONAL, FinancialVisibilityScope.HOUSEHOLD)
)


class FinancialGoalEventKind(StrEnum):
    """Direction of one virtual destination event."""

    ALLOCATE = "ALLOCATE"
    RELEASE = "RELEASE"


class FinancialGoalProgressStatus(StrEnum):
    """Allocated compared with the target. Derived, never stored."""

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    REACHED = "REACHED"
    EXCEEDED = "EXCEEDED"


class FinancialGoalBackingStatus(StrEnum):
    """Whether the account balance still covers everything allocated on it."""

    COVERED = "COVERED"
    INSUFFICIENT = "INSUFFICIENT"


class FinancialGoalAllocationError(ValueError):
    """The requested virtual destination contradicts a goal invariant."""


class FinancialGoalInsufficientAvailabilityError(FinancialGoalAllocationError):
    """Allocating would use more than the balance not yet allocated to goals."""


class FinancialGoalInsufficientAllocationError(FinancialGoalAllocationError):
    """Releasing would make the virtual balance of the goal/account negative."""


def _clean_text(value: str, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    cleaned = value.strip()
    if not 1 <= len(cleaned) <= max_length:
        raise ValueError(
            f"{field_name} must contain between 1 and {max_length} characters"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise ValueError(f"{field_name} contains control characters")
    return cleaned


def _clean_optional_text(
    value: str | None, field_name: str, max_length: int
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        return None
    return _clean_text(value, field_name, max_length)


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_scope(value: FinancialVisibilityScope) -> FinancialVisibilityScope:
    if not isinstance(value, FinancialVisibilityScope) or value not in _GOAL_SCOPES:
        raise ValueError("goal visibility_scope must be PERSONAL or HOUSEHOLD")
    return value


def _require_positive_money(value: Money, field_name: str) -> Money:
    if not isinstance(value, Money):
        raise TypeError(f"{field_name} must be Money")
    if value.amount <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _require_target_date(value: date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError("target_date must be date")
    return value


def goal_target_date_bounds(today: date) -> tuple[date, date]:
    """Inclusive ``(earliest, latest)`` target date accepted when one is set or changed.

    ``today`` is the server UTC date. The one-day tolerance keeps a user whose local
    date is still yesterday (UTC is never behind a local clock in the Americas) from
    being rejected for "today". The horizon is a plain sanity bound.
    """
    if isinstance(today, datetime) or not isinstance(today, date):
        raise TypeError("today must be date")
    earliest = today - timedelta(days=GOAL_TARGET_DATE_PAST_TOLERANCE_DAYS)
    latest = date(today.year + GOAL_TARGET_DATE_HORIZON_YEARS, 12, 31)
    return earliest, latest


def validate_goal_target_date(value: date | None, *, today: date) -> date | None:
    """Reject a new/changed target date outside :func:`goal_target_date_bounds`."""
    target_date = _require_target_date(value)
    if target_date is None:
        return None
    earliest, latest = goal_target_date_bounds(today)
    if not earliest <= target_date <= latest:
        raise ValueError("target_date is outside the accepted range")
    return target_date


@dataclass(frozen=True, slots=True, repr=False)
class FinancialGoalDraft:
    """Trusted goal creation intent. Owner and residence come from the session."""

    title: str
    description: str | None
    visibility_scope: FinancialVisibilityScope
    target: Money
    target_date: date | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "title", _clean_text(self.title, "title", GOAL_TITLE_MAX_LENGTH)
        )
        object.__setattr__(
            self,
            "description",
            _clean_optional_text(
                self.description, "description", GOAL_DESCRIPTION_MAX_LENGTH
            ),
        )
        _require_scope(self.visibility_scope)
        _require_positive_money(self.target, "target")
        _require_target_date(self.target_date)

    @property
    def currency(self) -> str:
        return self.target.currency

    def canonical_material(self) -> tuple[object, ...]:
        """Stable material for the create idempotency digest."""
        return (
            self.title,
            self.description,
            self.visibility_scope.value,
            self.target.currency,
            self.target.canonical_amount,
            self.target_date.isoformat() if self.target_date is not None else None,
        )

    def __repr__(self) -> str:
        return (
            "FinancialGoalDraft("
            f"visibility_scope={self.visibility_scope.value!r}, "
            "<title-and-amount-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialGoalReplacement:
    """Full replacement of the mutable planning data under CAS.

    Scope, owner and currency are the goal's identity and are immutable: they decide
    which accounts may back it. Allocation events are never touched by an edit.
    """

    expected_version: int
    title: str
    description: str | None
    target: Money
    target_date: date | None

    def __post_init__(self) -> None:
        if isinstance(self.expected_version, bool) or not isinstance(
            self.expected_version, int
        ):
            raise TypeError("expected_version must be an integer")
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        object.__setattr__(
            self, "title", _clean_text(self.title, "title", GOAL_TITLE_MAX_LENGTH)
        )
        object.__setattr__(
            self,
            "description",
            _clean_optional_text(
                self.description, "description", GOAL_DESCRIPTION_MAX_LENGTH
            ),
        )
        _require_positive_money(self.target, "target")
        _require_target_date(self.target_date)

    def __repr__(self) -> str:
        return (
            "FinancialGoalReplacement("
            f"expected_version={self.expected_version}, "
            "<title-and-amount-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialGoalRecord:
    """Canonical persisted goal at its current ``version``."""

    id: UUID
    residence_id: UUID
    owner_operator_id: UUID
    visibility_scope: FinancialVisibilityScope
    title: str
    description: str | None
    target: Money
    target_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        _require_uuid(self.residence_id, "residence_id")
        _require_uuid(self.owner_operator_id, "owner_operator_id")
        _require_scope(self.visibility_scope)
        object.__setattr__(
            self, "title", _clean_text(self.title, "title", GOAL_TITLE_MAX_LENGTH)
        )
        object.__setattr__(
            self,
            "description",
            _clean_optional_text(
                self.description, "description", GOAL_DESCRIPTION_MAX_LENGTH
            ),
        )
        _require_positive_money(self.target, "target")
        _require_target_date(self.target_date)
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise TypeError("version must be an integer")
        if self.version < 1:
            raise ValueError("version must be positive")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")

    @property
    def currency(self) -> str:
        return self.target.currency

    def __repr__(self) -> str:
        return (
            "FinancialGoalRecord("
            f"visibility_scope={self.visibility_scope.value!r}, "
            f"version={self.version}, <identity-title-and-amount-redacted>)"
        )


def can_edit_goal(*, goal: FinancialGoalRecord, operator_id: UUID) -> bool:
    """Write authority is the owner's. Reading a HOUSEHOLD goal never implies it."""
    return goal.owner_operator_id == operator_id


def is_goal_account_eligible(
    *,
    goal_visibility_scope: FinancialVisibilityScope,
    goal_owner_operator_id: UUID,
    goal_currency: str,
    account: FinancialAccountRecord,
    for_new_allocation: bool,
) -> bool:
    """Which accounts may back a goal (v1).

    ``PERSONAL`` goal -> ``PERSONAL`` account of the same owner. ``HOUSEHOLD`` goal
    -> ``HOUSEHOLD`` account of the same owner. ``SHARED`` accounts are never
    eligible. The currency must match exactly (no conversion). A *new* allocation
    needs an ``ACTIVE`` account; releasing a historical link works after archiving.
    Knowing an account id proves nothing: the same predicate runs in the database.
    """
    if not isinstance(account, FinancialAccountRecord):
        raise TypeError("account must be FinancialAccountRecord")
    validate_currency_code(goal_currency)
    _require_scope(goal_visibility_scope)
    if account.currency != goal_currency:
        return False
    if account.owner_operator_id != goal_owner_operator_id:
        return False
    if account.visibility_scope is not goal_visibility_scope:
        return False
    if for_new_allocation and account.status is not FinancialAccountStatus.ACTIVE:
        return False
    return True


@dataclass(frozen=True, slots=True, repr=False)
class FinancialGoalAllocationDraft:
    """Trusted ``ALLOCATE`` / ``RELEASE`` intent for one goal and one account."""

    kind: FinancialGoalEventKind
    account_id: UUID
    amount: Money

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FinancialGoalEventKind):
            raise TypeError("kind must be FinancialGoalEventKind")
        validate_financial_resource_id(self.account_id)
        _require_positive_money(self.amount, "amount")

    @property
    def signed_amount(self) -> Decimal:
        return (
            self.amount.amount
            if self.kind is FinancialGoalEventKind.ALLOCATE
            else -self.amount.amount
        )

    def canonical_material(self) -> tuple[str, ...]:
        return (
            self.kind.value,
            str(self.account_id),
            self.amount.currency,
            self.amount.canonical_amount,
        )

    def __repr__(self) -> str:
        return (
            "FinancialGoalAllocationDraft("
            f"kind={self.kind.value!r}, <account-and-amount-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialGoalEventRecord:
    """One persisted append-only virtual event. ``amount`` is the positive magnitude."""

    id: UUID
    goal_id: UUID
    account_id: UUID
    kind: FinancialGoalEventKind
    amount: Money
    actor_operator_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        validate_financial_resource_id(self.goal_id)
        validate_financial_resource_id(self.account_id)
        if not isinstance(self.kind, FinancialGoalEventKind):
            raise TypeError("kind must be FinancialGoalEventKind")
        _require_positive_money(self.amount, "amount")
        _require_uuid(self.actor_operator_id, "actor_operator_id")
        _require_aware(self.created_at, "created_at")

    @property
    def signed_amount(self) -> Decimal:
        return (
            self.amount.amount
            if self.kind is FinancialGoalEventKind.ALLOCATE
            else -self.amount.amount
        )

    def __repr__(self) -> str:
        return (
            "FinancialGoalEventRecord("
            f"kind={self.kind.value!r}, <identity-and-amount-redacted>)"
        )


def net_allocated_by_account(
    events: Iterable[FinancialGoalEventRecord],
) -> dict[UUID, Decimal]:
    """Virtual amount currently allocated per account, from the event history alone."""
    totals: dict[UUID, Decimal] = {}
    for event in events:
        totals[event.account_id] = (
            totals.get(event.account_id, Decimal(0)) + event.signed_amount
        )
    for total in totals.values():
        if total < 0:
            raise FinancialGoalAllocationError(
                "virtual allocation must not be negative"
            )
    return totals


def goal_account_availability(*, balance: Money, allocated_total: Money) -> Money:
    """Balance not yet allocated to goals. Negative when allocations lack backing."""
    if not isinstance(balance, Money) or not isinstance(allocated_total, Money):
        raise TypeError("balance and allocated_total must be Money")
    return balance - allocated_total


def require_allocation_within_availability(
    *, balance: Money, allocated_total: Money, amount: Money
) -> None:
    """A new allocation may use at most what is not already allocated to any goal."""
    available = goal_account_availability(
        balance=balance, allocated_total=allocated_total
    )
    if amount > available:
        raise FinancialGoalInsufficientAvailabilityError(
            "allocation exceeds the available balance"
        )


def require_release_within_allocated(*, allocated: Money, amount: Money) -> None:
    """A release may free at most what this goal holds on this account."""
    if amount > allocated:
        raise FinancialGoalInsufficientAllocationError(
            "release exceeds the amount allocated to the goal on this account"
        )


def goal_progress_percent(target: Decimal, allocated: Decimal) -> Decimal:
    """``allocated / target * 100`` as Decimal, half-up at 2 places (may exceed 100).

    The target is strictly positive by contract, so there is no division policy to
    invent; a non-positive target fails closed.
    """
    if target <= 0:
        raise ValueError("target must be positive")
    with localcontext() as context:
        context.prec = 60
        value = allocated * Decimal(100) / target
        return value.quantize(
            Decimal(1).scaleb(-GOAL_PERCENT_SCALE), rounding=ROUND_HALF_UP
        )


def goal_progress_status(
    target: Decimal, allocated: Decimal
) -> FinancialGoalProgressStatus:
    if allocated <= 0:
        return FinancialGoalProgressStatus.NOT_STARTED
    if allocated < target:
        return FinancialGoalProgressStatus.IN_PROGRESS
    if allocated == target:
        return FinancialGoalProgressStatus.REACHED
    return FinancialGoalProgressStatus.EXCEEDED


@dataclass(frozen=True, slots=True, repr=False)
class FinancialGoalAccountInput:
    """Store output for one account that backs the goal (facts only)."""

    account_id: UUID
    account_status: FinancialAccountStatus
    balance: Money
    allocated_total: Money  # across every goal on this account, net of releases

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.account_id)
        if not isinstance(self.account_status, FinancialAccountStatus):
            raise TypeError("account_status must be FinancialAccountStatus")
        if not isinstance(self.balance, Money) or not isinstance(
            self.allocated_total, Money
        ):
            raise TypeError("balance and allocated_total must be Money")
        if self.allocated_total.amount < 0:
            raise ValueError("allocated_total must not be negative")

    def __repr__(self) -> str:
        return "FinancialGoalAccountInput(<identity-and-amounts-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialGoalAccountSummary:
    account_id: UUID
    account_status: FinancialAccountStatus
    allocated: Money  # this goal on this account
    account_balance: Money  # canonical derived balance
    account_allocated_total: Money  # every goal on this account
    backing_status: FinancialGoalBackingStatus
    shortfall: Money  # allocated_total - balance when INSUFFICIENT, else zero

    def __repr__(self) -> str:
        return (
            "FinancialGoalAccountSummary("
            f"backing_status={self.backing_status.value!r}, <amounts-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialGoalSummary:
    goal: FinancialGoalRecord
    allocated: Money
    remaining_target: Money
    surplus: Money
    progress_percent: Decimal
    progress_status: FinancialGoalProgressStatus
    has_insufficient_backing: bool
    accounts: tuple[FinancialGoalAccountSummary, ...]
    events: tuple[FinancialGoalEventRecord, ...]

    def __repr__(self) -> str:
        return (
            "FinancialGoalSummary("
            f"progress_status={self.progress_status.value!r}, "
            f"accounts={len(self.accounts)}, events={len(self.events)})"
        )


def summarize_goal(
    goal: FinancialGoalRecord,
    events: Sequence[FinancialGoalEventRecord],
    account_inputs: Sequence[FinancialGoalAccountInput],
) -> FinancialGoalSummary:
    """Combine the goal, its event history and the canonical account facts. Pure.

    The goal never recomputes a balance: ``account_inputs`` carries the balance the
    canonical reader derived and the allocation total the store summed. Insufficient
    backing is *reported*, never repaired: no event is created or rewritten.
    """
    currency = goal.currency
    zero = Money(Decimal(0), currency)
    if len(events) > GOAL_EVENTS_MAX:
        raise FinancialGoalAllocationError("goal event history exceeds its bound")
    for event in events:
        if event.goal_id != goal.id or event.amount.currency != currency:
            raise FinancialGoalAllocationError("goal event does not belong to the goal")
    per_account = net_allocated_by_account(events)
    if len(per_account) > GOAL_ACCOUNTS_MAX:
        raise FinancialGoalAllocationError("goal account set exceeds its bound")
    inputs = {item.account_id: item for item in account_inputs}
    if set(inputs) != set(per_account):
        raise FinancialGoalAllocationError("account facts must match goal accounts")

    allocated_total = sum(per_account.values(), Decimal(0))
    summaries: list[FinancialGoalAccountSummary] = []
    for account_id in sorted(per_account, key=str):
        item = inputs[account_id]
        if (
            item.balance.currency != currency
            or item.allocated_total.currency != currency
        ):
            raise FinancialGoalAllocationError("account currency mismatch")
        insufficient = item.allocated_total.amount > item.balance.amount
        shortfall = (
            Money(item.allocated_total.amount - item.balance.amount, currency)
            if insufficient
            else zero
        )
        summaries.append(
            FinancialGoalAccountSummary(
                account_id=account_id,
                account_status=item.account_status,
                allocated=Money(per_account[account_id], currency),
                account_balance=item.balance,
                account_allocated_total=item.allocated_total,
                backing_status=(
                    FinancialGoalBackingStatus.INSUFFICIENT
                    if insufficient
                    else FinancialGoalBackingStatus.COVERED
                ),
                shortfall=shortfall,
            )
        )

    target = goal.target.amount
    remaining = max(target - allocated_total, Decimal(0))
    surplus = max(allocated_total - target, Decimal(0))
    return FinancialGoalSummary(
        goal=goal,
        allocated=Money(allocated_total, currency),
        remaining_target=Money(remaining, currency),
        surplus=Money(surplus, currency),
        progress_percent=goal_progress_percent(target, allocated_total),
        progress_status=goal_progress_status(target, allocated_total),
        has_insufficient_backing=any(
            summary.backing_status is FinancialGoalBackingStatus.INSUFFICIENT
            for summary in summaries
        ),
        accounts=tuple(summaries),
        events=tuple(events),
    )


__all__ = [
    "GOAL_ACCOUNTS_MAX",
    "GOAL_ALLOCATE_EVENTS_MAX",
    "GOAL_DESCRIPTION_MAX_LENGTH",
    "GOAL_EVENTS_MAX",
    "GOAL_PERCENT_SCALE",
    "GOAL_TARGET_DATE_HORIZON_YEARS",
    "GOAL_TARGET_DATE_PAST_TOLERANCE_DAYS",
    "GOAL_TITLE_MAX_LENGTH",
    "GOALS_PER_OWNER_MAX",
    "FinancialGoalAccountInput",
    "FinancialGoalAccountSummary",
    "FinancialGoalAllocationDraft",
    "FinancialGoalAllocationError",
    "FinancialGoalBackingStatus",
    "FinancialGoalDraft",
    "FinancialGoalEventKind",
    "FinancialGoalEventRecord",
    "FinancialGoalInsufficientAllocationError",
    "FinancialGoalInsufficientAvailabilityError",
    "FinancialGoalProgressStatus",
    "FinancialGoalRecord",
    "FinancialGoalReplacement",
    "FinancialGoalSummary",
    "can_edit_goal",
    "goal_account_availability",
    "goal_progress_percent",
    "goal_progress_status",
    "goal_target_date_bounds",
    "is_goal_account_eligible",
    "net_allocated_by_account",
    "require_allocation_within_availability",
    "require_release_within_allocated",
    "summarize_goal",
    "validate_goal_target_date",
]
