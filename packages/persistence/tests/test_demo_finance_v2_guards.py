from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select, update

from meufinanceiro_persistence import (
    DemoFixtureConflictError,
    DemoFixtureStore,
    DemoModeDisabledError,
    TaskQueue,
)
from meufinanceiro_persistence.demo_contract import (
    DEMO_CHECKING_ACCOUNT_ID,
    DEMO_OPERATOR_ID,
)
from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.identity_schema import identity_operators
from meufinanceiro_persistence.schema import demo_fixture, task_queue

_TEST_INPUT = "demo-fixture-test-input"


def _store(runtime_engine: Engine, admin_engine: Engine) -> DemoFixtureStore:
    return DemoFixtureStore(
        runtime_engine,
        enabled=True,
        operator_password=_TEST_INPUT,
        reset_engine=admin_engine,
    )


def test_status_tolerates_mutable_authentication_telemetry(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = _store(runtime_engine, engine)
    loaded = store.load()
    observed_at = datetime(2026, 11, 8, 13, 0, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            update(identity_operators)
            .where(identity_operators.c.id == DEMO_OPERATOR_ID)
            .values(
                failed_attempts=2,
                locked_until=observed_at,
                last_authenticated_at=observed_at,
                updated_at=observed_at,
            )
        )

    status = store.status()
    assert status.loaded is True
    assert status.loaded_at == loaded.loaded_at


def test_functional_drift_fails_closed(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = _store(runtime_engine, engine)
    store.load()
    with engine.begin() as connection:
        connection.execute(
            update(financial_accounts)
            .where(financial_accounts.c.id == DEMO_CHECKING_ACCOUNT_ID)
            .values(name="Estado divergente")
        )

    with pytest.raises(DemoFixtureConflictError, match="differs from contract"):
        store.status()


def test_metadata_drift_fails_closed(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = _store(runtime_engine, engine)
    store.load()
    with engine.begin() as connection:
        connection.execute(update(demo_fixture).values(fixture_version=1))

    with pytest.raises(DemoFixtureConflictError, match="canonical contract"):
        store.status()


def test_demo_mode_is_required(runtime_engine: Engine, engine: Engine) -> None:
    store = DemoFixtureStore(
        runtime_engine,
        enabled=False,
        operator_password=_TEST_INPUT,
        reset_engine=engine,
    )
    assert store.status().loaded is False
    with pytest.raises(DemoModeDisabledError):
        store.load()
    with pytest.raises(DemoModeDisabledError):
        store.reset()


def test_reset_preserves_normal_task_queue(runtime_engine: Engine, engine: Engine) -> None:
    queue = TaskQueue(engine)
    task = queue.enqueue(
        task_type="demo.echo",
        payload={"correlation": str(uuid4())},
        idempotency_key="demo-finance-v2-isolation",
    )
    store = _store(runtime_engine, engine)
    store.load()

    assert store.reset() is True
    assert queue.get(task.id) is not None
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(task_queue)) == 1
