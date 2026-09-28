"""Shared connection advisory gate for banking sync and disconnection."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, func, select


def connection_advisory_lock_key(connection_id: UUID) -> int:
    """Fold a UUID into PostgreSQL's signed 64-bit advisory-lock key space."""

    upper = connection_id.int >> 64
    lower = connection_id.int & ((1 << 64) - 1)
    value = upper ^ lower
    if value >= 1 << 63:
        value -= 1 << 64
    return value


def acquire_connection_advisory_xact_gate(
    connection: Connection,
    *,
    connection_id: UUID,
) -> None:
    """Wait for any session-held disconnect before locking the connection row."""

    connection.execute(
        select(func.pg_advisory_xact_lock(connection_advisory_lock_key(connection_id)))
    )
