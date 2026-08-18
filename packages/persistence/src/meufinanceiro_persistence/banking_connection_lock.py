"""Shared PostgreSQL advisory-lock key for connection-scoped provider mutations."""

from __future__ import annotations

from hashlib import blake2b
from uuid import UUID

_PERSONALIZATION = b"mf-bank-lock-v1"


def connection_operation_lock_key(connection_id: UUID) -> int:
    """Return a stable signed bigint key; collisions only over-serialize work."""
    if not isinstance(connection_id, UUID):
        raise TypeError("connection_id must be UUID")
    digest = blake2b(
        connection_id.bytes,
        digest_size=8,
        person=_PERSONALIZATION,
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


__all__ = ["connection_operation_lock_key"]
