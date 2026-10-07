"""PostgreSQL-backed proofs for the append-only history of recurrence rules.

Everything runs through the non-superuser runtime role with forced RLS. The history is
written by the database itself in the statement that stores the rule, so the proofs go
through the store *and* through raw SQL: a valid rule write cannot exist without its
revision, and the runtime cannot forge, skip or alter one.
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
    RECURRENCE_REVISION_PAGE_MAX,
    FinancialRecurrenceDraft,
    FinancialRecurrenceRecord,
    FinancialRecurrenceReplacement,
    FinancialRecurrenceRevisionRecord,
    FinancialRecurrenceStatus,
    FinancialRecurrenceWindow,
    FinancialResultEffect,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

import meufinanceiro_persistence.financial_recurrence_store as store_module
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import _set_context
from meufinanceiro_persistence.financial_recurrence_schema import (
    financial_recurrence_occurrences,
    financial_recurrence_revisions,
    financial_recurrences,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceConflictError,
    FinancialRecurrenceNotFoundError,
    FinancialRecurrenceStore,
    FinancialRecurrenceVersionConflictError,
)

if TYPE_CHECKING:
    from conftest import BudgetWorld

_TODAY = date(2026, 10, 6)
_REVISIONS = financial_recurrence_revisions


def _store(world: BudgetWorld) -> FinancialRecurrenceStore:
    return FinancialRecurrenceStore(world.runtime)


def _create(
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


def _replace(
    world: BudgetWorld, rule: FinancialRecurrenceRecord, version: int, **overrides: Any
) -> Any:
    values: dict[str, Any] = {
        "expected_version": version,
        "description": rule.description,
        "expected_amount": rule.expected.amount,
        "day_of_month": rule.day_of_month,
        "end_date": rule.end_date,
    }
    values.update(overrides)
    return _store(world).replace_recurrence(
        **world.scope(),
        recurrence_id=rule.id,
        replacement=FinancialRecurrenceReplacement(**values),
        today=_TODAY,
    )


def _history(
    world: BudgetWorld, rule: FinancialRecurrenceRecord
) -> tuple[FinancialRecurrenceRevisionRecord, ...]:
    return _store(world).list_recurrence_revisions(
        **world.scope(), recurrence_id=rule.id
    )


def _raw_versions(world: BudgetWorld, rule: FinancialRecurrenceRecord) -> list[int]:
    with world.engine.begin() as connection:
        return list(
            connection.scalars(
                select(_REVISIONS.c.version)
                .where(_REVISIONS.c.recurrence_id == rule.id)
                .order_by(_REVISIONS.c.version)
            )
        )


def _count(world: BudgetWorld, table: Any) -> int:
    with world.engine.begin() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    assert isinstance(value, int)
    return value


def _runtime_execute(
    world: BudgetWorld, statement: Any, operator_id: UUID | None = None
) -> Any:
    with world.runtime.begin() as connection:
        _set_context(connection, **world.scope(operator_id))
        return connection.execute(statement)


def _raw_rule_update(
    world: BudgetWorld, rule_id: UUID, version: int, **values: Any
) -> Any:
    return _runtime_execute(
        world,
        update(financial_recurrences)
        .where(financial_recurrences.c.id == rule_id)
        .values(
            version=version,
            updated_at=func.transaction_timestamp(),
            updated_by_operator_id=world.owner_id,
            **values,
        ),
    )


# --- 1. create ------------------------------------------------------------------


def test_create_records_exactly_revision_one(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    rule = _create(budget_world, account, end_date=date(2027, 1, 10))

    history = _history(budget_world, rule)

    assert len(history) == 1
    first = history[0]
    assert first.recurrence_id == rule.id and first.version == 1
    assert first.residence_id == budget_world.residence_id
    assert first.account_id == account
    assert first.owner_operator_id == budget_world.owner_id
    assert first.actor_operator_id == budget_world.owner_id
    assert first.description == "Internet"
    assert first.result_effect is FinancialResultEffect.EXPENSE
    assert first.expected == Money(Decimal("120"), "BRL")
    assert first.start_date == date(2026, 1, 10) and first.day_of_month == 10
    assert first.end_date == date(2027, 1, 10)
    assert first.status is FinancialRecurrenceStatus.ACTIVE
    assert first.recorded_at == rule.created_at == rule.updated_at
    assert _count(budget_world, financial_movements) == 0


def test_an_idempotent_create_replay_does_not_add_a_revision(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    key = new_financial_idempotency_key()
    draft = FinancialRecurrenceDraft(
        account_id=account,
        description="Internet",
        result_effect=FinancialResultEffect.EXPENSE,
        expected=Money(Decimal("120"), "BRL"),
        start_date=date(2026, 1, 10),
        day_of_month=10,
        end_date=None,
    )
    first = _store(budget_world).create_recurrence(
        **budget_world.scope(), idempotency_key=key, draft=draft
    )
    again = _store(budget_world).create_recurrence(
        **budget_world.scope(), idempotency_key=key, draft=draft
    )
    assert again == first
    assert _raw_versions(budget_world, first) == [1]
    assert _count(budget_world, _REVISIONS) == 1


# --- 2 / 3. edits preserve every snapshot -----------------------------------------


def test_an_edit_preserves_both_snapshots(budget_world: BudgetWorld) -> None:
    rule = _create(budget_world, end_date=date(2027, 1, 10))
    _replace(
        budget_world,
        rule,
        1,
        description="Internet fibra",
        expected_amount=Decimal("150.50"),
        day_of_month=20,
        end_date=date(2027, 6, 20),
    )

    first, second = _history(budget_world, rule)

    assert (first.version, second.version) == (1, 2)
    assert first.description == "Internet"
    assert first.expected.amount == Decimal("120")
    assert first.day_of_month == 10 and first.end_date == date(2027, 1, 10)
    assert second.description == "Internet fibra"
    assert second.expected.amount == Decimal("150.50")
    assert second.day_of_month == 20 and second.end_date == date(2027, 6, 20)
    # Identity never moves between revisions.
    for field in (
        "recurrence_id",
        "account_id",
        "owner_operator_id",
        "start_date",
        "result_effect",
    ):
        assert getattr(first, field) == getattr(second, field)
    assert second.actor_operator_id == budget_world.owner_id
    assert second.recorded_at >= first.recorded_at


def test_editing_before_any_occurrence_still_preserves_the_old_state(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world)
    assert _count(budget_world, financial_recurrence_occurrences) == 0

    _replace(budget_world, rule, 1, description="Nova", expected_amount=Decimal("99"))
    _replace(budget_world, rule, 2, day_of_month=25)

    history = _history(budget_world, rule)
    assert [r.version for r in history] == [1, 2, 3]
    assert (history[0].description, history[0].expected.amount) == (
        "Internet",
        Decimal("120"),
    )
    assert (history[1].description, history[1].expected.amount) == (
        "Nova",
        Decimal("99"),
    )
    assert [r.day_of_month for r in history] == [10, 10, 25]
    # No occurrence was ever needed to keep the old rule.
    assert _count(budget_world, financial_recurrence_occurrences) == 0


def test_the_history_keeps_what_occurrences_snapshot_and_what_they_did_not(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world)
    store = _store(budget_world)
    store.generate_occurrences(
        **budget_world.scope(),
        recurrence_id=rule.id,
        window=FinancialRecurrenceWindow(date(2026, 11, 1), date(2026, 11, 1)),
    )
    _replace(budget_world, rule, 1, description="Mudou")

    # The occurrence semantics are unchanged: the future PENDING one is SUPERSEDED.
    with budget_world.engine.begin() as connection:
        statuses = list(
            connection.scalars(
                select(financial_recurrence_occurrences.c.status).order_by(
                    financial_recurrence_occurrences.c.created_at
                )
            )
        )
    assert statuses == ["SUPERSEDED"]
    assert [r.description for r in _history(budget_world, rule)] == [
        "Internet",
        "Mudou",
    ]


# --- 4. pause / resume ----------------------------------------------------------


def test_pause_and_resume_record_their_own_versions(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world)
    store = _store(budget_world)
    store.pause_recurrence(**budget_world.scope(), recurrence_id=rule.id)
    store.resume_recurrence(**budget_world.scope(), recurrence_id=rule.id)

    history = _history(budget_world, rule)

    assert [(r.version, r.status.value) for r in history] == [
        (1, "ACTIVE"),
        (2, "PAUSED"),
        (3, "ACTIVE"),
    ]
    assert {r.description for r in history} == {"Internet"}
    assert all(r.actor_operator_id == budget_world.owner_id for r in history)
    assert [r.recorded_at for r in history] == sorted(r.recorded_at for r in history)


# --- 5. no-ops ------------------------------------------------------------------


def test_idempotent_pause_resume_and_noop_edit_record_nothing(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world)
    store = _store(budget_world)

    store.resume_recurrence(**budget_world.scope(), recurrence_id=rule.id)  # no-op
    outcome = _replace(budget_world, rule, 1)  # no-op edit
    assert outcome.recurrence == rule
    assert _raw_versions(budget_world, rule) == [1]

    store.pause_recurrence(**budget_world.scope(), recurrence_id=rule.id)
    store.pause_recurrence(**budget_world.scope(), recurrence_id=rule.id)  # no-op
    assert _raw_versions(budget_world, rule) == [1, 2]

    store.resume_recurrence(**budget_world.scope(), recurrence_id=rule.id)
    store.resume_recurrence(**budget_world.scope(), recurrence_id=rule.id)  # no-op
    assert _raw_versions(budget_world, rule) == [1, 2, 3]


# --- 6. stale CAS ---------------------------------------------------------------


def test_a_stale_cas_leaves_no_orphan_revision(budget_world: BudgetWorld) -> None:
    rule = _create(budget_world)
    _replace(budget_world, rule, 1, description="A")

    with pytest.raises(FinancialRecurrenceVersionConflictError):
        _replace(budget_world, rule, 1, description="B")
    with pytest.raises(FinancialRecurrenceVersionConflictError):
        _replace(budget_world, rule, 9, description="C")

    assert _raw_versions(budget_world, rule) == [1, 2]
    assert [r.description for r in _history(budget_world, rule)] == ["Internet", "A"]


# --- 7. atomicity ---------------------------------------------------------------


def test_a_failure_after_the_rule_update_rolls_back_rule_and_revision(
    budget_world: BudgetWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = _create(budget_world)
    _store(budget_world).generate_occurrences(
        **budget_world.scope(),
        recurrence_id=rule.id,
        window=FinancialRecurrenceWindow(date(2026, 11, 1), date(2026, 11, 1)),
    )

    def explode(*_args: Any, **_kwargs: Any) -> int:
        raise RuntimeError("injected failure after the rule update")

    monkeypatch.setattr(store_module, "_supersede_stale_future_pending", explode)
    with pytest.raises(RuntimeError, match="injected"):
        _replace(budget_world, rule, 1, description="Never persisted")
    monkeypatch.undo()

    current = _store(budget_world).get_recurrence(
        **budget_world.scope(), recurrence_id=rule.id
    )
    assert current.version == 1 and current.description == "Internet"
    assert _raw_versions(budget_world, rule) == [1]


def test_a_failed_transaction_around_a_raw_update_leaves_no_revision(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world)
    with pytest.raises(RuntimeError, match="boom"):
        with budget_world.runtime.begin() as connection:
            _set_context(connection, **budget_world.scope())
            connection.execute(
                update(financial_recurrences)
                .where(financial_recurrences.c.id == rule.id)
                .values(
                    status="PAUSED",
                    version=2,
                    updated_at=func.transaction_timestamp(),
                    updated_by_operator_id=budget_world.owner_id,
                )
            )
            # Inside the transaction the revision already exists...
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(_REVISIONS)
                    .where(_REVISIONS.c.recurrence_id == rule.id)
                )
                == 2
            )
            raise RuntimeError("boom")
    # ...and vanishes with the rule when the transaction rolls back.
    assert _raw_versions(budget_world, rule) == [1]


def test_a_rejected_rule_update_leaves_no_revision(budget_world: BudgetWorld) -> None:
    rule = _create(budget_world)
    with pytest.raises(DBAPIError):  # version skip: the row trigger refuses the rule
        _raw_rule_update(budget_world, rule.id, 3, description="Skip")
    with pytest.raises(DBAPIError):  # CHECK violation inside the same statement
        _raw_rule_update(budget_world, rule.id, 2, expected_amount=Decimal("-1"))
    assert _raw_versions(budget_world, rule) == [1]


def test_the_database_records_a_raw_runtime_update_without_the_store(
    budget_world: BudgetWorld,
) -> None:
    """Server-authoritative: no code path can store a rule state unrecorded."""
    rule = _create(budget_world)

    _raw_rule_update(budget_world, rule.id, 2, description="Raw", status="PAUSED")

    first, second = _history(budget_world, rule)
    assert (second.version, second.description) == (2, "Raw")
    assert second.status is FinancialRecurrenceStatus.PAUSED
    assert first.description == "Internet"
    assert second.actor_operator_id == budget_world.owner_id


# --- 8. concurrency -------------------------------------------------------------


def test_concurrent_edits_produce_a_gapless_duplicate_free_sequence(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world)
    workers, per_worker = 6, 3
    barrier = Barrier(workers)

    def worker(index: int) -> int:
        barrier.wait()
        won = 0
        for attempt in range(per_worker):
            while True:
                current = _store(budget_world).get_recurrence(
                    **budget_world.scope(), recurrence_id=rule.id
                )
                try:
                    _replace(
                        budget_world,
                        rule,
                        current.version,
                        description=f"w{index}-{attempt}",
                    )
                except FinancialRecurrenceVersionConflictError:
                    continue
                won += 1
                break
        return won

    with ThreadPoolExecutor(max_workers=workers) as pool:
        wins = [f.result() for f in [pool.submit(worker, i) for i in range(workers)]]

    total = sum(wins)
    assert total == workers * per_worker
    assert _raw_versions(budget_world, rule) == list(range(1, total + 2))
    history = _history_pages(budget_world, rule)
    assert len({r.description for r in history[1:]}) == total  # nobody lost an edit
    final = _store(budget_world).get_recurrence(
        **budget_world.scope(), recurrence_id=rule.id
    )
    assert final.version == total + 1
    assert history[-1].description == final.description


def _history_pages(
    world: BudgetWorld, rule: FinancialRecurrenceRecord
) -> list[FinancialRecurrenceRevisionRecord]:
    collected: list[FinancialRecurrenceRevisionRecord] = []
    after = 0
    while True:
        page = _store(world).list_recurrence_revisions(
            **world.scope(), recurrence_id=rule.id, after_version=after, limit=5
        )
        if not page:
            return collected
        collected.extend(page)
        after = page[-1].version


def test_history_is_read_by_keyset_pages_with_an_explicit_bound(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world)
    for version in range(1, 8):
        _replace(budget_world, rule, version, description=f"v{version + 1}")

    pages = _history_pages(budget_world, rule)
    assert [r.version for r in pages] == list(range(1, 9))
    assert [
        r.version
        for r in _store(budget_world).list_recurrence_revisions(
            **budget_world.scope(), recurrence_id=rule.id, after_version=6, limit=1
        )
    ] == [7]
    for bad_limit in (0, RECURRENCE_REVISION_PAGE_MAX + 1):
        with pytest.raises(ValueError):
            _store(budget_world).list_recurrence_revisions(
                **budget_world.scope(), recurrence_id=rule.id, limit=bad_limit
            )
    with pytest.raises(ValueError):
        _store(budget_world).list_recurrence_revisions(
            **budget_world.scope(), recurrence_id=rule.id, after_version=-1
        )


# --- 9. RLS / residence / account audience ---------------------------------------


def test_household_revisions_are_readable_by_members_but_not_writable(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world)
    _replace(budget_world, rule, 1, description="B")
    member = budget_world.scope(budget_world.member_id)

    seen = _store(budget_world).list_recurrence_revisions(
        **member, recurrence_id=rule.id
    )
    assert [r.version for r in seen] == [1, 2]
    # A member cannot move the rule, so no revision can be created through them.
    result = _runtime_execute(
        budget_world,
        update(financial_recurrences)
        .where(financial_recurrences.c.id == rule.id)
        .values(
            description="Hijack",
            version=3,
            updated_at=func.transaction_timestamp(),
            updated_by_operator_id=budget_world.member_id,
        ),
        operator_id=budget_world.member_id,
    )
    assert result.rowcount == 0
    assert _raw_versions(budget_world, rule) == [1, 2]


def test_personal_account_history_is_invisible_to_other_members(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world, budget_world.account(household=False))
    member = budget_world.scope(budget_world.member_id)

    with pytest.raises(FinancialRecurrenceNotFoundError):
        _store(budget_world).list_recurrence_revisions(**member, recurrence_id=rule.id)
    rows = _runtime_execute(
        budget_world, select(_REVISIONS), operator_id=budget_world.member_id
    ).all()
    assert rows == []
    assert len(_history(budget_world, rule)) == 1  # the owner still sees it


def test_shared_account_history_follows_the_account_grant(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account(shared=True)
    rule = _create(budget_world, account)
    member = budget_world.scope(budget_world.member_id)

    with pytest.raises(FinancialRecurrenceNotFoundError):
        _store(budget_world).list_recurrence_revisions(**member, recurrence_id=rule.id)
    budget_world.grant_account(account, budget_world.member_id)
    seen = _store(budget_world).list_recurrence_revisions(
        **member, recurrence_id=rule.id
    )
    assert [r.version for r in seen] == [1]


def test_cross_residence_history_fails_closed(budget_world: BudgetWorld) -> None:
    rule = _create(budget_world)
    outsider = budget_world.scope(
        budget_world.outsider_id, residence_id=budget_world.other_residence_id
    )
    with pytest.raises(FinancialRecurrenceNotFoundError):
        _store(budget_world).list_recurrence_revisions(
            **outsider, recurrence_id=rule.id
        )
    with budget_world.runtime.begin() as connection:
        _set_context(connection, **outsider)
        assert connection.execute(select(_REVISIONS)).all() == []
    # Presenting the home residence with a foreign operator is refused too.
    with budget_world.runtime.begin() as connection:
        _set_context(connection, **budget_world.scope(budget_world.outsider_id))
        assert connection.execute(select(_REVISIONS)).all() == []


# --- 10. append-only ------------------------------------------------------------


def test_the_runtime_cannot_update_delete_or_truncate_revisions(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world)
    for statement in (
        update(_REVISIONS)
        .where(_REVISIONS.c.recurrence_id == rule.id)
        .values(description="Rewritten"),
        delete(_REVISIONS).where(_REVISIONS.c.recurrence_id == rule.id),
        text("TRUNCATE finance.recurrence_revisions"),
    ):
        with pytest.raises(DBAPIError):
            _runtime_execute(budget_world, statement)
    assert _history(budget_world, rule)[0].description == "Internet"


def test_a_revision_is_immutable_even_for_the_privileged_role(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world)
    with pytest.raises(DBAPIError, match="append-only"):
        with budget_world.engine.begin() as connection:
            connection.execute(
                update(_REVISIONS)
                .where(_REVISIONS.c.recurrence_id == rule.id)
                .values(description="Rewritten")
            )
    assert _raw_versions(budget_world, rule) == [1]


def test_the_runtime_cannot_forge_a_revision_with_raw_inserts(
    budget_world: BudgetWorld,
) -> None:
    rule = _create(budget_world)
    _replace(budget_world, rule, 1, description="B")

    def forged(version: int, **overrides: Any) -> Any:
        values: dict[str, Any] = {
            "recurrence_id": rule.id,
            "version": version,
            "installation_id": budget_world.installation_id,
            "residence_id": budget_world.residence_id,
            "account_id": rule.account_id,
            "owner_operator_id": budget_world.owner_id,
            "description": "Forged",
            "result_effect": "EXPENSE",
            "currency": "BRL",
            "expected_amount": Decimal("1"),
            "frequency": "MONTHLY",
            "start_date": rule.start_date,
            "day_of_month": 10,
            "end_date": None,
            "status": "ACTIVE",
            "actor_operator_id": budget_world.owner_id,
            "recorded_at": func.transaction_timestamp(),
        }
        values.update(overrides)
        return insert(_REVISIONS).values(**values)

    # A client statement runs outside any trigger: the RLS policy refuses it, whether
    # it is the next version, a duplicate or a rewrite of the past.
    for version in (3, 2, 1):
        with pytest.raises(DBAPIError):
            _runtime_execute(budget_world, forged(version))
    assert _raw_versions(budget_world, rule) == [1, 2]
    assert [r.description for r in _history(budget_world, rule)] == ["Internet", "B"]


def test_the_database_refuses_a_revision_that_is_not_the_stored_rule(
    budget_world: BudgetWorld,
) -> None:
    """Even a privileged writer cannot insert history that disagrees with the rule."""
    rule = _create(budget_world)
    base: dict[str, Any] = {
        "installation_id": budget_world.installation_id,
        "residence_id": budget_world.residence_id,
        "recurrence_id": rule.id,
        "account_id": rule.account_id,
        "owner_operator_id": budget_world.owner_id,
        "result_effect": "EXPENSE",
        "currency": "BRL",
        "frequency": "MONTHLY",
        "start_date": rule.start_date,
        "day_of_month": 10,
        "end_date": None,
        "status": "ACTIVE",
        "actor_operator_id": budget_world.owner_id,
        "recorded_at": rule.updated_at,
    }
    for version, description, amount in (
        (1, "Internet", Decimal("120")),  # duplicate of the existing revision 1
        (2, "Internet", Decimal("120")),  # the rule is still version 1
        (1, "Other text", Decimal("120")),
        (1, "Internet", Decimal("121")),
    ):
        with pytest.raises(DBAPIError):
            with budget_world.engine.begin() as connection:
                connection.execute(
                    insert(_REVISIONS).values(
                        **base,
                        version=version,
                        description=description,
                        expected_amount=amount,
                    )
                )
    assert _raw_versions(budget_world, rule) == [1]


def test_the_database_refuses_to_extend_a_history_with_a_gap(
    budget_world: BudgetWorld,
) -> None:
    """If an earlier revision were ever lost, the next edit fails instead of hiding it."""
    rule = _create(budget_world)
    _replace(budget_world, rule, 1, description="B")
    with budget_world.engine.begin() as connection:  # privileged repair gone wrong
        connection.execute(
            delete(_REVISIONS).where(
                _REVISIONS.c.recurrence_id == rule.id, _REVISIONS.c.version == 2
            )
        )
    with pytest.raises(FinancialRecurrenceConflictError):
        _replace(budget_world, rule, 2, description="C")
    current = _store(budget_world).get_recurrence(
        **budget_world.scope(), recurrence_id=rule.id
    )
    assert current.version == 2 and current.description == "B"
    assert _raw_versions(budget_world, rule) == [1]
