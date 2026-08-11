from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountType,
    FinancialOpeningBalanceDraft,
    FinancialVisibilityScope,
    Money,
)
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_opening_balance_schema import (
    financial_opening_balances,
)
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceAccountNotFoundError,
    FinancialOpeningBalanceAlreadyExistsError,
    FinancialOpeningBalanceCurrencyMismatchError,
    FinancialOpeningBalanceStore,
)
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

NOW = datetime(2026, 8, 11, 3, 45, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_opening_balances(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(delete(financial_opening_balances))
    yield
    with engine.begin() as connection:
        connection.execute(delete(financial_opening_balances))


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
                name="Synthetic opening household",
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
                    login_name=f"opening-{index}",
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
    scope: FinancialVisibilityScope,
    currency: str = "BRL",
) -> UUID:
    record = FinancialAccountStore(runtime_engine).create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=FinancialAccountDraft(
            name="Synthetic opening account",
            currency=currency,
            account_type=FinancialAccountType.CHECKING,
            visibility_scope=scope,
        ),
    )
    return record.id


def _draft(amount: str, currency: str = "BRL") -> FinancialOpeningBalanceDraft:
    return FinancialOpeningBalanceDraft(
        amount=Money(Decimal(amount), currency),
        effective_date=date(2026, 8, 1),
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


def test_absence_is_distinct_from_explicit_zero(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.PERSONAL,
    )
    store = FinancialOpeningBalanceStore(runtime_engine)

    assert (
        store.get_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            account_id=account_id,
        )
        is None
    )

    created = store.create_opening_balance(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
        draft=_draft("0"),
    )
    assert created.amount.amount == Decimal("0")
    assert (
        store.get_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            account_id=account_id,
        )
        == created
    )


def test_second_opening_balance_for_same_account_fails_closed(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.PERSONAL,
    )
    store = FinancialOpeningBalanceStore(runtime_engine)
    store.create_opening_balance(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
        draft=_draft("100"),
    )

    with pytest.raises(FinancialOpeningBalanceAlreadyExistsError):
        store.create_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            account_id=account_id,
            draft=_draft("200"),
        )


def test_opening_balance_currency_must_match_account(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.PERSONAL,
        currency="BRL",
    )

    with pytest.raises(FinancialOpeningBalanceCurrencyMismatchError):
        FinancialOpeningBalanceStore(runtime_engine).create_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            account_id=account_id,
            draft=_draft("10", "USD"),
        )


def test_household_member_can_read_anchor_but_cannot_create_it(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
    )
    store = FinancialOpeningBalanceStore(runtime_engine)
    created = store.create_opening_balance(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
        draft=_draft("50"),
    )

    assert (
        store.get_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            account_id=account_id,
        )
        == created
    )

    second_account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.HOUSEHOLD,
    )
    with pytest.raises(FinancialOpeningBalanceAccountNotFoundError):
        store.create_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            account_id=second_account_id,
            draft=_draft("25"),
        )


def test_personal_anchor_is_hidden_from_other_member(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.PERSONAL,
    )
    store = FinancialOpeningBalanceStore(runtime_engine)
    store.create_opening_balance(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
        draft=_draft("10"),
    )

    assert (
        store.get_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            account_id=account_id,
        )
        is None
    )


def test_archived_account_rejects_new_opening_balance(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.PERSONAL,
    )
    with engine.begin() as connection:
        connection.execute(
            update(financial_accounts)
            .where(financial_accounts.c.id == account_id)
            .values(status="ARCHIVED", archived_at=NOW, updated_at=NOW)
        )

    with pytest.raises(FinancialOpeningBalanceAccountNotFoundError):
        FinancialOpeningBalanceStore(runtime_engine).create_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            account_id=account_id,
            draft=_draft("10"),
        )


def test_database_fk_rejects_currency_mismatch_even_outside_store(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.PERSONAL,
        currency="BRL",
    )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(financial_opening_balances).values(
                    id=uuid4(),
                    installation_id=installation_id,
                    residence_id=residence_id,
                    account_id=account_id,
                    currency="USD",
                    amount=Decimal("10"),
                    effective_date=date(2026, 8, 1),
                    created_by_operator_id=owner_id,
                    created_at=NOW,
                )
            )


def test_runtime_cannot_update_or_delete_opening_balance(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        scope=FinancialVisibilityScope.PERSONAL,
    )
    record = FinancialOpeningBalanceStore(runtime_engine).create_opening_balance(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=account_id,
        draft=_draft("10"),
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
                update(financial_opening_balances)
                .where(financial_opening_balances.c.id == record.id)
                .values(amount=Decimal("20"))
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
                delete(financial_opening_balances).where(
                    financial_opening_balances.c.id == record.id
                )
            )
