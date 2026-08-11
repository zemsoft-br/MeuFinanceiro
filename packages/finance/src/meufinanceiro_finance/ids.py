"""Canonical local identifiers for financial-domain resources."""

from __future__ import annotations

from uuid import RFC_4122, UUID, uuid4


def new_financial_resource_id() -> UUID:
    """Generate a local opaque UUID v4 using Python's system randomness."""

    return validate_financial_resource_id(uuid4())


def validate_financial_resource_id(value: UUID) -> UUID:
    """Require an RFC 4122 UUID v4 without coercing external representations."""

    if not isinstance(value, UUID):
        raise TypeError("financial resource id must be UUID")
    if value.int == 0:
        raise ValueError("financial resource id must not be nil")
    if value.variant != RFC_4122 or value.version != 4:
        raise ValueError("financial resource id must be RFC 4122 UUID v4")
    return value


__all__ = [
    "new_financial_resource_id",
    "validate_financial_resource_id",
]
