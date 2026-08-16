from __future__ import annotations

import os
import re
import secrets
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, delete, insert, select
from sqlalchemy.engine import Engine, make_url

from meufinanceiro_persistence.banking_ledger_review_schema import (
    reconciled_transaction_ledger_links,
)
from meufinanceiro_persistence.banking_observation_schema import external_observations
from meufinanceiro_persistence.banking_reconciliation_schema import (
    reconciled_transactions,
)
from meufinanceiro_persistence.bootstrap import normalize_psycopg_url
from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_opening_balance_schema import (
    financial_opening_balances,
)
from meufinanceiro_persistence.financial_transfer_schema import (
    financial_transfer_legs,
    financial_transfers,
)
from meufinanceiro_persistence.migrations import upgrade
from meufinanceiro_persistence.schema import (
    connection_capabilities,
    connections,
    demo_fixture,
    demo_task_effects,
    external_accounts,
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
    identity_sessions,
    provider_configurations,
    sync_cursors,
    sync_runs,
    task_queue,
)

_RUNTIME_PASSWORD = "disposable-rls-test-password"
_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest.fixture(scope="session")
def app_database_user(database_url: str) -> Iterator[str]:
    role_name = f"meufinanceiro_test_{secrets.token_hex(4)}"
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise ValueError("TEST_APP_DATABASE_USER is not a valid PostgreSQL role")

    with psycopg.connect(
        normalize_psycopg_url(database_url),
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS"
                ).format(
                    sql.Identifier(role_name),
                    sql.Literal(_RUNTIME_PASSWORD),
                )
            )
    yield role_name

    with psycopg.connect(
        normalize_psycopg_url(database_url),
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name))
            )
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


@pytest.fixture(scope="session")
def runtime_database_url(database_url: str, app_database_user: str) -> str:
    return (
        make_url(database_url)
        .set(
            username=app_database_user,
            password=_RUNTIME_PASSWORD,
        )
        .render_as_string(hide_password=False)
    )


@pytest.fixture(scope="session")
def engine(database_url: str, app_database_user: str) -> Iterator[Engine]:
    upgrade(database_url, app_database_user=app_database_user)
    engine = create_engine(database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def runtime_engine(runtime_database_url: str) -> Iterator[Engine]:
    engine = create_engine(runtime_database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def create_canonical_residences(
    engine: Engine,
) -> Callable[[UUID, tuple[UUID, ...]], None]:
    def _create(installation_id: UUID, residence_ids: tuple[UUID, ...]) -> None:
        if not residence_ids:
            raise ValueError("at least one canonical residence is required")
        now = datetime.now(UTC)
        operator_id = uuid4()
        with engine.begin() as connection:
            current_installation = connection.scalar(select(identity_installation.c.id))
            if current_installation is None:
                connection.execute(
                    insert(identity_installation).values(
                        singleton=True,
                        id=installation_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif current_installation != installation_id:
                raise AssertionError(
                    "canonical residence fixture cannot cross installation singleton"
                )

            connection.execute(
                insert(identity_operators).values(
                    id=operator_id,
                    installation_id=installation_id,
                    login_name="test-admin",
                    password_hash="synthetic-password-hash-material-000000000000",
                    role="installation_admin",
                    status="active",
                    failed_attempts=0,
                    locked_until=None,
                    last_authenticated_at=None,
                    password_changed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            for index, residence_id in enumerate(residence_ids, start=1):
                connection.execute(
                    insert(household_residences).values(
                        id=residence_id,
                        installation_id=installation_id,
                        name=f"Test residence {index}",
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                )
                connection.execute(
                    insert(household_memberships).values(
                        id=uuid4(),
                        installation_id=installation_id,
                        residence_id=residence_id,
                        operator_id=operator_id,
                        role="owner",
                        status="active",
                        is_primary=index == 1,
                        created_at=now,
                        updated_at=now,
                    )
                )

    return _create


@pytest.fixture(autouse=True)
def clean_persistence(engine: Engine) -> Iterator[None]:
    with engine.begin() as connection:
        connection.execute(delete(reconciled_transaction_ledger_links))
        connection.execute(delete(financial_transfer_legs))
        connection.execute(delete(financial_transfers))
        connection.execute(delete(financial_movements))
        connection.execute(delete(financial_opening_balances))
        connection.execute(delete(financial_categories))
        connection.execute(delete(financial_accounts))
        connection.execute(delete(reconciled_transactions))
        connection.execute(delete(external_observations))
        connection.execute(delete(sync_cursors))
        connection.execute(delete(external_accounts))
        connection.execute(delete(sync_runs))
        connection.execute(delete(connection_capabilities))
        connection.execute(delete(connections))
        connection.execute(delete(provider_configurations))
        connection.execute(delete(household_memberships))
        connection.execute(delete(household_residences))
        connection.execute(delete(identity_sessions))
        connection.execute(delete(identity_operators))
        connection.execute(delete(identity_installation))
        connection.execute(delete(demo_fixture))
        connection.execute(delete(demo_task_effects))
        connection.execute(delete(task_queue))
    yield
