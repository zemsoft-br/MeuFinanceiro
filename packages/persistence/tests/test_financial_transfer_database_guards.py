from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountType,
    FinancialMovementDraft,
    FinancialResultEffect,
    FinancialTransferDraft,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_transfer_schema import (
    financial_transfer_legs,
    financial_transfers,
)
from meufinanceiro_persistence.financial_transfer_store import FinancialTransferStore
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

NOW = datetime(2026, 8, 13, 6, 30, tzinfo=UTC)


def _household_and_accounts(
    engine: Engine,
    runtime_engine: Engine,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    installation_id = uuid4()
    residence_id = uuid4()
    owner_id = uuid4()
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
            insert(identity_operators).values(
                id=owner_id,
                installation_id=installation_id,
                login_name="transfer-guard-owner",
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
            insert(household_residences).values(
                id=residence_id,
                installation_id=installation_id,
                name="Transfer guard residence",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            insert(household_memberships).values(
                id=uuid4(),
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
                role="owner",
                status="active",
                is_primary=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    store = FinancialAccountStore(runtime_engine)
    source_id = store.create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=FinancialAccountDraft(
            name="Guard source",
            currency="BRL",
            account_type=FinancialAccountType.CHECKING,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
        ),
    ).id
    destination_id = store.create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=FinancialAccountDraft(
            name="Guard destination",
            currency="BRL",
            account_type=FinancialAccountType.CHECKING,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
        ),
    ).id
    return installation_id, residence_id, owner_id, source_id, destination_id


def _direct_transfer_values(
    *,
    transfer_id: UUID,
    installation_id: UUID,
    residence_id: UUID,
    owner_id: UUID,
    source_id: UUID,
    destination_id: UUID,
    digest_character: str,
) -> dict[str, object]:
    return {
        "id": transfer_id,
        "installation_id": installation_id,
        "residence_id": residence_id,
        "source_account_id": source_id,
        "destination_account_id": destination_id,
        "currency": "BRL",
        "role": "STANDARD",
        "reversal_of_id": None,
        "created_by_operator_id": owner_id,
        "idempotency_key": uuid4(),
        "request_digest": digest_character * 64,
        "created_at": NOW,
    }


def test_database_prevents_reusing_one_movement_in_another_transfer_direction(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, source_id, destination_id = (
        _household_and_accounts(engine, runtime_engine)
    )
    original = FinancialTransferStore(runtime_engine).create_transfer(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialTransferDraft(
            source_account_id=source_id,
            destination_account_id=destination_id,
            magnitude=Money(Decimal("10"), "BRL"),
            effective_date=date(2026, 8, 13),
            competence_date=date(2026, 8, 1),
            description="Original",
        ),
    )
    second_transfer_id = uuid4()

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(financial_transfers).values(
                    **_direct_transfer_values(
                        transfer_id=second_transfer_id,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        owner_id=owner_id,
                        source_id=source_id,
                        destination_id=destination_id,
                        digest_character="b",
                    )
                )
            )
            connection.execute(
                insert(financial_transfer_legs).values(
                    transfer_id=second_transfer_id,
                    direction="DESTINATION",
                    movement_id=original.source_movement_id,
                )
            )


def test_deferred_database_guard_rejects_non_opposite_transfer_amounts(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, source_id, destination_id = (
        _household_and_accounts(engine, runtime_engine)
    )
    movement_store = FinancialMovementStore(runtime_engine)
    source = movement_store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementDraft(
            account_id=source_id,
            amount=Money(Decimal("-100"), "BRL"),
            result_effect=FinancialResultEffect.NEUTRAL,
            effective_date=date(2026, 8, 13),
            competence_date=date(2026, 8, 1),
            description="Mismatch",
        ),
    )
    destination = movement_store.create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementDraft(
            account_id=destination_id,
            amount=Money(Decimal("90"), "BRL"),
            result_effect=FinancialResultEffect.NEUTRAL,
            effective_date=date(2026, 8, 13),
            competence_date=date(2026, 8, 1),
            description="Mismatch",
        ),
    )
    transfer_id = uuid4()

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(financial_transfers).values(
                    **_direct_transfer_values(
                        transfer_id=transfer_id,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        owner_id=owner_id,
                        source_id=source_id,
                        destination_id=destination_id,
                        digest_character="c",
                    )
                )
            )
            connection.execute(
                insert(financial_transfer_legs),
                (
                    {
                        "transfer_id": transfer_id,
                        "direction": "SOURCE",
                        "movement_id": source.id,
                    },
                    {
                        "transfer_id": transfer_id,
                        "direction": "DESTINATION",
                        "movement_id": destination.id,
                    },
                ),
            )
