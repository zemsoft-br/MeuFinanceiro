"""Operational identifiers that are deliberately distinct from resource IDs."""

from __future__ import annotations

from uuid import RFC_4122, UUID, uuid4


def new_financial_idempotency_key() -> UUID:
    """Return an opaque UUID v4 suitable for one retriable financial operation."""
    return uuid4()


def validate_financial_idempotency_key(value: UUID) -> UUID:
    """Validate an operation key without treating it as a canonical resource ID."""
    if not isinstance(value, UUID):
        raise TypeError("idempotency_key must be UUID")
    if value.int == 0:
        raise ValueError("idempotency_key must not be nil UUID")
    if value.version != 4:
        raise ValueError("idempotency_key must be UUID v4")
    if value.variant != RFC_4122:
        raise ValueError("idempotency_key must use RFC 4122 variant")
    return value


__all__ = [
    "new_financial_idempotency_key",
    "validate_financial_idempotency_key",
]
