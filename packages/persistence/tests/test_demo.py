from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select, update

from meufinanceiro_persistence import (
    DEMO_CONTRACT_CHECKSUM,
    DEMO_FIXTURE_ID,
    DemoFixtureConflictError,
    DemoFixtureStore,
    DemoModeDisabledError,
    TaskQueue,
)
from meufinanceiro_persistence.schema import demo_fixture, task_queue


def test_demo_fixture_load_is_deterministic_and_idempotent(engine: Engine) -> None:
    store = DemoFixtureStore(engine, enabled=True)

    before = store.status()
    first = store.load()
    second = store.load()

    assert before.enabled is True
    assert before.loaded is False
    assert first.loaded is True
    assert first.fixture_id == DEMO_FIXTURE_ID
    assert first.fixture_version == 1
    assert first.reference_date == date(2026, 11, 1)
    assert first.timezone == "America/Sao_Paulo"
    assert first.currency == "BRL"
    assert first.scope == "foundation_only"
    assert first.contract_checksum == DEMO_CONTRACT_CHECKSUM
    assert first.loaded_at is not None
    assert second == first

    with engine.connect() as connection:
        count = connection.scalar(select(func.count()).select_from(demo_fixture))
    assert count == 1


def test_demo_fixture_reset_is_idempotent(engine: Engine) -> None:
    store = DemoFixtureStore(engine, enabled=True)
    store.load()

    assert store.reset() is True
    assert store.reset() is False
    assert store.status().loaded is False


def test_demo_fixture_requires_explicit_demo_mode(engine: Engine) -> None:
    store = DemoFixtureStore(engine, enabled=False)

    status = store.status()
    assert status.enabled is False
    assert status.loaded is False

    with pytest.raises(DemoModeDisabledError, match="not enabled"):
        store.load()
    with pytest.raises(DemoModeDisabledError, match="not enabled"):
        store.reset()


def test_demo_fixture_rejects_persisted_contract_drift(engine: Engine) -> None:
    store = DemoFixtureStore(engine, enabled=True)
    store.load()
    with engine.begin() as connection:
        connection.execute(
            update(demo_fixture)
            .where(demo_fixture.c.fixture_id == DEMO_FIXTURE_ID)
            .values(contract_checksum="0" * 64)
        )

    with pytest.raises(DemoFixtureConflictError, match="canonical contract"):
        store.status()


def test_demo_reset_does_not_touch_normal_infrastructure(engine: Engine) -> None:
    queue = TaskQueue(engine)
    task = queue.enqueue(
        task_type="demo.echo",
        payload={"correlation": str(uuid4())},
        idempotency_key="demo-fixture-isolation",
    )
    store = DemoFixtureStore(engine, enabled=True)
    store.load()

    assert store.reset() is True
    assert queue.get(task.id) is not None
    with engine.connect() as connection:
        queue_count = connection.scalar(select(func.count()).select_from(task_queue))
    assert queue_count == 1
