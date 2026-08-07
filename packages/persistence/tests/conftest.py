from __future__ import annotations

import os
import re
import secrets
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from uuid import UUID

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, delete, insert, select
from sqlalchemy.engine import Engine, make_url

from meufinanceiro_persistence.bootstrap import normalize_psycopg_url
from meufinanceiro_persistence.migrations import upgrade
from meufinanceiro_persistence.schema import (
    connection_capabilities,
    connections,
    demo_fixture,
    demo_task_effects,
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
    identity_sessions,
    provider_configurations,
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
        now = datetime.now(UTC)
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

    return _create


@pytest.fixture(autouse=True)
def clean_persistence(engine: Engine) -> Iterator[None]:
    with engine.begin() as connection:
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
