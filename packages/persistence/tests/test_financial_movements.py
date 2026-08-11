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
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialMovementRole,
    FinancialOpeningBalanceDraft,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccountNotFoundError,
    FinancialMovementAlreadyReversedError,
    FinancialMovementBeforeOpeningBalanceError,
    FinancialMovementIdempotencyConflictError,
    FinancialMovementNotFoundError,
    FinancialMovementStore,
)
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceStore,
)
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

NOW = datetime(2026, 8, 11, 5, 0, tzinfo=UTC)


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
                name="Synthetic Movement household",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for index, (operator_id, role) in enumerate(
            ((owner_id, "owner"), (member_id, "member"))
        ):
            connection.execute(
                insert(identity_operators).values(
                    id=operator_id,
                    installation_id=installation_id,
                    login_name=f"movement-{index}",
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
                    role=role,
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
    scope: FinancialVisibilityScope = FinancialVisibilityScope.PERSONAL,
) -> UUID:
    return FinancialAccountStore(runtime_engine).create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=FinancialAccountDraft(
            name="Synthetic Movement account",
            currency="BRL",
            account_type=FinancialAccountType.CHECKING,
            visibility_scope=scope,
        ),
    ).id


def _draft(
    account_id: UUID,
    *,
    amount: str = "125.50",
    effect: FinancialResultEffect = FinancialResultEffect.INCOME,
    effective_date: date = date(2026, 8, 10),
    competence_date: date = date(2026, 8, 1),
    description: str = "Movimento sintético",
) -> FinancialMovementDraft:
    return FinancialMovementDraft(
        account_id=account_id,
        amount=Money(Decimal(amount), "BRL"),
        result_effect=effect,
        effective_date=effective_date,
        competence_date=competence_date,
        description=description,
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
            func.set_config("app.current_installation_id", str(installation_id), True),
            func.set_config("app.current_residence_id", str(residence_id), True),
            func.set_config("app.current_operator_id", str(operator_id), True),
        )
    )


def _count_movements(engine: Engine) -> int:
    with engine.begin() as connection:
        value = connection.scalar(select(func.count()).select_from(financial_movements))
    assert isinstance(value, int)
    return value


def test_create_replay_conflict_get_and_list(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    store = FinancialMovementStore(runtime_engine)
    key = new_financial_idempotency_key()
    draft = _draft(account_id)

    created = store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=key,
        draft=draft,
    )
    replay = store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=key,
        draft=draft,
    )

    assert replay == created
    assert replay.id == created.id
    assert created.role is FinancialMovementRole.STANDARD
    assert created.amount.amount == Decimal("125.50000000")
    assert store.get_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        movement_id=created.id,
    ) == created
    assert store.list_movements(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
    ) == (created,)
    assert _count_movements(engine) == 1

    with pytest.raises(FinancialMovementIdempotencyConflictError):
        store.create_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=key,
            draft=_draft(account_id, description="Outro request"),
        )


def test_opening_balance_blocks_only_earlier_effective_date(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    FinancialOpeningBalanceStore(runtime_engine).create_opening_balance(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
        draft=FinancialOpeningBalanceDraft(
            amount=Money(Decimal("500"), "BRL"),
            effective_date=date(2026, 8, 10),
        ),
    )
    store = FinancialMovementStore(runtime_engine)

    with pytest.raises(FinancialMovementBeforeOpeningBalanceError):
        store.create_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(
                account_id,
                effective_date=date(2026, 8, 9),
                competence_date=date(2026, 7, 1),
            ),
        )

    accepted = store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(
            account_id,
            effective_date=date(2026, 8, 10),
            competence_date=date(2026, 7, 1),
        ),
    )
    assert accepted.competence_date == date(2026, 7, 1)


def test_full_reversal_derives_opposite_amount_and_is_unique(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    store = FinancialMovementStore(runtime_engine)
    original = store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(account_id, amount="-75.25", effect=FinancialResultEffect.EXPENSE),
    )
    reversal_key = new_financial_idempotency_key()
    reversal_draft = FinancialMovementReversalDraft(
        movement_id=original.id,
        effective_date=date(2026, 8, 11),
        competence_date=date(2026, 8, 1),
        reason="Correção integral",
    )

    reversed_record = store.reverse_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=reversal_key,
        draft=reversal_draft,
    )
    replay = store.reverse_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=reversal_key,
        draft=reversal_draft,
    )

    assert replay == reversed_record
    assert reversed_record.role is FinancialMovementRole.REVERSAL
    assert reversed_record.reversal_of_id == original.id
    assert reversed_record.amount.amount == -original.amount.amount
    assert reversed_record.result_effect is original.result_effect
    assert reversed_record.account_id == original.account_id

    with pytest.raises(FinancialMovementAlreadyReversedError):
        store.reverse_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=reversal_draft,
        )

    with pytest.raises(FinancialMovementNotFoundError):
        store.reverse_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementReversalDraft(
                movement_id=reversed_record.id,
                effective_date=date(2026, 8, 12),
                competence_date=date(2026, 8, 1),
                reason="Não pode reverter reversão",
            ),
        )


def test_concurrent_same_create_request_converges_to_one_event(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    store = FinancialMovementStore(runtime_engine)
    key = new_financial_idempotency_key()
    draft = _draft(account_id)
    barrier = Barrier(2)

    def create_once() -> UUID:
        barrier.wait()
        return store.create_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=key,
            draft=draft,
        ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = tuple(executor.map(lambda _index: create_once(), range(2)))

    assert ids[0] == ids[1]
    assert _count_movements(engine) == 1


def test_concurrent_same_reversal_request_converges_to_one_event(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    store = FinancialMovementStore(runtime_engine)
    original = store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(account_id),
    )
    key = new_financial_idempotency_key()
    draft = FinancialMovementReversalDraft(
        movement_id=original.id,
        effective_date=date(2026, 8, 11),
        competence_date=date(2026, 8, 1),
        reason="Retry concorrente",
    )
    barrier = Barrier(2)

    def reverse_once() -> UUID:
        barrier.wait()
        return store.reverse_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=key,
            draft=draft,
        ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = tuple(executor.map(lambda _index: reverse_once(), range(2)))

    assert ids[0] == ids[1]
    assert _count_movements(engine) == 2


def test_concurrent_distinct_reversals_serialize_to_one_winner(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    store = FinancialMovementStore(runtime_engine)
    original = store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(account_id),
    )
    draft = FinancialMovementReversalDraft(
        movement_id=original.id,
        effective_date=date(2026, 8, 11),
        competence_date=date(2026, 8, 1),
        reason="Corrida de reversão",
    )
    keys = (new_financial_idempotency_key(), new_financial_idempotency_key())
    barrier = Barrier(2)

    def attempt(key: UUID) -> str:
        barrier.wait()
        try:
            store.reverse_movement(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
                idempotency_key=key,
                draft=draft,
            )
            return "created"
        except FinancialMovementAlreadyReversedError:
            return "already-reversed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(attempt, keys))

    assert sorted(outcomes) == ["already-reversed", "created"]
    assert _count_movements(engine) == 2


def test_archived_account_rejects_new_movement_and_reversal(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    store = FinancialMovementStore(runtime_engine)
    original = store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(account_id),
    )
    with engine.begin() as connection:
        connection.execute(
            update(financial_accounts)
            .where(financial_accounts.c.id == account_id)
            .values(
                status="ARCHIVED",
                archived_at=func.transaction_timestamp(),
                updated_at=func.transaction_timestamp(),
            )
        )

    with pytest.raises(FinancialMovementAccountNotFoundError):
        store.create_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(account_id, description="Após archive"),
        )

    with pytest.raises(FinancialMovementAccountNotFoundError):
        store.reverse_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementReversalDraft(
                movement_id=original.id,
                effective_date=date(2026, 8, 11),
                competence_date=date(2026, 8, 1),
                reason="Archive bloqueia reversão nova",
            ),
        )


def test_runtime_cannot_update_or_delete_movement(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
    )
    record = FinancialMovementStore(runtime_engine).create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(account_id),
    )

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )
            connection.execute(
                update(financial_movements)
                .where(financial_movements.c.id == record.id)
                .values(amount=Decimal("999"))
            )

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )
            connection.execute(
                delete(financial_movements).where(financial_movements.c.id == record.id)
            )
