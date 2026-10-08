from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest
from meufinanceiro_finance import (
    GOAL_ACCOUNTS_MAX,
    GOAL_ALLOCATE_EVENTS_MAX,
    GOAL_EVENTS_MAX,
    FinancialGoalAllocationDraft,
    FinancialGoalBackingStatus,
    FinancialGoalDraft,
    FinancialGoalEventKind,
    FinancialGoalProgressStatus,
    FinancialGoalReplacement,
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialOpeningBalanceDraft,
    FinancialResultEffect,
    FinancialTransferDraft,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
    summarize_goal,
)
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_goal_schema import (
    financial_goal_allocation_events,
    financial_goals,
)
from meufinanceiro_persistence.financial_goal_store import (
    FinancialGoalAccessError,
    FinancialGoalAccountNotFoundError,
    FinancialGoalAvailabilityError,
    FinancialGoalConflictError,
    FinancialGoalInvalidShapeError,
    FinancialGoalLimitError,
    FinancialGoalNotEditableError,
    FinancialGoalNotFoundError,
    FinancialGoalReleaseError,
    FinancialGoalStore,
    FinancialGoalVersionConflictError,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceStore,
)
from meufinanceiro_persistence.financial_transfer_store import FinancialTransferStore

if TYPE_CHECKING:
    from conftest import BudgetWorld

A = FinancialGoalEventKind.ALLOCATE
R = FinancialGoalEventKind.RELEASE
PERSONAL = FinancialVisibilityScope.PERSONAL
HOUSEHOLD = FinancialVisibilityScope.HOUSEHOLD


def _money(amount: str, currency: str = "BRL") -> Money:
    return Money(Decimal(amount), currency)


def _draft(
    scope: FinancialVisibilityScope = HOUSEHOLD,
    *,
    target: str = "1000",
    currency: str = "BRL",
    title: str = "Reserva",
    target_date: date | None = None,
) -> FinancialGoalDraft:
    return FinancialGoalDraft(
        title=title,
        description=None,
        visibility_scope=scope,
        target=_money(target, currency),
        target_date=target_date,
    )


def _goal(
    world: BudgetWorld,
    scope: FinancialVisibilityScope = HOUSEHOLD,
    operator_id: UUID | None = None,
    **kwargs: Any,
) -> UUID:
    return (
        FinancialGoalStore(world.runtime)
        .create_goal(
            **world.scope(operator_id),
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(scope, **kwargs),
        )
        .id
    )


def _funded(
    world: BudgetWorld,
    amount: str = "1000",
    *,
    household: bool = True,
    currency: str = "BRL",
    operator_id: UUID | None = None,
) -> UUID:
    account = world.account(
        household=household, currency=currency, operator_id=operator_id
    )
    FinancialOpeningBalanceStore(world.runtime).create_opening_balance(
        **world.scope(operator_id),
        account_id=account,
        draft=FinancialOpeningBalanceDraft(
            amount=_money(amount, currency), effective_date=date(2026, 1, 1)
        ),
    )
    return account


def _alloc(
    world: BudgetWorld,
    goal_id: UUID,
    account_id: UUID,
    amount: str,
    kind: FinancialGoalEventKind = A,
    *,
    operator_id: UUID | None = None,
    key: UUID | None = None,
    currency: str = "BRL",
):
    return FinancialGoalStore(world.runtime).allocate(
        **world.scope(operator_id),
        goal_id=goal_id,
        idempotency_key=key or new_financial_idempotency_key(),
        draft=FinancialGoalAllocationDraft(kind, account_id, _money(amount, currency)),
    )


def _facts(world: BudgetWorld, goal_id: UUID, operator_id: UUID | None = None):
    return FinancialGoalStore(world.runtime).read_goal_facts(
        **world.scope(operator_id), goal_id=goal_id
    )


def _summary(world: BudgetWorld, goal_id: UUID, operator_id: UUID | None = None):
    return summarize_goal(*_facts(world, goal_id, operator_id))


def _spend(
    world: BudgetWorld,
    account_id: UUID,
    amount: str,
    *,
    effective: date = date(2026, 10, 10),
):
    return FinancialMovementStore(world.runtime).create_movement(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementDraft(
            account_id=account_id,
            amount=_money(f"-{amount}"),
            result_effect=FinancialResultEffect.EXPENSE,
            effective_date=effective,
            competence_date=effective,
            description="Sintético",
        ),
    )


def _ledger_state(world: BudgetWorld) -> tuple[Any, ...]:
    with world.engine.begin() as connection:
        return (
            connection.scalar(select(func.count()).select_from(financial_movements)),
            connection.scalar(
                select(func.coalesce(func.sum(financial_movements.c.amount), 0))
            ),
            connection.scalar(text("SELECT count(*) FROM finance.audit_events")),
            connection.scalar(text("SELECT count(*) FROM finance.budgets")),
            connection.scalar(
                text("SELECT count(*) FROM finance.recurrence_occurrences")
            ),
        )


# -- goals: create / replay / CAS / audience ---------------------------------


def test_create_read_list_and_replay(budget_world: BudgetWorld) -> None:
    store = FinancialGoalStore(budget_world.runtime)
    key = new_financial_idempotency_key()
    draft = _draft(target="2500.5", target_date=date(2027, 6, 1))

    created = store.create_goal(
        **budget_world.scope(), idempotency_key=key, draft=draft
    )
    replay = store.create_goal(**budget_world.scope(), idempotency_key=key, draft=draft)

    assert created == replay
    assert created.version == 1
    assert created.owner_operator_id == budget_world.owner_id
    assert created.target == _money("2500.5")
    assert created.target_date == date(2027, 6, 1)
    assert store.get_goal(**budget_world.scope(), goal_id=created.id) == created
    assert store.list_goals(**budget_world.scope()) == ((created, _money("0")),)


def test_create_idempotency_conflicts_fail_closed(budget_world: BudgetWorld) -> None:
    store = FinancialGoalStore(budget_world.runtime)
    key = new_financial_idempotency_key()
    store.create_goal(**budget_world.scope(), idempotency_key=key, draft=_draft())

    with pytest.raises(FinancialGoalConflictError):
        store.create_goal(
            **budget_world.scope(), idempotency_key=key, draft=_draft(target="999")
        )
    with pytest.raises(FinancialGoalConflictError):
        store.create_goal(
            **budget_world.scope(budget_world.member_id),
            idempotency_key=key,
            draft=_draft(),
        )
    assert len(store.list_goals(**budget_world.scope())) == 1


def test_a_non_member_cannot_touch_goals(budget_world: BudgetWorld) -> None:
    store = FinancialGoalStore(budget_world.runtime)
    with pytest.raises(FinancialGoalAccessError):
        store.list_goals(
            **budget_world.scope(budget_world.outsider_id, budget_world.residence_id)
        )
    with pytest.raises(FinancialGoalAccessError):
        store.create_goal(
            **budget_world.scope(budget_world.outsider_id, budget_world.residence_id),
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(),
        )


def test_audience_read_and_write_matrix(budget_world: BudgetWorld) -> None:
    store = FinancialGoalStore(budget_world.runtime)
    household = _goal(budget_world, HOUSEHOLD)
    personal = _goal(budget_world, PERSONAL)
    member = budget_world.member_id

    # Members read the household goal; the personal one does not exist for them.
    assert (
        store.get_goal(**budget_world.scope(member), goal_id=household).id == household
    )
    with pytest.raises(FinancialGoalNotFoundError):
        store.get_goal(**budget_world.scope(member), goal_id=personal)
    assert {
        record.id for record, _ in store.list_goals(**budget_world.scope(member))
    } == {household}
    assert {record.id for record, _ in store.list_goals(**budget_world.scope())} == {
        household,
        personal,
    }

    # Reading never implies writing.
    replacement = FinancialGoalReplacement(
        expected_version=1,
        title="Outro",
        description=None,
        target=_money("10"),
        target_date=None,
    )
    with pytest.raises(FinancialGoalNotEditableError):
        store.replace_goal(
            **budget_world.scope(member), goal_id=household, replacement=replacement
        )
    with pytest.raises(FinancialGoalNotFoundError):
        store.replace_goal(
            **budget_world.scope(member), goal_id=personal, replacement=replacement
        )
    # Another residence sees nothing, with the same sanitized error.
    with pytest.raises(FinancialGoalNotFoundError):
        store.get_goal(
            installation_id=budget_world.installation_id,
            residence_id=budget_world.other_residence_id,
            operator_id=budget_world.outsider_id,
            goal_id=household,
        )


def test_cas_edit_preserves_events_and_rejects_stale_versions(
    budget_world: BudgetWorld,
) -> None:
    store = FinancialGoalStore(budget_world.runtime)
    goal = _goal(budget_world)
    account = _funded(budget_world)
    _alloc(budget_world, goal, account, "400")

    updated = store.replace_goal(
        **budget_world.scope(),
        goal_id=goal,
        replacement=FinancialGoalReplacement(
            expected_version=1,
            title="Nova meta",
            description="com descrição",
            target=_money("300"),
            target_date=date(2028, 1, 1),
        ),
    )

    assert updated.version == 2 and updated.title == "Nova meta"
    assert updated.target == _money("300")
    with pytest.raises(FinancialGoalVersionConflictError):
        store.replace_goal(
            **budget_world.scope(),
            goal_id=goal,
            replacement=FinancialGoalReplacement(
                expected_version=1,
                title="Stale",
                description=None,
                target=_money("5"),
                target_date=None,
            ),
        )
    assert store.get_goal(**budget_world.scope(), goal_id=goal).title == "Nova meta"
    # Lowering the target below the allocated value is explicit, never silent.
    summary = _summary(budget_world, goal)
    assert summary.allocated == _money("400")
    assert summary.progress_status is FinancialGoalProgressStatus.EXCEEDED
    assert summary.surplus == _money("100")
    assert len(summary.events) == 1


def test_cas_edit_rejects_currency_change_and_parallel_edits_lose(
    budget_world: BudgetWorld,
) -> None:
    store = FinancialGoalStore(budget_world.runtime)
    goal = _goal(budget_world)
    with pytest.raises(FinancialGoalInvalidShapeError):
        store.replace_goal(
            **budget_world.scope(),
            goal_id=goal,
            replacement=FinancialGoalReplacement(
                expected_version=1,
                title="x",
                description=None,
                target=_money("5", "USD"),
                target_date=None,
            ),
        )

    barrier = threading.Barrier(6)

    def edit(index: int) -> str:
        barrier.wait()
        try:
            store.replace_goal(
                **budget_world.scope(),
                goal_id=goal,
                replacement=FinancialGoalReplacement(
                    expected_version=1,
                    title=f"edit {index}",
                    description=None,
                    target=_money(str(100 + index)),
                    target_date=None,
                ),
            )
            return "won"
        except FinancialGoalVersionConflictError:
            return "lost"

    with ThreadPoolExecutor(6) as pool:
        outcomes = list(pool.map(edit, range(6)))
    assert outcomes.count("won") == 1 and outcomes.count("lost") == 5
    assert store.get_goal(**budget_world.scope(), goal_id=goal).version == 2


def test_cas_loses_a_race_that_happens_between_the_read_and_the_write(
    budget_world: BudgetWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A competing edit commits right after our read: the UPDATE must lose."""
    from meufinanceiro_persistence import financial_goal_store as module

    store = FinancialGoalStore(budget_world.runtime)
    goal = _goal(budget_world)
    real = module._visible_goal
    raced = {"done": False}

    def read_then_lose_the_race(*args: Any, **kwargs: Any):
        row = real(*args, **kwargs)
        if not raced["done"]:
            raced["done"] = True
            store.replace_goal(
                **budget_world.scope(),
                goal_id=goal,
                replacement=FinancialGoalReplacement(
                    expected_version=1,
                    title="Vencedora",
                    description=None,
                    target=_money("20"),
                    target_date=None,
                ),
            )
        return row

    monkeypatch.setattr(module, "_visible_goal", read_then_lose_the_race)
    with pytest.raises(FinancialGoalVersionConflictError):
        store.replace_goal(
            **budget_world.scope(),
            goal_id=goal,
            replacement=FinancialGoalReplacement(
                expected_version=1,
                title="Perdedora",
                description=None,
                target=_money("30"),
                target_date=None,
            ),
        )
    monkeypatch.undo()
    current = store.get_goal(**budget_world.scope(), goal_id=goal)
    assert current.title == "Vencedora" and current.version == 2


def test_owner_goal_limit_is_explicit(budget_world: BudgetWorld) -> None:
    store = FinancialGoalStore(budget_world.runtime)
    for index in range(200):
        store.create_goal(
            **budget_world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(title=f"Meta {index}"),
        )
    with pytest.raises(FinancialGoalLimitError):
        store.create_goal(
            **budget_world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(title="201"),
        )
    # The member has their own allowance; the limit is per owner.
    assert _goal(budget_world, operator_id=budget_world.member_id)
    assert len(store.list_goals(**budget_world.scope())) == 201


# -- allocation: availability, N:N, release -----------------------------------


def test_allocate_release_and_summary(budget_world: BudgetWorld) -> None:
    goal = _goal(budget_world, target="1000")
    account = _funded(budget_world, "1000")
    ledger_before = _ledger_state(budget_world)

    first = _alloc(budget_world, goal, account, "300")
    _alloc(budget_world, goal, account, "100.5")
    release = _alloc(budget_world, goal, account, "50.5", R)

    assert first.kind is A and first.amount == _money("300")
    assert release.kind is R and release.amount == _money("50.5")
    summary = _summary(budget_world, goal)
    assert summary.allocated == _money("350")
    assert summary.remaining_target == _money("650")
    assert summary.progress_percent == Decimal("35.00")
    assert summary.progress_status is FinancialGoalProgressStatus.IN_PROGRESS
    (row,) = summary.accounts
    assert row.allocated == _money("350")
    assert row.account_balance == _money("1000")
    assert row.account_allocated_total == _money("350")
    assert row.backing_status is FinancialGoalBackingStatus.COVERED
    assert [event.kind for event in summary.events] == [A, A, R]
    # Virtual only: not a single ledger/audit/budget/occurrence row was created.
    assert _ledger_state(budget_world) == ledger_before
    store = FinancialGoalStore(budget_world.runtime)
    ((record, allocated),) = store.list_goals(**budget_world.scope())
    assert record.id == goal and allocated == _money("350")


def test_allocation_cannot_exceed_the_balance(budget_world: BudgetWorld) -> None:
    goal = _goal(budget_world)
    account = _funded(budget_world, "100")

    with pytest.raises(FinancialGoalAvailabilityError):
        _alloc(budget_world, goal, account, "100.00000001")
    _alloc(budget_world, goal, account, "100")
    with pytest.raises(FinancialGoalAvailabilityError):
        _alloc(budget_world, goal, account, "0.00000001")
    assert _summary(budget_world, goal).allocated == _money("100")


def test_an_account_without_opening_balance_has_a_zero_balance(
    budget_world: BudgetWorld,
) -> None:
    goal = _goal(budget_world)
    account = budget_world.account()
    with pytest.raises(FinancialGoalAvailabilityError):
        _alloc(budget_world, goal, account, "1")


def test_one_account_sustains_many_goals_without_double_allocation(
    budget_world: BudgetWorld,
) -> None:
    first, second = _goal(budget_world), _goal(budget_world, title="Viagem")
    account = _funded(budget_world, "1000")

    _alloc(budget_world, first, account, "700")
    _alloc(budget_world, second, account, "300")
    with pytest.raises(FinancialGoalAvailabilityError):
        _alloc(budget_world, second, account, "0.01")
    # Releasing from one goal frees availability for the other.
    _alloc(budget_world, first, account, "200", R)
    _alloc(budget_world, second, account, "200")

    one, two = _summary(budget_world, first), _summary(budget_world, second)
    assert one.allocated == _money("500") and two.allocated == _money("500")
    assert one.accounts[0].account_allocated_total == _money("1000")
    assert two.accounts[0].account_allocated_total == _money("1000")
    assert one.accounts[0].backing_status is FinancialGoalBackingStatus.COVERED


def test_one_goal_uses_several_accounts(budget_world: BudgetWorld) -> None:
    goal = _goal(budget_world, target="1000")
    first = _funded(budget_world, "400")
    second = _funded(budget_world, "700")

    _alloc(budget_world, goal, first, "400")
    _alloc(budget_world, goal, second, "600")

    summary = _summary(budget_world, goal)
    assert summary.allocated == _money("1000")
    assert summary.progress_status is FinancialGoalProgressStatus.REACHED
    assert len(summary.accounts) == 2
    assert {row.allocated for row in summary.accounts} == {_money("400"), _money("600")}


def test_release_never_goes_negative_and_is_per_goal_and_account(
    budget_world: BudgetWorld,
) -> None:
    mine, other = _goal(budget_world), _goal(budget_world, title="Outra")
    first = _funded(budget_world, "1000")
    second = _funded(budget_world, "1000")
    _alloc(budget_world, mine, first, "100")
    _alloc(budget_world, other, first, "300")

    with pytest.raises(FinancialGoalReleaseError):
        _alloc(budget_world, mine, first, "100.01", R)  # more than the goal holds
    with pytest.raises(FinancialGoalReleaseError):
        _alloc(budget_world, mine, second, "1", R)  # nothing held on that account
    _alloc(budget_world, mine, first, "100", R)
    with pytest.raises(FinancialGoalReleaseError):
        _alloc(budget_world, mine, first, "0.00000001", R)
    assert _summary(budget_world, other).allocated == _money("300")


# -- eligibility ----------------------------------------------------------------


def test_account_eligibility_is_enforced_for_both_audiences(
    budget_world: BudgetWorld,
) -> None:
    household_goal = _goal(budget_world, HOUSEHOLD)
    personal_goal = _goal(budget_world, PERSONAL)
    household_account = _funded(budget_world, "100", household=True)
    personal_account = _funded(budget_world, "100", household=False)
    shared_account = budget_world.account(shared=True)
    members_household_account = _funded(
        budget_world, "100", household=True, operator_id=budget_world.member_id
    )

    _alloc(budget_world, household_goal, household_account, "10")
    _alloc(budget_world, personal_goal, personal_account, "10")
    for goal, account in (
        (household_goal, personal_account),
        (personal_goal, household_account),
        (household_goal, shared_account),
        (personal_goal, shared_account),
        # same audience but another owner's account
        (household_goal, members_household_account),
    ):
        with pytest.raises(FinancialGoalAccountNotFoundError):
            _alloc(budget_world, goal, account, "1")


def test_currency_and_forged_ids_are_rejected(budget_world: BudgetWorld) -> None:
    goal = _goal(budget_world, currency="BRL")
    usd_account = _funded(budget_world, "100", currency="USD")
    brl_account = _funded(budget_world, "100")

    with pytest.raises(FinancialGoalAccountNotFoundError):
        _alloc(budget_world, goal, usd_account, "1")
    with pytest.raises(FinancialGoalInvalidShapeError):
        _alloc(budget_world, goal, brl_account, "1", currency="USD")
    forged = UUID("11111111-1111-4111-8111-111111111111")
    with pytest.raises(FinancialGoalAccountNotFoundError):
        _alloc(budget_world, goal, forged, "1")
    with pytest.raises(FinancialGoalNotFoundError):
        _alloc(budget_world, forged, brl_account, "1")


def test_only_the_owner_allocates_and_outsiders_see_nothing(
    budget_world: BudgetWorld,
) -> None:
    goal = _goal(budget_world, HOUSEHOLD)
    account = _funded(budget_world, "100")
    member = budget_world.member_id

    with pytest.raises(FinancialGoalNotEditableError):
        _alloc(budget_world, goal, account, "1", operator_id=member)
    with pytest.raises(FinancialGoalNotFoundError):
        FinancialGoalStore(budget_world.runtime).allocate(
            installation_id=budget_world.installation_id,
            residence_id=budget_world.other_residence_id,
            operator_id=budget_world.outsider_id,
            goal_id=goal,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialGoalAllocationDraft(A, account, _money("1")),
        )
    # A member reads the household summary, including account facts.
    _alloc(budget_world, goal, account, "40")
    summary = _summary(budget_world, goal, member)
    assert summary.allocated == _money("40")
    assert summary.accounts[0].account_balance == _money("100")


def test_archived_accounts_accept_releases_only(budget_world: BudgetWorld) -> None:
    goal = _goal(budget_world)
    account = _funded(budget_world, "500")
    _alloc(budget_world, goal, account, "200")

    budget_world.archive_account(account)

    with pytest.raises(FinancialGoalAccountNotFoundError):
        _alloc(budget_world, goal, account, "1")
    _alloc(budget_world, goal, account, "150", R)
    summary = _summary(budget_world, goal)
    assert summary.allocated == _money("50")
    assert summary.accounts[0].account_status.value == "ARCHIVED"


# -- idempotency ----------------------------------------------------------------


def test_event_idempotency_replay_and_conflict(budget_world: BudgetWorld) -> None:
    goal, other = _goal(budget_world), _goal(budget_world, title="Outra")
    account = _funded(budget_world, "1000")
    key = new_financial_idempotency_key()

    first = _alloc(budget_world, goal, account, "100", key=key)
    again = _alloc(budget_world, goal, account, "100", key=key)

    assert again == first
    assert _summary(budget_world, goal).allocated == _money("100")
    for conflicting in (
        lambda: _alloc(budget_world, goal, account, "101", key=key),
        lambda: _alloc(budget_world, goal, account, "100", R, key=key),
        lambda: _alloc(budget_world, other, account, "100", key=key),
        lambda: _alloc(
            budget_world,
            goal,
            account,
            "100",
            key=key,
            operator_id=budget_world.member_id,
        ),
    ):
        with pytest.raises((FinancialGoalConflictError, FinancialGoalNotEditableError)):
            conflicting()
    assert len(_summary(budget_world, goal).events) == 1


def test_concurrent_replays_of_one_key_append_one_event(
    budget_world: BudgetWorld,
) -> None:
    goal = _goal(budget_world)
    account = _funded(budget_world, "1000")
    key = new_financial_idempotency_key()
    barrier = threading.Barrier(6)

    def attempt(_: int) -> UUID:
        barrier.wait()
        return _alloc(budget_world, goal, account, "100", key=key).id

    with ThreadPoolExecutor(6) as pool:
        ids = set(pool.map(attempt, range(6)))
    assert len(ids) == 1
    assert _summary(budget_world, goal).allocated == _money("100")


# -- concurrency ------------------------------------------------------------------


def test_concurrent_allocations_never_consume_the_same_availability(
    budget_world: BudgetWorld,
) -> None:
    goals = [_goal(budget_world, title=f"Meta {index}") for index in range(8)]
    account = _funded(budget_world, "100")
    barrier = threading.Barrier(len(goals))

    def attempt(goal: UUID) -> str:
        barrier.wait()
        try:
            _alloc(budget_world, goal, account, "30")
            return "ok"
        except FinancialGoalAvailabilityError:
            return "full"

    with ThreadPoolExecutor(len(goals)) as pool:
        outcomes = list(pool.map(attempt, goals))

    assert outcomes.count("ok") == 3
    assert outcomes.count("full") == 5
    totals = [_summary(budget_world, goal).allocated.amount for goal in goals]
    assert sum(totals) == Decimal(90)
    assert all(
        _summary(budget_world, goal).accounts[0].backing_status
        is FinancialGoalBackingStatus.COVERED
        for goal in goals
        if _summary(budget_world, goal).accounts
    )


def test_concurrent_allocations_of_one_goal_stay_exact(
    budget_world: BudgetWorld,
) -> None:
    goal = _goal(budget_world, target="100000")
    account = _funded(budget_world, "100")
    barrier = threading.Barrier(10)

    def attempt(_: int) -> str:
        barrier.wait()
        try:
            _alloc(budget_world, goal, account, "15")
            return "ok"
        except FinancialGoalAvailabilityError:
            return "full"

    with ThreadPoolExecutor(10) as pool:
        outcomes = list(pool.map(attempt, range(10)))
    assert outcomes.count("ok") == 6
    assert _summary(budget_world, goal).allocated == _money("90")


def test_concurrent_releases_never_go_negative(budget_world: BudgetWorld) -> None:
    goal = _goal(budget_world)
    account = _funded(budget_world, "100")
    _alloc(budget_world, goal, account, "50")
    barrier = threading.Barrier(8)

    def attempt(_: int) -> str:
        barrier.wait()
        try:
            _alloc(budget_world, goal, account, "20", R)
            return "ok"
        except FinancialGoalReleaseError:
            return "empty"

    with ThreadPoolExecutor(8) as pool:
        outcomes = list(pool.map(attempt, range(8)))
    assert outcomes.count("ok") == 2
    assert _summary(budget_world, goal).allocated == _money("10")


def test_an_in_flight_allocation_never_blocks_the_ledger(
    budget_world: BudgetWorld,
) -> None:
    goal = _goal(budget_world)
    account = _funded(budget_world, "100")
    _alloc(budget_world, goal, account, "10")
    key = "meufinanceiro:goal-account:" + str(account)

    # Hold the very lock allocations take; Movements must not wait for it.
    with budget_world.engine.begin() as holder:
        holder.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
        )
        movement = _spend(budget_world, account, "5")
        assert movement.id is not None


# -- balance that falls later -------------------------------------------------------


def test_a_later_expense_flags_insufficient_backing_without_touching_events(
    budget_world: BudgetWorld,
) -> None:
    goal, other = _goal(budget_world), _goal(budget_world, title="Outra")
    account = _funded(budget_world, "1000")
    _alloc(budget_world, goal, account, "400")
    _alloc(budget_world, other, account, "400")
    events_before = _summary(budget_world, goal).events

    _spend(budget_world, account, "500")  # the balance (500) is now below 800

    summary = _summary(budget_world, goal)
    assert summary.events == events_before
    assert summary.allocated == _money("400")
    (row,) = summary.accounts
    assert row.account_balance == _money("500")
    assert row.account_allocated_total == _money("800")
    assert row.backing_status is FinancialGoalBackingStatus.INSUFFICIENT
    assert row.shortfall == _money("300")
    assert summary.has_insufficient_backing is True
    assert _summary(budget_world, other).has_insufficient_backing is True
    # No new allocation while insufficient, but a release is always possible.
    with pytest.raises(FinancialGoalAvailabilityError):
        _alloc(budget_world, goal, account, "0.00000001")
    _alloc(budget_world, goal, account, "400", R)
    assert _summary(budget_world, other).has_insufficient_backing is False


def test_reversal_and_transfer_follow_the_canonical_balance(
    budget_world: BudgetWorld,
) -> None:
    goal = _goal(budget_world)
    source = _funded(budget_world, "1000")
    target = _funded(budget_world, "0")
    movements = FinancialMovementStore(budget_world.runtime)

    spent = _spend(budget_world, source, "300")
    with pytest.raises(FinancialGoalAvailabilityError):
        _alloc(budget_world, goal, source, "700.00000001")
    # Reversing the expense gives the money back.
    movements.reverse_movement(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=spent.id,
            effective_date=date(2026, 10, 20),
            competence_date=date(2026, 10, 20),
            reason="Sintético",
        ),
    )
    _alloc(budget_world, goal, source, "1000")

    # A transfer is cash leaving the account: the leg is a Movement of the account.
    _alloc(budget_world, goal, source, "1000", R)
    FinancialTransferStore(budget_world.runtime).create_transfer(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialTransferDraft(
            source_account_id=source,
            destination_account_id=target,
            magnitude=_money("400"),
            effective_date=date(2026, 10, 25),
            competence_date=date(2026, 10, 25),
            description="Sintético",
        ),
    )
    with pytest.raises(FinancialGoalAvailabilityError):
        _alloc(budget_world, goal, source, "600.00000001")
    _alloc(budget_world, goal, source, "600")
    _alloc(budget_world, goal, target, "400")


def test_month_rollover_and_reads_never_create_events(
    budget_world: BudgetWorld,
) -> None:
    goal = _goal(budget_world)
    account = _funded(budget_world, "100")
    _alloc(budget_world, goal, account, "10")
    with budget_world.engine.begin() as connection:
        before = connection.scalar(
            select(func.count()).select_from(financial_goal_allocation_events)
        )

    for _ in range(3):
        _summary(budget_world, goal)
        FinancialGoalStore(budget_world.runtime).list_goals(**budget_world.scope())

    with budget_world.engine.begin() as connection:
        after = connection.scalar(
            select(func.count()).select_from(financial_goal_allocation_events)
        )
    assert before == after == 1


# -- database guarantees ------------------------------------------------------------


def test_events_are_append_only_and_unreachable_for_the_runtime(
    budget_world: BudgetWorld,
) -> None:
    goal = _goal(budget_world)
    account = _funded(budget_world, "100")
    _alloc(budget_world, goal, account, "10")
    events = financial_goal_allocation_events

    with budget_world.runtime.begin() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(update(events).values(kind="RELEASE"))
    with budget_world.runtime.begin() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(events.delete())
    # Even the table owner cannot rewrite history.
    with pytest.raises(DBAPIError):
        with budget_world.engine.begin() as connection:
            connection.execute(update(events).values(amount=Decimal("99")))
    with budget_world.engine.begin() as connection:
        assert connection.scalar(select(events.c.amount)) == Decimal("10")


def test_the_database_rejects_what_the_store_would_never_write(
    budget_world: BudgetWorld,
) -> None:
    goal = _goal(budget_world, PERSONAL)
    personal = _funded(budget_world, "100", household=False)
    household = _funded(budget_world, "100", household=True)
    _alloc(budget_world, goal, personal, "10")
    events = financial_goal_allocation_events

    def raw_insert(account_id: UUID, kind: str, amount: str, key: UUID) -> None:
        with budget_world.runtime.begin() as connection:
            connection.execute(
                text(
                    "SELECT set_config('app.current_installation_id', :i, true), "
                    "set_config('app.current_residence_id', :r, true), "
                    "set_config('app.current_operator_id', :o, true)"
                ),
                {
                    "i": str(budget_world.installation_id),
                    "r": str(budget_world.residence_id),
                    "o": str(budget_world.owner_id),
                },
            )
            connection.execute(
                events.insert().values(
                    id=UUID("22222222-2222-4222-8222-222222222222"),
                    installation_id=budget_world.installation_id,
                    residence_id=budget_world.residence_id,
                    goal_id=goal,
                    account_id=account_id,
                    currency="BRL",
                    kind=kind,
                    amount=Decimal(amount),
                    actor_operator_id=budget_world.owner_id,
                    idempotency_key=key,
                    request_digest="0" * 64,
                    created_at=func.transaction_timestamp(),
                )
            )

    # Wrong audience, negative virtual balance, wrong sign: all refused by the DB,
    # even from a path that skipped the store's own checks.
    with pytest.raises(DBAPIError):
        raw_insert(household, "ALLOCATE", "1", new_financial_idempotency_key())
    with pytest.raises(DBAPIError):
        raw_insert(personal, "RELEASE", "-10.00000001", new_financial_idempotency_key())
    with pytest.raises(DBAPIError):
        raw_insert(personal, "ALLOCATE", "-1", new_financial_idempotency_key())
    with pytest.raises(DBAPIError):
        raw_insert(personal, "ALLOCATE", "0", new_financial_idempotency_key())
    raw_insert(personal, "RELEASE", "-10", new_financial_idempotency_key())


def test_goals_expose_no_money_authority_and_the_ledger_has_no_goal_pointer(
    budget_world: BudgetWorld,
) -> None:
    with budget_world.engine.begin() as connection:
        goal_columns = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'finance' AND table_name = 'goals'"
                )
            )
        }
        movement_columns = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'finance' AND table_name = 'movements'"
                )
            )
        }
    assert not {"allocated", "remaining", "balance", "saved_amount"} & goal_columns
    assert not {"goal_id", "project_id"} & movement_columns
    assert financial_goals.c.target_amount is not None


# -- explicit bounds -------------------------------------------------------------------


def test_event_history_is_bounded_and_releases_keep_their_reserve(
    budget_world: BudgetWorld,
) -> None:
    goal = _goal(budget_world, target="1000000")
    account = _funded(budget_world, "1000000")
    store = FinancialGoalStore(budget_world.runtime)

    for _ in range(GOAL_ALLOCATE_EVENTS_MAX):
        _alloc(budget_world, goal, account, "1")
    with pytest.raises(FinancialGoalLimitError):
        _alloc(budget_world, goal, account, "1")
    # The reserve lets the owner give every account back even at the allocation cap.
    for _ in range(GOAL_EVENTS_MAX - GOAL_ALLOCATE_EVENTS_MAX):
        _alloc(budget_world, goal, account, "1", R)
    with pytest.raises(FinancialGoalLimitError):
        _alloc(budget_world, goal, account, "1", R)

    # The full history is readable up to the bound and never truncated.
    _, events, _ = store.read_goal_facts(**budget_world.scope(), goal_id=goal)
    assert len(events) == GOAL_EVENTS_MAX


def test_a_goal_uses_at_most_the_account_bound(budget_world: BudgetWorld) -> None:
    goal = _goal(budget_world, target="1000000")
    accounts = [_funded(budget_world, "10") for _ in range(GOAL_ACCOUNTS_MAX + 1)]
    for account in accounts[:GOAL_ACCOUNTS_MAX]:
        _alloc(budget_world, goal, account, "1")
    with pytest.raises(FinancialGoalLimitError):
        _alloc(budget_world, goal, accounts[GOAL_ACCOUNTS_MAX], "1")
    # An account already used still accepts events.
    _alloc(budget_world, goal, accounts[0], "1")
    assert len(_summary(budget_world, goal).accounts) == GOAL_ACCOUNTS_MAX


# -- read cost -----------------------------------------------------------------------------


def test_reads_have_a_bounded_number_of_statements(budget_world: BudgetWorld) -> None:
    goal = _goal(budget_world, target="100000")
    account = _funded(budget_world, "100000")
    _alloc(budget_world, goal, account, "1")

    def cost(call: Any) -> int:
        statements: list[str] = []

        def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
            statements.append(statement)

        event.listen(budget_world.runtime, "before_cursor_execute", record)
        try:
            call()
        finally:
            event.remove(budget_world.runtime, "before_cursor_execute", record)
        return len(statements)

    summary_cost = cost(lambda: _facts(budget_world, goal))
    list_cost = cost(
        lambda: FinancialGoalStore(budget_world.runtime).list_goals(
            **budget_world.scope()
        )
    )
    for _ in range(40):
        _alloc(budget_world, goal, account, "1")
        _spend(budget_world, account, "1")
    for _ in range(5):
        _goal(budget_world, title="Extra")

    # More events, Movements and goals never change the statement count.
    assert cost(lambda: _facts(budget_world, goal)) == summary_cost
    assert (
        cost(
            lambda: FinancialGoalStore(budget_world.runtime).list_goals(
                **budget_world.scope()
            )
        )
        == list_cost
    )
    assert list_cost <= 5
    assert summary_cost <= 12
