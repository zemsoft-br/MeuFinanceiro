"""Functional load/verify/reset primitives for the isolated financial demo fixture."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from meufinanceiro_persistence.demo_contract import (
    DEMO_CASH_ACCOUNT_ID,
    DEMO_CHECKING_ACCOUNT_ID,
    DEMO_CREATED_AT,
    DEMO_CURRENCY,
    DEMO_INSTALLATION_ID,
    DEMO_LOGIN_NAME,
    DEMO_MEMBERSHIP_ID,
    DEMO_OPENING_AMOUNT,
    DEMO_OPENING_BALANCE_ID,
    DEMO_OPENING_DATE,
    DEMO_OPERATOR_ID,
    DEMO_RESIDENCE_ID,
    DEMO_RESIDENCE_NAME,
)
from meufinanceiro_persistence.demo_finance_data import (
    DEMO_ACCOUNTS,
    DEMO_CATEGORIES,
    DEMO_MOVEMENTS,
)
from meufinanceiro_persistence.financial_account_schema import (
    financial_account_grants,
    financial_accounts,
)
from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_opening_balance_schema import (
    financial_opening_balances,
)
from meufinanceiro_persistence.household_schema import (
    household_memberships,
    household_residences,
)
from meufinanceiro_persistence.identity_schema import (
    identity_installation,
    identity_operators,
    identity_sessions,
)
from meufinanceiro_security.errors import PasswordHashError
from meufinanceiro_security.passwords import PasswordService


class DemoFinancialFixtureConflictError(RuntimeError):
    """Functional demo rows differ from the versioned synthetic contract."""


def load_demo_financial_fixture(
    connection: Connection,
    *,
    operator_password: str,
) -> None:
    """Insert expected functional rows without rewriting existing canonical rows."""
    if not isinstance(operator_password, str) or not operator_password:
        raise ValueError("demo operator password is required")

    _insert_or_verify(
        connection,
        identity_installation,
        {"singleton": True},
        {
            "singleton": True,
            "id": DEMO_INSTALLATION_ID,
            "created_at": DEMO_CREATED_AT,
            "updated_at": DEMO_CREATED_AT,
        },
        label="installation",
    )
    _insert_operator(connection, operator_password)
    _insert_or_verify(
        connection,
        household_residences,
        {"id": DEMO_RESIDENCE_ID},
        {
            "id": DEMO_RESIDENCE_ID,
            "installation_id": DEMO_INSTALLATION_ID,
            "name": DEMO_RESIDENCE_NAME,
            "status": "active",
            "created_at": DEMO_CREATED_AT,
            "updated_at": DEMO_CREATED_AT,
        },
        label="residence",
    )
    _insert_or_verify(
        connection,
        household_memberships,
        {"id": DEMO_MEMBERSHIP_ID},
        {
            "id": DEMO_MEMBERSHIP_ID,
            "installation_id": DEMO_INSTALLATION_ID,
            "residence_id": DEMO_RESIDENCE_ID,
            "operator_id": DEMO_OPERATOR_ID,
            "role": "owner",
            "status": "active",
            "is_primary": True,
            "created_at": DEMO_CREATED_AT,
            "updated_at": DEMO_CREATED_AT,
        },
        label="membership",
    )

    _set_financial_context(connection)
    for category in DEMO_CATEGORIES:
        _insert_or_verify(
            connection,
            financial_categories,
            {"id": category.id},
            {
                "id": category.id,
                "installation_id": DEMO_INSTALLATION_ID,
                "residence_id": DEMO_RESIDENCE_ID,
                "owner_operator_id": DEMO_OPERATOR_ID,
                "visibility_scope": category.visibility_scope,
                "parent_id": None,
                "name": category.name,
                "status": "ACTIVE",
                "created_at": DEMO_CREATED_AT,
                "updated_at": DEMO_CREATED_AT,
                "disabled_at": None,
            },
            label=f"category:{category.id}",
        )
    for account in DEMO_ACCOUNTS:
        _insert_or_verify(
            connection,
            financial_accounts,
            {"id": account.id},
            {
                "id": account.id,
                "installation_id": DEMO_INSTALLATION_ID,
                "residence_id": DEMO_RESIDENCE_ID,
                "owner_operator_id": DEMO_OPERATOR_ID,
                "visibility_scope": account.visibility_scope,
                "account_type": account.account_type,
                "custom_type_name": None,
                "name": account.name,
                "currency": DEMO_CURRENCY,
                "status": "ACTIVE",
                "created_at": DEMO_CREATED_AT,
                "updated_at": DEMO_CREATED_AT,
                "archived_at": None,
            },
            label=f"account:{account.id}",
        )

    _insert_or_verify(
        connection,
        financial_opening_balances,
        {"id": DEMO_OPENING_BALANCE_ID},
        {
            "id": DEMO_OPENING_BALANCE_ID,
            "installation_id": DEMO_INSTALLATION_ID,
            "residence_id": DEMO_RESIDENCE_ID,
            "account_id": DEMO_CHECKING_ACCOUNT_ID,
            "currency": DEMO_CURRENCY,
            "amount": DEMO_OPENING_AMOUNT,
            "effective_date": DEMO_OPENING_DATE,
            "created_by_operator_id": DEMO_OPERATOR_ID,
            "created_at": DEMO_CREATED_AT,
        },
        label="opening-balance",
    )
    for movement in DEMO_MOVEMENTS:
        _insert_or_verify(
            connection,
            financial_movements,
            {"id": movement.id},
            _movement_values(movement),
            label=f"movement:{movement.id}",
        )

    _verify_operator(connection, operator_password=operator_password)
    verify_demo_financial_fixture(connection)


def verify_demo_financial_fixture(connection: Connection) -> None:
    """Fail closed unless every expected functional row matches the contract."""
    _verify_row(
        connection,
        identity_installation,
        {"singleton": True},
        {
            "id": DEMO_INSTALLATION_ID,
            "created_at": DEMO_CREATED_AT,
            "updated_at": DEMO_CREATED_AT,
        },
        label="installation",
    )
    _verify_operator(connection)
    _verify_row(
        connection,
        household_residences,
        {"id": DEMO_RESIDENCE_ID},
        {
            "installation_id": DEMO_INSTALLATION_ID,
            "name": DEMO_RESIDENCE_NAME,
            "status": "active",
            "created_at": DEMO_CREATED_AT,
            "updated_at": DEMO_CREATED_AT,
        },
        label="residence",
    )
    _verify_row(
        connection,
        household_memberships,
        {"id": DEMO_MEMBERSHIP_ID},
        {
            "installation_id": DEMO_INSTALLATION_ID,
            "residence_id": DEMO_RESIDENCE_ID,
            "operator_id": DEMO_OPERATOR_ID,
            "role": "owner",
            "status": "active",
            "is_primary": True,
            "created_at": DEMO_CREATED_AT,
            "updated_at": DEMO_CREATED_AT,
        },
        label="membership",
    )

    _set_financial_context(connection)
    for category in DEMO_CATEGORIES:
        _verify_row(
            connection,
            financial_categories,
            {"id": category.id},
            {
                "installation_id": DEMO_INSTALLATION_ID,
                "residence_id": DEMO_RESIDENCE_ID,
                "owner_operator_id": DEMO_OPERATOR_ID,
                "visibility_scope": category.visibility_scope,
                "parent_id": None,
                "name": category.name,
                "status": "ACTIVE",
                "disabled_at": None,
            },
            label=f"category:{category.id}",
        )
    for account in DEMO_ACCOUNTS:
        _verify_row(
            connection,
            financial_accounts,
            {"id": account.id},
            {
                "installation_id": DEMO_INSTALLATION_ID,
                "residence_id": DEMO_RESIDENCE_ID,
                "owner_operator_id": DEMO_OPERATOR_ID,
                "visibility_scope": account.visibility_scope,
                "account_type": account.account_type,
                "custom_type_name": None,
                "name": account.name,
                "currency": DEMO_CURRENCY,
                "status": "ACTIVE",
                "archived_at": None,
            },
            label=f"account:{account.id}",
        )
    _verify_row(
        connection,
        financial_opening_balances,
        {"id": DEMO_OPENING_BALANCE_ID},
        {
            "installation_id": DEMO_INSTALLATION_ID,
            "residence_id": DEMO_RESIDENCE_ID,
            "account_id": DEMO_CHECKING_ACCOUNT_ID,
            "currency": DEMO_CURRENCY,
            "amount": DEMO_OPENING_AMOUNT,
            "effective_date": DEMO_OPENING_DATE,
            "created_by_operator_id": DEMO_OPERATOR_ID,
        },
        label="opening-balance",
    )
    for movement in DEMO_MOVEMENTS:
        _verify_row(
            connection,
            financial_movements,
            {"id": movement.id},
            _movement_values(movement),
            label=f"movement:{movement.id}",
        )

    cash_opening_count = connection.scalar(
        select(func.count()).select_from(financial_opening_balances).where(
            financial_opening_balances.c.account_id == DEMO_CASH_ACCOUNT_ID
        )
    )
    if cash_opening_count != 0:
        raise DemoFinancialFixtureConflictError(
            "demo cash account must not have an opening balance"
        )


def demo_functional_rows_exist(connection: Connection) -> bool:
    """Detect hidden partial fixture state when metadata is absent."""
    checks = (
        select(identity_installation.c.id).where(
            identity_installation.c.id == DEMO_INSTALLATION_ID
        ),
        select(identity_operators.c.id).where(identity_operators.c.id == DEMO_OPERATOR_ID),
        select(household_residences.c.id).where(
            household_residences.c.id == DEMO_RESIDENCE_ID
        ),
        select(household_memberships.c.id).where(
            household_memberships.c.id == DEMO_MEMBERSHIP_ID
        ),
    )
    return any(connection.scalar(statement) is not None for statement in checks)


def reset_demo_financial_fixture(connection: Connection) -> bool:
    """Delete only the isolated demo installation scope with an admin connection."""
    changed = False
    changed |= _delete_scope(
        connection,
        identity_sessions,
        identity_sessions.c.operator_id == DEMO_OPERATOR_ID,
    )
    changed |= _delete_scope(
        connection,
        financial_movements,
        (financial_movements.c.installation_id == DEMO_INSTALLATION_ID)
        & (financial_movements.c.role == "REVERSAL"),
    )
    changed |= _delete_scope(
        connection,
        financial_movements,
        financial_movements.c.installation_id == DEMO_INSTALLATION_ID,
    )
    for table in (
        financial_opening_balances,
        financial_account_grants,
        financial_categories,
        financial_accounts,
        household_memberships,
        household_residences,
        identity_operators,
    ):
        changed |= _delete_scope(
            connection,
            table,
            table.c.installation_id == DEMO_INSTALLATION_ID,
        )
    changed |= _delete_scope(
        connection,
        identity_installation,
        identity_installation.c.id == DEMO_INSTALLATION_ID,
    )
    return changed


def _insert_operator(connection: Connection, operator_password: str) -> None:
    password_hash = PasswordService().hash(operator_password)
    connection.execute(
        pg_insert(identity_operators)
        .values(
            id=DEMO_OPERATOR_ID,
            installation_id=DEMO_INSTALLATION_ID,
            login_name=DEMO_LOGIN_NAME,
            password_hash=password_hash,
            role="installation_admin",
            status="active",
            failed_attempts=0,
            locked_until=None,
            last_authenticated_at=None,
            password_changed_at=DEMO_CREATED_AT,
            created_at=DEMO_CREATED_AT,
            updated_at=DEMO_CREATED_AT,
        )
        .on_conflict_do_nothing()
    )


def _verify_operator(
    connection: Connection,
    *,
    operator_password: str | None = None,
) -> None:
    row = (
        connection.execute(
            select(identity_operators).where(identity_operators.c.id == DEMO_OPERATOR_ID)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise DemoFinancialFixtureConflictError("demo operator is missing")

    stable = {
        "installation_id": DEMO_INSTALLATION_ID,
        "login_name": DEMO_LOGIN_NAME,
        "role": "installation_admin",
        "status": "active",
        "password_changed_at": DEMO_CREATED_AT,
        "created_at": DEMO_CREATED_AT,
    }
    for key, expected_value in stable.items():
        if row[key] != expected_value:
            raise DemoFinancialFixtureConflictError("demo operator differs from contract")

    password_service = PasswordService()
    try:
        encoded_hash = row["password_hash"]
        if not isinstance(encoded_hash, str) or password_service.needs_rehash(encoded_hash):
            raise DemoFinancialFixtureConflictError("demo operator hash profile differs")
        if operator_password is not None and not password_service.verify(
            encoded_hash, operator_password
        ):
            raise DemoFinancialFixtureConflictError("demo operator credential differs")
    except PasswordHashError:
        raise DemoFinancialFixtureConflictError("demo operator hash is invalid") from None


def _movement_values(movement: Any) -> dict[str, object]:
    return {
        "id": movement.id,
        "installation_id": DEMO_INSTALLATION_ID,
        "residence_id": DEMO_RESIDENCE_ID,
        "account_id": DEMO_CHECKING_ACCOUNT_ID,
        "currency": DEMO_CURRENCY,
        "amount": movement.amount,
        "result_effect": movement.result_effect,
        "role": movement.role,
        "effective_date": movement.effective_date,
        "competence_date": movement.competence_date,
        "description": movement.description,
        "reversal_of_id": movement.reversal_of_id,
        "reversal_target_role": "STANDARD" if movement.role == "REVERSAL" else None,
        "reversal_reason": movement.reversal_reason,
        "created_by_operator_id": DEMO_OPERATOR_ID,
        "idempotency_key": movement.idempotency_key,
        "request_digest": movement.request_digest,
        "created_at": movement.created_at,
    }


def _insert_or_verify(
    connection: Connection,
    table: Any,
    identity: Mapping[str, object],
    values: Mapping[str, object],
    *,
    label: str,
) -> None:
    connection.execute(pg_insert(table).values(**values).on_conflict_do_nothing())
    _verify_row(connection, table, identity, values, label=label)


def _verify_row(
    connection: Connection,
    table: Any,
    identity: Mapping[str, object],
    expected: Mapping[str, object],
    *,
    label: str,
) -> None:
    conditions = [table.c[key] == value for key, value in identity.items()]
    row = connection.execute(select(table).where(*conditions)).mappings().one_or_none()
    if row is None:
        raise DemoFinancialFixtureConflictError(f"demo {label} is missing")
    for key, expected_value in expected.items():
        if row[key] != expected_value:
            raise DemoFinancialFixtureConflictError(f"demo {label} differs from contract")


def _set_financial_context(connection: Connection) -> None:
    connection.execute(
        select(
            func.set_config(
                "app.current_installation_id", str(DEMO_INSTALLATION_ID), True
            ),
            func.set_config("app.current_residence_id", str(DEMO_RESIDENCE_ID), True),
            func.set_config("app.current_operator_id", str(DEMO_OPERATOR_ID), True),
        )
    )


def _delete_scope(connection: Connection, table: Any, condition: Any) -> bool:
    result = connection.execute(delete(table).where(condition))
    return bool(result.rowcount)


__all__ = [
    "DemoFinancialFixtureConflictError",
    "demo_functional_rows_exist",
    "load_demo_financial_fixture",
    "reset_demo_financial_fixture",
    "verify_demo_financial_fixture",
]
