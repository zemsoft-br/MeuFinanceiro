from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Barrier
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
    FinancialMovementReversalDraft,
    FinancialResultEffect,
    FinancialTransferDraft,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
    new_financial_resource_id,
)
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.financial_category_store import FinancialCategoryStore
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
    financial_movement_allocations,
)
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationCategoryNotFoundError,
    FinancialMovementAllocationConflictError,
    FinancialMovementAllocationMovementNotFoundError,
    FinancialMovementAllocationStore,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_transfer_store import FinancialTransferStore
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

_NOW = datetime(2026, 8, 17, 3, 0, tzinfo=UTC)


def _household(engine: Engine) -> tuple[UUID, UUID, UUID, UUID]:
    installation_id = uuid4()
    residence_id = uuid4()
    owner_id = uuid4()
    member_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(identity_installation).values(
                singleton=True,
                id=installation_id,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        connection.execute(
            insert(household_residences).values(
                id=residence_id,
                installation_id=installation_id,
                name="Synthetic allocation residence",
                status="active",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        for index, (operator_id, role) in enumerate(
            ((owner_id, "owner"), (member_id, "member"))
        ):
            connection.execute(
                insert(identity_operators).values(
                    id=operator_id,
                    installation_id=installation_id,
                    login_name=f"allocation-{index}",
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
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    role=role,
                    status="active",
                    is_primary=index == 0,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
    return installation_id, residence_id, owner_id, member_id


def _account(
    runtime_engine: Engine,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    scope: FinancialVisibilityScope = FinancialVisibilityScope.PERSONAL,
    name: str = "Synthetic allocation account",
) -> UUID:
    return (
        FinancialAccountStore(runtime_engine)
        .create_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            draft=FinancialAccountDraft(
                name=name,
                currency="BRL",
                account_type=FinancialAccountType.CHECKING,
                visibility_scope=scope,
            ),
        )
        .id
    )


def _category(
    runtime_engine: Engine,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    scope: FinancialVisibilityScope,
    name: str,
) -> UUID:
    return (
        FinancialCategoryStore(runtime_engine)
        .create_category(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            draft=FinancialCategoryDraft(
                name=name,
                visibility_scope=scope,
            ),
        )
        .id
    )


def _movement(
    runtime_engine: Engine,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    account_id: UUID,
    amount: str = "-100.00",
) -> UUID:
    effect = (
        FinancialResultEffect.INCOME
        if Decimal(amount) > 0
        else FinancialResultEffect.EXPENSE
    )
    return (
        FinancialMovementStore(runtime_engine)
        .create_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementDraft(
                account_id=account_id,
                amount=Money(Decimal(amount), "BRL"),
                result_effect=effect,
                effective_date=date(2026, 8, 17),
                competence_date=date(2026, 8, 1),
                description="Synthetic allocation Movement",
            ),
        )
        .id
    )


def _set_context(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> None:
    connection.execute(
        select(
            func.set_config(
                "app.current_installation_id",
                str(installation_id),
                True,
            ),
            func.set_config(
                "app.current_residence_id",
                str(residence_id),
                True,
            ),
            func.set_config(
                "app.current_operator_id",
                str(operator_id),
                True,
            ),
        )
    )


def _count(engine: Engine, table: object) -> int:
    with engine.begin() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    assert isinstance(value, int)
    return value


def test_create_simple_classification_replays_without_touching_movement(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    movement_id = _movement(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
    )
    category_id = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        scope=FinancialVisibilityScope.PERSONAL,
        name="Mercado",
    )
    store = FinancialMovementAllocationStore(runtime_engine)
    key = new_financial_idempotency_key()
    draft = FinancialMovementAllocationSetDraft(
        movement_id=movement_id,
        allocations=(
            FinancialMovementAllocationDraft(
                category_id=category_id,
                amount=Money(Decimal("-100.00"), "BRL"),
            ),
        ),
    )

    created = store.create_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=key,
        draft=draft,
    )
    replay = store.create_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=key,
        draft=draft,
    )

    assert replay == created
    assert created.revision == 1
    assert created.supersedes_id is None
    assert created.allocations[0].amount == Money(Decimal("-100.00"), "BRL")
    assert store.get_current_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        movement_id=movement_id,
    ) == created
    assert _count(engine, financial_movements) == 1
    assert _count(engine, financial_movement_allocation_sets) == 1
    assert _count(engine, financial_movement_allocations) == 1


def test_split_revision_is_append_only_and_history_is_linear(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    movement_id = _movement(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
    )
    first_category = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        scope=FinancialVisibilityScope.PERSONAL,
        name="Mercado",
    )
    second_category = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
        name="Casa",
    )
    store = FinancialMovementAllocationStore(runtime_engine)
    first = store.create_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationSetDraft(
            movement_id=movement_id,
            allocations=(
                FinancialMovementAllocationDraft(
                    first_category,
                    Money(Decimal("-100"), "BRL"),
                ),
            ),
        ),
    )

    revised = store.revise_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationRevisionDraft(
            movement_id=movement_id,
            supersedes_id=first.id,
            allocations=(
                FinancialMovementAllocationDraft(
                    first_category,
                    Money(Decimal("-70"), "BRL"),
                ),
                FinancialMovementAllocationDraft(
                    second_category,
                    Money(Decimal("-30"), "BRL"),
                ),
            ),
        ),
    )

    assert revised.revision == 2
    assert revised.supersedes_id == first.id
    assert sum(item.amount.amount for item in revised.allocations) == Decimal("-100")
    history = store.list_allocation_history(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        movement_id=movement_id,
    )
    assert history == (first, revised)
    assert _count(engine, financial_movement_allocation_sets) == 2
    assert _count(engine, financial_movement_allocations) == 3
    assert _count(engine, financial_movements) == 1


def test_total_currency_and_idempotency_conflicts_fail_closed(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    movement_id = _movement(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
    )
    category_id = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
        name="Casa",
    )
    store = FinancialMovementAllocationStore(runtime_engine)

    with pytest.raises(FinancialMovementAllocationConflictError):
        store.create_allocation_set(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementAllocationSetDraft(
                movement_id=movement_id,
                allocations=(
                    FinancialMovementAllocationDraft(
                        category_id,
                        Money(Decimal("-90"), "BRL"),
                    ),
                ),
            ),
        )

    with pytest.raises(FinancialMovementAllocationConflictError):
        store.create_allocation_set(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementAllocationSetDraft(
                movement_id=movement_id,
                allocations=(
                    FinancialMovementAllocationDraft(
                        category_id,
                        Money(Decimal("-100"), "USD"),
                    ),
                ),
            ),
        )

    key = new_financial_idempotency_key()
    valid = FinancialMovementAllocationSetDraft(
        movement_id=movement_id,
        allocations=(
            FinancialMovementAllocationDraft(
                category_id,
                Money(Decimal("-100"), "BRL"),
            ),
        ),
    )
    store.create_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=key,
        draft=valid,
    )
    other_category = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
        name="Outro",
    )
    with pytest.raises(FinancialMovementAllocationConflictError):
        store.create_allocation_set(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=key,
            draft=FinancialMovementAllocationSetDraft(
                movement_id=movement_id,
                allocations=(
                    FinancialMovementAllocationDraft(
                        other_category,
                        Money(Decimal("-100"), "BRL"),
                    ),
                ),
            ),
        )


def test_category_status_and_audience_are_fail_closed(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
    )
    movement_id = _movement(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
    )
    member_personal = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
        scope=FinancialVisibilityScope.PERSONAL,
        name="Privada do membro",
    )
    disabled = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
        name="Desabilitada",
    )
    with engine.begin() as connection:
        connection.execute(
            update(financial_categories)
            .where(financial_categories.c.id == disabled)
            .values(
                status="DISABLED",
                disabled_at=func.transaction_timestamp(),
                updated_at=func.transaction_timestamp(),
            )
        )

    store = FinancialMovementAllocationStore(runtime_engine)
    for category_id in (member_personal, disabled):
        with pytest.raises(FinancialMovementAllocationCategoryNotFoundError):
            store.create_allocation_set(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
                idempotency_key=new_financial_idempotency_key(),
                draft=FinancialMovementAllocationSetDraft(
                    movement_id=movement_id,
                    allocations=(
                        FinancialMovementAllocationDraft(
                            category_id,
                            Money(Decimal("-100"), "BRL"),
                        ),
                    ),
                ),
            )

    household = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
        name="Compartilhada",
    )
    created = store.create_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationSetDraft(
            movement_id=movement_id,
            allocations=(
                FinancialMovementAllocationDraft(
                    household,
                    Money(Decimal("-100"), "BRL"),
                ),
            ),
        ),
    )
    assert created.revision == 1


def test_neutral_and_reversal_movements_are_not_classifiable(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _household(engine)
    source = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        name="Origem",
    )
    destination = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        name="Destino",
    )
    transfer = FinancialTransferStore(runtime_engine).create_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialTransferDraft(
            source_account_id=source,
            destination_account_id=destination,
            magnitude=Money(Decimal("20"), "BRL"),
            effective_date=date(2026, 8, 17),
            competence_date=date(2026, 8, 1),
            description="Synthetic neutral transfer",
        ),
    )
    category = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
        name="Casa",
    )
    store = FinancialMovementAllocationStore(runtime_engine)

    with pytest.raises(FinancialMovementAllocationMovementNotFoundError):
        store.create_allocation_set(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementAllocationSetDraft(
                movement_id=transfer.source_movement_id,
                allocations=(
                    FinancialMovementAllocationDraft(
                        category,
                        Money(Decimal("-20"), "BRL"),
                    ),
                ),
            ),
        )

    standard_id = _movement(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=source,
        amount="-10",
    )
    reversal = FinancialMovementStore(runtime_engine).reverse_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=standard_id,
            effective_date=date(2026, 8, 18),
            competence_date=date(2026, 8, 1),
            reason="Synthetic reversal",
        ),
    )
    with pytest.raises(FinancialMovementAllocationMovementNotFoundError):
        store.create_allocation_set(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementAllocationSetDraft(
                movement_id=reversal.id,
                allocations=(
                    FinancialMovementAllocationDraft(
                        category,
                        Money(Decimal("10"), "BRL"),
                    ),
                ),
            ),
        )


def test_concurrent_revisions_cannot_fork(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    movement_id = _movement(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
    )
    categories = tuple(
        _category(
            runtime_engine,
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            scope=FinancialVisibilityScope.HOUSEHOLD,
            name=f"Categoria {index}",
        )
        for index in range(3)
    )
    store = FinancialMovementAllocationStore(runtime_engine)
    first = store.create_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationSetDraft(
            movement_id=movement_id,
            allocations=(
                FinancialMovementAllocationDraft(
                    categories[0],
                    Money(Decimal("-100"), "BRL"),
                ),
            ),
        ),
    )
    barrier = Barrier(2)

    def revise(index: int) -> object:
        barrier.wait(timeout=5)
        return FinancialMovementAllocationStore(runtime_engine).revise_allocation_set(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementAllocationRevisionDraft(
                movement_id=movement_id,
                supersedes_id=first.id,
                allocations=(
                    FinancialMovementAllocationDraft(
                        categories[index + 1],
                        Money(Decimal("-100"), "BRL"),
                    ),
                ),
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(revise, index) for index in range(2))
        outcomes: list[object] = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10))
            except FinancialMovementAllocationConflictError as error:
                outcomes.append(error)

    assert sum(
        not isinstance(item, FinancialMovementAllocationConflictError)
        for item in outcomes
    ) == 1
    assert _count(engine, financial_movement_allocation_sets) == 2


def test_direct_sql_cannot_append_share_to_committed_set(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    movement_id = _movement(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
    )
    first_category = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
        name="Primeira",
    )
    extra_category = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
        name="Extra",
    )
    created = FinancialMovementAllocationStore(runtime_engine).create_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationSetDraft(
            movement_id=movement_id,
            allocations=(
                FinancialMovementAllocationDraft(
                    first_category,
                    Money(Decimal("-100"), "BRL"),
                ),
            ),
        ),
    )

    with pytest.raises(IntegrityError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )
            connection.execute(
                insert(financial_movement_allocations).values(
                    id=new_financial_resource_id(),
                    allocation_set_id=created.id,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    movement_id=movement_id,
                    category_id=extra_category,
                    currency="BRL",
                    amount=Decimal("-1"),
                    created_at=func.transaction_timestamp(),
                )
            )

    assert _count(engine, financial_movement_allocations) == 1
