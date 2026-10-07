"""PostgreSQL-backed proofs for manual monthly recurrence rules.

Everything runs through the non-superuser runtime role with forced RLS. A rule is
planning only: these proofs also show that no ledger row is ever written.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialOccurrenceStatus,
    FinancialRecurrenceDraft,
    FinancialRecurrenceRecord,
    FinancialRecurrenceReplacement,
    FinancialRecurrenceStatus,
    FinancialResultEffect,
    Money,
    monthly_occurrence_date,
    new_financial_idempotency_key,
    new_financial_resource_id,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import _set_context
from meufinanceiro_persistence.financial_recurrence_schema import (
    financial_recurrence_occurrences,
    financial_recurrences,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceAccessError,
    FinancialRecurrenceAccountNotFoundError,
    FinancialRecurrenceConflictError,
    FinancialRecurrenceInvalidShapeError,
    FinancialRecurrenceNotEditableError,
    FinancialRecurrenceNotFoundError,
    FinancialRecurrenceStore,
    FinancialRecurrenceVersionConflictError,
)

if TYPE_CHECKING:
    from conftest import BudgetWorld

_TODAY = date(2026, 10, 6)
_EXPENSE = FinancialResultEffect.EXPENSE
_INCOME = FinancialResultEffect.INCOME


def _draft(account_id: UUID, **overrides: Any) -> FinancialRecurrenceDraft:
    values: dict[str, Any] = {
        "account_id": account_id,
        "description": "Internet",
        "result_effect": _EXPENSE,
        "expected": Money(Decimal("120"), "BRL"),
        "start_date": date(2026, 1, 10),
        "day_of_month": 10,
        "end_date": None,
    }
    values.update(overrides)
    return FinancialRecurrenceDraft(**values)


def _store(world: BudgetWorld) -> FinancialRecurrenceStore:
    return FinancialRecurrenceStore(world.runtime)


def _create(
    world: BudgetWorld,
    account_id: UUID,
    *,
    operator_id: UUID | None = None,
    key: UUID | None = None,
    **overrides: Any,
) -> FinancialRecurrenceRecord:
    return _store(world).create_recurrence(
        **world.scope(operator_id),
        idempotency_key=key or new_financial_idempotency_key(),
        draft=_draft(account_id, **overrides),
    )


def _replacement(version: int = 1, **overrides: Any) -> FinancialRecurrenceReplacement:
    values: dict[str, Any] = {
        "expected_version": version,
        "description": "Internet",
        "expected_amount": Decimal("120"),
        "day_of_month": 10,
        "end_date": None,
    }
    values.update(overrides)
    return FinancialRecurrenceReplacement(**values)


def _count(world: BudgetWorld, table: Any) -> int:
    with world.engine.begin() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    assert isinstance(value, int)
    return value


def _insert_occurrence(
    world: BudgetWorld,
    rule: FinancialRecurrenceRecord,
    period_start: date,
    *,
    operator_id: UUID | None = None,
    **overrides: Any,
) -> UUID:
    """Insert one PENDING occurrence as the runtime role (what generation will do)."""
    occurrence_id = new_financial_resource_id()
    scope = world.scope(operator_id)
    values: dict[str, Any] = {
        "id": occurrence_id,
        "installation_id": scope["installation_id"],
        "residence_id": scope["residence_id"],
        "recurrence_id": rule.id,
        "account_id": rule.account_id,
        "owner_operator_id": rule.owner_operator_id,
        "period_start": period_start,
        "scheduled_date": monthly_occurrence_date(period_start, rule.day_of_month),
        "rule_version": rule.version,
        "result_effect": rule.result_effect.value,
        "currency": rule.expected.currency,
        "expected_amount": rule.expected.amount,
        "description": rule.description,
        "status": "PENDING",
        "created_at": func.transaction_timestamp(),
        "updated_at": func.transaction_timestamp(),
    }
    values.update(overrides)
    with world.runtime.begin() as connection:
        _set_context(connection, **scope)
        connection.execute(financial_recurrence_occurrences.insert().values(**values))
    return occurrence_id


def _status(world: BudgetWorld, occurrence_id: UUID) -> str:
    with world.engine.begin() as connection:
        value = connection.scalar(
            select(financial_recurrence_occurrences.c.status).where(
                financial_recurrence_occurrences.c.id == occurrence_id
            )
        )
    assert isinstance(value, str)
    return value


def _runtime_execute(
    world: BudgetWorld, statement: Any, operator_id: UUID | None = None
) -> Any:
    with world.runtime.begin() as connection:
        _set_context(connection, **world.scope(operator_id))
        return connection.execute(statement)


# --- create / read ------------------------------------------------------------


def test_create_persists_planning_only(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    ledger_before = _count(budget_world, financial_movements)

    record = _create(budget_world, account)

    assert record.version == 1
    assert record.status is FinancialRecurrenceStatus.ACTIVE
    assert record.owner_operator_id == budget_world.owner_id
    assert record.account_id == account
    assert record.expected == Money(Decimal("120"), "BRL")
    assert record.result_effect is _EXPENSE
    assert record.start_date == date(2026, 1, 10) and record.day_of_month == 10
    assert record.end_date is None
    assert _count(budget_world, financial_movements) == ledger_before == 0
    assert _count(budget_world, financial_recurrence_occurrences) == 0
    assert (
        _store(budget_world).get_recurrence(
            **budget_world.scope(), recurrence_id=record.id
        )
        == record
    )


def test_money_is_exact_decimal_numeric_24_8(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    record = _create(
        budget_world,
        account,
        expected=Money(Decimal("1234567.12345678"), "BRL"),
    )
    assert record.expected.amount == Decimal("1234567.12345678")


def test_create_with_an_end_date_and_income_effect(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    record = _create(
        budget_world,
        account,
        result_effect=_INCOME,
        end_date=date(2026, 12, 31),
        day_of_month=31,
    )
    assert record.result_effect is _INCOME
    assert record.end_date == date(2026, 12, 31) and record.day_of_month == 31


def test_create_is_replay_safe_and_digest_checked(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    key = new_financial_idempotency_key()

    first = _create(budget_world, account, key=key)
    again = _create(budget_world, account, key=key)

    assert again == first
    assert _count(budget_world, financial_recurrences) == 1
    with pytest.raises(FinancialRecurrenceConflictError):
        _create(budget_world, account, key=key, description="Other")
    with pytest.raises(FinancialRecurrenceConflictError):
        _create(budget_world, account, key=key, day_of_month=11)
    assert _count(budget_world, financial_recurrences) == 1


def test_concurrent_creates_with_one_key_converge(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    key = new_financial_idempotency_key()
    barrier = Barrier(4)

    def attempt() -> UUID:
        barrier.wait()
        return _create(budget_world, account, key=key).id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = {future.result() for future in [pool.submit(attempt) for _ in range(4)]}

    assert len(ids) == 1
    assert _count(budget_world, financial_recurrences) == 1


def test_two_rules_may_share_an_account_with_distinct_keys(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    first = _create(budget_world, account)
    second = _create(budget_world, account)
    assert first.id != second.id
    listed = _store(budget_world).list_recurrences(**budget_world.scope())
    assert [item.id for item in listed] == [first.id, second.id]


def test_list_filters_by_status_and_is_bounded(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    _create(budget_world, account)
    assert (
        _store(budget_world).list_recurrences(
            **budget_world.scope(), status=FinancialRecurrenceStatus.PAUSED
        )
        == ()
    )
    assert (
        len(
            _store(budget_world).list_recurrences(
                **budget_world.scope(), status=FinancialRecurrenceStatus.ACTIVE
            )
        )
        == 1
    )


# --- account validation -------------------------------------------------------


def test_the_account_must_be_owned_active_and_in_the_rule_currency(
    budget_world: BudgetWorld,
) -> None:
    member = budget_world.member_id
    household = budget_world.account()  # owner's HOUSEHOLD account
    with pytest.raises(FinancialRecurrenceAccountNotFoundError):
        _create(budget_world, household, operator_id=member)  # visible, not owned

    usd = budget_world.account(currency="USD")
    with pytest.raises(FinancialRecurrenceAccountNotFoundError):
        _create(budget_world, usd)  # BRL rule on a USD account

    archived = budget_world.account()
    budget_world.archive_account(archived)
    with pytest.raises(FinancialRecurrenceAccountNotFoundError):
        _create(budget_world, archived)

    with pytest.raises(FinancialRecurrenceAccountNotFoundError):
        _create(budget_world, new_financial_resource_id())
    assert _count(budget_world, financial_recurrences) == 0


def test_a_personal_account_of_another_member_is_not_found(
    budget_world: BudgetWorld,
) -> None:
    personal = budget_world.account(household=False)
    with pytest.raises(FinancialRecurrenceAccountNotFoundError):
        _create(budget_world, personal, operator_id=budget_world.member_id)


def test_a_non_member_has_no_access_and_cross_residence_fails_closed(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    with pytest.raises(FinancialRecurrenceAccessError):
        _create(budget_world, account, operator_id=budget_world.outsider_id)
    with pytest.raises(FinancialRecurrenceAccessError):
        _store(budget_world).list_recurrences(
            **budget_world.scope(
                budget_world.outsider_id, residence_id=budget_world.residence_id
            )
        )
    # The outsider acting in its own residence cannot reach the owner's account.
    with pytest.raises(FinancialRecurrenceAccountNotFoundError):
        _store(budget_world).create_recurrence(
            **budget_world.scope(
                budget_world.outsider_id, residence_id=budget_world.other_residence_id
            ),
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(account),
        )


# --- audience derived from the account (RLS) ----------------------------------


def test_household_account_rule_is_visible_to_members_but_read_only(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    member = budget_world.scope(budget_world.member_id)

    seen = _store(budget_world).get_recurrence(**member, recurrence_id=rule.id)
    assert seen == rule
    assert [r.id for r in _store(budget_world).list_recurrences(**member)] == [rule.id]
    with pytest.raises(FinancialRecurrenceNotEditableError):
        _store(budget_world).replace_recurrence(
            **member,
            recurrence_id=rule.id,
            replacement=_replacement(description="Hacked"),
            today=_TODAY,
        )


def test_personal_account_rule_is_invisible_to_other_members(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account(household=False)
    rule = _create(budget_world, account)
    member = budget_world.scope(budget_world.member_id)

    with pytest.raises(FinancialRecurrenceNotFoundError):
        _store(budget_world).get_recurrence(**member, recurrence_id=rule.id)
    assert _store(budget_world).list_recurrences(**member) == ()
    with pytest.raises(FinancialRecurrenceNotFoundError):
        _store(budget_world).replace_recurrence(
            **member,
            recurrence_id=rule.id,
            replacement=_replacement(),
            today=_TODAY,
        )


def test_shared_account_rule_is_visible_only_to_the_grantee(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account(shared=True)
    rule = _create(budget_world, account)
    member = budget_world.scope(budget_world.member_id)

    with pytest.raises(FinancialRecurrenceNotFoundError):
        _store(budget_world).get_recurrence(**member, recurrence_id=rule.id)
    budget_world.grant_account(account, budget_world.member_id)
    assert (
        _store(budget_world).get_recurrence(**member, recurrence_id=rule.id).id
        == rule.id
    )
    with pytest.raises(FinancialRecurrenceNotEditableError):
        _store(budget_world).replace_recurrence(
            **member,
            recurrence_id=rule.id,
            replacement=_replacement(description="Hacked"),
            today=_TODAY,
        )


def test_knowing_an_id_in_another_residence_proves_nothing(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    with pytest.raises(FinancialRecurrenceNotFoundError):
        _store(budget_world).get_recurrence(
            **budget_world.scope(
                budget_world.outsider_id, residence_id=budget_world.other_residence_id
            ),
            recurrence_id=rule.id,
        )


# --- CAS ----------------------------------------------------------------------


def test_edit_advances_the_version_and_keeps_identity(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)

    outcome = _store(budget_world).replace_recurrence(
        **budget_world.scope(),
        recurrence_id=rule.id,
        replacement=_replacement(
            description="Internet fibra",
            expected_amount=Decimal("135.50"),
            day_of_month=15,
            end_date=date(2027, 6, 30),
        ),
        today=_TODAY,
    )

    edited = outcome.recurrence
    assert outcome.superseded_count == 0
    assert edited.version == 2
    assert edited.description == "Internet fibra"
    assert edited.expected.amount == Decimal("135.5")
    assert edited.day_of_month == 15 and edited.end_date == date(2027, 6, 30)
    assert edited.created_at == rule.created_at
    assert edited.updated_at >= rule.updated_at
    # Identity stays put.
    assert (edited.account_id, edited.start_date, edited.result_effect) == (
        rule.account_id,
        rule.start_date,
        rule.result_effect,
    )


def test_a_stale_version_writes_nothing(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    _store(budget_world).replace_recurrence(
        **budget_world.scope(),
        recurrence_id=rule.id,
        replacement=_replacement(description="A"),
        today=_TODAY,
    )
    with pytest.raises(FinancialRecurrenceVersionConflictError):
        _store(budget_world).replace_recurrence(
            **budget_world.scope(),
            recurrence_id=rule.id,
            replacement=_replacement(version=1, description="B"),
            today=_TODAY,
        )
    current = _store(budget_world).get_recurrence(
        **budget_world.scope(), recurrence_id=rule.id
    )
    assert current.description == "A" and current.version == 2


def test_an_edit_that_changes_nothing_does_not_bump_the_version(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    outcome = _store(budget_world).replace_recurrence(
        **budget_world.scope(),
        recurrence_id=rule.id,
        replacement=_replacement(),
        today=_TODAY,
    )
    assert outcome.recurrence == rule and outcome.superseded_count == 0
    # The CAS still applies to a no-op: a stale version is a conflict, not a success.
    with pytest.raises(FinancialRecurrenceVersionConflictError):
        _store(budget_world).replace_recurrence(
            **budget_world.scope(),
            recurrence_id=rule.id,
            replacement=_replacement(version=7),
            today=_TODAY,
        )


def test_end_date_before_start_is_an_invalid_shape(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    with pytest.raises(FinancialRecurrenceInvalidShapeError):
        _store(budget_world).replace_recurrence(
            **budget_world.scope(),
            recurrence_id=rule.id,
            replacement=_replacement(end_date=date(2025, 12, 31)),
            today=_TODAY,
        )


def test_concurrent_edits_with_the_same_version_have_exactly_one_winner(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    barrier = Barrier(4)

    def attempt(index: int) -> str:
        barrier.wait()
        try:
            _store(budget_world).replace_recurrence(
                **budget_world.scope(),
                recurrence_id=rule.id,
                replacement=_replacement(description=f"Racer {index}"),
                today=_TODAY,
            )
        except FinancialRecurrenceVersionConflictError:
            return "stale"
        return "won"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [f.result() for f in [pool.submit(attempt, i) for i in range(4)]]

    assert results.count("won") == 1 and results.count("stale") == 3
    current = _store(budget_world).get_recurrence(
        **budget_world.scope(), recurrence_id=rule.id
    )
    assert current.version == 2


# --- edit treats future PENDING explicitly -------------------------------------


def test_edit_supersedes_future_pending_and_preserves_history(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    overdue = _insert_occurrence(budget_world, rule, date(2026, 9, 1))  # < today
    skipped = _insert_occurrence(budget_world, rule, date(2026, 10, 1))
    november = _insert_occurrence(budget_world, rule, date(2026, 11, 1))
    december = _insert_occurrence(budget_world, rule, date(2026, 12, 1))
    _runtime_execute(
        budget_world,
        update(financial_recurrence_occurrences)
        .where(financial_recurrence_occurrences.c.id == skipped)
        .values(
            status="SKIPPED",
            skipped_at=func.transaction_timestamp(),
            updated_at=func.transaction_timestamp(),
        ),
    )

    outcome = _store(budget_world).replace_recurrence(
        **budget_world.scope(),
        recurrence_id=rule.id,
        replacement=_replacement(expected_amount=Decimal("130")),
        today=_TODAY,
    )

    assert outcome.superseded_count == 2
    assert _status(budget_world, overdue) == "PENDING"  # history, untouched
    assert _status(budget_world, skipped) == "SKIPPED"  # terminal, untouched
    assert _status(budget_world, november) == "SUPERSEDED"
    assert _status(budget_world, december) == "SUPERSEDED"
    assert _count(budget_world, financial_movements) == 0


def test_edit_keeps_future_pending_that_the_new_revision_still_describes(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    november = _insert_occurrence(budget_world, rule, date(2026, 11, 1))
    december = _insert_occurrence(budget_world, rule, date(2026, 12, 1))

    outcome = _store(budget_world).replace_recurrence(
        **budget_world.scope(),
        recurrence_id=rule.id,
        replacement=_replacement(end_date=date(2026, 11, 30)),
        today=_TODAY,
    )

    assert outcome.superseded_count == 1
    assert _status(budget_world, november) == "PENDING"
    assert _status(budget_world, december) == "SUPERSEDED"


def test_a_superseded_month_can_hold_a_replacement_occurrence(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    november = _insert_occurrence(budget_world, rule, date(2026, 11, 1))
    edited = (
        _store(budget_world)
        .replace_recurrence(
            **budget_world.scope(),
            recurrence_id=rule.id,
            replacement=_replacement(expected_amount=Decimal("140")),
            today=_TODAY,
        )
        .recurrence
    )
    assert _status(budget_world, november) == "SUPERSEDED"

    replacement_id = _insert_occurrence(budget_world, edited, date(2026, 11, 1))

    assert _status(budget_world, replacement_id) == "PENDING"
    with pytest.raises(DBAPIError):  # a second live occurrence for the month
        _insert_occurrence(budget_world, edited, date(2026, 11, 1))


# --- database-enforced invariants ---------------------------------------------


def test_runtime_role_cannot_delete_or_truncate(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    _insert_occurrence(budget_world, rule, date(2026, 10, 1))
    for table in ("finance.recurrences", "finance.recurrence_occurrences"):
        with pytest.raises(DBAPIError):
            _runtime_execute(budget_world, text(f"DELETE FROM {table}"))
        with pytest.raises(DBAPIError):
            _runtime_execute(budget_world, text(f"TRUNCATE {table} CASCADE"))
    assert _count(budget_world, financial_recurrences) == 1
    assert _count(budget_world, financial_recurrence_occurrences) == 1


@pytest.mark.parametrize(
    "values",
    [
        {"currency": "USD"},
        {"start_date": date(2026, 2, 1)},
        {"result_effect": "INCOME"},
        {"account_id": uuid4()},
        {"owner_operator_id": uuid4()},
        {"frequency": "WEEKLY"},
    ],
)
def test_rule_identity_columns_are_immutable_for_the_runtime_role(
    budget_world: BudgetWorld, values: dict[str, Any]
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    with pytest.raises(DBAPIError):
        _runtime_execute(
            budget_world,
            update(financial_recurrences)
            .where(financial_recurrences.c.id == rule.id)
            .values(**values),
        )


def test_the_database_enforces_cas_steps_of_one(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    for version in (1, 3):  # same version and a skip are both rejected
        with pytest.raises(DBAPIError):
            _runtime_execute(
                budget_world,
                update(financial_recurrences)
                .where(financial_recurrences.c.id == rule.id)
                .values(
                    description="X",
                    version=version,
                    updated_at=func.transaction_timestamp(),
                    updated_by_operator_id=budget_world.owner_id,
                ),
            )
    assert (
        _store(budget_world)
        .get_recurrence(**budget_world.scope(), recurrence_id=rule.id)
        .version
        == 1
    )


def test_a_member_cannot_move_another_members_rule_even_with_raw_sql(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    result = _runtime_execute(
        budget_world,
        update(financial_recurrences)
        .where(financial_recurrences.c.id == rule.id)
        .values(
            description="Hijack",
            version=2,
            updated_at=func.transaction_timestamp(),
            updated_by_operator_id=budget_world.member_id,
        ),
        operator_id=budget_world.member_id,
    )
    assert result.rowcount == 0
    assert (
        _store(budget_world)
        .get_recurrence(**budget_world.scope(), recurrence_id=rule.id)
        .description
        == "Internet"
    )


def test_a_paused_rule_cannot_receive_a_new_occurrence_at_the_database(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    _runtime_execute(
        budget_world,
        update(financial_recurrences)
        .where(financial_recurrences.c.id == rule.id)
        .values(
            status="PAUSED",
            version=2,
            updated_at=func.transaction_timestamp(),
            updated_by_operator_id=budget_world.owner_id,
        ),
    )
    paused = _store(budget_world).get_recurrence(
        **budget_world.scope(), recurrence_id=rule.id
    )
    assert paused.status is FinancialRecurrenceStatus.PAUSED
    with pytest.raises(DBAPIError):
        _insert_occurrence(budget_world, paused, date(2026, 10, 1))
    assert _count(budget_world, financial_recurrence_occurrences) == 0


@pytest.mark.parametrize(
    "override",
    [
        {"scheduled_date": date(2026, 10, 11)},  # not the calendar's date
        {"rule_version": 9},  # not the current revision
        {"expected_amount": Decimal("999")},  # not the rule's snapshot
        {"description": "Other"},
        {"currency": "USD"},
        {"status": "SKIPPED"},  # born terminal
        {"account_id": uuid4()},
        {"owner_operator_id": uuid4()},
    ],
)
def test_an_occurrence_must_snapshot_the_current_revision(
    budget_world: BudgetWorld, override: dict[str, Any]
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    with pytest.raises(DBAPIError):
        _insert_occurrence(budget_world, rule, date(2026, 10, 1), **override)
    assert _count(budget_world, financial_recurrence_occurrences) == 0


def test_an_occurrence_outside_start_and_end_is_rejected(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(
        budget_world,
        account,
        start_date=date(2026, 3, 15),
        day_of_month=10,
        end_date=date(2026, 8, 10),
    )
    with pytest.raises(DBAPIError):
        _insert_occurrence(budget_world, rule, date(2026, 3, 1))  # 10th < start 15th
    with pytest.raises(DBAPIError):
        _insert_occurrence(budget_world, rule, date(2026, 9, 1))  # after end
    assert _insert_occurrence(budget_world, rule, date(2026, 8, 1))  # end inclusive


def test_an_occurrence_on_an_archived_account_is_rejected(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    budget_world.archive_account(account)
    with pytest.raises(DBAPIError):
        _insert_occurrence(budget_world, rule, date(2026, 10, 1))


def test_terminal_occurrences_are_immutable(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    occurrence = _insert_occurrence(budget_world, rule, date(2026, 10, 1))
    _runtime_execute(
        budget_world,
        update(financial_recurrence_occurrences)
        .where(financial_recurrence_occurrences.c.id == occurrence)
        .values(
            status="SKIPPED",
            skipped_at=func.transaction_timestamp(),
            updated_at=func.transaction_timestamp(),
        ),
    )
    for values in (
        {"status": "PENDING", "skipped_at": None},
        {
            "status": "SUPERSEDED",
            "skipped_at": None,
            "superseded_at": func.transaction_timestamp(),
        },
        {"updated_at": func.transaction_timestamp()},
    ):
        with pytest.raises(DBAPIError):
            _runtime_execute(
                budget_world,
                update(financial_recurrence_occurrences)
                .where(financial_recurrence_occurrences.c.id == occurrence)
                .values(**values),
            )
    assert _status(budget_world, occurrence) == "SKIPPED"


def test_snapshot_columns_of_an_occurrence_cannot_be_updated(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    occurrence = _insert_occurrence(budget_world, rule, date(2026, 10, 1))
    for column, value in (
        ("expected_amount", Decimal("1")),
        ("description", "Other"),
        ("scheduled_date", date(2026, 10, 12)),
        ("rule_version", 5),
    ):
        with pytest.raises(DBAPIError):
            _runtime_execute(
                budget_world,
                update(financial_recurrence_occurrences)
                .where(financial_recurrence_occurrences.c.id == occurrence)
                .values(**{column: value}),
            )


def test_a_realization_cannot_point_at_a_foreign_movement(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    occurrence = _insert_occurrence(budget_world, rule, date(2026, 10, 1))
    with pytest.raises(DBAPIError):
        _runtime_execute(
            budget_world,
            update(financial_recurrence_occurrences)
            .where(financial_recurrence_occurrences.c.id == occurrence)
            .values(
                status="REALIZED",
                movement_id=new_financial_resource_id(),
                realization_idempotency_key=new_financial_idempotency_key(),
                realization_request_digest="0" * 64,
                realized_at=func.transaction_timestamp(),
                realized_by_operator_id=budget_world.owner_id,
                updated_at=func.transaction_timestamp(),
            ),
        )
    assert _status(budget_world, occurrence) == "PENDING"


def test_the_ledger_is_untouched(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account)
    _insert_occurrence(budget_world, rule, date(2026, 10, 1))
    assert _count(budget_world, financial_movements) == 0
    assert FinancialOccurrenceStatus.PENDING.value == _status(
        budget_world,
        _insert_occurrence(budget_world, rule, date(2026, 11, 1)),
    )
