from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_movement_schema import financial_movements

_LOCK_FUNCTION = "finance.lock_standard_movement_for_reversal(uuid, uuid, uuid, uuid)"


def test_runtime_keeps_append_only_table_privileges_and_can_execute_lock(
    runtime_engine: Engine,
) -> None:
    with runtime_engine.begin() as connection:
        can_select = connection.scalar(
            select(func.has_table_privilege("finance.movements", "SELECT"))
        )
        can_insert = connection.scalar(
            select(func.has_table_privilege("finance.movements", "INSERT"))
        )
        can_update = connection.scalar(
            select(func.has_table_privilege("finance.movements", "UPDATE"))
        )
        can_delete = connection.scalar(
            select(func.has_table_privilege("finance.movements", "DELETE"))
        )
        can_lock = connection.scalar(
            select(func.has_function_privilege(_LOCK_FUNCTION, "EXECUTE"))
        )

    assert can_select is True
    assert can_insert is True
    assert can_update is False
    assert can_delete is False
    assert can_lock is True


def test_runtime_cannot_bypass_lock_function_with_direct_select_for_update(
    runtime_engine: Engine,
) -> None:
    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            connection.execute(
                select(financial_movements.c.id).limit(1).with_for_update()
            )
