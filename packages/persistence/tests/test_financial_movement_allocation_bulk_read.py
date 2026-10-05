"""Bulk current-allocation read path: current-only, RLS-scoped, constant round trips."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountType,
    FinancialCategoryDraft,
    FinancialMovementAllocationDraft,
    FinancialMovementAllocationRevisionDraft,
    FinancialMovementAllocationSetDraft,
    FinancialMovementDraft,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import event, insert
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_category_store import FinancialCategoryStore
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationAccessError,
    FinancialMovementAllocationAccountNotFoundError,
    FinancialMovementAllocationConflictError,
    FinancialMovementAllocationInvalidShapeError,
    FinancialMovementAllocationPersistenceError,
    FinancialMovementAllocationStore,
)
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

_NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)


class _Scope:
    def __init__(self, engine: Engine) -> None:
        self.installation_id = uuid4()
        self.residence_id = uuid4()
        self.owner_id = uuid4()
        self.member_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                insert(identity_installation).values(
                    singleton=True,
                    id=self.installation_id,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            connection.execute(
                insert(household_residences).values(
                    id=self.residence_id,
                    installation_id=self.installation_id,
                    name="Synthetic bulk-read residence",
                    status="active",
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            for index, (operator_id, role) in enumerate(
                ((self.owner_id, "owner"), (self.member_id, "member"))
            ):
                connection.execute(
                    insert(identity_operators).values(
                        id=operator_id,
                        installation_id=self.installation_id,
                        login_name=f"bulk-read-{index}",
                        password_hash="synthetic-password-hash-material-000000000000",
                        role="installation_admin",
                        status="active",
                        failed_attempts=0,
                        locked_until=None,
                        last_authenticated_at=None,
                        password_changed_at=_NOW,
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )
                connection.execute(
                    insert(household_memberships).values(
                        id=uuid4(),
                        installation_id=self.installation_id,
                        residence_id=self.residence_id,
                        operator_id=operator_id,
                        role=role,
                        status="active",
                        is_primary=index == 0,
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )

    def scope(self, operator_id: UUID | None = None) -> dict[str, UUID]:
        return {
            "installation_id": self.installation_id,
            "residence_id": self.residence_id,
            "operator_id": operator_id or self.owner_id,
        }


def _account(
    engine: Engine, scope: _Scope, visibility: FinancialVisibilityScope
) -> UUID:
    return (
        FinancialAccountStore(engine)
        .create_account(
            **scope.scope(),
            draft=FinancialAccountDraft(
                name="Synthetic bulk account",
                currency="BRL",
                account_type=FinancialAccountType.CHECKING,
                visibility_scope=visibility,
            ),
        )
        .id
    )


def _category(engine: Engine, scope: _Scope) -> UUID:
    return (
        FinancialCategoryStore(engine)
        .create_category(
            **scope.scope(),
            draft=FinancialCategoryDraft(
                name=f"Cat {uuid4().hex[:6]}",
                visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
            ),
        )
        .id
    )


def _expense(
    engine: Engine, scope: _Scope, account_id: UUID, day: int, amount: str = "-10.00"
) -> UUID:
    return (
        FinancialMovementStore(engine)
        .create_movement(
            **scope.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementDraft(
                account_id=account_id,
                amount=Money(Decimal(amount), "BRL"),
                result_effect=FinancialResultEffect.EXPENSE,
                effective_date=date(2026, 9, day),
                competence_date=date(2026, 9, day),
                description="Synthetic bulk Movement",
            ),
        )
        .id
    )


def _share(category_id: UUID, amount: str) -> FinancialMovementAllocationDraft:
    return FinancialMovementAllocationDraft(
        category_id=category_id, amount=Money(Decimal(amount), "BRL")
    )


def _classify(
    engine: Engine, scope: _Scope, movement_id: UUID, *shares: tuple[UUID, str]
) -> Any:
    return FinancialMovementAllocationStore(engine).create_allocation_set(
        **scope.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationSetDraft(
            movement_id=movement_id,
            allocations=tuple(_share(c, a) for c, a in shares),
        ),
    )


def _bulk(
    engine: Engine,
    scope: _Scope,
    account_id: UUID,
    operator_id: UUID | None = None,
) -> Any:
    return FinancialMovementAllocationStore(engine).list_current_allocation_sets(
        **scope.scope(operator_id), account_id=account_id
    )


def test_bulk_returns_current_versions_only_in_movement_order(
    engine: Engine, runtime_engine: Engine
) -> None:
    scope = _Scope(engine)
    account = _account(runtime_engine, scope, FinancialVisibilityScope.PERSONAL)
    other_account = _account(runtime_engine, scope, FinancialVisibilityScope.PERSONAL)
    first_cat, second_cat = (
        _category(runtime_engine, scope),
        _category(runtime_engine, scope),
    )
    late = _expense(runtime_engine, scope, account, 25, "-30.00")
    early = _expense(runtime_engine, scope, account, 5, "-10.00")
    untouched = _expense(runtime_engine, scope, account, 15)
    foreign_account_movement = _expense(runtime_engine, scope, other_account, 6)
    _classify(runtime_engine, scope, late, (first_cat, "-30.00"))
    early_v1 = _classify(runtime_engine, scope, early, (first_cat, "-10.00"))
    _classify(runtime_engine, scope, foreign_account_movement, (first_cat, "-10.00"))
    early_v2 = FinancialMovementAllocationStore(runtime_engine).revise_allocation_set(
        **scope.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationRevisionDraft(
            movement_id=early,
            supersedes_id=early_v1.id,
            allocations=(_share(first_cat, "-4.00"), _share(second_cat, "-6.00")),
        ),
    )

    records = _bulk(runtime_engine, scope, account)

    assert [record.movement_id for record in records] == [early, late]
    assert untouched not in {record.movement_id for record in records}
    assert records[0].id == early_v2.id
    assert records[0].revision == 2
    assert early_v1.id not in {record.id for record in records}
    assert [item.category_id for item in records[0].allocations] == sorted(
        [first_cat, second_cat]
    )
    assert records[0] == FinancialMovementAllocationStore(
        runtime_engine
    ).get_current_allocation_set(**scope.scope(), movement_id=early)


def test_bulk_issues_a_constant_number_of_statements(
    engine: Engine, runtime_engine: Engine
) -> None:
    scope = _Scope(engine)
    category = _category(runtime_engine, scope)
    small = _account(runtime_engine, scope, FinancialVisibilityScope.PERSONAL)
    large = _account(runtime_engine, scope, FinancialVisibilityScope.PERSONAL)
    for day in range(1, 3):
        _classify(
            runtime_engine,
            scope,
            _expense(runtime_engine, scope, small, day),
            (category, "-10.00"),
        )
    for day in range(1, 21):
        _classify(
            runtime_engine,
            scope,
            _expense(runtime_engine, scope, large, day),
            (category, "-10.00"),
        )

    counts: list[int] = []

    def count(*_args: Any) -> None:
        counts[-1] += 1

    event.listen(runtime_engine, "before_cursor_execute", count)
    try:
        for account in (small, large):
            counts.append(0)
            records = _bulk(runtime_engine, scope, account)
            assert len(records) == (2 if account == small else 20)
    finally:
        event.remove(runtime_engine, "before_cursor_execute", count)

    assert counts[0] == counts[1]
    # context + membership + visible account + one set/shares statement
    assert counts[1] <= 5


def test_bulk_for_empty_account_is_empty(
    engine: Engine, runtime_engine: Engine
) -> None:
    scope = _Scope(engine)
    account = _account(runtime_engine, scope, FinancialVisibilityScope.PERSONAL)
    _expense(runtime_engine, scope, account, 3)

    assert _bulk(runtime_engine, scope, account) == ()


def test_bulk_follows_account_audience_and_membership(
    engine: Engine, runtime_engine: Engine
) -> None:
    scope = _Scope(engine)
    personal = _account(runtime_engine, scope, FinancialVisibilityScope.PERSONAL)
    shared = _account(runtime_engine, scope, FinancialVisibilityScope.HOUSEHOLD)
    category = _category(runtime_engine, scope)
    for account in (personal, shared):
        _classify(
            runtime_engine,
            scope,
            _expense(runtime_engine, scope, account, 4),
            (category, "-10.00"),
        )

    assert len(_bulk(runtime_engine, scope, shared, scope.member_id)) == 1
    with pytest.raises(FinancialMovementAllocationAccountNotFoundError):
        _bulk(runtime_engine, scope, personal, scope.member_id)
    with pytest.raises(FinancialMovementAllocationAccountNotFoundError):
        _bulk(runtime_engine, scope, uuid4(), scope.owner_id)
    with pytest.raises(FinancialMovementAllocationAccessError):
        _bulk(runtime_engine, scope, personal, uuid4())


def test_bulk_is_isolated_between_residences(
    engine: Engine, runtime_engine: Engine
) -> None:
    scope = _Scope(engine)
    account = _account(runtime_engine, scope, FinancialVisibilityScope.HOUSEHOLD)
    _classify(
        runtime_engine,
        scope,
        _expense(runtime_engine, scope, account, 4),
        (_category(runtime_engine, scope), "-10.00"),
    )
    foreign = FinancialMovementAllocationStore(runtime_engine)

    with pytest.raises(FinancialMovementAllocationAccessError):
        foreign.list_current_allocation_sets(
            installation_id=scope.installation_id,
            residence_id=uuid4(),
            operator_id=scope.owner_id,
            account_id=account,
        )


def test_bulk_rejects_non_uuid_arguments(
    engine: Engine, runtime_engine: Engine
) -> None:
    scope = _Scope(engine)
    store = FinancialMovementAllocationStore(runtime_engine)

    with pytest.raises(TypeError):
        store.list_current_allocation_sets(
            installation_id=scope.installation_id,
            residence_id=scope.residence_id,
            operator_id=scope.owner_id,
            account_id="not-a-uuid",  # type: ignore[arg-type]
        )


def test_shape_violations_are_not_conflicts_and_conflicts_are_not_shape_violations(
    engine: Engine, runtime_engine: Engine
) -> None:
    scope = _Scope(engine)
    account = _account(runtime_engine, scope, FinancialVisibilityScope.PERSONAL)
    category = _category(runtime_engine, scope)
    movement = _expense(runtime_engine, scope, account, 4, "-10.00")

    with pytest.raises(FinancialMovementAllocationInvalidShapeError) as shape:
        _classify(runtime_engine, scope, movement, (category, "-9.99"))
    assert not isinstance(shape.value, FinancialMovementAllocationConflictError)
    assert isinstance(shape.value, FinancialMovementAllocationPersistenceError)

    _classify(runtime_engine, scope, movement, (category, "-10.00"))
    with pytest.raises(FinancialMovementAllocationConflictError) as stale:
        _classify(runtime_engine, scope, movement, (category, "-10.00"))
    assert not isinstance(stale.value, FinancialMovementAllocationInvalidShapeError)
    assert isinstance(stale.value, FinancialMovementAllocationPersistenceError)
