from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAuditEventDraft,
    FinancialAuditEventType,
)
from sqlalchemy import Connection, func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_audit_schema import financial_audit_events
from meufinanceiro_persistence.financial_audit_store import (
    FinancialAuditStore,
    _append_financial_audit_event,
)
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

_NOW = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)


def _create_household(
    engine: Engine,
) -> tuple[UUID, UUID, UUID, UUID]:
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
                name="Synthetic audit security residence",
                status="active",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )

        for index, (operator_id, role) in enumerate(
            (
                (owner_id, "owner"),
                (member_id, "member"),
            )
        ):
            connection.execute(
                insert(identity_operators).values(
                    id=operator_id,
                    installation_id=installation_id,
                    login_name=f"audit-security-{index}",
                    password_hash=("synthetic-password-hash-material-000000000000"),
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


def _insert_account(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> UUID:
    account_id = uuid4()

    connection.execute(
        insert(financial_accounts).values(
            id=account_id,
            installation_id=installation_id,
            residence_id=residence_id,
            owner_operator_id=operator_id,
            visibility_scope="PERSONAL",
            account_type="CHECKING",
            custom_type_name=None,
            name="Synthetic audit foundation account",
            currency="BRL",
            status="ACTIVE",
            created_at=func.transaction_timestamp(),
            updated_at=func.transaction_timestamp(),
            archived_at=None,
        )
    )

    return account_id


def test_append_financial_audit_event_is_transaction_scoped_and_actor_only(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)

    with runtime_engine.begin() as connection:
        _set_context(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
        )

        account_id = _insert_account(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
        )

        event_id = _append_financial_audit_event(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
            actor_operator_id=owner_id,
            draft=FinancialAuditEventDraft(
                event_type=FinancialAuditEventType.ACCOUNT_CREATED,
                subject_id=account_id,
            ),
        )

    owner_events = FinancialAuditStore(runtime_engine).list_events(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )

    assert len(owner_events) == 1
    assert owner_events[0].id == event_id
    assert owner_events[0].actor_operator_id == owner_id
    assert owner_events[0].event_type is FinancialAuditEventType.ACCOUNT_CREATED
    assert owner_events[0].subject_id == account_id
    assert owner_events[0].related_subject_id is None

    member_events = FinancialAuditStore(runtime_engine).list_events(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
    )

    assert member_events == ()


def test_append_financial_audit_event_rejects_actor_spoofing(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )

            account_id = _insert_account(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )

            connection.scalar(
                select(
                    func.finance.append_financial_audit_event(
                        installation_id,
                        residence_id,
                        member_id,
                        "ACCOUNT_CREATED",
                        account_id,
                        None,
                    )
                )
            )


def test_financial_audit_event_rolls_back_with_financial_mutation(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)

    account_id: UUID | None = None
    event_id: UUID | None = None

    with pytest.raises(RuntimeError, match="synthetic transaction rollback"):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )

            account_id = _insert_account(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )

            event_id = _append_financial_audit_event(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                actor_operator_id=owner_id,
                draft=FinancialAuditEventDraft(
                    event_type=FinancialAuditEventType.ACCOUNT_CREATED,
                    subject_id=account_id,
                ),
            )

            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(financial_accounts)
                    .where(financial_accounts.c.id == account_id)
                )
                == 1
            )
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(financial_audit_events)
                    .where(financial_audit_events.c.id == event_id)
                )
                == 1
            )

            raise RuntimeError("synthetic transaction rollback")

    assert isinstance(account_id, UUID)
    assert isinstance(event_id, UUID)

    with engine.begin() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(financial_accounts)
                .where(financial_accounts.c.id == account_id)
            )
            == 0
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(financial_audit_events)
                .where(financial_audit_events.c.id == event_id)
            )
            == 0
        )


@pytest.mark.parametrize(
    "mismatched_scope",
    ("installation", "residence"),
)
def test_financial_audit_rejects_cross_scope_context(
    engine: Engine,
    runtime_engine: Engine,
    mismatched_scope: str,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )

            account_id = _insert_account(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )

            requested_installation_id = (
                uuid4() if mismatched_scope == "installation" else installation_id
            )
            requested_residence_id = (
                uuid4() if mismatched_scope == "residence" else residence_id
            )

            connection.scalar(
                select(
                    func.finance.append_financial_audit_event(
                        requested_installation_id,
                        requested_residence_id,
                        owner_id,
                        "ACCOUNT_CREATED",
                        account_id,
                        None,
                    )
                )
            )

    with engine.begin() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(financial_audit_events))
            == 0
        )


def test_financial_audit_occurred_at_is_server_transaction_timestamp(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)

    with runtime_engine.begin() as connection:
        _set_context(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
        )

        account_id = _insert_account(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
        )

        event_id = _append_financial_audit_event(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
            actor_operator_id=owner_id,
            draft=FinancialAuditEventDraft(
                event_type=FinancialAuditEventType.ACCOUNT_CREATED,
                subject_id=account_id,
            ),
        )

        account_created_at = connection.scalar(
            select(financial_accounts.c.created_at).where(
                financial_accounts.c.id == account_id
            )
        )
        audit_occurred_at = connection.scalar(
            select(financial_audit_events.c.occurred_at).where(
                financial_audit_events.c.id == event_id
            )
        )
        database_transaction_timestamp = connection.scalar(
            select(func.transaction_timestamp())
        )

        assert account_created_at is not None
        assert audit_occurred_at is not None
        assert database_transaction_timestamp is not None

        assert audit_occurred_at == database_transaction_timestamp
        assert audit_occurred_at == account_created_at
        assert audit_occurred_at.tzinfo is not None
        assert audit_occurred_at.utcoffset() is not None
