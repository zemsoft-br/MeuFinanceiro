"""Sanitized Pluggy credit-card bill snapshots for the read-only adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

_IDENTIFIER_MAX_LENGTH = 512


def _clean_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > _IDENTIFIER_MAX_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _clean_currency(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("currency must be a string")
    currency = value.strip().upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise ValueError("currency must be a three-letter ASCII code")
    return currency


def _require_date(value: date | None, field_name: str, *, optional: bool) -> date | None:
    if value is None:
        if optional:
            return None
        raise TypeError(f"{field_name} must be date")
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{field_name} must be date")
    return value


def _require_non_negative_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return value


class PluggyCreditCardBillState(StrEnum):
    """Provider-specific bill state before neutral normalization."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True, repr=False)
class PluggyCreditCardBillSnapshot:
    """Allowlisted bill fields; the raw Pluggy payload never crosses this boundary."""

    bill_id: str
    account_id: str
    state: PluggyCreditCardBillState
    due_date: date
    total_amount: Decimal
    currency: str
    close_date: date | None = None
    minimum_payment: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bill_id", _clean_identifier(self.bill_id, "bill_id"))
        object.__setattr__(
            self,
            "account_id",
            _clean_identifier(self.account_id, "account_id"),
        )
        if not isinstance(self.state, PluggyCreditCardBillState):
            raise TypeError("state must be PluggyCreditCardBillState")
        _require_date(self.due_date, "due_date", optional=False)
        _require_date(self.close_date, "close_date", optional=True)
        total = _require_non_negative_decimal(self.total_amount, "total_amount")
        if self.minimum_payment is not None:
            minimum = _require_non_negative_decimal(
                self.minimum_payment,
                "minimum_payment",
            )
            if minimum > total:
                raise ValueError("minimum_payment must not exceed total_amount")
        object.__setattr__(self, "currency", _clean_currency(self.currency))

    def __repr__(self) -> str:
        return "PluggyCreditCardBillSnapshot(<bill-data-redacted>)"


@runtime_checkable
class PluggyCreditCardBillsGateway(Protocol):
    """Optional read-only capability implemented by gateways that expose bills."""

    def list_credit_card_bills(
        self,
        account_id: str,
    ) -> tuple[PluggyCreditCardBillSnapshot, ...]: ...


__all__ = [
    "PluggyCreditCardBillSnapshot",
    "PluggyCreditCardBillState",
    "PluggyCreditCardBillsGateway",
]
