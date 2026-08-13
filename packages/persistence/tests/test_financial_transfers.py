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
    FinancialMovementReversalDraft,
    FinancialOpeningBalanceDraft,
    FinancialTransferDraft,
    FinancialTransferRecord,
    FinancialTransferReversalDraft,
    FinancialTransferRole,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine, RowMapping

from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementPersistenceError,
    FinancialMovementStore,
)
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceStore,
)
from meufinanceiro_persistence.financial_transfer_schema import (
    financial_transfer_legs,
    financial_transfers,
)
from meufinanceiro_persistence.financial_transfer_store import (
    FinancialTransferAccessError,
    FinancialTransferAccountNotFoundError,
    FinancialTransferAlreadyReversedError,
    FinancialTransferBeforeOpeningBalanceError,
    FinancialTransferIdempotencyConflictError,
    FinancialTransferNotFoundError,
    FinancialTransferStore,
)
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

NOW = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)


def _create_household(engine: Engine) -> tuple[UUID, UUID, UUID, UUID]:
    installation_id = uuid4()
    residence_id = uuid4()
    owner_id = uuid4()
    member_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(identity_installation).values(
                singleton=True,
                id=installation_id,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            insert(household_residences).values(
                id=residence_id,
                installation_id=installation_id,
                name="Synthetic transfer household",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for index, (operator_id, membership_role) in enumerate(
            ((owner_id, "owner"), (member_id, "member"))
        ):
            connection.execute(
                insert(identity_operators).values(
                    id=operator_id,
                    installation_id=installation_id,
                    login_name=f"transfer-{index}",
                    password_hash="synthetic-password-hash-material-000000000000",
                    role="installation_admin",
                    status="active",
                    failed_attempts=0,
                    locked_until=None,
                    last_authenticated_at=None,
                    password_changed_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            connection.execute(
                insert(household_memberships).values(
                    id=uuid4(),
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    role=membership_role,
                    status="active",
                    is_primary=index == 0,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
    return installation_id, residence_id, owner_id, member_id


def _create_account(
    runtime_engine: Engine,
    *,
    installation_id: UUID,
    residence_id: UUID,
    owner_id: UUID,
    currency: str = "BRL",
    scope: FinancialVisibilityScope = FinancialVisibilityScope.PERSONAL,
    name: str = "Synthetic transfer account",
) -> UUID:
    return (
        FinancialAccountStore(runtime_engine)
        .create_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            draft=FinancialAccountDraft(
                name=name,
                currency=currency,
                account_type=FinancialAccountType.CHECKING,
                visibility_scope=scope,
            ),
        )
        .id
    )


def _draft(
    source_account_id: UUID,
    destination_account_id: UUID,
    *,
    amount: str = "100.00",
    currency: str = "BRL",
    effective_date: date = date(2026, 8, 13),
    description: str = "Transferência sintética",
) -> FinancialTransferDraft:
    return FinancialTransferDraft(
        source_account_id=source_account_id,
        destination_account_id=destination_account_id,
        magnitude=Money(Decimal(amount), currency),
        effective_date=effective_date,
        competence_date=date(2026, 8, 1),
        description=description,
    )


def _counts(engine: Engine) -> tuple[int, int, int]:
    with engine.begin() as connection:
        transfers = connection.scalar(select(func.count()).select_from(financial_transfers))
        legs = connection.scalar(select(func.count()).select_from(financial_transfer_legs))
        movements = connection.scalar(select(func.count()).select_from(financial_movements))
    assert isinstance(transfers, int)
    assert isinstance(legs, int)
    assert isinstance(movements, int)
    return transfers, legs, movements


def _movement_rows(engine: Engine, *movement_ids: UUID) -> list[RowMapping]:
    with engine.begin() as connection:
        return list(
            connection.execute(
                select(financial_movements).where(
                    financial_movements.c.id.in_(movement_ids)
                )
            )
            .mappings()
            .all()
        )


def test_create_transfer_replay_and_two_neutral_legs(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    source_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        name="Origem",
    )
    destination_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        name="Destino",
    )
    store = FinancialTransferStore(runtime_engine)
    key = new_financial_idempotency_key()
    draft = _draft(source_id, destination_id, amount="125.50")

    created = store.create_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=key,
        draft=draft,
    )
    replay = store.create_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=key,
        draft=draft,
    )

    assert replay == created
    assert created.role is FinancialTransferRole.STANDARD
    assert created.source_account_id == source_id
    assert created.destination_account_id == destination_id
    rows = {
        row["id"]: row
        for row in _movement_rows(
            engine,
            created.source_movement_id,
            created.destination_movement_id,
        )
    }
    source = rows[created.source_movement_id]
    destination = rows[created.destination_movement_id]
    assert source["amount"] == Decimal("-125.50000000")
    assert destination["amount"] == Decimal("125.50000000")
    assert source["result_effect"] == destination["result_effect"] == "NEUTRAL"
    assert source["role"] == destination["role"] == "STANDARD"
    assert _counts(engine) == (1, 2, 2)

    with pytest.raises(FinancialTransferIdempotencyConflictError):
        store.create_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=key,
            draft=_draft(source_id, destination_id, amount="126.00"),
        )
    assert _counts(engine) == (1, 2, 2)


def test_transfer_requires_owner_of_both_accounts_and_same_currency(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)
    source_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    member_account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=member_id,
        name="Conta do membro",
    )
    usd_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        currency="USD",
        name="Conta USD",
    )
    store = FinancialTransferStore(runtime_engine)

    with pytest.raises(FinancialTransferAccountNotFoundError):
        store.create_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(source_id, member_account_id),
        )

    with pytest.raises(FinancialTransferAccountNotFoundError):
        store.create_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(source_id, usd_id),
        )

    assert _counts(engine) == (0, 0, 0)


def test_destination_opening_anchor_rolls_back_claim_source_leg_and_links(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    source_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    destination_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    FinancialOpeningBalanceStore(runtime_engine).create_opening_balance(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=destination_id,
        draft=FinancialOpeningBalanceDraft(
            amount=Money(Decimal("500"), "BRL"),
            effective_date=date(2026, 8, 14),
        ),
    )

    with pytest.raises(FinancialTransferBeforeOpeningBalanceError):
        FinancialTransferStore(runtime_engine).create_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(
                source_id,
                destination_id,
                effective_date=date(2026, 8, 13),
            ),
        )

    assert _counts(engine) == (0, 0, 0)


def test_concurrent_same_transfer_request_converges_to_one_operation(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    source_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    destination_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    key = new_financial_idempotency_key()
    draft = _draft(source_id, destination_id)
    barrier = Barrier(2)

    def create() -> FinancialTransferRecord:
        barrier.wait(timeout=5)
        return FinancialTransferStore(runtime_engine).create_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=key,
            draft=draft,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(create) for _index in range(2))
        results = tuple(future.result(timeout=10) for future in futures)

    assert results[0] == results[1]
    assert _counts(engine) == (1, 2, 2)


def test_generic_movement_reversal_cannot_reverse_one_transfer_leg(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    source_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    destination_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    created = FinancialTransferStore(runtime_engine).create_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(source_id, destination_id),
    )

    with pytest.raises(FinancialMovementPersistenceError):
        FinancialMovementStore(runtime_engine).reverse_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementReversalDraft(
                movement_id=created.source_movement_id,
                effective_date=date(2026, 8, 14),
                competence_date=date(2026, 8, 1),
                reason="Reversão isolada proibida",
            ),
        )

    assert _counts(engine) == (1, 2, 2)


def test_reverse_transfer_is_atomic_swapped_and_idempotent(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    source_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    destination_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    store = FinancialTransferStore(runtime_engine)
    original = store.create_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(source_id, destination_id, amount="75.25"),
    )
    reversal_key = new_financial_idempotency_key()
    reversal_draft = FinancialTransferReversalDraft(
        transfer_id=original.id,
        effective_date=date(2026, 8, 14),
        competence_date=date(2026, 8, 1),
        reason="Correção integral",
    )

    reversed_transfer = store.reverse_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=reversal_key,
        draft=reversal_draft,
    )
    replay = store.reverse_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=reversal_key,
        draft=reversal_draft,
    )

    assert replay == reversed_transfer
    assert reversed_transfer.role is FinancialTransferRole.REVERSAL
    assert reversed_transfer.reversal_of_id == original.id
    assert reversed_transfer.source_account_id == original.destination_account_id
    assert reversed_transfer.destination_account_id == original.source_account_id

    rows = {
        row["id"]: row
        for row in _movement_rows(
            engine,
            reversed_transfer.source_movement_id,
            reversed_transfer.destination_movement_id,
        )
    }
    source = rows[reversed_transfer.source_movement_id]
    destination = rows[reversed_transfer.destination_movement_id]
    assert source["amount"] == Decimal("-75.25000000")
    assert destination["amount"] == Decimal("75.25000000")
    assert source["reversal_of_id"] == original.destination_movement_id
    assert destination["reversal_of_id"] == original.source_movement_id
    assert source["result_effect"] == destination["result_effect"] == "NEUTRAL"
    assert _counts(engine) == (2, 4, 4)

    with pytest.raises(FinancialTransferAlreadyReversedError):
        store.reverse_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=reversal_draft,
        )


def test_transfer_relation_visibility_is_intersection_of_both_accounts(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)
    source_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
        name="Conta familiar",
    )
    destination_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.PERSONAL,
        name="Conta pessoal",
    )
    transfer = FinancialTransferStore(runtime_engine).create_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(source_id, destination_id),
    )

    member_movements = FinancialMovementStore(runtime_engine).list_movements(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
        account_id=source_id,
    )
    assert tuple(row.id for row in member_movements) == (transfer.source_movement_id,)

    member_transfer_store = FinancialTransferStore(runtime_engine)
    assert member_transfer_store.list_transfers(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
        account_id=source_id,
    ) == ()
    with pytest.raises(FinancialTransferNotFoundError):
        member_transfer_store.get_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            transfer_id=transfer.id,
        )


def test_inactive_owner_membership_blocks_new_transfer(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    source_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    destination_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    with engine.begin() as connection:
        connection.execute(
            update(household_memberships)
            .where(
                household_memberships.c.residence_id == residence_id,
                household_memberships.c.operator_id == owner_id,
            )
            .values(status="disabled", is_primary=False, updated_at=NOW)
        )

    with pytest.raises(FinancialTransferAccessError):
        FinancialTransferStore(runtime_engine).create_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(source_id, destination_id),
        )
