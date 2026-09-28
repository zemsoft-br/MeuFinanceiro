"""Sanitized Pluggy loan snapshots for the read-only adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

_IDENTIFIER_MAX_LENGTH = 512


def _clean_text(value: str, field_name: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > max_length
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _clean_identifier(value: str, field_name: str) -> str:
    return _clean_text(value, field_name, max_length=_IDENTIFIER_MAX_LENGTH)


def _clean_currency(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("currency must be a string")
    currency = value.strip().upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise ValueError("currency must be a three-letter ASCII code")
    return currency


def _require_non_negative_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return value


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_date(value: date | None, field_name: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{field_name} must be date")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class PluggyLoanSnapshot:
    """Allowlisted loan fields; contract/payment detail stays provider-internal."""

    loan_id: str
    item_id: str
    kind: str
    outstanding_balance: Decimal
    currency: str
    as_of: datetime
    contracted_at: date | None = None
    due_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "loan_id", _clean_identifier(self.loan_id, "loan_id"))
        object.__setattr__(self, "item_id", _clean_identifier(self.item_id, "item_id"))
        object.__setattr__(
            self,
            "kind",
            _clean_text(self.kind, "kind", max_length=128).upper(),
        )
        _require_non_negative_decimal(
            self.outstanding_balance,
            "outstanding_balance",
        )
        object.__setattr__(self, "currency", _clean_currency(self.currency))
        _require_aware(self.as_of, "as_of")
        _require_date(self.contracted_at, "contracted_at")
        _require_date(self.due_date, "due_date")
        if (
            self.contracted_at is not None
            and self.due_date is not None
            and self.due_date < self.contracted_at
        ):
            raise ValueError("due_date must not be before contracted_at")

    def __repr__(self) -> str:
        return "PluggyLoanSnapshot(<loan-data-redacted>)"


@runtime_checkable
class PluggyLoansGateway(Protocol):
    """Optional read-only capability implemented by loan-aware gateways."""

    def list_loans(self, item_id: str) -> tuple[PluggyLoanSnapshot, ...]: ...


__all__ = [
    "PluggyLoanSnapshot",
    "PluggyLoansGateway",
]
