from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.accounts import (
    FinancialAccountRecord,
    FinancialAccountStatus,
    FinancialAccountType,
)
from meufinanceiro_finance.balance_statement import FinancialLedgerStateError
from meufinanceiro_finance.cash_flow import (
    CASH_FLOW_EVENTS_MAX,
    CASH_FLOW_EXCLUDED_SOURCES,
    FinancialCashFlowAccountInput,
    FinancialCashFlowEventKind,
    FinancialCashFlowIssueCode,
    FinancialCashFlowIssueSeverity,
    FinancialCashFlowLimitError,
    FinancialCashFlowProjection,
    FinancialCashFlowProjectionStatus,
    FinancialCashFlowSource,
    FinancialCashFlowWindow,
    FinancialCashFlowWindowError,
    cash_flow_rule_months,
    cash_flow_window,
    project_cash_flow,
)
from meufinanceiro_finance.ids import new_financial_resource_id
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.movements import (
    FinancialMovementRole,
    FinancialResultEffect,
)
from meufinanceiro_finance.opening_balances import FinancialOpeningBalanceRecord
from meufinanceiro_finance.recurrences import (
    FinancialOccurrenceMovementState,
    FinancialOccurrenceStatus,
    FinancialRecurrenceFrequency,
    FinancialRecurrenceOccurrenceRecord,
    FinancialRecurrenceRealization,
    FinancialRecurrenceRecord,
    FinancialRecurrenceStatus,
    FinancialRecurrenceWindow,
)

RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000001")
OPERATOR_ID = UUID("30000000-0000-4000-8000-000000000001")
CHECKING = UUID("10000000-0000-4000-8000-000000000001")
SAVINGS = UUID("10000000-0000-4000-8000-000000000002")
EURO = UUID("10000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
TODAY = date(2026, 10, 10)
INCOME = FinancialResultEffect.INCOME
EXPENSE = FinancialResultEffect.EXPENSE
NEUTRAL = FinancialResultEffect.NEUTRAL

_sequence = iter(range(1, 10_000_000))


def _money(amount: str, currency: str = "BRL") -> Money:
    return Money(Decimal(amount), currency)


def _account(
    account_id: UUID = CHECKING,
    *,
    name: str = "Conta corrente",
    currency: str = "BRL",
    status: FinancialAccountStatus = FinancialAccountStatus.ACTIVE,
) -> FinancialAccountRecord:
    created_at = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    return FinancialAccountRecord(
        id=account_id,
        residence_id=RESIDENCE_ID,
        owner_operator_id=OPERATOR_ID,
        visibility_scope=FinancialVisibilityScope.PERSONAL,
        account_type=FinancialAccountType.CHECKING,
        custom_type_name=None,
        name=name,
        currency=currency,
        status=status,
        created_at=created_at,
        updated_at=created_at,
        archived_at=None if status is FinancialAccountStatus.ACTIVE else created_at,
    )


def _opening(
    account_id: UUID, amount: str, *, currency: str = "BRL", on: date = date(2026, 1, 1)
) -> FinancialOpeningBalanceRecord:
    return FinancialOpeningBalanceRecord(
        id=new_financial_resource_id(),
        residence_id=RESIDENCE_ID,
        account_id=account_id,
        amount=_money(amount, currency),
        effective_date=on,
        created_by_operator_id=OPERATOR_ID,
        created_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    )


def _entry(
    account: FinancialAccountRecord,
    *,
    opening: str | None = "1000",
    before: str = "0",
    through_reference: str | None = None,
    opening_on: date = date(2026, 1, 1),
) -> FinancialCashFlowAccountInput:
    return FinancialCashFlowAccountInput(
        account=account,
        opening_balance=(
            None
            if opening is None
            else _opening(account.id, opening, currency=account.currency, on=opening_on)
        ),
        net_before_window=_money(before, account.currency),
        net_through_reference=_money(
            before if through_reference is None else through_reference,
            account.currency,
        ),
    )


def _movement(
    amount: str,
    effect: FinancialResultEffect,
    on: date,
    *,
    account_id: UUID = CHECKING,
    currency: str = "BRL",
    reversal_of: FinancialMovementRecord | None = None,
    description: str = "Movimento",
) -> FinancialMovementRecord:
    sequence = next(_sequence)
    role = (
        FinancialMovementRole.STANDARD
        if reversal_of is None
        else FinancialMovementRole.REVERSAL
    )
    return FinancialMovementRecord(
        id=new_financial_resource_id(),
        account_id=account_id,
        amount=_money(amount, currency),
        result_effect=effect,
        role=role,
        effective_date=on,
        competence_date=on,
        description=description if reversal_of is None else None,
        reversal_of_id=None if reversal_of is None else reversal_of.id,
        reversal_reason=None if reversal_of is None else "Estorno",
        created_by_operator_id=OPERATOR_ID,
        created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=sequence),
    )


def _rule(
    *,
    account_id: UUID = CHECKING,
    effect: FinancialResultEffect = EXPENSE,
    expected: str = "120",
    currency: str = "BRL",
    day: int = 15,
    start: date = date(2026, 1, 1),
    end: date | None = None,
    status: FinancialRecurrenceStatus = FinancialRecurrenceStatus.ACTIVE,
    description: str = "Internet",
    version: int = 1,
) -> FinancialRecurrenceRecord:
    return FinancialRecurrenceRecord(
        id=new_financial_resource_id(),
        residence_id=RESIDENCE_ID,
        account_id=account_id,
        owner_operator_id=OPERATOR_ID,
        description=description,
        result_effect=effect,
        expected=_money(expected, currency),
        frequency=FinancialRecurrenceFrequency.MONTHLY,
        start_date=start,
        day_of_month=day,
        end_date=end,
        status=status,
        version=version,
        created_at=NOW,
        updated_at=NOW,
    )


def _occurrence(
    rule: FinancialRecurrenceRecord,
    scheduled: date,
    *,
    status: FinancialOccurrenceStatus = FinancialOccurrenceStatus.PENDING,
    expected: str | None = None,
    movement: FinancialMovementRecord | None = None,
) -> FinancialRecurrenceOccurrenceRecord:
    realization = None
    if status is FinancialOccurrenceStatus.REALIZED:
        assert movement is not None
        realization = FinancialRecurrenceRealization(
            movement_id=movement.id,
            actual=abs(movement.amount),
            effective_date=movement.effective_date,
            competence_date=movement.competence_date,
            realized_at=NOW,
            movement_state=FinancialOccurrenceMovementState.ACTIVE,
        )
    return FinancialRecurrenceOccurrenceRecord(
        id=new_financial_resource_id(),
        residence_id=RESIDENCE_ID,
        recurrence_id=rule.id,
        account_id=rule.account_id,
        owner_operator_id=OPERATOR_ID,
        period_start=scheduled.replace(day=1),
        scheduled_date=scheduled,
        rule_version=rule.version,
        result_effect=rule.result_effect,
        expected=rule.expected if expected is None else _money(expected),
        description=rule.description,
        status=status,
        created_at=NOW,
        updated_at=NOW,
        realization=realization,
    )


def _source(
    *entries: FinancialCashFlowAccountInput,
    movements: tuple[FinancialMovementRecord, ...] = (),
    transfer_ids: dict[UUID, UUID] | None = None,
    realized: tuple[FinancialRecurrenceOccurrenceRecord, ...] = (),
    pending: tuple[FinancialRecurrenceOccurrenceRecord, ...] = (),
    live: tuple[FinancialRecurrenceOccurrenceRecord, ...] = (),
    rules: tuple[FinancialRecurrenceRecord, ...] = (),
) -> FinancialCashFlowSource:
    return FinancialCashFlowSource(
        accounts=entries,
        movements=movements,
        transfer_ids=transfer_ids or {},
        realized_occurrences={
            occurrence.realization.movement_id: occurrence
            for occurrence in realized
            if occurrence.realization is not None
        },
        pending_occurrences=pending,
        live_occurrence_months=frozenset(
            (occurrence.recurrence_id, occurrence.period_start)
            for occurrence in (*live, *realized)
        ),
        rules=rules,
    )


def _window(
    start: date = TODAY, end: date = date(2026, 11, 8), today: date = TODAY
) -> FinancialCashFlowWindow:
    return FinancialCashFlowWindow(start, end, today)


def _project(
    source: FinancialCashFlowSource, window: FinancialCashFlowWindow | None = None
) -> FinancialCashFlowProjection:
    return project_cash_flow(
        window=window or _window(), source=source, calculated_at=NOW
    )


# --- window -----------------------------------------------------------------------


def test_window_defaults_to_thirty_days_from_the_reference_date() -> None:
    window = cash_flow_window(from_date=None, through_date=None, reference_date=TODAY)

    assert window.from_date == TODAY
    assert window.through_date == date(2026, 11, 8)
    assert window.days == 30
    assert window.is_historical is False


def test_window_accepts_ninety_two_days_and_a_past_start() -> None:
    window = cash_flow_window(
        from_date=date(2026, 7, 1), through_date=date(2026, 9, 30), reference_date=TODAY
    )
    assert window.days == 92
    assert window.is_historical is True


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 10, 11), date(2026, 10, 20)),  # from in the future
        (date(2026, 10, 10), date(2026, 10, 9)),  # through before from
        (date(2026, 10, 10), date(2027, 1, 10)),  # 93 days
    ],
)
def test_window_outside_the_contract_is_refused(start: date, end: date) -> None:
    with pytest.raises(FinancialCashFlowWindowError):
        cash_flow_window(from_date=start, through_date=end, reference_date=TODAY)


def test_window_rejects_datetimes() -> None:
    with pytest.raises(TypeError):
        cash_flow_window(
            from_date=datetime(2026, 10, 10, tzinfo=UTC),  # type: ignore[arg-type]
            through_date=None,
            reference_date=TODAY,
        )


def test_window_overflow_is_a_window_error() -> None:
    with pytest.raises(FinancialCashFlowWindowError):
        cash_flow_window(
            from_date=date(9999, 12, 20), through_date=None, reference_date=date.max
        )


def test_rule_months_cover_the_reference_month_and_the_window() -> None:
    assert cash_flow_rule_months(_window()) == FinancialRecurrenceWindow(
        date(2026, 10, 1), date(2026, 11, 1)
    )
    assert cash_flow_rule_months(
        _window(date(2026, 9, 20), date(2026, 10, 31))
    ) == FinancialRecurrenceWindow(date(2026, 9, 1), date(2026, 10, 1))
    assert cash_flow_rule_months(_window(date(2026, 9, 1), date(2026, 9, 30))) is None


# --- realized ---------------------------------------------------------------------


def test_balances_derive_from_opening_and_movements_only() -> None:
    salary = _movement("5000", INCOME, date(2026, 10, 5))
    rent = _movement("-1800", EXPENSE, date(2026, 10, 10))
    future = _movement("-200", EXPENSE, date(2026, 10, 20))
    source = _source(
        _entry(_account(), opening="1000", before="300", through_reference="3500"),
        movements=(future, rent, salary),
    )

    group = _project(source, _window(date(2026, 10, 1), date(2026, 10, 31))).groups[0]

    assert group.starting_balance == _money("1300")
    assert group.balance_at_reference == _money("4500")
    assert group.closing_balance == _money("4300")
    assert [event.movement_id for event in group.events] == [
        salary.id,
        rent.id,
        future.id,
    ]
    assert [event.balance_after for event in group.events] == [
        _money("6300"),
        _money("4500"),
        _money("4300"),
    ]
    assert all(e.kind is FinancialCashFlowEventKind.REALIZED for e in group.events)
    assert group.totals.realized_income == _money("5000")
    assert group.totals.realized_expense == _money("2000")
    assert group.totals.realized_net == _money("3000")
    assert group.totals.expected_net == _money("0")
    assert group.projection_status is FinancialCashFlowProjectionStatus.COMPLETE
    assert group.issues == ()


def test_days_cover_every_date_and_chain_opening_to_closing() -> None:
    movement = _movement("-50", EXPENSE, date(2026, 10, 12))
    source = _source(_entry(_account()), movements=(movement,))

    days = _project(source).groups[0].days

    assert len(days) == 30
    assert days[0].date == TODAY and days[-1].date == date(2026, 11, 8)
    for previous, current in zip(days, days[1:], strict=False):
        assert current.opening == previous.closing
    assert days[2].realized_expense == _money("50")
    assert days[2].closing == _money("950")
    assert all(day.projected for day in days)


def test_reversal_inside_the_window_nets_the_expense_to_zero() -> None:
    expense = _movement("-300", EXPENSE, date(2026, 10, 12))
    reversal = _movement("300", EXPENSE, date(2026, 10, 14), reversal_of=expense)
    source = _source(_entry(_account()), movements=(reversal, expense))

    group = _project(source).groups[0]

    assert group.totals.realized_expense == _money("0")
    assert group.closing_balance == _money("1000")
    assert group.events[1].movement_role is FinancialMovementRole.REVERSAL
    assert group.events[1].reversal_of_id == expense.id


def test_reversal_of_an_earlier_expense_lowers_the_window_expense() -> None:
    reversal_target = _movement("-300", EXPENSE, date(2026, 9, 1))
    reversal = _movement(
        "300", EXPENSE, date(2026, 10, 12), reversal_of=reversal_target
    )
    source = _source(
        _entry(_account(), before="-300", through_reference="-300"),
        movements=(reversal,),
    )

    group = _project(source).groups[0]

    assert group.starting_balance == _money("700")
    assert group.totals.realized_expense == _money("-300")
    assert group.closing_balance == _money("1000")


def test_transfer_between_selected_accounts_is_neutral_and_nets_out() -> None:
    transfer_id = uuid4()
    out_leg = _movement("-400", NEUTRAL, date(2026, 10, 12))
    in_leg = _movement("400", NEUTRAL, date(2026, 10, 12), account_id=SAVINGS)
    source = _source(
        _entry(_account()),
        _entry(_account(SAVINGS, name="Poupança"), opening="0"),
        movements=(out_leg, in_leg),
        transfer_ids={out_leg.id: transfer_id, in_leg.id: transfer_id},
    )

    group = _project(source).groups[0]

    assert group.totals.realized_income == _money("0")
    assert group.totals.realized_expense == _money("0")
    assert group.totals.neutral_in == _money("400")
    assert group.totals.neutral_out == _money("400")
    assert group.closing_balance == group.starting_balance == _money("1000")
    assert {event.transfer_id for event in group.events} == {transfer_id}
    checking, savings = sorted(group.accounts, key=lambda a: a.account.name)
    assert checking.closing_balance == _money("600")
    assert savings.closing_balance == _money("400")
    assert group.days[2].neutral_net == _money("0")


def test_transfer_to_an_unselected_account_changes_cash_but_not_result() -> None:
    out_leg = _movement("-400", NEUTRAL, date(2026, 10, 12))
    source = _source(
        _entry(_account()), movements=(out_leg,), transfer_ids={out_leg.id: uuid4()}
    )

    group = _project(source).groups[0]

    assert group.closing_balance == _money("600")
    assert group.totals.realized_expense == _money("0")
    assert group.totals.neutral_out == _money("400")
    assert group.days[2].neutral_net == _money("-400")


# --- expected ---------------------------------------------------------------------


def test_pending_occurrence_and_rule_months_are_projected_without_overlap() -> None:
    rule = _rule(day=15, expected="120")
    october = _occurrence(rule, date(2026, 10, 15))
    source = _source(
        _entry(_account()), pending=(october,), live=(october,), rules=(rule,)
    )

    group = _project(source, _window(TODAY, date(2026, 12, 31))).groups[0]

    expected = [(e.kind, e.date) for e in group.events]
    assert expected == [
        (FinancialCashFlowEventKind.EXPECTED_OCCURRENCE, date(2026, 10, 15)),
        (FinancialCashFlowEventKind.EXPECTED_RULE, date(2026, 11, 15)),
        (FinancialCashFlowEventKind.EXPECTED_RULE, date(2026, 12, 15)),
    ]
    assert group.events[0].occurrence_id == october.id
    assert group.events[1].occurrence_id is None
    assert group.events[1].recurrence_id == rule.id
    assert group.events[1].rule_version == 1
    assert group.events[1].period_start == date(2026, 11, 1)
    assert group.totals.expected_expense == _money("360")
    assert group.closing_balance == _money("640")
    assert group.balance_at_reference == _money("1000")


def test_persisted_snapshot_wins_over_the_current_rule_amount() -> None:
    rule = _rule(expected="150", version=2)
    october = _occurrence(rule, date(2026, 10, 15), expected="120")
    source = _source(
        _entry(_account()), pending=(october,), live=(october,), rules=(rule,)
    )

    events = _project(source, _window(TODAY, date(2026, 11, 30))).groups[0].events

    assert [e.amount for e in events] == [_money("-120"), _money("-150")]


def test_overdue_pending_occurrence_lands_on_the_reference_date() -> None:
    rule = _rule(day=5, effect=INCOME, expected="900", description="Aluguel recebido")
    september = _occurrence(rule, date(2026, 9, 5))
    october = _occurrence(rule, date(2026, 10, 5))
    source = _source(
        _entry(_account()),
        pending=(september, october),
        live=(september, october),
        rules=(rule,),
    )

    group = _project(source).groups[0]

    overdue = [e for e in group.events if e.overdue]
    assert [e.date for e in overdue] == [TODAY, TODAY]
    assert [e.scheduled_date for e in overdue] == [date(2026, 9, 5), date(2026, 10, 5)]
    assert group.totals.overdue_count == 2
    assert group.totals.overdue_net == _money("1800")
    issue = group.issues[0]
    assert issue.code is FinancialCashFlowIssueCode.OVERDUE_OCCURRENCES
    assert issue.severity is FinancialCashFlowIssueSeverity.ATTENTION
    assert issue.count == 2
    assert issue.account_ids == (CHECKING,)
    # Overdue is still a projection: the real balance on the reference is untouched.
    assert group.balance_at_reference == _money("1000")
    assert group.accounts[0].balance_at_reference == _money("1000")
    assert group.projection_status is FinancialCashFlowProjectionStatus.COMPLETE


def test_realized_occurrence_uses_only_its_movement() -> None:
    rule = _rule(day=12, expected="120")
    payment = _movement("-127.50", EXPENSE, date(2026, 10, 12), description="Internet")
    october = _occurrence(
        rule,
        date(2026, 10, 12),
        status=FinancialOccurrenceStatus.REALIZED,
        movement=payment,
    )
    source = _source(
        _entry(_account()), movements=(payment,), realized=(october,), rules=(rule,)
    )

    group = _project(source, _window(TODAY, date(2026, 11, 30))).groups[0]

    october_events = [e for e in group.events if e.date.month == 10]
    assert len(october_events) == 1
    event = october_events[0]
    assert event.kind is FinancialCashFlowEventKind.REALIZED
    assert event.occurrence_id == october.id
    assert event.recurrence_id == rule.id
    assert event.expected_amount == _money("-120")
    assert event.amount == _money("-127.50")
    assert group.totals.recurrence_realized_count == 1
    assert group.totals.recurrence_realized_expected == _money("-120")
    assert group.totals.recurrence_realized_actual == _money("-127.50")
    # November is still due from the rule.
    assert [e.kind for e in group.events][1:] == [
        FinancialCashFlowEventKind.EXPECTED_RULE
    ]


def test_reversed_realization_reopens_nothing() -> None:
    rule = _rule(day=12)
    payment = _movement("-120", EXPENSE, date(2026, 10, 12))
    reversal = _movement("120", EXPENSE, date(2026, 10, 13), reversal_of=payment)
    october = _occurrence(
        rule,
        date(2026, 10, 12),
        status=FinancialOccurrenceStatus.REALIZED,
        movement=payment,
    )
    source = _source(
        _entry(_account()),
        movements=(payment, reversal),
        realized=(october,),
        rules=(rule,),
    )

    group = _project(source, _window(TODAY, date(2026, 10, 31))).groups[0]

    assert [e.kind for e in group.events] == [
        FinancialCashFlowEventKind.REALIZED,
        FinancialCashFlowEventKind.REALIZED,
    ]
    assert group.closing_balance == _money("1000")
    assert group.totals.expected_count == 0


def test_skipped_month_expects_nothing_and_superseded_falls_back_to_the_rule() -> None:
    rule = _rule(day=20, expected="80", version=3)
    skipped = _occurrence(
        rule, date(2026, 10, 20), status=FinancialOccurrenceStatus.SKIPPED
    )
    # A SUPERSEDED November row is history: it is not live, so the rule decides.
    source = _source(_entry(_account()), live=(skipped,), rules=(rule,))

    events = _project(source, _window(TODAY, date(2026, 11, 30))).groups[0].events

    assert [(e.kind, e.date, e.rule_version) for e in events] == [
        (FinancialCashFlowEventKind.EXPECTED_RULE, date(2026, 11, 20), 3)
    ]
    assert events[0].amount == _money("-80")


def test_paused_rule_projects_no_new_month_but_its_pending_still_counts() -> None:
    rule = _rule(day=15, status=FinancialRecurrenceStatus.PAUSED)
    october = _occurrence(rule, date(2026, 10, 15))
    source = _source(
        _entry(_account()), pending=(october,), live=(october,), rules=(rule,)
    )

    group = _project(source, _window(TODAY, date(2026, 12, 31))).groups[0]

    assert [e.kind for e in group.events] == [
        FinancialCashFlowEventKind.EXPECTED_OCCURRENCE
    ]
    assert [(i.code, i.count) for i in group.issues] == [
        (FinancialCashFlowIssueCode.PAUSED_RULES, 1)
    ]
    assert group.projection_status is FinancialCashFlowProjectionStatus.COMPLETE


def test_rule_of_an_archived_account_makes_the_projection_incomplete() -> None:
    archived = _account(status=FinancialAccountStatus.ARCHIVED)
    rule = _rule()
    source = _source(_entry(archived), rules=(rule,))

    group = _project(source).groups[0]

    assert group.events == ()
    assert group.issues[0].code is FinancialCashFlowIssueCode.RULE_ACCOUNT_INACTIVE
    assert group.issues[0].account_ids == (CHECKING,)
    assert group.projection_status is FinancialCashFlowProjectionStatus.INCOMPLETE


def test_ungenerated_past_months_are_reported_not_invented() -> None:
    rule = _rule(day=5)
    source = _source(_entry(_account()), rules=(rule,))

    group = _project(source, _window(date(2026, 9, 1), date(2026, 10, 31))).groups[0]

    # September 5 and October 5 passed with no occurrence: nothing is projected.
    assert group.events == ()
    issue = group.issues[0]
    assert issue.code is FinancialCashFlowIssueCode.UNGENERATED_PAST_OCCURRENCES
    assert issue.count == 2


def test_rule_start_and_end_dates_bound_the_projection() -> None:
    late_start = _rule(day=1, start=date(2026, 11, 2), description="Academia")
    ends = _rule(day=25, end=date(2026, 11, 24), description="Curso")
    source = _source(_entry(_account()), rules=(late_start, ends))

    events = _project(source, _window(TODAY, date(2027, 1, 7))).groups[0].events

    assert [(e.description, e.date) for e in events] == [
        ("Curso", date(2026, 10, 25)),
        ("Academia", date(2026, 12, 1)),
        ("Academia", date(2027, 1, 1)),
    ]


def test_day_31_falls_on_the_last_day_and_leap_years_are_respected() -> None:
    rule = _rule(day=31, start=date(2027, 1, 1))
    source = _source(_entry(_account()), rules=(rule,))

    leap = _project(
        source,
        FinancialCashFlowWindow(date(2028, 2, 1), date(2028, 4, 30), date(2028, 2, 1)),
    ).groups[0]
    common = _project(
        source,
        FinancialCashFlowWindow(date(2027, 2, 1), date(2027, 4, 30), date(2027, 2, 1)),
    ).groups[0]

    assert [e.date for e in leap.events] == [
        date(2028, 2, 29),
        date(2028, 3, 31),
        date(2028, 4, 30),
    ]
    assert [e.date for e in common.events] == [
        date(2027, 2, 28),
        date(2027, 3, 31),
        date(2027, 4, 30),
    ]


def test_window_boundaries_are_inclusive() -> None:
    rule = _rule(day=8)
    source = _source(_entry(_account()), rules=(rule,))

    inside = _project(source, _window(TODAY, date(2026, 11, 8))).groups[0]
    outside = _project(source, _window(TODAY, date(2026, 11, 7))).groups[0]

    assert [e.date for e in inside.events] == [date(2026, 11, 8)]
    assert outside.events == ()


def test_negative_risk_identifies_the_first_deficit_day() -> None:
    rule = _rule(day=20, expected="1500", description="Aluguel")
    salary = _rule(day=5, effect=INCOME, expected="3000", description="Salário")
    source = _source(_entry(_account()), rules=(rule, salary))

    group = _project(source, _window(TODAY, date(2026, 11, 30))).groups[0]

    assert group.risk.first_negative_date == date(2026, 10, 20)
    assert group.risk.minimum_balance == _money("-500")
    assert group.risk.minimum_balance_date == date(2026, 10, 20)
    assert group.risk.negative_days == 16  # Oct 20 .. Nov 4
    negative = [day for day in group.days if day.negative]
    assert negative[0].date == date(2026, 10, 20)
    assert negative[-1].date == date(2026, 11, 4)
    assert group.accounts[0].risk.first_negative_date == date(2026, 10, 20)


def test_per_account_risk_is_visible_even_when_the_group_is_positive() -> None:
    rule = _rule(account_id=SAVINGS, expected="200")
    source = _source(
        _entry(_account()),
        _entry(_account(SAVINGS, name="Poupança"), opening="100"),
        rules=(rule,),
    )

    group = _project(source).groups[0]

    assert group.risk.first_negative_date is None
    savings = next(a for a in group.accounts if a.account.id == SAVINGS)
    assert savings.risk.first_negative_date == date(2026, 10, 15)
    assert savings.closing_balance == _money("-100")


def test_ordering_on_one_day_is_realized_then_overdue_then_scheduled() -> None:
    rule_a = _rule(day=10, description="B scheduled")
    rule_b = _rule(day=1, description="A overdue")
    overdue = _occurrence(rule_b, date(2026, 10, 1))
    realized = _movement("-10", EXPENSE, TODAY)
    source = _source(
        _entry(_account(), through_reference="-10"),
        movements=(realized,),
        pending=(overdue,),
        live=(overdue,),
        rules=(rule_a, rule_b),
    )

    events = _project(source, _window(TODAY, date(2026, 10, 31))).groups[0].events

    assert [(e.kind, e.description) for e in events] == [
        (FinancialCashFlowEventKind.REALIZED, "Movimento"),
        (FinancialCashFlowEventKind.EXPECTED_OCCURRENCE, "A overdue"),
        (FinancialCashFlowEventKind.EXPECTED_RULE, "B scheduled"),
    ]


def test_projection_is_deterministic_under_input_order() -> None:
    rules = tuple(
        _rule(day=day, description=f"Regra {day}") for day in (11, 15, 15, 28)
    )
    pending = (_occurrence(rules[0], date(2026, 10, 11)),)
    movements = tuple(
        _movement(f"-{index}", EXPENSE, date(2026, 10, 11 + index % 5))
        for index in range(1, 20)
    )
    entries = (_entry(_account()), _entry(_account(SAVINGS, name="Poupança")))

    def build(seed: int) -> FinancialCashFlowProjection:
        shuffle = random.Random(seed)
        return _project(
            _source(
                *shuffle.sample(entries, len(entries)),
                movements=tuple(shuffle.sample(movements, len(movements))),
                pending=pending,
                live=pending,
                rules=tuple(shuffle.sample(rules, len(rules))),
            )
        )

    reference = build(0)
    for seed in range(1, 6):
        other = build(seed)
        assert [
            (e.kind, e.movement_id, e.recurrence_id, e.balance_after)
            for e in other.groups[0].events
        ] == [
            (e.kind, e.movement_id, e.recurrence_id, e.balance_after)
            for e in reference.groups[0].events
        ]
        assert other.groups[0].days == reference.groups[0].days


# --- currencies, completeness and history -----------------------------------------


def test_currencies_are_separate_groups_and_never_summed() -> None:
    euro = _account(EURO, name="Conta euro", currency="EUR")
    source = _source(
        _entry(_account(), opening="1000"),
        _entry(euro, opening="50"),
        movements=(
            _movement(
                "-10", EXPENSE, date(2026, 10, 12), account_id=EURO, currency="EUR"
            ),
        ),
        rules=(_rule(account_id=EURO, currency="EUR", expected="5"),),
    )

    projection = _project(source)

    assert [group.currency for group in projection.groups] == ["BRL", "EUR"]
    brl, eur = projection.groups
    assert brl.closing_balance == _money("1000")
    assert eur.closing_balance == _money("35", "EUR")
    assert {e.amount.currency for e in eur.events} == {"EUR"}
    assert brl.events == ()


def test_missing_opening_balance_is_incomplete_not_zero() -> None:
    source = _source(
        _entry(_account(), opening=None, before="-50", through_reference="-50")
    )

    group = _project(source).groups[0]

    assert group.starting_balance == _money("-50")
    assert group.accounts[0].has_opening_balance is False
    assert group.issues[0].code is FinancialCashFlowIssueCode.OPENING_BALANCE_MISSING
    assert group.issues[0].severity is FinancialCashFlowIssueSeverity.INCOMPLETE
    assert group.projection_status is FinancialCashFlowProjectionStatus.INCOMPLETE


def test_opening_inside_the_window_is_flagged() -> None:
    source = _source(_entry(_account(), opening_on=date(2026, 10, 20)))

    group = _project(source, _window(date(2026, 10, 1), date(2026, 10, 31))).groups[0]

    assert [i.code for i in group.issues] == [
        FinancialCashFlowIssueCode.OPENING_BALANCE_AFTER_WINDOW_START
    ]
    # Review R2 (P2-3): days before the anchor are not a trustworthy history.
    assert group.projection_status is FinancialCashFlowProjectionStatus.INCOMPLETE
    assert group.issues[0].severity is FinancialCashFlowIssueSeverity.INCOMPLETE


def test_historical_window_shows_only_realized_events() -> None:
    rule = _rule(day=15)
    pending = _occurrence(rule, date(2026, 9, 15))
    paid = _movement("-30", EXPENSE, date(2026, 9, 2))
    source = _source(
        _entry(_account(), before="0", through_reference="-30"),
        movements=(paid,),
        pending=(pending,),
        live=(pending,),
        rules=(rule,),
    )

    group = _project(source, _window(date(2026, 9, 1), date(2026, 9, 30))).groups[0]

    assert [e.kind for e in group.events] == [FinancialCashFlowEventKind.REALIZED]
    assert group.projection_status is FinancialCashFlowProjectionStatus.NOT_APPLICABLE
    assert [i.code for i in group.issues] == [
        FinancialCashFlowIssueCode.HISTORICAL_WINDOW
    ]
    assert not any(day.projected for day in group.days)
    assert group.balance_at_reference == _money("970")


def test_excluded_sources_are_stated() -> None:
    projection = _project(_source(_entry(_account())))
    assert projection.excluded_sources == CASH_FLOW_EXCLUDED_SOURCES
    assert {source.value for source in projection.excluded_sources} >= {
        "BUDGETS",
        "GOALS",
        "PROJECTS",
        "CARDS",
        "INSTALLMENTS",
        "LOANS",
    }


# --- fail closed ------------------------------------------------------------------


def test_inconsistent_snapshot_aggregates_fail_closed() -> None:
    movement = _movement("-10", EXPENSE, TODAY)
    source = _source(
        _entry(_account(), before="0", through_reference="0"), movements=(movement,)
    )
    with pytest.raises(FinancialLedgerStateError, match="inconsistent"):
        _project(source)


def test_too_many_events_are_refused_not_truncated() -> None:
    rules = tuple(
        _rule(day=(index % 28) + 1, description=f"Regra {index}")
        for index in range(CASH_FLOW_EVENTS_MAX // 3 + 1)
    )
    source = _source(_entry(_account()), rules=rules)
    window = FinancialCashFlowWindow(TODAY, date(2027, 1, 9), TODAY)

    with pytest.raises(FinancialCashFlowLimitError):
        _project(source, window)


def test_more_than_the_account_cap_is_refused() -> None:
    entries = tuple(
        _entry(_account(new_financial_resource_id(), name=f"Conta {index}"))
        for index in range(51)
    )
    with pytest.raises(FinancialCashFlowLimitError):
        _source(*entries)


@pytest.mark.parametrize(
    "case",
    [
        "movement_outside_window",
        "movement_unselected_account",
        "movement_currency",
        "duplicate_movement",
        "transfer_not_in_window",
        "pending_not_pending",
        "pending_after_window",
        "pending_unselected_account",
        "rule_unselected_account",
        "realized_link_mismatch",
        "duplicate_account",
    ],
)
def test_inconsistent_inputs_fail_closed(case: str) -> None:
    entry = _entry(_account())
    rule = _rule()
    inside = _movement("-1", EXPENSE, date(2026, 10, 12))
    source: FinancialCashFlowSource
    if case == "movement_outside_window":
        source = _source(
            entry, movements=(_movement("-1", EXPENSE, date(2026, 11, 9)),)
        )
    elif case == "movement_unselected_account":
        source = _source(
            entry, movements=(_movement("-1", EXPENSE, TODAY, account_id=SAVINGS),)
        )
    elif case == "movement_currency":
        source = _source(
            entry, movements=(_movement("-1", EXPENSE, TODAY, currency="EUR"),)
        )
    elif case == "duplicate_movement":
        source = _source(entry, movements=(inside, inside))
    elif case == "transfer_not_in_window":
        source = _source(entry, transfer_ids={uuid4(): uuid4()})
    elif case == "pending_not_pending":
        skipped = _occurrence(
            rule, date(2026, 10, 15), status=FinancialOccurrenceStatus.SKIPPED
        )
        source = _source(entry, pending=(skipped,), rules=(rule,))
    elif case == "pending_after_window":
        source = _source(
            entry, pending=(_occurrence(rule, date(2026, 11, 15)),), rules=(rule,)
        )
    elif case == "pending_unselected_account":
        other = _rule(account_id=SAVINGS)
        source = _source(entry, pending=(_occurrence(other, date(2026, 10, 15)),))
    elif case == "rule_unselected_account":
        source = _source(entry, rules=(_rule(account_id=SAVINGS),))
    elif case == "realized_link_mismatch":
        other = _movement("-5", EXPENSE, date(2026, 10, 13))
        occurrence = _occurrence(
            rule,
            date(2026, 10, 12),
            status=FinancialOccurrenceStatus.REALIZED,
            movement=other,
        )
        source = FinancialCashFlowSource(
            accounts=(entry,),
            movements=(inside, other),
            transfer_ids={},
            realized_occurrences={inside.id: occurrence},
            pending_occurrences=(),
            live_occurrence_months=frozenset(),
            rules=(rule,),
        )
    else:
        source = _source(entry, entry)
    with pytest.raises(FinancialLedgerStateError):
        _project(source)


def test_reprs_redact_money_and_identity() -> None:
    rule = _rule(description="Segredo")
    source = _source(
        _entry(_account(name="Conta secreta"), opening="12345"), rules=(rule,)
    )
    projection = _project(source)
    group = projection.groups[0]
    texts = [
        repr(projection),
        repr(group),
        repr(group.events[0]),
        repr(group.days[0]),
        repr(group.totals),
        repr(group.risk),
        repr(group.accounts[0]),
        repr(source),
        repr(source.accounts[0]),
    ]
    for text in texts:
        assert "12345" not in text
        assert "Segredo" not in text
        assert "secreta" not in text
        assert str(CHECKING) not in text


# --- review R2: historical vs prospective risk, opening anchor -------------------


def _mixed_window() -> FinancialCashFlowWindow:
    return _window(date(2026, 10, 1), date(2026, 10, 31))


def test_r2_past_only_deficit_is_not_announced_as_future_risk() -> None:
    dip = _movement("-1500", EXPENSE, date(2026, 10, 3))
    back = _movement("2000", INCOME, date(2026, 10, 6))
    source = _source(
        _entry(_account(), before="0", through_reference="500"),
        movements=(dip, back),
    )

    group = _project(source, _mixed_window()).groups[0]

    assert group.risk is not None
    assert group.risk.first_negative_date is None
    assert group.historical_risk is not None
    assert group.historical_risk.first_negative_date == date(2026, 10, 3)
    assert group.historical_risk.negative_days == 3
    account = group.accounts[0]
    assert account.risk is not None and account.risk.first_negative_date is None
    assert account.historical_risk is not None
    assert account.historical_risk.first_negative_date == date(2026, 10, 3)


def test_r2_days_before_the_opening_anchor_are_not_trusted() -> None:
    source = _source(_entry(_account(), opening="1000", opening_on=date(2026, 10, 5)))

    group = _project(source, _mixed_window()).groups[0]

    assert group.projection_status is FinancialCashFlowProjectionStatus.INCOMPLETE
    issue = group.issues[0]
    assert issue.code is FinancialCashFlowIssueCode.OPENING_BALANCE_AFTER_WINDOW_START
    assert issue.severity is FinancialCashFlowIssueSeverity.INCOMPLETE
    assert [day.anchored for day in group.days[:5]] == [False] * 4 + [True]


def test_r2_future_only_deficit_is_a_prospective_risk() -> None:
    rent = _rule(day=20, expected="1500")
    source = _source(
        _entry(_account(), before="0", through_reference="0"), rules=(rent,)
    )

    group = _project(source, _mixed_window()).groups[0]

    assert group.risk is not None
    assert group.risk.first_negative_date == date(2026, 10, 20)
    assert group.risk.negative_days == 12
    assert group.risk.evaluated_days == 22  # Oct 10 .. Oct 31
    assert group.historical_risk is not None
    assert group.historical_risk.first_negative_date is None
    assert group.historical_risk.evaluated_days == 9  # Oct 1 .. Oct 9


def test_r2_past_and_future_deficits_are_reported_separately() -> None:
    dip = _movement("-1500", EXPENSE, date(2026, 10, 2))
    back = _movement("1500", INCOME, date(2026, 10, 4))
    rent = _rule(day=25, expected="1200")
    source = _source(
        _entry(_account(), before="0", through_reference="0"),
        movements=(dip, back),
        rules=(rent,),
    )

    group = _project(source, _mixed_window()).groups[0]

    assert group.historical_risk is not None
    assert group.historical_risk.first_negative_date == date(2026, 10, 2)
    assert group.historical_risk.minimum_balance == _money("-500")
    assert group.risk is not None
    assert group.risk.first_negative_date == date(2026, 10, 25)
    assert group.risk.minimum_balance == _money("-200")


def test_r2_account_level_risks_are_split_independently_of_the_group() -> None:
    dip = _movement("-300", EXPENSE, date(2026, 10, 2), account_id=SAVINGS)
    back = _movement("300", INCOME, date(2026, 10, 3), account_id=SAVINGS)
    source = _source(
        _entry(_account()),
        _entry(
            _account(SAVINGS, name="Poupança"),
            opening="100",
            before="0",
            through_reference="0",
        ),
        movements=(dip, back),
    )

    group = _project(source, _mixed_window()).groups[0]

    assert group.historical_risk is not None
    assert group.historical_risk.first_negative_date is None  # 1100 - 300 > 0
    savings = next(a for a in group.accounts if a.account.id == SAVINGS)
    assert savings.historical_risk is not None
    assert savings.historical_risk.first_negative_date == date(2026, 10, 2)
    assert savings.risk is not None
    assert savings.risk.first_negative_date is None


def test_r2_missing_opening_balance_means_no_risk_is_evaluated() -> None:
    rent = _rule(day=20, expected="1500")
    source = _source(
        _entry(_account(), opening=None),
        _entry(_account(SAVINGS, name="Poupança"), opening="5000"),
        rules=(rent,),
    )

    group = _project(source).groups[0]

    assert group.risk is None
    assert group.historical_risk is None  # the window starts on the reference
    assert not any(day.anchored for day in group.days)
    checking = next(a for a in group.accounts if a.account.id == CHECKING)
    assert checking.risk is None
    savings = next(a for a in group.accounts if a.account.id == SAVINGS)
    assert savings.risk is not None
    assert savings.risk.evaluated_days == 30


def test_r2_pre_anchor_days_are_excluded_from_every_risk() -> None:
    # The opening (1000) anchors on Oct 5; before it the series would show the
    # same 1000, which is not a fact and must never be called "no deficit".
    source = _source(_entry(_account(), opening="1000", opening_on=date(2026, 10, 5)))

    group = _project(source, _mixed_window()).groups[0]

    assert group.historical_risk is not None
    assert group.historical_risk.evaluated_days == 5  # Oct 5 .. Oct 9
    assert group.historical_risk.minimum_balance_date == date(2026, 10, 5)
    assert group.accounts[0].historical_risk is not None
    assert group.accounts[0].historical_risk.evaluated_days == 5


def test_r2_historical_window_before_the_anchor_has_no_risk() -> None:
    source = _source(
        _entry(
            _account(),
            opening="1000",
            opening_on=date(2026, 9, 20),
            before="0",
            through_reference="0",
        )
    )

    group = _project(source, _window(date(2026, 9, 1), date(2026, 9, 15))).groups[0]

    assert group.projection_status is FinancialCashFlowProjectionStatus.NOT_APPLICABLE
    assert group.risk is None
    assert group.historical_risk is None
    assert [i.code for i in group.issues] == [
        FinancialCashFlowIssueCode.OPENING_BALANCE_AFTER_WINDOW_START,
        FinancialCashFlowIssueCode.HISTORICAL_WINDOW,
    ]


def test_r2_window_accepts_a_relative_length() -> None:
    window = cash_flow_window(
        from_date=None, through_date=None, reference_date=TODAY, days=7
    )
    assert (window.from_date, window.through_date) == (TODAY, date(2026, 10, 16))
    assert (
        cash_flow_window(
            from_date=None, through_date=None, reference_date=TODAY, days=92
        ).days
        == 92
    )
    for bad in (0, 93, -1, True):
        with pytest.raises(FinancialCashFlowWindowError):
            cash_flow_window(
                from_date=None, through_date=None, reference_date=TODAY, days=bad
            )
    with pytest.raises(FinancialCashFlowWindowError):
        cash_flow_window(
            from_date=None,
            through_date=date(2026, 10, 20),
            reference_date=TODAY,
            days=5,
        )
