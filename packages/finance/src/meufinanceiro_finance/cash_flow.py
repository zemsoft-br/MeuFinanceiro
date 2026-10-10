"""Pure, deterministic cash flow projection over the canonical ledger (ADR-0031).

A cash flow is a *read*: it never creates a Movement, an occurrence or a stored
balance. Realized facts come only from Movements (opening balance + signed
amounts, exactly like the balance and statement derivation). Expectations come
only from what the residence already declared:

- PENDING recurrence occurrences that are persisted (``EXPECTED_OCCURRENCE``);
- months of ACTIVE recurrence rules that have no live occurrence yet, derived
  with the canonical monthly calendar and labelled as such (``EXPECTED_RULE``).
  Nothing is generated or stored for them.

Expectations exist only from the reference date on. A PENDING occurrence whose
scheduled date already passed is placed on the reference date and flagged
``overdue``. A REALIZED occurrence is represented solely by its canonical
Movement (never twice); SKIPPED and SUPERSEDED occurrences expect nothing.
NEUTRAL Movements (transfer legs) move cash per account but are never income or
expense. Currencies are never summed together: every figure belongs to one
currency group. Budgets, goals, projects, cards, installments, loans and bank
observations are not sources of this projection.

Every date is a plain ``date``; nothing here reads a clock. The caller injects
the reference date and the calculation instant.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import date as _Date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.accounts import (
    FinancialAccountRecord,
    FinancialAccountStatus,
)
from meufinanceiro_finance.balance_statement import FinancialLedgerStateError
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.movements import (
    FinancialMovementRole,
    FinancialResultEffect,
)
from meufinanceiro_finance.opening_balances import FinancialOpeningBalanceRecord
from meufinanceiro_finance.recurrences import (
    FinancialOccurrenceStatus,
    FinancialRecurrenceOccurrenceRecord,
    FinancialRecurrenceRecord,
    FinancialRecurrenceStatus,
    FinancialRecurrenceWindow,
    month_start,
    scheduled_occurrences,
)

# Any three civil months fit (31 + 31 + 30 = 92): a window is short and auditable.
CASH_FLOW_WINDOW_MAX_DAYS = 92
CASH_FLOW_DEFAULT_WINDOW_DAYS = 30
CASH_FLOW_ACCOUNTS_MAX = 50
# Realized plus expected events of one response. Exceeding it is refused, never
# truncated: a projection with silently missing events would be wrong.
CASH_FLOW_EVENTS_MAX = 2000


class FinancialCashFlowWindowError(ValueError):
    """The requested window is outside the v1 contract."""


class FinancialCashFlowLimitError(ValueError):
    """The window holds more events or accounts than one read may return."""


class FinancialCashFlowEventKind(StrEnum):
    """Where one event of the projection comes from."""

    REALIZED = "REALIZED"
    EXPECTED_OCCURRENCE = "EXPECTED_OCCURRENCE"
    EXPECTED_RULE = "EXPECTED_RULE"


class FinancialCashFlowProjectionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FinancialCashFlowIssueSeverity(StrEnum):
    """INCOMPLETE makes the projection unreliable; ATTENTION only informs."""

    INCOMPLETE = "INCOMPLETE"
    ATTENTION = "ATTENTION"


class FinancialCashFlowIssueCode(StrEnum):
    OPENING_BALANCE_MISSING = "OPENING_BALANCE_MISSING"
    OPENING_BALANCE_AFTER_WINDOW_START = "OPENING_BALANCE_AFTER_WINDOW_START"
    RULE_ACCOUNT_INACTIVE = "RULE_ACCOUNT_INACTIVE"
    OVERDUE_OCCURRENCES = "OVERDUE_OCCURRENCES"
    UNGENERATED_PAST_OCCURRENCES = "UNGENERATED_PAST_OCCURRENCES"
    PAUSED_RULES = "PAUSED_RULES"
    HISTORICAL_WINDOW = "HISTORICAL_WINDOW"


_ISSUE_SEVERITY: dict[FinancialCashFlowIssueCode, FinancialCashFlowIssueSeverity] = {
    FinancialCashFlowIssueCode.OPENING_BALANCE_MISSING: (
        FinancialCashFlowIssueSeverity.INCOMPLETE
    ),
    FinancialCashFlowIssueCode.OPENING_BALANCE_AFTER_WINDOW_START: (
        FinancialCashFlowIssueSeverity.ATTENTION
    ),
    FinancialCashFlowIssueCode.RULE_ACCOUNT_INACTIVE: (
        FinancialCashFlowIssueSeverity.INCOMPLETE
    ),
    FinancialCashFlowIssueCode.OVERDUE_OCCURRENCES: (
        FinancialCashFlowIssueSeverity.ATTENTION
    ),
    FinancialCashFlowIssueCode.UNGENERATED_PAST_OCCURRENCES: (
        FinancialCashFlowIssueSeverity.ATTENTION
    ),
    FinancialCashFlowIssueCode.PAUSED_RULES: FinancialCashFlowIssueSeverity.ATTENTION,
    FinancialCashFlowIssueCode.HISTORICAL_WINDOW: (
        FinancialCashFlowIssueSeverity.ATTENTION
    ),
}


class FinancialCashFlowExcludedSource(StrEnum):
    """Sources deliberately absent from the v1 projection (stated, not hidden)."""

    BUDGETS = "BUDGETS"
    GOALS = "GOALS"
    PROJECTS = "PROJECTS"
    CARDS = "CARDS"
    INSTALLMENTS = "INSTALLMENTS"
    LOANS = "LOANS"
    BANK_OBSERVATIONS = "BANK_OBSERVATIONS"


CASH_FLOW_EXCLUDED_SOURCES = tuple(FinancialCashFlowExcludedSource)


# --- window ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FinancialCashFlowWindow:
    """Inclusive ``[from_date, through_date]`` read against ``reference_date``."""

    from_date: date
    through_date: date
    reference_date: date

    def __post_init__(self) -> None:
        for name in ("from_date", "through_date", "reference_date"):
            _require_plain_date(getattr(self, name), name)
        if self.through_date < self.from_date:
            raise FinancialCashFlowWindowError("through must not precede from")
        if self.from_date > self.reference_date:
            raise FinancialCashFlowWindowError(
                "from must not be after the reference date"
            )
        if self.days > CASH_FLOW_WINDOW_MAX_DAYS:
            raise FinancialCashFlowWindowError(
                f"window must not exceed {CASH_FLOW_WINDOW_MAX_DAYS} days"
            )

    @property
    def days(self) -> int:
        return (self.through_date - self.from_date).days + 1

    @property
    def is_historical(self) -> bool:
        """Only the past: nothing is expected, the projection does not apply."""
        return self.through_date < self.reference_date


def cash_flow_window(
    *,
    from_date: date | None,
    through_date: date | None,
    reference_date: date,
) -> FinancialCashFlowWindow:
    """Apply the v1 defaults (from today, 30 days) and validate the window."""
    _require_plain_date(reference_date, "reference_date")
    start = reference_date if from_date is None else from_date
    _require_plain_date(start, "from_date")
    if through_date is None:
        try:
            end = start + timedelta(days=CASH_FLOW_DEFAULT_WINDOW_DAYS - 1)
        except OverflowError:
            raise FinancialCashFlowWindowError("window is out of range") from None
    else:
        end = through_date
    return FinancialCashFlowWindow(start, end, reference_date)


def cash_flow_rule_months(
    window: FinancialCashFlowWindow,
) -> FinancialRecurrenceWindow | None:
    """Months whose occurrences decide what a rule still expects (or ``None``).

    From the month of the earlier of ``from`` and the first day of the reference
    month, through the month of ``through``: future months are projected, earlier
    months only reported. A historical window looks at no rule at all. The store
    must read the live occurrences of exactly these months.
    """
    if window.is_historical:
        return None
    first = min(window.from_date, month_start(window.reference_date))
    return FinancialRecurrenceWindow(
        month_start(first), month_start(window.through_date)
    )


# --- inputs ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCashFlowAccountInput:
    """One selected account with the ledger aggregates read in the same snapshot.

    ``net_before_window`` is the signed sum of every Movement with an effective
    date before the window; ``net_through_reference`` the signed sum of every
    Movement up to and including the reference date. Both are exact ledger
    aggregates, never stored.
    """

    account: FinancialAccountRecord
    opening_balance: FinancialOpeningBalanceRecord | None
    net_before_window: Money
    net_through_reference: Money

    def __post_init__(self) -> None:
        if not isinstance(self.account, FinancialAccountRecord):
            raise TypeError("account must be FinancialAccountRecord")
        currency = self.account.currency
        if self.opening_balance is not None:
            if not isinstance(self.opening_balance, FinancialOpeningBalanceRecord):
                raise TypeError("opening_balance must be FinancialOpeningBalanceRecord")
            if self.opening_balance.account_id != self.account.id:
                raise FinancialLedgerStateError("opening balance account mismatch")
            _require_currency(self.opening_balance.amount, currency, "opening balance")
        _require_currency(self.net_before_window, currency, "net_before_window")
        _require_currency(self.net_through_reference, currency, "net_through_reference")

    def __repr__(self) -> str:
        return "FinancialCashFlowAccountInput(<identity-and-money-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCashFlowSource:
    """Everything one projection reads, from one consistent snapshot.

    - ``movements``: every visible Movement of the selected accounts whose
      effective date is inside the window;
    - ``transfer_ids``: transfer id of the Movements that are transfer legs;
    - ``realized_occurrences``: the REALIZED occurrence linked to a window
      STANDARD Movement, keyed by that Movement id;
    - ``pending_occurrences``: every PENDING occurrence of the selected accounts
      scheduled on or before the end of the window (overdue ones included);
    - ``live_occurrence_months``: ``(recurrence_id, period_start)`` of every
      non-SUPERSEDED occurrence in the months touched by the projection;
    - ``rules``: every visible recurrence rule of the selected accounts.
    """

    accounts: tuple[FinancialCashFlowAccountInput, ...]
    movements: tuple[FinancialMovementRecord, ...]
    transfer_ids: Mapping[UUID, UUID]
    realized_occurrences: Mapping[UUID, FinancialRecurrenceOccurrenceRecord]
    pending_occurrences: tuple[FinancialRecurrenceOccurrenceRecord, ...]
    live_occurrence_months: frozenset[tuple[UUID, date]]
    rules: tuple[FinancialRecurrenceRecord, ...]

    def __post_init__(self) -> None:
        for name in ("accounts", "movements", "pending_occurrences", "rules"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} must be tuple")
        if not isinstance(self.live_occurrence_months, frozenset):
            raise TypeError("live_occurrence_months must be frozenset")
        if len(self.accounts) > CASH_FLOW_ACCOUNTS_MAX:
            raise FinancialCashFlowLimitError("too many cash flow accounts")

    def __repr__(self) -> str:
        return (
            "FinancialCashFlowSource("
            f"accounts={len(self.accounts)}, movements={len(self.movements)}, "
            f"pending={len(self.pending_occurrences)}, rules={len(self.rules)})"
        )


# --- outputs --------------------------------------------------------------------


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCashFlowEvent:
    """One contribution to the projection, with the balances right after it.

    ``amount`` is signed (cash in > 0, cash out < 0). For a REALIZED event it is
    the Movement amount itself. For an expected event it is ``+expected`` for
    INCOME and ``-expected`` for EXPENSE. ``expected_amount`` is the signed
    expectation of the recurrence behind the event, when there is one, so a
    realized occurrence can be compared with what was planned.
    """

    date: _Date
    kind: FinancialCashFlowEventKind
    account_id: UUID
    amount: Money
    result_effect: FinancialResultEffect
    description: str | None
    movement_id: UUID | None
    movement_role: FinancialMovementRole | None
    reversal_of_id: UUID | None
    transfer_id: UUID | None
    occurrence_id: UUID | None
    recurrence_id: UUID | None
    rule_version: int | None
    period_start: _Date | None
    scheduled_date: _Date | None
    overdue: bool
    expected_amount: Money | None
    balance_after: Money
    account_balance_after: Money

    def __repr__(self) -> str:
        return (
            "FinancialCashFlowEvent("
            f"kind={self.kind.value!r}, result_effect={self.result_effect.value!r}, "
            f"overdue={self.overdue}, <identity-money-and-text-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCashFlowDay:
    """One day of the consolidated series of a currency group.

    Income and expense figures are magnitudes netted of reversals (a reversal of
    an expense lowers the day's expense); ``neutral_net`` is the signed effect of
    NEUTRAL Movements. ``projected`` days are on or after the reference date of a
    non-historical window, where expectations apply.
    """

    date: date
    opening: Money
    realized_income: Money
    realized_expense: Money
    expected_income: Money
    expected_expense: Money
    neutral_net: Money
    closing: Money
    projected: bool

    @property
    def negative(self) -> bool:
        return self.closing.amount < 0

    def __repr__(self) -> str:
        return f"FinancialCashFlowDay(projected={self.projected}, <money-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCashFlowRisk:
    """Lowest closing balance of the window and the first day below zero."""

    minimum_balance: Money
    minimum_balance_date: date
    first_negative_date: date | None
    negative_days: int

    def __repr__(self) -> str:
        return f"FinancialCashFlowRisk(negative_days={self.negative_days})"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCashFlowTotals:
    """Realized against expected inside the window of one currency group."""

    realized_income: Money
    realized_expense: Money
    neutral_in: Money
    neutral_out: Money
    realized_net: Money
    expected_income: Money
    expected_expense: Money
    expected_net: Money
    overdue_count: int
    overdue_net: Money
    recurrence_realized_count: int
    recurrence_realized_expected: Money
    recurrence_realized_actual: Money
    realized_count: int
    expected_count: int

    def __repr__(self) -> str:
        return (
            "FinancialCashFlowTotals("
            f"realized_count={self.realized_count}, "
            f"expected_count={self.expected_count}, <money-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCashFlowAccountSummary:
    account: FinancialAccountRecord
    opening_balance: FinancialOpeningBalanceRecord | None
    starting_balance: Money
    balance_at_reference: Money
    realized_net: Money
    expected_net: Money
    closing_balance: Money
    risk: FinancialCashFlowRisk

    @property
    def has_opening_balance(self) -> bool:
        return self.opening_balance is not None

    def __repr__(self) -> str:
        return (
            "FinancialCashFlowAccountSummary("
            f"has_opening_balance={self.has_opening_balance}, "
            "<identity-and-money-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCashFlowIssue:
    code: FinancialCashFlowIssueCode
    severity: FinancialCashFlowIssueSeverity
    count: int
    account_ids: tuple[UUID, ...]

    def __repr__(self) -> str:
        return f"FinancialCashFlowIssue(code={self.code.value!r}, count={self.count})"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCashFlowGroup:
    """Everything of one currency. Groups are never added to each other."""

    currency: str
    accounts: tuple[FinancialCashFlowAccountSummary, ...]
    starting_balance: Money
    balance_at_reference: Money
    closing_balance: Money
    totals: FinancialCashFlowTotals
    risk: FinancialCashFlowRisk
    days: tuple[FinancialCashFlowDay, ...]
    events: tuple[FinancialCashFlowEvent, ...]
    projection_status: FinancialCashFlowProjectionStatus
    issues: tuple[FinancialCashFlowIssue, ...]

    def __repr__(self) -> str:
        return (
            "FinancialCashFlowGroup("
            f"currency={self.currency!r}, accounts={len(self.accounts)}, "
            f"events={len(self.events)}, status={self.projection_status.value!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCashFlowProjection:
    window: FinancialCashFlowWindow
    calculated_at: datetime
    groups: tuple[FinancialCashFlowGroup, ...]
    excluded_sources: tuple[FinancialCashFlowExcludedSource, ...]

    def __repr__(self) -> str:
        return f"FinancialCashFlowProjection(groups={len(self.groups)})"


# --- derivation -----------------------------------------------------------------


@dataclass(slots=True)
class _Draft:
    """An event before balances are attached (internal)."""

    date: _Date
    kind: FinancialCashFlowEventKind
    account_id: UUID
    amount: Money
    result_effect: FinancialResultEffect
    description: str | None
    movement: FinancialMovementRecord | None = None
    transfer_id: UUID | None = None
    occurrence_id: UUID | None = None
    recurrence_id: UUID | None = None
    rule_version: int | None = None
    period_start: _Date | None = None
    scheduled_date: _Date | None = None
    overdue: bool = False
    expected_amount: Money | None = None


def project_cash_flow(
    *,
    window: FinancialCashFlowWindow,
    source: FinancialCashFlowSource,
    calculated_at: datetime,
) -> FinancialCashFlowProjection:
    """Derive the projection. Deterministic: same input, same output."""
    if not isinstance(window, FinancialCashFlowWindow):
        raise TypeError("window must be FinancialCashFlowWindow")
    if not isinstance(source, FinancialCashFlowSource):
        raise TypeError("source must be FinancialCashFlowSource")
    _require_aware(calculated_at, "calculated_at")

    accounts = _accounts_by_id(source.accounts)
    realized = _realized_drafts(window, source, accounts)
    expected, pending_months = _pending_drafts(window, source, accounts)
    live_months = source.live_occurrence_months | pending_months
    rule_drafts, rule_issues = _rule_drafts(window, source, accounts, live_months)
    expected.extend(rule_drafts)
    if len(realized) + len(expected) > CASH_FLOW_EVENTS_MAX:
        raise FinancialCashFlowLimitError("cash flow window has too many events")

    currencies = sorted({entry.account.currency for entry in source.accounts})
    groups = tuple(
        _group(
            currency=currency,
            window=window,
            entries=[e for e in source.accounts if e.account.currency == currency],
            realized=[d for d in realized if d.amount.currency == currency],
            expected=[d for d in expected if d.amount.currency == currency],
            rule_issues=rule_issues.get(currency, {}),
        )
        for currency in currencies
    )
    return FinancialCashFlowProjection(
        window=window,
        calculated_at=calculated_at,
        groups=groups,
        excluded_sources=CASH_FLOW_EXCLUDED_SOURCES,
    )


def _accounts_by_id(
    entries: tuple[FinancialCashFlowAccountInput, ...],
) -> dict[UUID, FinancialCashFlowAccountInput]:
    accounts: dict[UUID, FinancialCashFlowAccountInput] = {}
    for entry in entries:
        if not isinstance(entry, FinancialCashFlowAccountInput):
            raise TypeError("accounts must contain FinancialCashFlowAccountInput")
        if entry.account.id in accounts:
            raise FinancialLedgerStateError("duplicate cash flow account")
        accounts[entry.account.id] = entry
    return accounts


def _realized_drafts(
    window: FinancialCashFlowWindow,
    source: FinancialCashFlowSource,
    accounts: dict[UUID, FinancialCashFlowAccountInput],
) -> list[_Draft]:
    seen: set[UUID] = set()
    ordered: list[FinancialMovementRecord] = []
    for movement in source.movements:
        if not isinstance(movement, FinancialMovementRecord):
            raise TypeError("movements must contain FinancialMovementRecord")
        if movement.id in seen:
            raise FinancialLedgerStateError("duplicate Movement in cash flow input")
        seen.add(movement.id)
        entry = accounts.get(movement.account_id)
        if entry is None:
            raise FinancialLedgerStateError("Movement account is not selected")
        _require_currency(movement.amount, entry.account.currency, "Movement amount")
        if not window.from_date <= movement.effective_date <= window.through_date:
            raise FinancialLedgerStateError("Movement is outside the window")
        ordered.append(movement)
    for movement_id in source.transfer_ids:
        if movement_id not in seen:
            raise FinancialLedgerStateError("transfer leg is not a window Movement")
    by_id = {movement.id: movement for movement in ordered}
    for movement_id, linked in source.realized_occurrences.items():
        target = by_id.get(movement_id)
        if (
            target is None
            or not isinstance(linked, FinancialRecurrenceOccurrenceRecord)
            or linked.status is not FinancialOccurrenceStatus.REALIZED
            or linked.realization is None
            or linked.realization.movement_id != target.id
            or target.role is not FinancialMovementRole.STANDARD
            or linked.account_id != target.account_id
            or linked.result_effect is not target.result_effect
            or linked.expected.currency != target.amount.currency
        ):
            raise FinancialLedgerStateError("realized occurrence link is invalid")

    # The statement order, across accounts: effective date, creation, id.
    ordered.sort(key=lambda m: (m.effective_date, m.created_at, m.id.int))
    drafts: list[_Draft] = []
    for movement in ordered:
        occurrence: FinancialRecurrenceOccurrenceRecord | None = (
            source.realized_occurrences.get(movement.id)
        )
        drafts.append(
            _Draft(
                date=movement.effective_date,
                kind=FinancialCashFlowEventKind.REALIZED,
                account_id=movement.account_id,
                amount=movement.amount,
                result_effect=movement.result_effect,
                description=movement.description,
                movement=movement,
                transfer_id=source.transfer_ids.get(movement.id),
                occurrence_id=None if occurrence is None else occurrence.id,
                recurrence_id=None if occurrence is None else occurrence.recurrence_id,
                rule_version=None if occurrence is None else occurrence.rule_version,
                period_start=None if occurrence is None else occurrence.period_start,
                scheduled_date=(
                    None if occurrence is None else occurrence.scheduled_date
                ),
                expected_amount=(
                    None
                    if occurrence is None
                    else _signed(occurrence.expected, occurrence.result_effect)
                ),
            )
        )
    return drafts


def _pending_drafts(
    window: FinancialCashFlowWindow,
    source: FinancialCashFlowSource,
    accounts: dict[UUID, FinancialCashFlowAccountInput],
) -> tuple[list[_Draft], frozenset[tuple[UUID, date]]]:
    """Persisted PENDING occurrences: on their date, or on the reference if overdue."""
    seen: set[UUID] = set()
    months: set[tuple[UUID, date]] = set()
    drafts: list[_Draft] = []
    for occurrence in source.pending_occurrences:
        if not isinstance(occurrence, FinancialRecurrenceOccurrenceRecord):
            raise TypeError("pending_occurrences must contain occurrence records")
        if occurrence.status is not FinancialOccurrenceStatus.PENDING:
            raise FinancialLedgerStateError("pending occurrence is not PENDING")
        if occurrence.id in seen:
            raise FinancialLedgerStateError("duplicate occurrence in cash flow input")
        seen.add(occurrence.id)
        entry = accounts.get(occurrence.account_id)
        if entry is None:
            raise FinancialLedgerStateError("occurrence account is not selected")
        _require_currency(occurrence.expected, entry.account.currency, "occurrence")
        if occurrence.scheduled_date > window.through_date:
            raise FinancialLedgerStateError("occurrence is after the window")
        months.add((occurrence.recurrence_id, occurrence.period_start))
        if window.is_historical:
            continue
        overdue = occurrence.scheduled_date < window.reference_date
        amount = _signed(occurrence.expected, occurrence.result_effect)
        drafts.append(
            _Draft(
                date=window.reference_date if overdue else occurrence.scheduled_date,
                kind=FinancialCashFlowEventKind.EXPECTED_OCCURRENCE,
                account_id=occurrence.account_id,
                amount=amount,
                result_effect=occurrence.result_effect,
                description=occurrence.description,
                occurrence_id=occurrence.id,
                recurrence_id=occurrence.recurrence_id,
                rule_version=occurrence.rule_version,
                period_start=occurrence.period_start,
                scheduled_date=occurrence.scheduled_date,
                overdue=overdue,
                expected_amount=amount,
            )
        )
    return drafts, frozenset(months)


_RuleIssues = dict[FinancialCashFlowIssueCode, tuple[int, frozenset[UUID]]]


def _rule_drafts(
    window: FinancialCashFlowWindow,
    source: FinancialCashFlowSource,
    accounts: dict[UUID, FinancialCashFlowAccountInput],
    live_months: frozenset[tuple[UUID, date]],
) -> tuple[list[_Draft], dict[str, _RuleIssues]]:
    """Virtual expectations of ACTIVE rules for months with no live occurrence.

    Only dates from the reference date to the end of the window are projected.
    Nothing else is projected, and nothing is silently dropped; it is reported:

    - a PAUSED rule that would still be due (``PAUSED_RULES``, per rule);
    - an ACTIVE rule of an archived account (``RULE_ACCOUNT_INACTIVE``, per rule);
    - a due date before the reference date (in the reference month or in the
      window) with no occurrence (``UNGENERATED_PAST_OCCURRENCES``, per month):
      it may have been paid by an unlinked Movement, so it is never invented.
    """
    drafts: list[_Draft] = []
    found: dict[str, dict[FinancialCashFlowIssueCode, tuple[int, set[UUID]]]] = {}
    seen: set[UUID] = set()
    months = cash_flow_rule_months(window)

    def report(
        currency: str, code: FinancialCashFlowIssueCode, count: int, account_id: UUID
    ) -> None:
        by_code = found.setdefault(currency, {})
        total, account_ids = by_code.get(code, (0, set()))
        account_ids.add(account_id)
        by_code[code] = (total + count, account_ids)

    for rule in source.rules:
        if not isinstance(rule, FinancialRecurrenceRecord):
            raise TypeError("rules must contain FinancialRecurrenceRecord")
        if rule.id in seen:
            raise FinancialLedgerStateError("duplicate rule in cash flow input")
        seen.add(rule.id)
        entry = accounts.get(rule.account_id)
        if entry is None:
            raise FinancialLedgerStateError("rule account is not selected")
        currency = entry.account.currency
        _require_currency(rule.expected, currency, "rule")
        if months is None:
            continue
        missing = [
            due
            for due in scheduled_occurrences(
                start_date=rule.start_date,
                day_of_month=rule.day_of_month,
                end_date=rule.end_date,
                window=months,
            )
            if due.scheduled_date <= window.through_date
            and (rule.id, due.period_start) not in live_months
        ]
        future = [d for d in missing if d.scheduled_date >= window.reference_date]
        past = len(missing) - len(future)
        if rule.status is FinancialRecurrenceStatus.PAUSED:
            if future:
                report(
                    currency,
                    FinancialCashFlowIssueCode.PAUSED_RULES,
                    1,
                    rule.account_id,
                )
            continue
        if entry.account.status is not FinancialAccountStatus.ACTIVE:
            if future:
                report(
                    currency,
                    FinancialCashFlowIssueCode.RULE_ACCOUNT_INACTIVE,
                    1,
                    rule.account_id,
                )
            continue
        if past:
            report(
                currency,
                FinancialCashFlowIssueCode.UNGENERATED_PAST_OCCURRENCES,
                past,
                rule.account_id,
            )
        amount = _signed(rule.expected, rule.result_effect)
        for due in future:
            drafts.append(
                _Draft(
                    date=due.scheduled_date,
                    kind=FinancialCashFlowEventKind.EXPECTED_RULE,
                    account_id=rule.account_id,
                    amount=amount,
                    result_effect=rule.result_effect,
                    description=rule.description,
                    recurrence_id=rule.id,
                    rule_version=rule.version,
                    period_start=due.period_start,
                    scheduled_date=due.scheduled_date,
                    expected_amount=amount,
                )
            )
    issues = {
        currency: {
            code: (count, frozenset(account_ids))
            for code, (count, account_ids) in by_code.items()
        }
        for currency, by_code in found.items()
    }
    return drafts, issues


def _group(
    *,
    currency: str,
    window: FinancialCashFlowWindow,
    entries: list[FinancialCashFlowAccountInput],
    realized: list[_Draft],
    expected: list[_Draft],
    rule_issues: _RuleIssues,
) -> FinancialCashFlowGroup:
    zero = Money(Decimal(0), currency)
    entries = sorted(
        entries, key=lambda e: (e.account.name.casefold(), e.account.id.int)
    )
    position = {entry.account.id: index for index, entry in enumerate(entries)}
    expected.sort(
        key=lambda d: (
            d.date,
            not d.overdue,
            d.scheduled_date or d.date,
            position[d.account_id],
            d.kind is FinancialCashFlowEventKind.EXPECTED_RULE,
            (d.description or "").casefold(),
            (d.recurrence_id.int if d.recurrence_id else 0),
            (d.occurrence_id.int if d.occurrence_id else 0),
        )
    )
    # Realized first on a day (already in statement order), then expected.
    ordered = sorted(
        [*realized, *expected],
        key=lambda d: (d.date, d.kind is not FinancialCashFlowEventKind.REALIZED),
    )

    starting = {
        entry.account.id: _base(entry) + entry.net_before_window for entry in entries
    }
    at_reference = {
        entry.account.id: _base(entry) + entry.net_through_reference
        for entry in entries
    }
    running = dict(starting)
    group_running = _sum(starting.values(), zero)
    group_starting = group_running

    events: list[FinancialCashFlowEvent] = []
    by_day: dict[date, list[FinancialCashFlowEvent]] = {}
    for draft in ordered:
        running[draft.account_id] = running[draft.account_id] + draft.amount
        group_running = group_running + draft.amount
        movement = draft.movement
        event = FinancialCashFlowEvent(
            date=draft.date,
            kind=draft.kind,
            account_id=draft.account_id,
            amount=draft.amount,
            result_effect=draft.result_effect,
            description=draft.description,
            movement_id=None if movement is None else movement.id,
            movement_role=None if movement is None else movement.role,
            reversal_of_id=None if movement is None else movement.reversal_of_id,
            transfer_id=draft.transfer_id,
            occurrence_id=draft.occurrence_id,
            recurrence_id=draft.recurrence_id,
            rule_version=draft.rule_version,
            period_start=draft.period_start,
            scheduled_date=draft.scheduled_date,
            overdue=draft.overdue,
            expected_amount=draft.expected_amount,
            balance_after=group_running,
            account_balance_after=running[draft.account_id],
        )
        events.append(event)
        by_day.setdefault(event.date, []).append(event)

    if not window.is_historical:
        # The realized balance on the reference date read from the ledger must be
        # the starting balance plus every realized event up to that date: a
        # mismatch means the inputs do not come from one consistent snapshot.
        for entry in entries:
            account_id = entry.account.id
            realized_until = _sum(
                (
                    d.amount
                    for d in realized
                    if d.account_id == account_id and d.date <= window.reference_date
                ),
                zero,
            )
            if starting[account_id] + realized_until != at_reference[account_id]:
                raise FinancialLedgerStateError("cash flow aggregates are inconsistent")

    days = _days(window, by_day, group_starting, zero)
    account_summaries = tuple(
        _account_summary(entry, window, events, starting, at_reference, zero)
        for entry in entries
    )
    overdue = [d for d in expected if d.overdue]
    rule_issues = {
        **rule_issues,
        FinancialCashFlowIssueCode.OVERDUE_OCCURRENCES: (
            len(overdue),
            frozenset(d.account_id for d in overdue),
        ),
    }
    issues = _issues(window, entries, rule_issues)
    if window.is_historical:
        status = FinancialCashFlowProjectionStatus.NOT_APPLICABLE
    elif any(
        issue.severity is FinancialCashFlowIssueSeverity.INCOMPLETE for issue in issues
    ):
        status = FinancialCashFlowProjectionStatus.INCOMPLETE
    else:
        status = FinancialCashFlowProjectionStatus.COMPLETE
    return FinancialCashFlowGroup(
        currency=currency,
        accounts=account_summaries,
        starting_balance=group_starting,
        balance_at_reference=_sum(at_reference.values(), zero),
        closing_balance=group_running,
        totals=_totals(events, zero),
        risk=_risk([(day.date, day.closing) for day in days]),
        days=days,
        events=tuple(events),
        projection_status=status,
        issues=issues,
    )


def _days(
    window: FinancialCashFlowWindow,
    by_day: dict[date, list[FinancialCashFlowEvent]],
    opening: Money,
    zero: Money,
) -> tuple[FinancialCashFlowDay, ...]:
    days: list[FinancialCashFlowDay] = []
    current = window.from_date
    for _ in range(window.days):
        events = by_day.get(current, [])
        totals = _totals(events, zero)
        closing = opening + totals.realized_net + totals.expected_net
        days.append(
            FinancialCashFlowDay(
                date=current,
                opening=opening,
                realized_income=totals.realized_income,
                realized_expense=totals.realized_expense,
                expected_income=totals.expected_income,
                expected_expense=totals.expected_expense,
                neutral_net=totals.neutral_in - totals.neutral_out,
                closing=closing,
                projected=(
                    not window.is_historical and current >= window.reference_date
                ),
            )
        )
        opening = closing
        current = current + timedelta(days=1)
    return tuple(days)


def _account_summary(
    entry: FinancialCashFlowAccountInput,
    window: FinancialCashFlowWindow,
    events: list[FinancialCashFlowEvent],
    starting: dict[UUID, Money],
    at_reference: dict[UUID, Money],
    zero: Money,
) -> FinancialCashFlowAccountSummary:
    account_id = entry.account.id
    own = [event for event in events if event.account_id == account_id]
    totals = _totals(own, zero)
    closing_by_day: dict[date, Money] = {}
    for event in own:
        closing_by_day[event.date] = event.account_balance_after
    series: list[tuple[date, Money]] = []
    balance = starting[account_id]
    current = window.from_date
    for _ in range(window.days):
        balance = closing_by_day.get(current, balance)
        series.append((current, balance))
        current = current + timedelta(days=1)
    return FinancialCashFlowAccountSummary(
        account=entry.account,
        opening_balance=entry.opening_balance,
        starting_balance=starting[account_id],
        balance_at_reference=at_reference[account_id],
        realized_net=totals.realized_net,
        expected_net=totals.expected_net,
        closing_balance=balance,
        risk=_risk(series),
    )


def _totals(
    events: list[FinancialCashFlowEvent], zero: Money
) -> FinancialCashFlowTotals:
    realized_income = realized_expense = neutral_in = neutral_out = zero
    expected_income = expected_expense = overdue_net = zero
    recurrence_expected = recurrence_actual = zero
    overdue_count = recurrence_count = realized_count = expected_count = 0
    for event in events:
        amount = event.amount
        if event.kind is FinancialCashFlowEventKind.REALIZED:
            realized_count += 1
            if event.result_effect is FinancialResultEffect.INCOME:
                realized_income = realized_income + amount
            elif event.result_effect is FinancialResultEffect.EXPENSE:
                realized_expense = realized_expense - amount
            elif amount.amount > 0:
                neutral_in = neutral_in + amount
            else:
                neutral_out = neutral_out - amount
            if event.expected_amount is not None:
                recurrence_count += 1
                recurrence_expected = recurrence_expected + event.expected_amount
                recurrence_actual = recurrence_actual + amount
            continue
        expected_count += 1
        if event.result_effect is FinancialResultEffect.INCOME:
            expected_income = expected_income + amount
        else:
            expected_expense = expected_expense - amount
        if event.overdue:
            overdue_count += 1
            overdue_net = overdue_net + amount
    return FinancialCashFlowTotals(
        realized_income=realized_income,
        realized_expense=realized_expense,
        neutral_in=neutral_in,
        neutral_out=neutral_out,
        realized_net=realized_income - realized_expense + neutral_in - neutral_out,
        expected_income=expected_income,
        expected_expense=expected_expense,
        expected_net=expected_income - expected_expense,
        overdue_count=overdue_count,
        overdue_net=overdue_net,
        recurrence_realized_count=recurrence_count,
        recurrence_realized_expected=recurrence_expected,
        recurrence_realized_actual=recurrence_actual,
        realized_count=realized_count,
        expected_count=expected_count,
    )


def _risk(series: list[tuple[date, Money]]) -> FinancialCashFlowRisk:
    minimum_date, minimum = series[0]
    first_negative: date | None = None
    negative_days = 0
    for day, closing in series:
        if closing < minimum:
            minimum_date, minimum = day, closing
        if closing.amount < 0:
            negative_days += 1
            if first_negative is None:
                first_negative = day
    return FinancialCashFlowRisk(
        minimum_balance=minimum,
        minimum_balance_date=minimum_date,
        first_negative_date=first_negative,
        negative_days=negative_days,
    )


def _issues(
    window: FinancialCashFlowWindow,
    entries: list[FinancialCashFlowAccountInput],
    counted: _RuleIssues,
) -> tuple[FinancialCashFlowIssue, ...]:
    """Issues in a fixed order; accounts listed in the group's account order.

    Counts: accounts for the opening-balance codes, occurrences for
    ``OVERDUE_OCCURRENCES``, months for ``UNGENERATED_PAST_OCCURRENCES`` and
    rules for ``RULE_ACCOUNT_INACTIVE`` / ``PAUSED_RULES``.
    """
    issues: list[FinancialCashFlowIssue] = []

    def add(
        code: FinancialCashFlowIssueCode, count: int, account_ids: tuple[UUID, ...]
    ) -> None:
        if count > 0:
            issues.append(
                FinancialCashFlowIssue(code, _ISSUE_SEVERITY[code], count, account_ids)
            )

    missing = tuple(e.account.id for e in entries if e.opening_balance is None)
    add(FinancialCashFlowIssueCode.OPENING_BALANCE_MISSING, len(missing), missing)
    late = tuple(
        e.account.id
        for e in entries
        if e.opening_balance is not None
        and e.opening_balance.effective_date > window.from_date
    )
    add(FinancialCashFlowIssueCode.OPENING_BALANCE_AFTER_WINDOW_START, len(late), late)
    order = {entry.account.id: index for index, entry in enumerate(entries)}
    for code in (
        FinancialCashFlowIssueCode.RULE_ACCOUNT_INACTIVE,
        FinancialCashFlowIssueCode.OVERDUE_OCCURRENCES,
        FinancialCashFlowIssueCode.UNGENERATED_PAST_OCCURRENCES,
        FinancialCashFlowIssueCode.PAUSED_RULES,
    ):
        count, account_ids = counted.get(code, (0, frozenset()))
        add(code, count, tuple(sorted(account_ids, key=order.__getitem__)))
    if window.is_historical:
        add(FinancialCashFlowIssueCode.HISTORICAL_WINDOW, 1, ())
    return tuple(issues)


def _base(entry: FinancialCashFlowAccountInput) -> Money:
    if entry.opening_balance is None:
        return Money(Decimal(0), entry.account.currency)
    return entry.opening_balance.amount


def _signed(expected: Money, effect: FinancialResultEffect) -> Money:
    if effect is FinancialResultEffect.INCOME:
        return expected
    if effect is FinancialResultEffect.EXPENSE:
        return -expected
    raise FinancialLedgerStateError("recurrence effect must be INCOME or EXPENSE")


def _sum(values: Iterable[Money], zero: Money) -> Money:
    total = zero
    for value in values:
        total = total + value
    return total


def _require_currency(money: Money, currency: str, field_name: str) -> None:
    if not isinstance(money, Money):
        raise TypeError(f"{field_name} must be Money")
    if money.currency != currency:
        raise FinancialLedgerStateError(f"{field_name} currency mismatch")


def _require_plain_date(value: object, field_name: str) -> None:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{field_name} must be date")


def _require_aware(value: datetime, field_name: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "CASH_FLOW_ACCOUNTS_MAX",
    "CASH_FLOW_DEFAULT_WINDOW_DAYS",
    "CASH_FLOW_EVENTS_MAX",
    "CASH_FLOW_EXCLUDED_SOURCES",
    "CASH_FLOW_WINDOW_MAX_DAYS",
    "FinancialCashFlowAccountInput",
    "FinancialCashFlowAccountSummary",
    "FinancialCashFlowDay",
    "FinancialCashFlowEvent",
    "FinancialCashFlowEventKind",
    "FinancialCashFlowExcludedSource",
    "FinancialCashFlowGroup",
    "FinancialCashFlowIssue",
    "FinancialCashFlowIssueCode",
    "FinancialCashFlowIssueSeverity",
    "FinancialCashFlowLimitError",
    "FinancialCashFlowProjection",
    "FinancialCashFlowProjectionStatus",
    "FinancialCashFlowRisk",
    "FinancialCashFlowSource",
    "FinancialCashFlowTotals",
    "FinancialCashFlowWindow",
    "FinancialCashFlowWindowError",
    "cash_flow_rule_months",
    "cash_flow_window",
    "project_cash_flow",
]
