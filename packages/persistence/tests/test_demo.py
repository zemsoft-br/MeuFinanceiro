from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, insert, select, update

from meufinanceiro_persistence import (
    DEMO_CONTRACT_CHECKSUM,
    DEMO_FIXTURE_ID,
    DemoFixtureConflictError,
    DemoFixtureStore,
    DemoModeDisabledError,
    TaskQueue,
)
from meufinanceiro_persistence.demo_contract import (
    DEMO_CASH_ACCOUNT_ID,
    DEMO_CHECKING_ACCOUNT_ID,
    DEMO_EXPECTED_CHECKING_BALANCE,
    DEMO_EXPECTED_MOVEMENT_NET,
    DEMO_INSTALLATION_ID,
    DEMO_OPERATOR_ID,
    DEMO_OPENING_AMOUNT,
)
from meufinanceiro_persistence.demo_finance_data import DEMO_MOVEMENTS
from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_opening_balance_schema import (
    financial_opening_balances,
)
from meufinanceiro_persistence.identity_schema import identity_operators
from meufinanceiro_persistence.schema import demo_fixture, task_queue
from meufinanceiro_security.passwords import PasswordService

_TEST_OPERATOR_INPUT = "A" * 24


def _store(runtime_engine: Engine, admin_engine: Engine) -> DemoFixtureStore:
    return DemoFixtureStore(
        runtime_engine,
        enabled=True,
        operator_password=_TEST_OPERATOR_INPUT,
        reset_engine=admin_engine,
    )


def test_demo_fixture_load_is_financial_deterministic_and_idempotent(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = _store(runtime_engine, engine)

    before = store.status()
    first = store.load()
    second = store.load()

    assert before.enabled is True
    assert before.loaded is False
    assert first.loaded is True
    assert first.fixture_id == DEMO_FIXTURE_ID
    assert first.fixture_version == 2
    assert first.reference_date == date(2026, 11, 1)
    assert first.timezone == "America/Sao_Paulo"
    assert first.currency == "BRL"
    assert first.scope == "finance_phase1"
    assert first.contract_checksum == DEMO_CONTRACT_CHECKSUM
    assert first.loaded_at is not None
    assert second == first

    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(demo_fixture)) == 1
        assert connection.scalar(select(func.count()).select_from(financial_accounts)) == 2
        assert connection.scalar(select(func.count()).select_from(financial_movements)) == 5
        opening_rows = (
            connection.execute(select(financial_opening_balances)).mappings().all()
        )
        operator_hash = connection.scalar(
            select(identity_operators.c.password_hash).where(
                identity_operators.c.id == DEMO_OPERATOR_ID
            )
        )

    assert len(opening_rows) == 1
    assert opening_rows[0]["account_id"] == DEMO_CHECKING_ACCOUNT_ID
    assert opening_rows[0]["amount"] == DEMO_OPENING_AMOUNT
    assert all(
        row["account_id"] != DEMO_CASH_ACCOUNT_ID for row in opening_rows
    )
    assert isinstance(operator_hash, str)
    assert PasswordService().verify(operator_hash, _TEST_OPERATOR_INPUT)


def test_demo_fixture_movements_have_expected_append_only_result(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = _store(runtime_engine, engine)
    store.load()

    with engine.connect() as connection:
        rows = (
            connection.execute(
                select(financial_movements)
                .where(financial_movements.c.installation_id == DEMO_INSTALLATION_ID)
                .order_by(financial_movements.c.effective_date)
            )
            .mappings()
            .all()
        )

    assert len(rows) == len(DEMO_MOVEMENTS) == 5
    assert [row["role"] for row in rows] == [
        "STANDARD",
        "STANDARD",
        "STANDARD",
        "STANDARD",
        "REVERSAL",
    ]
    assert sum((row["amount"] for row in rows), Decimal("0")) == (
        DEMO_EXPECTED_MOVEMENT_NET
    )
    assert DEMO_OPENING_AMOUNT + DEMO_EXPECTED_MOVEMENT_NET == (
        DEMO_EXPECTED_CHECKING_BALANCE
    )
    assert rows[-1]["reversal_of_id"] == rows[-2]["id"]
    assert rows[-1]["amount"] == -rows[-2]["amount"]


def test_demo_status_tolerates_mutable_authentication_telemetry(
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


def test_demo_fixture_reset_is_admin_scoped_and_idempotent(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = _store(runtime_engine, engine)
    store.load()

    assert store.reset() is True
    assert store.reset() is False
    assert store.status().loaded is False

    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(financial_movements)) == 0
        assert connection.scalar(select(func.count()).select_from(financial_accounts)) == 0
        assert connection.scalar(
            select(func.count()).select_from(identity_operators)
        ) == 0


def test_demo_fixture_requires_explicit_demo_mode(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = DemoFixtureStore(
        runtime_engine,
        enabled=False,
        operator_password=_TEST_OPERATOR_INPUT,
        reset_engine=engine,
    )

    status = store.status()
    assert status.enabled is False
    assert status.loaded is False

    with pytest.raises(DemoModeDisabledError, match="not enabled"):
        store.load()
    with pytest.raises(DemoModeDisabledError, match="not enabled"):
        store.reset()


def test_demo_fixture_rejects_persisted_contract_drift(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = _store(runtime_engine, engine)
    store.load()
    with engine.begin() as connection:
        connection.execute(
            update(demo_fixture)
            .where(demo_fixture.c.fixture_id == DEMO_FIXTURE_ID)
            .values(contract_checksum="0" * 64)
        )

    with pytest.raises(DemoFixtureConflictError, match="canonical contract"):
        store.status()


def test_demo_fixture_rejects_functional_drift(
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


def test_demo_reset_preserves_normal_infrastructure(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    queue = TaskQueue(engine)
    task = queue.enqueue(
        task_type="demo.echo",
        payload={"correlation": str(uuid4())},
        idempotency_key="demo-fixture-isolation",
    )
    store = _store(runtime_engine, engine)
    store.load()

    assert store.reset() is True
    assert queue.get(task.id) is not None
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(task_queue)) == 1


def test_demo_metadata_without_functional_rows_is_not_loaded(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = _store(runtime_engine, engine)
    loaded = store.load()
    assert loaded.loaded is True

    with engine.begin() as connection:
        connection.execute(
            update(financial_accounts)
            .where(financial_accounts.c.id == DEMO_CHECKING_ACCOUNT_ID)
            .values(name="Incompatível")
        )

    with pytest.raises(DemoFixtureConflictError):
        store.status()
