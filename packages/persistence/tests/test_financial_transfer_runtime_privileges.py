from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.engine import Engine


def test_runtime_keeps_transfer_tables_append_only(runtime_engine: Engine) -> None:
    with runtime_engine.begin() as connection:
        transfer_privileges = {
            privilege: connection.scalar(
                select(func.has_table_privilege("finance.transfers", privilege))
            )
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
        }
        leg_privileges = {
            privilege: connection.scalar(
                select(func.has_table_privilege("finance.transfer_legs", privilege))
            )
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
        }

    assert transfer_privileges == {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": False,
        "DELETE": False,
    }
    assert leg_privileges == {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": False,
        "DELETE": False,
    }
