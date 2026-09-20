"""Sanitized Pluggy investment snapshots for the read-only adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

_IDENTIFIER_MAX_LENGTH = 512
_TEXT_MAX_LENGTH = 512


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


@dataclass(frozen=True, slots=True, repr=False)
class PluggyInvestmentSnapshot:
    """Allowlisted investment fields; raw provider material never crosses here."""

    investment_id: str
    item_id: str
    name: str
    kind: str
    balance: Decimal
    currency: str
    as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "investment_id",
            _clean_identifier(self.investment_id, "investment_id"),
        )
        object.__setattr__(self, "item_id", _clean_identifier(self.item_id, "item_id"))
        object.__setattr__(
            self,
            "name",
            _clean_text(self.name, "name", max_length=_TEXT_MAX_LENGTH),
        )
        object.__setattr__(
            self,
            "kind",
            _clean_text(self.kind, "kind", max_length=128).upper(),
        )
        _require_non_negative_decimal(self.balance, "balance")
        object.__setattr__(self, "currency", _clean_currency(self.currency))
        _require_aware(self.as_of, "as_of")

    def __repr__(self) -> str:
        return "PluggyInvestmentSnapshot(<investment-data-redacted>)"


@runtime_checkable
class PluggyInvestmentsGateway(Protocol):
    """Optional read-only capability implemented by investment-aware gateways."""

    def list_investments(
        self,
        item_id: str,
    ) -> tuple[PluggyInvestmentSnapshot, ...]: ...


__all__ = [
    "PluggyInvestmentSnapshot",
    "PluggyInvestmentsGateway",
]
