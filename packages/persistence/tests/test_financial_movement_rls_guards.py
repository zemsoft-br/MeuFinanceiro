from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountType,
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_account_schema import (
    financial_account_grants,
)
from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    FinancialMovementAccountNotFoundError,
    FinancialMovementNotFoundError,
    FinancialMovementStore,
)
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

NOW = datetime(2026, 8, 11, 5, 30, tzinfo=UTC)


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
                name="Movement RLS household",
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
                    login_name=f"movement-rls-{index}",
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


def _account(
    runtime_engine: Engine,
    *,
    installation_id: UUID,
    residence_id: UUID,
    owner_id: UUID,
    scope: FinancialVisibilityScope,
) -> UUID:
    return (
        FinancialAccountStore(runtime_engine)
        .create_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            draft=FinancialAccountDraft(
                name=f"{scope.value} Movement account",
                currency="BRL",
                account_type=FinancialAccountType.CHECKING,
                visibility_scope=scope,
            ),
        )
        .id
    )


def _draft(account_id: UUID) -> FinancialMovementDraft:
    return FinancialMovementDraft(
        account_id=account_id,
        amount=Money(Decimal("20"), "BRL"),
        result_effect=FinancialResultEffect.INCOME,
        effective_date=date(2026, 8, 10),
        competence_date=date(2026, 8, 1),
        description="RLS sintético",
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


def test_household_member_reads_ledger_but_cannot_mutate_owner_account(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
    )
    store = FinancialMovementStore(runtime_engine)
    created = store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(account_id),
    )

    assert (
        store.get_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            movement_id=created.id,
        )
        == created
    )
    assert store.list_movements(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
        account_id=account_id,
    ) == (created,)

    with pytest.raises(FinancialMovementAccountNotFoundError):
        store.create_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(account_id),
        )

    with pytest.raises(FinancialMovementAccountNotFoundError):
        store.reverse_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementReversalDraft(
                movement_id=created.id,
                effective_date=date(2026, 8, 11),
                competence_date=date(2026, 8, 1),
                reason="Membro não pode reverter",
            ),
        )


def test_privileged_reversal_lock_does_not_grant_owner_capability_to_member(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
    )
    created = FinancialMovementStore(runtime_engine).create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(account_id),
    )

    with runtime_engine.begin() as connection:
        _set_context(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
        )
        member_result = connection.scalar(
            select(
                func.finance.lock_standard_movement_for_reversal(
                    created.id,
                    installation_id,
                    residence_id,
                    member_id,
                )
            )
        )
        spoofed_owner_result = connection.scalar(
            select(
                func.finance.lock_standard_movement_for_reversal(
                    created.id,
                    installation_id,
                    residence_id,
                    owner_id,
                )
            )
        )

    assert member_result is False
    assert spoofed_owner_result is False


def test_personal_ledger_is_hidden_from_other_member(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.PERSONAL,
    )
    store = FinancialMovementStore(runtime_engine)
    created = store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(account_id),
    )

    with pytest.raises(FinancialMovementNotFoundError):
        store.get_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            movement_id=created.id,
        )

    with pytest.raises(FinancialMovementAccountNotFoundError):
        store.list_movements(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            account_id=account_id,
        )


def test_shared_ledger_is_visible_only_after_account_grant(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.SHARED,
    )
    store = FinancialMovementStore(runtime_engine)
    created = store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(account_id),
    )

    with pytest.raises(FinancialMovementNotFoundError):
        store.get_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            movement_id=created.id,
        )

    with engine.begin() as connection:
        connection.execute(
            insert(financial_account_grants).values(
                id=uuid4(),
                installation_id=installation_id,
                residence_id=residence_id,
                account_id=account_id,
                owner_operator_id=owner_id,
                visibility_scope="SHARED",
                operator_id=member_id,
                created_at=NOW,
            )
        )

    assert (
        store.get_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            movement_id=created.id,
        )
        == created
    )


def test_runtime_rls_rejects_direct_non_owner_insert(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
    )

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=member_id,
            )
            connection.execute(
                insert(financial_movements).values(
                    id=uuid4(),
                    installation_id=installation_id,
                    residence_id=residence_id,
                    account_id=account_id,
                    currency="BRL",
                    amount=Decimal("20"),
                    result_effect="INCOME",
                    role="STANDARD",
                    effective_date=date(2026, 8, 10),
                    competence_date=date(2026, 8, 1),
                    description="Bypass do store",
                    reversal_of_id=None,
                    reversal_target_role=None,
                    reversal_reason=None,
                    created_by_operator_id=member_id,
                    idempotency_key=uuid4(),
                    request_digest="a" * 64,
                    created_at=NOW,
                )
            )


def test_disabled_member_cannot_read_visible_ledger(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
    )
    store = FinancialMovementStore(runtime_engine)
    created = store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=_draft(account_id),
    )
    with engine.begin() as connection:
        connection.execute(
            update(household_memberships)
            .where(
                household_memberships.c.residence_id == residence_id,
                household_memberships.c.operator_id == member_id,
            )
            .values(status="disabled", is_primary=False, updated_at=NOW)
        )

    with pytest.raises(FinancialMovementAccessError):
        store.get_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            movement_id=created.id,
        )
