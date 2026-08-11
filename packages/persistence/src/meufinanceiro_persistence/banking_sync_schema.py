"""Typed access to banking sync tables registered in shared metadata."""

from __future__ import annotations

from sqlalchemy import Table

from meufinanceiro_persistence.schema import metadata


def _registered_table(qualified_name: str) -> Table:
    table = metadata.tables.get(qualified_name)
    if table is None:
        raise RuntimeError("required banking metadata table is not registered")
    return table


external_accounts = _registered_table("integrations.external_accounts")
sync_cursors = _registered_table("integrations.sync_cursors")
sync_runs = _registered_table("integrations.sync_runs")

__all__ = ["external_accounts", "sync_cursors", "sync_runs"]
