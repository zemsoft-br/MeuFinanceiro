from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import upgrade
from meufinanceiro_persistence.schema import demo_task_effects, task_queue


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest.fixture(scope="session")
def app_database_user() -> str:
    return os.environ.get("TEST_APP_DATABASE_USER", "postgres")


@pytest.fixture(scope="session")
def engine(database_url: str, app_database_user: str) -> Iterator[Engine]:
    upgrade(database_url, app_database_user=app_database_user)
    engine = create_engine(database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_queue(engine: Engine) -> Iterator[None]:
    with engine.begin() as connection:
        connection.execute(delete(demo_task_effects))
        connection.execute(delete(task_queue))
    yield
