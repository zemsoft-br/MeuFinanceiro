from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, func, select

from meufinanceiro_persistence import DEMO_CONTRACT_CHECKSUM, DemoFixtureStore
from meufinanceiro_persistence.demo_contract import (
    DEMO_CASH_ACCOUNT_ID,
    DEMO_CHECKING_ACCOUNT_ID,
    DEMO_EXPECTED_CHECKING_BALANCE,
    DEMO_EXPECTED_MOVEMENT_NET,
    DEMO_INSTALLATION_ID,
    DEMO_OPENING_AMOUNT,
)
from meufinanceiro_persistence.demo_finance_data import DEMO_MOVEMENTS
from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_opening_balance_schema import (
    financial_opening_balances,
)
from meufinanceiro_persistence.schema import demo_fixture

_TEST_INPUT = "demo-fixture-test-input"


def _store(runtime_engine: Engine, admin_engine: Engine) -> DemoFixtureStore:
    return DemoFixtureStore(
        runtime_engine,
        enabled=True,
        operator_password=_TEST_INPUT,
        reset_engine=admin_engine,
    )


def test_finance_v2_load_is_deterministic_and_idempotent(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = _store(runtime_engine, engine)
    assert store.status().loaded is False

    first = store.load()
    second = store.load()

    assert first == second
    assert first.fixture_version == 2
    assert first.reference_date == date(2026, 11, 1)
    assert first.scope == "finance_phase1"
    assert first.contract_checksum == DEMO_CONTRACT_CHECKSUM
    assert first.loaded_at is not None

    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(demo_fixture)) == 1
        assert (
            connection.scalar(select(func.count()).select_from(financial_accounts)) == 2
        )
        assert (
            connection.scalar(select(func.count()).select_from(financial_movements))
            == 5
        )
        openings = (
            connection.execute(select(financial_opening_balances)).mappings().all()
        )

    assert len(openings) == 1
    assert openings[0]["account_id"] == DEMO_CHECKING_ACCOUNT_ID
    assert openings[0]["amount"] == DEMO_OPENING_AMOUNT
    assert all(row["account_id"] != DEMO_CASH_ACCOUNT_ID for row in openings)


def test_finance_v2_preserves_standard_and_reversal_events(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    _store(runtime_engine, engine).load()

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
    assert (
        sum((row["amount"] for row in rows), Decimal("0")) == DEMO_EXPECTED_MOVEMENT_NET
    )
    assert (
        DEMO_OPENING_AMOUNT + DEMO_EXPECTED_MOVEMENT_NET
        == DEMO_EXPECTED_CHECKING_BALANCE
    )
    assert rows[-1]["reversal_of_id"] == rows[-2]["id"]
    assert rows[-1]["amount"] == -rows[-2]["amount"]


def test_finance_v2_admin_reset_is_idempotent(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = _store(runtime_engine, engine)
    store.load()

    assert store.reset() is True
    assert store.reset() is False
    assert store.status().loaded is False

    with engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(financial_movements))
            == 0
        )
        assert (
            connection.scalar(select(func.count()).select_from(financial_accounts)) == 0
        )
