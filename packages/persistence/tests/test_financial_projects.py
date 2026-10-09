"""PostgreSQL v1 project store tests: serialized links and canonical ledger."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import date
from decimal import Decimal
from threading import Barrier
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialProjectDraft,
    FinancialProjectLinkRevisionDraft,
    FinancialProjectReplacement,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
    summarize_project,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_project_schema import (
    financial_project_link_revisions,
    financial_projects,
)
from meufinanceiro_persistence.financial_project_store import (
    FinancialProjectAccessError,
    FinancialProjectConflictError,
    FinancialProjectNotEditableError,
    FinancialProjectNotFoundError,
    FinancialProjectStore,
)

if TYPE_CHECKING:
    from conftest import BudgetWorld

HOUSEHOLD = FinancialVisibilityScope.HOUSEHOLD
PERSONAL = FinancialVisibilityScope.PERSONAL
_DAY = date(2026, 10, 8)


def _draft(
    scope: FinancialVisibilityScope = HOUSEHOLD,
    title: str = "Reforma",
    amount: str = "1000",
) -> FinancialProjectDraft:
    return FinancialProjectDraft(
        title=title,
        description=None,
        visibility_scope=scope,
        planned=Money(Decimal(amount), "BRL"),
        target_date=None,
    )


def _new(
    world: BudgetWorld,
    *,
    scope: FinancialVisibilityScope = HOUSEHOLD,
    title: str = "Reforma",
    operator_id: UUID | None = None,
    key: UUID | None = None,
) -> UUID:
    return (
        FinancialProjectStore(world.runtime)
        .create_project(
            **world.scope(operator_id),
            idempotency_key=key or new_financial_idempotency_key(),
            draft=_draft(scope, title),
        )
        .id
    )


def _expense(
    world: BudgetWorld,
    account_id: UUID,
    amount: str = "90",
) -> UUID:
    return (
        FinancialMovementStore(world.runtime)
        .create_movement(
            **world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementDraft(
                account_id=account_id,
                amount=Money(Decimal("-" + amount), "BRL"),
                result_effect=FinancialResultEffect.EXPENSE,
                effective_date=_DAY,
                competence_date=_DAY,
                description="Material de obra",
            ),
        )
        .id
    )


def _link(
    world: BudgetWorld,
    movement_id: UUID,
    project_id: UUID | None,
    *,
    prev: UUID | None = None,
    key: UUID | None = None,
    operator_id: UUID | None = None,
):
    return FinancialProjectStore(world.runtime).revise_link(
        **world.scope(operator_id),
        idempotency_key=key or new_financial_idempotency_key(),
        draft=FinancialProjectLinkRevisionDraft(
            movement_id=movement_id,
            project_id=project_id,
            expected_predecessor_id=prev,
        ),
    )


def _summary(world: BudgetWorld, project_id: UUID, operator_id: UUID | None = None):
    result = FinancialProjectStore(world.runtime).read_project_facts(
        **world.scope(operator_id),
        project_id=project_id,
    )
    return summarize_project(*result)


def _count(world: BudgetWorld, table):
    with world.engine.begin() as conn:
        return conn.scalar(select(func.count()).select_from(table))


def test_project_create_replay_cas_scope_and_no_ledger_writes(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    store = FinancialProjectStore(world.runtime)
    key = new_financial_idempotency_key()
    original = store.create_project(
        **world.scope(), idempotency_key=key, draft=_draft()
    )
    replay = store.create_project(**world.scope(), idempotency_key=key, draft=_draft())
    assert replay.id == original.id
    assert _count(world, financial_projects) == 1
    assert _count(world, financial_movements) == 0
    with pytest.raises(FinancialProjectConflictError):
        store.create_project(
            **world.scope(),
            idempotency_key=key,
            draft=_draft(title="Outro projeto"),
        )
    edited = store.replace_project(
        **world.scope(),
        project_id=original.id,
        replacement=FinancialProjectReplacement(
            expected_version=1,
            title="Reforma nova",
            description=None,
            planned=Money(Decimal("1200"), "BRL"),
            target_date=None,
        ),
    )
    assert edited.version == 2
    with pytest.raises(FinancialProjectConflictError):
        store.replace_project(
            **world.scope(),
            project_id=original.id,
            replacement=FinancialProjectReplacement(
                expected_version=1,
                title="Stale",
                description=None,
                planned=Money(Decimal("1200"), "BRL"),
                target_date=None,
            ),
        )
    assert (
        store.get_project(**world.scope(world.member_id), project_id=original.id).title
        == "Reforma nova"
    )
    with pytest.raises(FinancialProjectNotEditableError):
        store.replace_project(
            **world.scope(world.member_id),
            project_id=original.id,
            replacement=FinancialProjectReplacement(
                expected_version=2,
                title="Inválido",
                description=None,
                planned=Money(Decimal("1200"), "BRL"),
                target_date=None,
            ),
        )
    private_id = _new(world, scope=PERSONAL)
    assert {p.id for p in store.list_projects(**world.scope(world.member_id))} == {
        original.id
    }
    with pytest.raises(FinancialProjectNotFoundError):
        store.get_project(**world.scope(world.member_id), project_id=private_id)
    with pytest.raises(FinancialProjectAccessError):
        store.list_projects(**world.scope(world.outsider_id))


def test_link_replay_reassign_unlink_and_canonical_reversal(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account = world.account()
    first_project = _new(world, title="Primeiro")
    second_project = _new(world, title="Segundo")
    expense_id = _expense(world, account, "125")
    assert _summary(world, first_project).realized.amount == 0

    first_key = new_financial_idempotency_key()
    first = _link(world, expense_id, first_project, key=first_key)
    assert _link(world, expense_id, first_project, key=first_key).id == first.id
    assert _summary(world, first_project).realized.amount == 125
    with pytest.raises(FinancialProjectConflictError):
        _link(world, expense_id, second_project, key=first_key)
    with pytest.raises(FinancialProjectConflictError):
        _link(world, expense_id, second_project)
    moved = _link(world, expense_id, second_project, prev=first.id)
    assert moved.revision == 2
    assert _summary(world, first_project).realized.amount == 0
    assert _summary(world, second_project).realized.amount == 125
    assert _summary(world, second_project, world.member_id).realized.amount == 125

    reversal = FinancialMovementStore(world.runtime).reverse_movement(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=expense_id,
            effective_date=_DAY,
            competence_date=_DAY,
            reason="Reembolso integral",
        ),
    )
    assert reversal.reversal_of_id == expense_id
    assert _summary(world, second_project).realized.amount == 0
    assert _count(world, financial_movements) == 2
    unlinked = _link(world, expense_id, None, prev=moved.id)
    assert unlinked.revision == 3
    assert _summary(world, first_project).expense_count == 0
    assert _summary(world, second_project).expense_count == 0
    assert _count(world, financial_project_link_revisions) == 3
    assert (
        FinancialProjectStore(world.runtime)
        .get_link(
            **world.scope(),
            movement_id=expense_id,
        )
        .project_id
        is None
    )
    assert _count(world, financial_movements) == 2


def test_returning_to_original_project_counts_only_the_current_link(
    budget_world: BudgetWorld,
) -> None:
    """A -> B -> A must realize A once, not twice from its historical links."""
    world = budget_world
    account = world.account()
    first_project = _new(world, title="Pintura")
    second_project = _new(world, title="Móveis")
    expense_id = _expense(world, account, "140")

    first = _link(world, expense_id, first_project)
    second = _link(world, expense_id, second_project, prev=first.id)
    third = _link(world, expense_id, first_project, prev=second.id)

    first_summary = _summary(world, first_project)
    second_summary = _summary(world, second_project)
    assert first_summary.expense_count == 1
    assert first_summary.realized.amount == Decimal("140")
    assert second_summary.expense_count == 0
    assert second_summary.realized.amount == 0
    assert (
        FinancialProjectStore(world.runtime)
        .get_link(
            **world.scope(),
            movement_id=expense_id,
        )
        .id
        == third.id
    )
    history = FinancialProjectStore(world.runtime).read_link_history(
        **world.scope(),
        movement_id=expense_id,
    )
    assert [event.revision for event in history] == [1, 2, 3]
    assert [event.project_id for event in history] == [
        first_project,
        second_project,
        first_project,
    ]


def test_original_link_key_replays_after_unlink_and_account_archive(
    budget_world: BudgetWorld,
) -> None:
    """Replay remains historical even after mutable eligibility changes."""
    world = budget_world
    account = world.account()
    project_id = _new(world)
    expense_id = _expense(world, account, "30")
    original_key = new_financial_idempotency_key()
    first = _link(world, expense_id, project_id, key=original_key)
    _link(world, expense_id, None, prev=first.id)
    world.archive_account(account)

    replay = _link(world, expense_id, project_id, key=original_key)
    assert replay.id == first.id
    assert replay.revision == 1
    current = FinancialProjectStore(world.runtime).get_link(
        **world.scope(),
        movement_id=expense_id,
    )
    assert current is not None
    assert current.revision == 2
    assert current.project_id is None
    assert _count(world, financial_project_link_revisions) == 2
    assert _summary(world, project_id).realized.amount == 0

    with pytest.raises(FinancialProjectConflictError):
        _link(
            world,
            expense_id,
            project_id,
            key=original_key,
            prev=first.id,
        )


def test_reversal_before_project_link_has_zero_realized(
    budget_world: BudgetWorld,
) -> None:
    """Canonical reversal before LINK still cancels exactly one expense."""
    world = budget_world
    account = world.account()
    project_id = _new(world)
    expense_id = _expense(world, account, "175")
    original = FinancialMovementStore(world.runtime)
    reverse = original.reverse_movement(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=expense_id,
            effective_date=_DAY,
            competence_date=_DAY,
            reason="Estorno anterior ao projeto",
        ),
    )
    assert reverse.reversal_of_id == expense_id
    _link(world, expense_id, project_id)
    summary = _summary(world, project_id)
    assert summary.realized.amount == 0
    assert summary.expense_count == 1
    assert _count(world, financial_movements) == 2


def test_outsider_cannot_read_project_link_or_its_history(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account = world.account()
    project_id = _new(world)
    expense_id = _expense(world, account)
    _link(world, expense_id, project_id)
    store = FinancialProjectStore(world.runtime)
    with pytest.raises(FinancialProjectAccessError):
        store.get_link(
            **world.scope(world.outsider_id),
            movement_id=expense_id,
        )
    with pytest.raises(FinancialProjectAccessError):
        store.read_link_history(
            **world.scope(world.outsider_id),
            movement_id=expense_id,
        )


def test_archiving_serializes_against_new_project_link(
    budget_world: BudgetWorld,
) -> None:
    """An ARCHIVED transition wins only before the subsequent LINK validates.

    Archive happens in a privileged transaction, as the product has no public
    archive API. Its DB trigger holds the same advisory lock as the LINK insert
    trigger; the loser must recheck ACTIVE rather than write from a stale read.
    """
    world = budget_world
    account = world.account()
    project_id = _new(world)
    movement_id = _expense(world, account)
    account_lock = "meufinanceiro:project-account:" + str(account)
    with ThreadPoolExecutor(max_workers=1) as workers:
        with world.engine.begin() as archiver:
            archiver.execute(
                update(financial_accounts)
                .where(financial_accounts.c.id == account)
                .values(
                    status="ARCHIVED",
                    archived_at=func.transaction_timestamp(),
                    updated_at=func.transaction_timestamp(),
                )
            )
            # Prove the archive writer actually holds the database guard.
            with world.engine.connect() as probe:
                free = probe.scalar(
                    select(
                        func.pg_try_advisory_xact_lock(
                            func.hashtextextended(account_lock, 0)
                        )
                    )
                )
                assert free is False
            future = workers.submit(_link, world, movement_id, project_id)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=0.15)
        # The archive commit releases the lock. A newer LINK must now observe
        # archived status and cannot create an historical first association.
        with pytest.raises(FinancialProjectConflictError):
            future.result(timeout=15)
    assert _count(world, financial_project_link_revisions) == 0
    assert _summary(world, project_id).realized.amount == 0


def test_project_link_audience_and_archived_unlink(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    household_project = _new(world)
    personal_project = _new(world, scope=PERSONAL)
    household_account = world.account()
    personal_account = world.account(household=False)
    house_expense = _expense(world, household_account)
    # Personal account is not eligible for a HOUSEHOLD project.
    personal_expense = _expense(world, personal_account)
    with pytest.raises(FinancialProjectConflictError):
        _link(world, personal_expense, household_project)
    with pytest.raises(FinancialProjectConflictError):
        _link(world, house_expense, personal_project)
    first = _link(world, house_expense, household_project)
    with pytest.raises(FinancialProjectNotEditableError):
        _link(
            world,
            house_expense,
            household_project,
            prev=first.id,
            operator_id=world.member_id,
        )
    world.archive_account(household_account)
    with pytest.raises(FinancialProjectConflictError):
        _link(world, house_expense, personal_project, prev=first.id)
    _link(world, house_expense, None, prev=first.id)
    assert _summary(world, household_project).expense_count == 0


def test_current_project_link_query_is_indexable_and_has_no_history_window(
    budget_world: BudgetWorld,
) -> None:
    """EXPLAIN ANALYZE on PG18.4 + FORCE RLS: project-first candidate index.

    This is a plan-shape proof, not a latency benchmark. seqscan is disabled
    only to prove the intended index is usable on a deliberately tiny fixture;
    no production planner settings are changed.
    """
    from meufinanceiro_persistence.financial_movement_store import _set_context

    world = budget_world
    account = world.account()
    project_id = _new(world)
    another = _new(world, title="Outro")
    expense_id = _expense(world, account, "45")
    first = _link(world, expense_id, another)
    current = _link(world, expense_id, project_id, prev=first.id)
    # Exercise project-first candidates with dozens of historical entries:
    # a previous project id alone is not evidence that a link remains current.
    for _ in range(40):
        moved = _link(world, expense_id, another, prev=current.id)
        current = _link(world, expense_id, project_id, prev=moved.id)
    assert current.revision == 82

    query = text(
        "EXPLAIN (FORMAT JSON, ANALYZE, BUFFERS) "
        "SELECT h.movement_id "
        "FROM finance.project_movement_link_revisions AS h "
        "WHERE h.installation_id = :installation_id "
        "AND h.residence_id = :residence_id "
        "AND h.project_id = :project_id "
        "AND NOT EXISTS ("
        "SELECT 1 FROM finance.project_movement_link_revisions AS successor "
        "WHERE successor.supersedes_id = h.id"
        ") ORDER BY h.movement_id LIMIT 1001"
    )
    with world.runtime.connect() as conn:
        with conn.begin():
            _set_context(conn, **world.scope())
            conn.execute(text("SET LOCAL enable_seqscan = off"))
            explained = conn.execute(
                query,
                {**world.scope(), "project_id": project_id},
            ).scalar_one()

    assert isinstance(explained, list) and len(explained) == 1
    root = explained[0]["Plan"]

    def flatten(node: dict[str, object]) -> list[dict[str, object]]:
        result = [node]
        for child in node.get("Plans", []):
            result.extend(flatten(child))
        return result

    nodes = flatten(root)
    assert not any(node["Node Type"] == "WindowAgg" for node in nodes)
    assert any(
        node.get("Index Name") == "ix_finance_project_links_project"
        for node in nodes
    ), nodes
    assert root["Actual Rows"] == 1
    assert _summary(world, project_id).realized.amount == 45


def test_same_movement_two_projects_concurrent_first_link_only_one_wins(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account = world.account()
    expense_id = _expense(world, account, "100")
    projects = (_new(world, title="A"), _new(world, title="B"))
    barrier = Barrier(2)

    def attempt(project_id: UUID) -> str:
        barrier.wait(timeout=15)
        try:
            _link(world, expense_id, project_id)
        except FinancialProjectConflictError:
            return "CONFLICT"
        return "CREATED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        output = list(pool.map(attempt, projects))
    assert sorted(output) == ["CONFLICT", "CREATED"]
    assert _count(world, financial_project_link_revisions) == 1
    assert sum(_summary(world, p).realized.amount for p in projects) == 100


def test_same_key_concurrent_requests_return_the_same_link(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account = world.account()
    expense_id = _expense(world, account)
    project_id = _new(world)
    key = new_financial_idempotency_key()
    barrier = Barrier(4)

    def attempt(_: int) -> UUID:
        barrier.wait(timeout=15)
        return _link(world, expense_id, project_id, key=key).id

    with ThreadPoolExecutor(max_workers=4) as pool:
        links = list(pool.map(attempt, range(4)))
    assert len(set(links)) == 1
    assert _count(world, financial_project_link_revisions) == 1


def test_bad_link_insert_is_denied_even_when_client_bypasses_store(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account = world.account()
    expense_id = _expense(world, account)
    project_id = _new(world)
    first = _link(world, expense_id, project_id)
    from meufinanceiro_persistence.financial_movement_store import _set_context

    with pytest.raises(DBAPIError):
        with world.runtime.begin() as conn:
            _set_context(conn, **world.scope())
            conn.execute(
                financial_project_link_revisions.update()
                .where(financial_project_link_revisions.c.id == first.id)
                .values(project_id=uuid4())
            )
