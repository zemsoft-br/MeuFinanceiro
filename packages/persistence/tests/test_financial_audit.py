from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
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
    FinancialOpeningBalanceDraft,
    FinancialResultEffect,
    FinancialTransferDraft,
    FinancialTransferReversalDraft,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_account_store import (
    FinancialAccountPersistenceError,
    FinancialAccountStore,
)
from meufinanceiro_persistence.financial_audit_schema import financial_audit_events
from meufinanceiro_persistence.financial_audit_store import (
    FinancialAuditAccessError,
    FinancialAuditStore,
)
from meufinanceiro_persistence.financial_category_store import FinancialCategoryStore
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationStore,
)
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceStore,
)
from meufinanceiro_persistence.financial_transfer_store import FinancialTransferStore
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

_NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)
_AUDIT_FUNCTION = (
    "finance.append_financial_audit_event("
    "uuid, uuid, uuid, varchar, uuid, uuid)"
)


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
                name="Synthetic audit residence",
                status="active",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        for index, (operator_id, membership_role) in enumerate(
            ((owner_id, "owner"), (member_id, "member"))
        ):
            connection.execute(
                insert(identity_operators).values(
                    id=operator_id,
                    installation_id=installation_id,
                    login_name=f"audit-{index}",
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
                    role=membership_role,
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
    name: str,
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
                visibility_scope=FinancialVisibilityScope.PERSONAL,
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
                visibility_scope=FinancialVisibilityScope.PERSONAL,
            ),
        )
        .id
    )


def _movement_draft(account_id: UUID, amount: str, description: str) -> FinancialMovementDraft:
    decimal_amount = Decimal(amount)
    return FinancialMovementDraft(
        account_id=account_id,
        amount=Money(decimal_amount, "BRL"),
        result_effect=(
            FinancialResultEffect.INCOME
            if decimal_amount > 0
            else FinancialResultEffect.EXPENSE
        ),
        effective_date=date(2026, 8, 18),
        competence_date=date(2026, 8, 1),
        description=description,
    )


def _event_tuples(
    runtime_engine: Engine,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> list[tuple[str, str, UUID, UUID | None]]:
    events = FinancialAuditStore(runtime_engine).list_events(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
    )
    return [
        (
            event.event_type.value,
            event.subject_type.value,
            event.subject_id,
            event.related_subject_id,
        )
        for event in events
    ]


def test_financial_mutations_emit_typed_events_and_replays_do_not_duplicate(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _household(engine)

    account_a = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        name="Audit A",
    )
    account_b = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        name="Audit B",
    )
    account_c = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        name="Audit C",
    )
    category_a = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        name="Mercado",
    )
    category_b = _category(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        name="Casa",
    )

    opening = FinancialOpeningBalanceStore(runtime_engine).create_opening_balance(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_a,
        draft=FinancialOpeningBalanceDraft(
            amount=Money(Decimal("500.00"), "BRL"),
            effective_date=date(2026, 8, 18),
        ),
    )

    movement_store = FinancialMovementStore(runtime_engine)
    movement_key = new_financial_idempotency_key()
    movement_draft = _movement_draft(account_a, "-100.00", "Compra sintética")
    movement = movement_store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=movement_key,
        draft=movement_draft,
    )
    assert movement_store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=movement_key,
        draft=movement_draft,
    ) == movement

    reversal = movement_store.reverse_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=movement.id,
            effective_date=date(2026, 8, 18),
            competence_date=date(2026, 8, 1),
            reason="Correção sintética",
        ),
    )

    allocation_movement = movement_store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_movement_draft(account_c, "-100.00", "Rateio sintético"),
    )

    transfer_store = FinancialTransferStore(runtime_engine)
    transfer_key = new_financial_idempotency_key()
    transfer_draft = FinancialTransferDraft(
        source_account_id=account_b,
        destination_account_id=account_c,
        magnitude=Money(Decimal("25.00"), "BRL"),
        effective_date=date(2026, 8, 18),
        competence_date=date(2026, 8, 1),
        description="Transferência sintética",
    )
    transfer = transfer_store.create_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=transfer_key,
        draft=transfer_draft,
    )
    assert transfer_store.create_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=transfer_key,
        draft=transfer_draft,
    ) == transfer

    transfer_reversal = transfer_store.reverse_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialTransferReversalDraft(
            transfer_id=transfer.id,
            effective_date=date(2026, 8, 18),
            competence_date=date(2026, 8, 1),
            reason="Correção de transferência",
        ),
    )

    allocation_store = FinancialMovementAllocationStore(runtime_engine)
    allocation_key = new_financial_idempotency_key()
    allocation_draft = FinancialMovementAllocationSetDraft(
        movement_id=allocation_movement.id,
        allocations=(
            FinancialMovementAllocationDraft(
                category_id=category_a,
                amount=Money(Decimal("-100.00"), "BRL"),
            ),
        ),
    )
    allocation = allocation_store.create_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=allocation_key,
        draft=allocation_draft,
    )
    assert allocation_store.create_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=allocation_key,
        draft=allocation_draft,
    ) == allocation

    revised = allocation_store.revise_allocation_set(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationRevisionDraft(
            movement_id=allocation_movement.id,
            supersedes_id=allocation.id,
            allocations=(
                FinancialMovementAllocationDraft(
                    category_id=category_a,
                    amount=Money(Decimal("-60.00"), "BRL"),
                ),
                FinancialMovementAllocationDraft(
                    category_id=category_b,
                    amount=Money(Decimal("-40.00"), "BRL"),
                ),
            ),
        ),
    )

    events = _event_tuples(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    assert len(events) == 13
    assert ("ACCOUNT_CREATED", "ACCOUNT", account_a, None) in events
    assert ("ACCOUNT_CREATED", "ACCOUNT", account_b, None) in events
    assert ("ACCOUNT_CREATED", "ACCOUNT", account_c, None) in events
    assert ("CATEGORY_CREATED", "CATEGORY", category_a, None) in events
    assert ("CATEGORY_CREATED", "CATEGORY", category_b, None) in events
    assert ("OPENING_BALANCE_CREATED", "OPENING_BALANCE", opening.id, None) in events
    assert ("MOVEMENT_CREATED", "MOVEMENT", movement.id, None) in events
    assert ("MOVEMENT_REVERSED", "MOVEMENT", reversal.id, movement.id) in events
    assert (
        "MOVEMENT_CREATED",
        "MOVEMENT",
        allocation_movement.id,
        None,
    ) in events
    assert ("TRANSFER_CREATED", "TRANSFER", transfer.id, None) in events
    assert (
        "TRANSFER_REVERSED",
        "TRANSFER",
        transfer_reversal.id,
        transfer.id,
    ) in events
    assert (
        "ALLOCATION_SET_CREATED",
        "ALLOCATION_SET",
        allocation.id,
        None,
    ) in events
    assert (
        "ALLOCATION_SET_REVISED",
        "ALLOCATION_SET",
        revised.id,
        allocation.id,
    ) in events


def test_financial_audit_is_actor_only_and_inactive_membership_fails_closed(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        name="Private audit account",
    )

    owner_events = _event_tuples(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    assert owner_events == [("ACCOUNT_CREATED", "ACCOUNT", account_id, None)]
    assert _event_tuples(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
    ) == []

    with engine.begin() as connection:
        connection.execute(
            update(household_memberships)
            .where(
                household_memberships.c.residence_id == residence_id,
                household_memberships.c.operator_id == owner_id,
            )
            .values(status="disabled", updated_at=datetime(2026, 8, 18, 2, 0, tzinfo=UTC))
        )

    with pytest.raises(FinancialAuditAccessError):
        FinancialAuditStore(runtime_engine).list_events(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
        )


def test_audit_failure_rolls_back_financial_mutation(
    engine: Engine,
    runtime_engine: Engine,
    app_database_user: str,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _household(engine)

    with engine.begin() as connection:
        connection.exec_driver_sql(
            f'REVOKE EXECUTE ON FUNCTION {_AUDIT_FUNCTION} '
            f'FROM "{app_database_user}"'
        )

    try:
        with pytest.raises(FinancialAccountPersistenceError):
            _account(
                runtime_engine,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
                name="Must rollback",
            )
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f'GRANT EXECUTE ON FUNCTION {_AUDIT_FUNCTION} '
                f'TO "{app_database_user}"'
            )

    with engine.begin() as connection:
        account_count = connection.scalar(select(func.count()).select_from(financial_accounts))
        audit_count = connection.scalar(
            select(func.count()).select_from(financial_audit_events)
        )
    assert account_count == 0
    assert audit_count == 0


def test_runtime_cannot_bypass_audit_or_fabricate_historical_event(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _household(engine)

    direct_account_id = uuid4()
    with pytest.raises(IntegrityError):
        with runtime_engine.begin() as connection:
            connection.execute(
                select(
                    func.set_config(
                        "app.current_installation_id", str(installation_id), True
                    ),
                    func.set_config("app.current_residence_id", str(residence_id), True),
                    func.set_config("app.current_operator_id", str(owner_id), True),
                )
            )
            connection.execute(
                insert(financial_accounts).values(
                    id=direct_account_id,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    owner_operator_id=owner_id,
                    visibility_scope="PERSONAL",
                    account_type="CHECKING",
                    custom_type_name=None,
                    name="Unaudited runtime account",
                    currency="BRL",
                    status="ACTIVE",
                    created_at=func.transaction_timestamp(),
                    updated_at=func.transaction_timestamp(),
                    archived_at=None,
                )
            )

    with engine.begin() as connection:
        assert connection.scalar(
            select(func.count()).select_from(financial_accounts).where(
                financial_accounts.c.id == direct_account_id
            )
        ) == 0

        historical_account_id = uuid4()
        connection.execute(
            insert(financial_accounts).values(
                id=historical_account_id,
                installation_id=installation_id,
                residence_id=residence_id,
                owner_operator_id=owner_id,
                visibility_scope="PERSONAL",
                account_type="CHECKING",
                custom_type_name=None,
                name="Historical admin fixture",
                currency="BRL",
                status="ACTIVE",
                created_at=_NOW,
                updated_at=_NOW,
                archived_at=None,
            )
        )

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            connection.execute(
                select(
                    func.set_config(
                        "app.current_installation_id", str(installation_id), True
                    ),
                    func.set_config("app.current_residence_id", str(residence_id), True),
                    func.set_config("app.current_operator_id", str(owner_id), True),
                )
            )
            connection.scalar(
                select(
                    func.finance.append_financial_audit_event(
                        installation_id,
                        residence_id,
                        owner_id,
                        "ACCOUNT_CREATED",
                        historical_account_id,
                        None,
                    )
                )
            )

    with engine.begin() as connection:
        assert connection.scalar(
            select(func.count()).select_from(financial_audit_events).where(
                financial_audit_events.c.subject_id == historical_account_id
            )
        ) == 0
