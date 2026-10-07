"""PostgreSQL-backed proofs for generation, skip and pause/resume of recurrences.

Everything runs through the non-superuser runtime role with forced RLS. Planning
never writes a Movement: every proof here also checks the ledger stays empty.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest
from meufinanceiro_finance import (
    FinancialOccurrenceStatus,
    FinancialRecurrenceDraft,
    FinancialRecurrenceOccurrenceRecord,
    FinancialRecurrenceRecord,
    FinancialRecurrenceReplacement,
    FinancialRecurrenceStatus,
    FinancialRecurrenceWindow,
    FinancialResultEffect,
    Money,
    new_financial_idempotency_key,
    validate_financial_resource_id,
)
from sqlalchemy import func, select

from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_recurrence_schema import (
    financial_recurrence_occurrences,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceAccountNotFoundError,
    FinancialRecurrenceInvalidShapeError,
    FinancialRecurrenceNotEditableError,
    FinancialRecurrenceNotFoundError,
    FinancialRecurrenceOccurrenceNotFoundError,
    FinancialRecurrenceOccurrenceStateError,
    FinancialRecurrencePausedError,
    FinancialRecurrenceStore,
)

if TYPE_CHECKING:
    from conftest import BudgetWorld

_TODAY = date(2026, 10, 6)
_OCT = date(2026, 10, 1)
_NOV = date(2026, 11, 1)
_DEC = date(2026, 12, 1)


def _window(first: date, last: date | None = None) -> FinancialRecurrenceWindow:
    return FinancialRecurrenceWindow(first, last or first)


def _store(world: BudgetWorld) -> FinancialRecurrenceStore:
    return FinancialRecurrenceStore(world.runtime)


def _rule(
    world: BudgetWorld, account_id: UUID | None = None, **overrides: Any
) -> FinancialRecurrenceRecord:
    values: dict[str, Any] = {
        "account_id": account_id or world.account(),
        "description": "Internet",
        "result_effect": FinancialResultEffect.EXPENSE,
        "expected": Money(Decimal("120"), "BRL"),
        "start_date": date(2026, 1, 10),
        "day_of_month": 10,
        "end_date": None,
    }
    values.update(overrides)
    return _store(world).create_recurrence(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialRecurrenceDraft(**values),
    )


def _generate(
    world: BudgetWorld,
    rule: FinancialRecurrenceRecord,
    first: date,
    last: date | None = None,
    operator_id: UUID | None = None,
) -> Any:
    return _store(world).generate_occurrences(
        **world.scope(operator_id),
        recurrence_id=rule.id,
        window=_window(first, last),
    )


def _count(world: BudgetWorld, table: Any) -> int:
    with world.engine.begin() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    assert isinstance(value, int)
    return value


def _get_rule(world: BudgetWorld, rule: FinancialRecurrenceRecord) -> Any:
    return _store(world).get_recurrence(**world.scope(), recurrence_id=rule.id)


# --- generation ---------------------------------------------------------------


def test_generate_creates_a_pending_occurrence_with_the_rule_snapshot(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)

    result = _generate(budget_world, rule, _OCT)

    assert result.created_count == 1 and len(result.occurrences) == 1
    occurrence = result.occurrences[0]
    validate_financial_resource_id(occurrence.id)  # UUID v4
    assert occurrence.status is FinancialOccurrenceStatus.PENDING
    assert occurrence.period_start == _OCT
    assert occurrence.scheduled_date == date(2026, 10, 10)
    assert occurrence.rule_version == 1
    assert occurrence.expected == Money(Decimal("120"), "BRL")
    assert occurrence.description == "Internet"
    assert occurrence.result_effect is FinancialResultEffect.EXPENSE
    assert (
        occurrence.recurrence_id == rule.id and occurrence.account_id == rule.account_id
    )
    assert occurrence.realization is None
    # A forecast is not a fact.
    assert _count(budget_world, financial_movements) == 0


def test_generation_is_idempotent_and_replay_safe(budget_world: BudgetWorld) -> None:
    rule = _rule(budget_world)
    first = _generate(budget_world, rule, _OCT, _DEC)
    again = _generate(budget_world, rule, _OCT, _DEC)
    overlapping = _generate(budget_world, rule, _NOV, date(2027, 1, 1))

    assert first.created_count == 3 and again.created_count == 0
    assert [o.id for o in again.occurrences] == [o.id for o in first.occurrences]
    assert overlapping.created_count == 1  # only January is new
    assert _count(budget_world, financial_recurrence_occurrences) == 4
    assert _count(budget_world, financial_movements) == 0


def test_concurrent_generation_converges_without_duplicates(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    barrier = Barrier(6)

    def attempt() -> tuple[int, tuple[UUID, ...]]:
        barrier.wait()
        result = _generate(budget_world, rule, _OCT, date(2027, 3, 1))
        return result.created_count, tuple(o.id for o in result.occurrences)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = [f.result() for f in [pool.submit(attempt) for _ in range(6)]]

    assert sum(created for created, _ in results) == 6  # six months, once each
    assert len({ids for _, ids in results}) == 1  # everyone sees the same set
    assert _count(budget_world, financial_recurrence_occurrences) == 6


def test_generation_honours_start_and_end_boundaries(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(
        budget_world,
        start_date=date(2026, 10, 15),
        day_of_month=10,
        end_date=date(2026, 12, 10),
    )
    result = _generate(budget_world, rule, date(2026, 9, 1), date(2027, 2, 1))
    assert [o.scheduled_date for o in result.occurrences] == [
        date(2026, 11, 10),  # October 10 precedes the October 15 start
        date(2026, 12, 10),  # the end date is inclusive
    ]


def test_generation_clamps_the_day_to_the_month_length(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world, start_date=date(2027, 1, 31), day_of_month=31)
    result = _generate(budget_world, rule, date(2027, 1, 1), date(2027, 4, 1))
    assert [o.scheduled_date for o in result.occurrences] == [
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
        date(2027, 4, 30),
    ]
    leap = _rule(budget_world, start_date=date(2028, 1, 1), day_of_month=30)
    assert [
        o.scheduled_date
        for o in _generate(
            budget_world, leap, date(2028, 2, 1), date(2028, 2, 1)
        ).occurrences
    ] == [date(2028, 2, 29)]


def test_a_window_beyond_twelve_months_is_refused_without_writing(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    with pytest.raises(FinancialRecurrenceInvalidShapeError):
        _generate(budget_world, rule, date(2026, 1, 1), date(2027, 1, 1))
    assert _count(budget_world, financial_recurrence_occurrences) == 0


def test_a_paused_rule_never_generates(budget_world: BudgetWorld) -> None:
    rule = _rule(budget_world)
    _generate(budget_world, rule, _OCT)
    _store(budget_world).pause_recurrence(**budget_world.scope(), recurrence_id=rule.id)

    with pytest.raises(FinancialRecurrencePausedError):
        _generate(budget_world, rule, _NOV)

    assert _count(budget_world, financial_recurrence_occurrences) == 1


def test_resume_allows_generation_again_and_generates_nothing_itself(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    _store(budget_world).pause_recurrence(**budget_world.scope(), recurrence_id=rule.id)
    resumed = _store(budget_world).resume_recurrence(
        **budget_world.scope(), recurrence_id=rule.id
    )
    assert resumed.status is FinancialRecurrenceStatus.ACTIVE
    assert _count(budget_world, financial_recurrence_occurrences) == 0

    assert _generate(budget_world, rule, _DEC).created_count == 1


def test_generation_after_an_edit_snapshots_the_new_revision(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    _generate(budget_world, rule, _OCT)
    edited = (
        _store(budget_world)
        .replace_recurrence(
            **budget_world.scope(),
            recurrence_id=rule.id,
            replacement=FinancialRecurrenceReplacement(
                expected_version=1,
                description="Internet fibra",
                expected_amount=Decimal("150"),
                day_of_month=12,
                end_date=None,
            ),
            today=_TODAY,
        )
        .recurrence
    )
    assert edited.version == 2

    result = _generate(budget_world, rule, _OCT, _NOV)

    october, november = result.occurrences
    # October 10 is still ahead of today but now disagrees with the revision:
    # it was superseded and the live one is the new snapshot.
    assert october.rule_version == 2 and november.rule_version == 2
    assert october.scheduled_date == date(2026, 10, 12)
    assert november.expected.amount == Decimal("150")
    history = _store(budget_world).list_occurrences(
        **budget_world.scope(),
        window=_window(_OCT),
        status=FinancialOccurrenceStatus.SUPERSEDED,
    )
    assert [(o.rule_version, o.expected.amount) for o in history] == [
        (1, Decimal("120"))
    ]
    live = _store(budget_world).list_occurrences(
        **budget_world.scope(), window=_window(_OCT)
    )
    assert [o.id for o in live] == [october.id]  # SUPERSEDED hidden by default
    assert _count(budget_world, financial_movements) == 0


def test_generation_on_an_archived_account_fails_closed(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _rule(budget_world, account)
    budget_world.archive_account(account)
    with pytest.raises(FinancialRecurrenceAccountNotFoundError):
        _generate(budget_world, rule, _OCT)
    assert _count(budget_world, financial_recurrence_occurrences) == 0


def test_only_the_owner_generates_and_foreign_rules_are_invisible(
    budget_world: BudgetWorld,
) -> None:
    household = _rule(budget_world)  # HOUSEHOLD account: members can read
    personal = _rule(budget_world, budget_world.account(household=False))
    member = budget_world.member_id

    with pytest.raises(FinancialRecurrenceNotEditableError):
        _generate(budget_world, household, _OCT, operator_id=member)
    with pytest.raises(FinancialRecurrenceNotFoundError):
        _generate(budget_world, personal, _OCT, operator_id=member)
    assert _count(budget_world, financial_recurrence_occurrences) == 0


# --- reads --------------------------------------------------------------------


def test_list_is_windowed_filtered_and_audience_aware(
    budget_world: BudgetWorld,
) -> None:
    household = _rule(budget_world, description="Aluguel")
    personal = _rule(
        budget_world, budget_world.account(household=False), description="Academia"
    )
    _generate(budget_world, household, _OCT, _NOV)
    _generate(budget_world, personal, _OCT, _NOV)
    owner = budget_world.scope()
    member = budget_world.scope(budget_world.member_id)

    owner_view = _store(budget_world).list_occurrences(
        **owner, window=_window(_OCT, _NOV)
    )
    assert len(owner_view) == 4
    assert sorted((o.period_start, o.description) for o in owner_view) == [
        (_OCT, "Academia"),
        (_OCT, "Aluguel"),
        (_NOV, "Academia"),
        (_NOV, "Aluguel"),
    ]
    one_month = _store(budget_world).list_occurrences(**owner, window=_window(_NOV))
    assert {o.period_start for o in one_month} == {_NOV}
    only_rent = _store(budget_world).list_occurrences(
        **owner, window=_window(_OCT, _NOV), recurrence_id=household.id
    )
    assert {o.recurrence_id for o in only_rent} == {household.id}

    member_view = _store(budget_world).list_occurrences(
        **member, window=_window(_OCT, _NOV)
    )
    assert {o.recurrence_id for o in member_view} == {household.id}  # personal hidden
    with pytest.raises(FinancialRecurrenceNotFoundError):
        _store(budget_world).list_occurrences(
            **member, window=_window(_OCT), recurrence_id=personal.id
        )


def test_get_occurrence_follows_the_account_audience(
    budget_world: BudgetWorld,
) -> None:
    household = _rule(budget_world)
    personal = _rule(budget_world, budget_world.account(household=False))
    house_occurrence = _generate(budget_world, household, _OCT).occurrences[0]
    own_occurrence = _generate(budget_world, personal, _OCT).occurrences[0]
    member = budget_world.scope(budget_world.member_id)

    assert (
        _store(budget_world)
        .get_occurrence(**member, occurrence_id=house_occurrence.id)
        .id
        == house_occurrence.id
    )
    with pytest.raises(FinancialRecurrenceOccurrenceNotFoundError):
        _store(budget_world).get_occurrence(**member, occurrence_id=own_occurrence.id)
    with pytest.raises(FinancialRecurrenceOccurrenceNotFoundError):
        _store(budget_world).get_occurrence(
            **budget_world.scope(
                budget_world.outsider_id, residence_id=budget_world.other_residence_id
            ),
            occurrence_id=house_occurrence.id,
        )


def test_read_window_is_bounded(budget_world: BudgetWorld) -> None:
    with pytest.raises(FinancialRecurrenceInvalidShapeError):
        _store(budget_world).list_occurrences(
            **budget_world.scope(), window=_window(date(2026, 1, 1), date(2027, 1, 1))
        )


# --- skip ---------------------------------------------------------------------


def _only(result: Any) -> FinancialRecurrenceOccurrenceRecord:
    assert len(result.occurrences) == 1
    return result.occurrences[0]


def test_skip_marks_pending_as_skipped_without_any_movement(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _only(_generate(budget_world, rule, _DEC))

    skipped = _store(budget_world).skip_occurrence(
        **budget_world.scope(), occurrence_id=occurrence.id
    )

    assert skipped.status is FinancialOccurrenceStatus.SKIPPED
    assert skipped.realization is None
    assert _count(budget_world, financial_movements) == 0


def test_skip_is_idempotent(budget_world: BudgetWorld) -> None:
    rule = _rule(budget_world)
    occurrence = _only(_generate(budget_world, rule, _DEC))
    first = _store(budget_world).skip_occurrence(
        **budget_world.scope(), occurrence_id=occurrence.id
    )
    again = _store(budget_world).skip_occurrence(
        **budget_world.scope(), occurrence_id=occurrence.id
    )
    assert again == first  # same updated_at: nothing was rewritten


def test_concurrent_skips_converge(budget_world: BudgetWorld) -> None:
    rule = _rule(budget_world)
    occurrence = _only(_generate(budget_world, rule, _DEC))
    barrier = Barrier(4)

    def attempt() -> FinancialOccurrenceStatus:
        barrier.wait()
        return (
            _store(budget_world)
            .skip_occurrence(**budget_world.scope(), occurrence_id=occurrence.id)
            .status
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = {f.result() for f in [pool.submit(attempt) for _ in range(4)]}
    assert statuses == {FinancialOccurrenceStatus.SKIPPED}


def test_skipped_occurrences_are_not_regenerated_nor_rewritten_by_edits(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _only(_generate(budget_world, rule, _DEC))
    _store(budget_world).skip_occurrence(
        **budget_world.scope(), occurrence_id=occurrence.id
    )

    _store(budget_world).replace_recurrence(
        **budget_world.scope(),
        recurrence_id=rule.id,
        replacement=FinancialRecurrenceReplacement(
            expected_version=1,
            description="Internet",
            expected_amount=Decimal("999"),
            day_of_month=10,
            end_date=None,
        ),
        today=_TODAY,
    )
    again = _generate(budget_world, rule, _DEC)

    assert again.created_count == 0  # the skipped month is not recreated
    only = _only(again)
    assert only.id == occurrence.id
    assert only.status is FinancialOccurrenceStatus.SKIPPED
    assert only.expected.amount == Decimal("120")  # old snapshot, untouched


def test_a_superseded_occurrence_cannot_be_skipped(budget_world: BudgetWorld) -> None:
    rule = _rule(budget_world)
    occurrence = _only(_generate(budget_world, rule, _DEC))
    _store(budget_world).replace_recurrence(
        **budget_world.scope(),
        recurrence_id=rule.id,
        replacement=FinancialRecurrenceReplacement(
            expected_version=1,
            description="Internet",
            expected_amount=Decimal("130"),
            day_of_month=10,
            end_date=None,
        ),
        today=_TODAY,
    )
    with pytest.raises(FinancialRecurrenceOccurrenceStateError):
        _store(budget_world).skip_occurrence(
            **budget_world.scope(), occurrence_id=occurrence.id
        )


def test_skip_is_owner_only_and_hidden_ids_are_not_found(
    budget_world: BudgetWorld,
) -> None:
    household = _rule(budget_world)
    personal = _rule(budget_world, budget_world.account(household=False))
    house_occurrence = _only(_generate(budget_world, household, _OCT))
    own_occurrence = _only(_generate(budget_world, personal, _OCT))
    member = budget_world.scope(budget_world.member_id)

    with pytest.raises(FinancialRecurrenceNotEditableError):
        _store(budget_world).skip_occurrence(
            **member, occurrence_id=house_occurrence.id
        )
    with pytest.raises(FinancialRecurrenceOccurrenceNotFoundError):
        _store(budget_world).skip_occurrence(**member, occurrence_id=own_occurrence.id)
    statuses = {
        o.status
        for o in _store(budget_world).list_occurrences(
            **budget_world.scope(), window=_window(_OCT)
        )
    }
    assert statuses == {FinancialOccurrenceStatus.PENDING}


# --- pause / resume -----------------------------------------------------------


def test_pause_and_resume_are_idempotent_by_state_and_keep_history(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    generated = _generate(budget_world, rule, _OCT, _NOV)
    scope = budget_world.scope()

    paused = _store(budget_world).pause_recurrence(**scope, recurrence_id=rule.id)
    assert paused.status is FinancialRecurrenceStatus.PAUSED and paused.version == 2
    again = _store(budget_world).pause_recurrence(**scope, recurrence_id=rule.id)
    assert again == paused  # no new version for an unchanged state

    resumed = _store(budget_world).resume_recurrence(**scope, recurrence_id=rule.id)
    assert resumed.status is FinancialRecurrenceStatus.ACTIVE and resumed.version == 3
    assert (
        _store(budget_world).resume_recurrence(**scope, recurrence_id=rule.id)
        == resumed
    )

    survivors = _store(budget_world).list_occurrences(
        **scope, window=_window(_OCT, _NOV)
    )
    assert [o.id for o in survivors] == [o.id for o in generated.occurrences]
    assert all(o.status is FinancialOccurrenceStatus.PENDING for o in survivors)


def test_pause_and_resume_are_owner_only(budget_world: BudgetWorld) -> None:
    rule = _rule(budget_world)
    member = budget_world.scope(budget_world.member_id)
    with pytest.raises(FinancialRecurrenceNotEditableError):
        _store(budget_world).pause_recurrence(**member, recurrence_id=rule.id)
    with pytest.raises(FinancialRecurrenceNotEditableError):
        _store(budget_world).resume_recurrence(**member, recurrence_id=rule.id)
    assert _get_rule(budget_world, rule).status is FinancialRecurrenceStatus.ACTIVE


def test_a_stale_edit_after_a_pause_conflicts(budget_world: BudgetWorld) -> None:
    from meufinanceiro_persistence.financial_recurrence_store import (
        FinancialRecurrenceVersionConflictError,
    )

    rule = _rule(budget_world)
    _store(budget_world).pause_recurrence(**budget_world.scope(), recurrence_id=rule.id)
    with pytest.raises(FinancialRecurrenceVersionConflictError):
        _store(budget_world).replace_recurrence(
            **budget_world.scope(),
            recurrence_id=rule.id,
            replacement=FinancialRecurrenceReplacement(
                expected_version=1,
                description="Late",
                expected_amount=Decimal("1"),
                day_of_month=1,
                end_date=None,
            ),
            today=_TODAY,
        )


def test_the_vertical_without_a_realization_never_creates_a_movement(
    budget_world: BudgetWorld,
) -> None:
    """Internet 120 on day 10: October, November, pause, resume, December, skip."""
    rule = _rule(budget_world)
    october = _only(_generate(budget_world, rule, _OCT))
    assert october.status is FinancialOccurrenceStatus.PENDING
    _generate(budget_world, rule, _NOV)
    _store(budget_world).pause_recurrence(**budget_world.scope(), recurrence_id=rule.id)
    with pytest.raises(FinancialRecurrencePausedError):
        _generate(budget_world, rule, _DEC)
    _store(budget_world).resume_recurrence(
        **budget_world.scope(), recurrence_id=rule.id
    )
    december = _only(_generate(budget_world, rule, _DEC))
    skipped = _store(budget_world).skip_occurrence(
        **budget_world.scope(), occurrence_id=december.id
    )
    assert skipped.status is FinancialOccurrenceStatus.SKIPPED
    assert _count(budget_world, financial_movements) == 0
