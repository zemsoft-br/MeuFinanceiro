"""PostgreSQL-backed proofs for the read-only cash flow source (ADR-0031).

Everything runs through the non-superuser runtime role with forced RLS. The store
only reads: these proofs show the audience is decided by the database, the read is
one consistent snapshot, the statement count is fixed and nothing is written.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest
from meufinanceiro_finance import (
    FinancialCashFlowEventKind,
    FinancialCashFlowIssueCode,
    FinancialCashFlowProjection,
    FinancialCashFlowProjectionStatus,
    FinancialCashFlowSource,
    FinancialCashFlowWindow,
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialOpeningBalanceDraft,
    FinancialRecurrenceDraft,
    FinancialRecurrenceRealizationDraft,
    FinancialRecurrenceRecord,
    FinancialRecurrenceWindow,
    FinancialResultEffect,
    FinancialTransferDraft,
    Money,
    derive_financial_account_balance_and_statement,
    new_financial_idempotency_key,
    new_financial_resource_id,
    project_cash_flow,
)
from sqlalchemy import event, func, select, text

import meufinanceiro_persistence.financial_cash_flow_store as store_module
from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_cash_flow_store import (
    FinancialCashFlowAccessError,
    FinancialCashFlowAccountNotFoundError,
    FinancialCashFlowLimitExceededError,
    FinancialCashFlowStore,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceStore,
)
from meufinanceiro_persistence.financial_recurrence_schema import (
    financial_recurrence_occurrences,
    financial_recurrences,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceStore,
)
from meufinanceiro_persistence.financial_transfer_store import FinancialTransferStore

if TYPE_CHECKING:
    from conftest import BudgetWorld

_TODAY = date(2026, 10, 10)
_NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
_INCOME = FinancialResultEffect.INCOME
_EXPENSE = FinancialResultEffect.EXPENSE


def _brl(amount: str) -> Money:
    return Money(Decimal(amount), "BRL")


def _window(
    start: date = _TODAY, end: date = date(2026, 11, 30)
) -> FinancialCashFlowWindow:
    return FinancialCashFlowWindow(start, end, _TODAY)


def _store(world: BudgetWorld) -> FinancialCashFlowStore:
    return FinancialCashFlowStore(world.runtime)


def _read(
    world: BudgetWorld,
    window: FinancialCashFlowWindow | None = None,
    *,
    operator_id: UUID | None = None,
    **kwargs: Any,
) -> FinancialCashFlowSource:
    return _store(world).read_source(
        **world.scope(operator_id), window=window or _window(), **kwargs
    )


def _project(
    world: BudgetWorld,
    window: FinancialCashFlowWindow | None = None,
    **kwargs: Any,
) -> FinancialCashFlowProjection:
    window = window or _window()
    return project_cash_flow(
        window=window, source=_read(world, window, **kwargs), calculated_at=_NOW
    )


def _opening(
    world: BudgetWorld,
    account_id: UUID,
    amount: str,
    *,
    operator_id: UUID | None = None,
    currency: str = "BRL",
    on: date = date(2026, 1, 1),
) -> None:
    FinancialOpeningBalanceStore(world.runtime).create_opening_balance(
        **world.scope(operator_id),
        account_id=account_id,
        draft=FinancialOpeningBalanceDraft(
            amount=Money(Decimal(amount), currency), effective_date=on
        ),
    )


def _movement(
    world: BudgetWorld,
    account_id: UUID,
    amount: str,
    effect: FinancialResultEffect,
    on: date,
    *,
    operator_id: UUID | None = None,
    currency: str = "BRL",
    description: str = "Movimento",
) -> UUID:
    return (
        FinancialMovementStore(world.runtime)
        .create_movement(
            **world.scope(operator_id),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementDraft(
                account_id=account_id,
                amount=Money(Decimal(amount), currency),
                result_effect=effect,
                effective_date=on,
                competence_date=on,
                description=description,
            ),
        )
        .id
    )


def _reverse(world: BudgetWorld, movement_id: UUID, on: date) -> UUID:
    return (
        FinancialMovementStore(world.runtime)
        .reverse_movement(
            **world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementReversalDraft(
                movement_id=movement_id,
                effective_date=on,
                competence_date=on,
                reason="Estorno integral",
            ),
        )
        .id
    )


def _rule(
    world: BudgetWorld,
    account_id: UUID,
    *,
    day: int = 15,
    expected: str = "120",
    effect: FinancialResultEffect = _EXPENSE,
    description: str = "Internet",
    operator_id: UUID | None = None,
) -> FinancialRecurrenceRecord:
    return FinancialRecurrenceStore(world.runtime).create_recurrence(
        **world.scope(operator_id),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialRecurrenceDraft(
            account_id=account_id,
            description=description,
            result_effect=effect,
            expected=_brl(expected),
            start_date=date(2026, 1, 1),
            day_of_month=day,
        ),
    )


def _generate(
    world: BudgetWorld, rule: FinancialRecurrenceRecord, first: date, last: date
) -> list[UUID]:
    result = FinancialRecurrenceStore(world.runtime).generate_occurrences(
        **world.scope(),
        recurrence_id=rule.id,
        window=FinancialRecurrenceWindow(first, last),
    )
    return [occurrence.id for occurrence in result.occurrences]


def _counts(world: BudgetWorld) -> dict[str, int]:
    """Row counts of every finance table (privileged read)."""
    with world.engine.begin() as connection:
        tables = connection.scalars(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'finance' "
                "ORDER BY tablename"
            )
        ).all()
        return {
            table: int(
                connection.scalar(text(f'SELECT count(*) FROM finance."{table}"')) or 0
            )
            for table in tables
        }


# --- vertical ---------------------------------------------------------------------


def test_source_matches_the_canonical_balance_and_projects_the_rule(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    checking = world.account(name="Corrente")
    savings = world.account(name="Poupança")
    _opening(world, checking, "1000")
    _opening(world, savings, "0")
    _movement(world, checking, "300", _INCOME, date(2026, 9, 1), description="Bônus")
    salary = _movement(world, checking, "5000", _INCOME, date(2026, 10, 5))
    rent = _movement(world, checking, "-1800", _EXPENSE, date(2026, 10, 8))
    transfer = FinancialTransferStore(world.runtime).create_transfer(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialTransferDraft(
            source_account_id=checking,
            destination_account_id=savings,
            magnitude=_brl("500"),
            effective_date=date(2026, 10, 9),
            competence_date=date(2026, 10, 9),
            description="Reserva",
        ),
    )
    internet = _rule(world, checking, day=15, expected="120")
    october = _generate(world, internet, date(2026, 10, 1), date(2026, 10, 1))
    before = _counts(world)

    window = _window(date(2026, 10, 1), date(2026, 11, 30))
    source = _read(world, window)
    projection = project_cash_flow(window=window, source=source, calculated_at=_NOW)

    assert _counts(world) == before  # the read wrote nothing
    group = projection.groups[0]
    assert group.currency == "BRL"
    assert group.starting_balance == _brl("1300")
    assert group.balance_at_reference == _brl("4500")
    # The consolidated reference balance is the canonical derivation, account by account.
    accounts = {a.account.id: a for a in group.accounts}
    for account_id in (checking, savings):
        record = FinancialAccountStore(world.runtime).get_account(
            **world.scope(), account_id=account_id
        )
        snapshot, _ = derive_financial_account_balance_and_statement(
            account=record,
            opening_balance=FinancialOpeningBalanceStore(
                world.runtime
            ).get_opening_balance(**world.scope(), account_id=account_id),
            movements=FinancialMovementStore(world.runtime).list_movements(
                **world.scope(), account_id=account_id
            ),
            calculated_at=_NOW,
        )
        assert accounts[account_id].balance_at_reference == snapshot.current_balance
    kinds = [(e.kind, e.date) for e in group.events]
    assert kinds == [
        (FinancialCashFlowEventKind.REALIZED, date(2026, 10, 5)),
        (FinancialCashFlowEventKind.REALIZED, date(2026, 10, 8)),
        (FinancialCashFlowEventKind.REALIZED, date(2026, 10, 9)),
        (FinancialCashFlowEventKind.REALIZED, date(2026, 10, 9)),
        (FinancialCashFlowEventKind.EXPECTED_OCCURRENCE, date(2026, 10, 15)),
        (FinancialCashFlowEventKind.EXPECTED_RULE, date(2026, 11, 15)),
    ]
    assert group.events[0].movement_id == salary
    assert group.events[1].movement_id == rent
    assert {e.transfer_id for e in group.events[2:4]} == {transfer.id}
    assert group.events[4].occurrence_id == october[0]
    assert group.totals.neutral_in == group.totals.neutral_out == _brl("500")
    assert group.totals.realized_expense == _brl("1800")
    assert group.closing_balance == _brl("4260")
    assert group.projection_status is FinancialCashFlowProjectionStatus.COMPLETE


def test_realization_and_reversal_never_duplicate_the_occurrence(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account = world.account()
    _opening(world, account, "1000")
    rule = _rule(world, account, day=12, expected="120")
    occurrence_id = _generate(world, rule, date(2026, 10, 1), date(2026, 10, 1))[0]
    realized = FinancialRecurrenceStore(world.runtime).realize_occurrence(
        **world.scope(),
        occurrence_id=occurrence_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialRecurrenceRealizationDraft(
            actual=_brl("127.50"),
            effective_date=date(2026, 10, 9),
            competence_date=date(2026, 10, 9),
        ),
    )
    assert realized.realization is not None
    movement_id = realized.realization.movement_id

    group = _project(world, _window(date(2026, 10, 1), date(2026, 10, 31))).groups[0]
    assert [(e.kind, e.movement_id) for e in group.events] == [
        (FinancialCashFlowEventKind.REALIZED, movement_id)
    ]
    assert group.events[0].occurrence_id == occurrence_id
    assert group.events[0].expected_amount == _brl("-120")
    assert group.totals.recurrence_realized_actual == _brl("-127.50")

    reversal = _reverse(world, movement_id, date(2026, 10, 10))
    group = _project(world, _window(date(2026, 10, 1), date(2026, 10, 31))).groups[0]
    assert [e.movement_id for e in group.events] == [movement_id, reversal]
    assert group.totals.expected_count == 0
    assert group.closing_balance == _brl("1000")


def test_skip_pause_and_supersede_follow_the_recurrence_contract(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account = world.account()
    _opening(world, account, "1000")
    store = FinancialRecurrenceStore(world.runtime)
    rule = _rule(world, account, day=20, expected="80")
    october, november = _generate(world, rule, date(2026, 10, 1), date(2026, 11, 1))
    store.skip_occurrence(**world.scope(), occurrence_id=october)

    group = _project(world).groups[0]
    assert [(e.kind, e.date) for e in group.events] == [
        (FinancialCashFlowEventKind.EXPECTED_OCCURRENCE, date(2026, 11, 20))
    ]
    assert group.events[0].occurrence_id == november

    store.pause_recurrence(**world.scope(), recurrence_id=rule.id)
    group = _project(world, _window(_TODAY, date(2026, 12, 31))).groups[0]
    # November is still expected; December is not projected and is reported.
    assert [e.date for e in group.events] == [date(2026, 11, 20)]
    assert [i.code for i in group.issues] == [FinancialCashFlowIssueCode.PAUSED_RULES]


def test_audience_is_decided_by_forced_rls(budget_world: BudgetWorld) -> None:
    world = budget_world
    household = world.account(name="Casa")
    personal = world.account(household=False, name="Pessoal do dono")
    shared = world.account(shared=True, name="Compartilhada")
    member_personal = world.account(
        household=False, operator_id=world.member_id, name="Pessoal do membro"
    )
    for account_id in (household, personal, shared):
        _opening(world, account_id, "100")
    _opening(world, member_personal, "100", operator_id=world.member_id)
    _movement(world, personal, "-40", _EXPENSE, date(2026, 10, 12))
    _rule(world, personal, description="Segredo do dono")

    owner = _read(world)
    assert {e.account.id for e in owner.accounts} == {household, personal, shared}

    member = _read(world, operator_id=world.member_id)
    assert {e.account.id for e in member.accounts} == {household, member_personal}
    assert member.movements == ()
    assert member.rules == ()
    with pytest.raises(FinancialCashFlowAccountNotFoundError):
        _read(world, operator_id=world.member_id, account_ids=(personal,))
    with pytest.raises(FinancialCashFlowAccountNotFoundError):
        _read(world, operator_id=world.member_id, account_ids=(shared,))

    world.grant_account(shared, world.member_id)
    granted = _read(world, operator_id=world.member_id, account_ids=(shared,))
    assert [e.account.id for e in granted.accounts] == [shared]

    with pytest.raises(FinancialCashFlowAccessError):
        _read(world, operator_id=world.outsider_id)
    with pytest.raises(FinancialCashFlowAccountNotFoundError):
        _store(world).read_source(
            installation_id=world.installation_id,
            residence_id=world.other_residence_id,
            operator_id=world.outsider_id,
            window=_window(),
            account_ids=(household,),
        )
    with pytest.raises(FinancialCashFlowAccountNotFoundError):
        _read(world, account_ids=(new_financial_resource_id(),))


def test_transfer_to_an_invisible_account_stays_neutral_without_leaking(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    household = world.account(name="Casa")
    personal = world.account(household=False, name="Pessoal do dono")
    _opening(world, household, "1000")
    _opening(world, personal, "0")
    FinancialTransferStore(world.runtime).create_transfer(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialTransferDraft(
            source_account_id=household,
            destination_account_id=personal,
            magnitude=_brl("300"),
            effective_date=date(2026, 10, 12),
            competence_date=date(2026, 10, 12),
            description="Retirada",
        ),
    )

    group = _project(world, operator_id=world.member_id).groups[0]

    assert [a.account.id for a in group.accounts] == [household]
    (event,) = group.events
    assert event.result_effect is FinancialResultEffect.NEUTRAL
    assert event.transfer_id is None  # the transfer itself is not visible
    assert group.totals.neutral_out == _brl("300")
    assert group.totals.realized_expense == _brl("0")
    assert group.closing_balance == _brl("700")


def test_revoked_membership_fails_closed(budget_world: BudgetWorld) -> None:
    world = budget_world
    world.account()
    with world.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE household.memberships SET status = 'disabled', is_primary = false "
                "WHERE operator_id = :operator"
            ),
            {"operator": world.member_id},
        )
    with pytest.raises(FinancialCashFlowAccessError):
        _read(world, operator_id=world.member_id)


def test_archived_accounts_are_explicit_only_and_their_rules_are_reported(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    active = world.account(name="Ativa")
    archived = world.account(name="Arquivada")
    _opening(world, active, "10")
    _opening(world, archived, "10")
    _rule(world, archived)
    world.archive_account(archived)

    assert [e.account.id for e in _read(world).accounts] == [active]
    group = _project(world, account_ids=(archived,)).groups[0]
    assert group.issues[0].code is FinancialCashFlowIssueCode.RULE_ACCOUNT_INACTIVE
    assert group.projection_status is FinancialCashFlowProjectionStatus.INCOMPLETE


def test_currency_filter_and_groups(budget_world: BudgetWorld) -> None:
    world = budget_world
    brl = world.account(name="Real")
    eur = world.account(name="Euro", currency="EUR")
    _opening(world, brl, "10")
    _opening(world, eur, "5", currency="EUR")
    _movement(world, eur, "-1", _EXPENSE, date(2026, 10, 12), currency="EUR")

    assert [g.currency for g in _project(world).groups] == ["BRL", "EUR"]
    only_eur = _read(world, currency="EUR")
    assert [e.account.id for e in only_eur.accounts] == [eur]
    narrowed = _read(world, account_ids=(brl, eur), currency="BRL")
    assert [e.account.id for e in narrowed.accounts] == [brl]
    assert narrowed.movements == ()


def test_missing_opening_balance_is_read_as_absent(budget_world: BudgetWorld) -> None:
    world = budget_world
    account = world.account()
    group = _project(world, account_ids=(account,)).groups[0]
    assert group.accounts[0].has_opening_balance is False
    assert group.projection_status is FinancialCashFlowProjectionStatus.INCOMPLETE


def test_historical_window_skips_the_recurrence_reads(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account = world.account()
    _opening(world, account, "100")
    rule = _rule(world, account, day=5)
    _generate(world, rule, date(2026, 9, 1), date(2026, 9, 1))
    source = _read(
        world, FinancialCashFlowWindow(date(2026, 9, 1), date(2026, 9, 30), _TODAY)
    )
    assert source.pending_occurrences == ()
    assert source.live_occurrence_months == frozenset()


# --- snapshot, limits and cost ------------------------------------------------------


def test_a_concurrent_write_never_splits_the_snapshot(
    budget_world: BudgetWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = budget_world
    account = world.account()
    _opening(world, account, "1000")
    _movement(world, account, "-10", _EXPENSE, date(2026, 10, 5))
    original = store_module._window_movements
    inserted: list[UUID] = []

    def concurrent(*args: Any, **kwargs: Any) -> Any:
        # Committed by another transaction after the aggregates were read.
        inserted.append(_movement(world, account, "-999", _EXPENSE, date(2026, 10, 6)))
        return original(*args, **kwargs)

    monkeypatch.setattr(store_module, "_window_movements", concurrent)
    window = _window(date(2026, 10, 1), date(2026, 10, 31))
    source = _read(world, window)
    projection = project_cash_flow(window=window, source=source, calculated_at=_NOW)

    assert inserted
    assert inserted[0] not in {m.id for m in source.movements}
    assert projection.groups[0].balance_at_reference == _brl("990")
    monkeypatch.undo()
    after = _project(world, window).groups[0]
    assert after.balance_at_reference == _brl("-9")


def test_the_read_runs_in_a_read_only_transaction(
    budget_world: BudgetWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = budget_world
    account = world.account()
    _opening(world, account, "1")
    seen: list[tuple[str, str]] = []
    original = store_module._aggregates

    def probe(connection: Any, *args: Any) -> Any:
        seen.append(
            (
                connection.scalar(text("SHOW transaction_read_only")),
                connection.scalar(text("SHOW transaction_isolation")),
            )
        )
        return original(connection, *args)

    monkeypatch.setattr(store_module, "_aggregates", probe)
    _read(world)
    assert seen == [("on", "repeatable read")]


def test_overflowing_lists_fail_instead_of_truncating(
    budget_world: BudgetWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = budget_world
    account = world.account()
    _opening(world, account, "100")
    for day in (11, 12, 13):
        _movement(world, account, "-1", _EXPENSE, date(2026, 10, day))
    monkeypatch.setattr(store_module, "CASH_FLOW_EVENTS_MAX", 2)
    with pytest.raises(FinancialCashFlowLimitExceededError):
        _read(world)
    monkeypatch.setattr(store_module, "CASH_FLOW_EVENTS_MAX", 2000)
    monkeypatch.setattr(store_module, "CASH_FLOW_ACCOUNTS_MAX", 1)
    world.account(name="Segunda")
    with pytest.raises(FinancialCashFlowLimitExceededError):
        _read(world)


def test_selection_shape_is_validated_before_any_read(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account = world.account()
    with pytest.raises(ValueError):
        _read(world, account_ids=(account, account))
    with pytest.raises(ValueError):
        _read(world, account_ids=())
    with pytest.raises(FinancialCashFlowLimitExceededError):
        _read(world, account_ids=tuple(new_financial_resource_id() for _ in range(51)))


class _Counter:
    def __init__(self, world: BudgetWorld) -> None:
        self._engine = world.runtime
        self.count = 0

    def _on(self, *_: Any) -> None:
        self.count += 1

    def __enter__(self) -> _Counter:
        event.listen(self._engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *_: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._on)


def _statements(world: BudgetWorld) -> int:
    with _Counter(world) as counter:
        _read(world)
    return counter.count


def test_statement_count_is_fixed_whatever_the_volume(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    first = world.account(name="Primeira")
    _opening(world, first, "1000")
    rule = _rule(world, first, day=11)
    _generate(world, rule, date(2026, 10, 1), date(2026, 10, 1))
    movement = _movement(world, first, "-1", _EXPENSE, date(2026, 10, 3))
    small = _statements(world)

    for index in range(6):
        account = world.account(name=f"Conta {index}")
        _opening(world, account, "10")
        for day in range(1, 8):
            _movement(world, account, "-1", _EXPENSE, date(2026, 10, day))
        extra = _rule(world, account, day=11 + index, description=f"Regra {index}")
        _generate(world, extra, date(2026, 10, 1), date(2026, 11, 1))
    _reverse(world, movement, date(2026, 10, 4))
    large = _statements(world)

    assert small == large
    assert large <= 14


def test_large_household_reads_within_a_generous_ceiling(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    accounts = [world.account(name=f"Conta {index}") for index in range(5)]
    for account in accounts:
        _opening(world, account, "100000", on=date(2024, 1, 1))
    with world.engine.begin() as connection:
        # Bulk history straight into the ledger table (privileged, test-only): two
        # years of daily Movements per account, so the aggregates scan real volume.
        connection.execute(
            text(
                """
                INSERT INTO finance.movements (
                    id, installation_id, residence_id, account_id, currency, amount,
                    result_effect, role, effective_date, competence_date,
                    description, created_by_operator_id, idempotency_key,
                    request_digest, created_at)
                SELECT gen_random_uuid(), a.installation_id, a.residence_id, a.id,
                       'BRL', -1, 'EXPENSE', 'STANDARD', d::date, d::date, 'Histórico',
                       a.owner_operator_id, gen_random_uuid(), repeat('0', 64),
                       now()
                  FROM finance.accounts a
                 CROSS JOIN generate_series(date '2024-10-10', date '2026-10-09',
                                            interval '1 day') d
                 WHERE a.id = ANY(:ids)
                """
            ),
            {"ids": accounts},
        )
    for index, account in enumerate(accounts):
        for day in range(10, 28):
            rule = _rule(world, account, day=day, description=f"Regra {index}-{day}")
            if day % 2:
                _generate(world, rule, date(2026, 10, 1), date(2026, 12, 1))

    started = time.perf_counter()
    window = FinancialCashFlowWindow(_TODAY, date(2027, 1, 9), _TODAY)
    projection = project_cash_flow(
        window=window, source=_read(world, window), calculated_at=_NOW
    )
    elapsed = time.perf_counter() - started

    with world.engine.begin() as connection:
        connection.execute(text("ANALYZE finance.movements"))
        plan = chr(10).join(
            connection.scalars(
                text(
                    "EXPLAIN SELECT * FROM finance.movements "
                    "WHERE installation_id = :i AND residence_id = :r "
                    "AND account_id = ANY(:ids) AND effective_date >= :f "
                    "AND effective_date <= :t "
                    "ORDER BY effective_date, created_at, id"
                ),
                {
                    "i": world.installation_id,
                    "r": world.residence_id,
                    "ids": accounts,
                    "f": window.from_date,
                    "t": window.through_date,
                },
            ).all()
        )
    assert "ix_finance_movements_account_effective" in plan, plan
    group = projection.groups[0]
    assert len(group.accounts) == 5
    assert group.balance_at_reference == _brl(str(5 * 100000 - 5 * 730))
    assert group.totals.expected_count == 5 * 18 * 3
    assert elapsed < 5.0


def test_ledger_tables_are_untouched_by_reads(budget_world: BudgetWorld) -> None:
    world = budget_world
    account = world.account()
    _opening(world, account, "50")
    _rule(world, account)
    with world.engine.begin() as connection:
        movements_before = connection.scalar(
            select(func.count()).select_from(financial_movements)
        )
        occurrences_before = connection.scalar(
            select(func.count()).select_from(financial_recurrence_occurrences)
        )
        rules_before = connection.scalar(
            select(func.count()).select_from(financial_recurrences)
        )
    for _ in range(3):
        _project(world, _window(_TODAY, date(2027, 1, 9)))
    with world.engine.begin() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(financial_movements))
            == movements_before
        )
        assert (
            connection.scalar(
                select(func.count()).select_from(financial_recurrence_occurrences)
            )
            == occurrences_before
            == 0
        )
        assert (
            connection.scalar(select(func.count()).select_from(financial_recurrences))
            == rules_before
        )
