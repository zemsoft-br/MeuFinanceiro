"""Canonical monetary value object for the financial domain."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Decimal,
    localcontext,
)
from enum import StrEnum
from functools import total_ordering

_MAX_SCALE = 8
_MAX_INTEGER_DIGITS = 16
_QUANTIZE_CONTEXT_PRECISION = 40


class CurrencyMismatchError(ValueError):
    """Raised when arithmetic or ordering mixes different currencies."""


class RoundingMode(StrEnum):
    """Explicit rounding policies supported by the financial domain."""

    HALF_EVEN = "HALF_EVEN"
    HALF_UP = "HALF_UP"
    DOWN = "DOWN"


_DECIMAL_ROUNDING = {
    RoundingMode.HALF_EVEN: ROUND_HALF_EVEN,
    RoundingMode.HALF_UP: ROUND_HALF_UP,
    RoundingMode.DOWN: ROUND_DOWN,
}


def _clean_currency(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("currency must be a string")
    if len(value) != 3 or not value.isascii() or not value.isalpha():
        raise ValueError("currency must be a three-letter ASCII code")
    if value != value.upper():
        raise ValueError("currency must be uppercase")
    return value


def _canonical_decimal(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("amount must be Decimal")
    if not value.is_finite():
        raise ValueError("amount must be finite")

    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):  # Defensive typing for DecimalTuple specials.
        raise ValueError("amount must be finite")

    mutable_digits = list(digits)
    mutable_exponent = exponent

    if not any(mutable_digits):
        return Decimal(0)

    while len(mutable_digits) > 1 and mutable_digits[-1] == 0:
        mutable_digits.pop()
        mutable_exponent += 1

    normalized = Decimal((sign, tuple(mutable_digits), mutable_exponent))
    scale = max(-mutable_exponent, 0)
    integer_digits = max(len(mutable_digits) + mutable_exponent, 0)

    if scale > _MAX_SCALE:
        raise ValueError(f"amount exceeds {_MAX_SCALE} fractional digits")
    if integer_digits > _MAX_INTEGER_DIGITS:
        raise ValueError(
            f"amount exceeds {_MAX_INTEGER_DIGITS} integer digits"
        )
    return normalized


def _clean_scale(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("scale must be an integer")
    if value < 0 or value > _MAX_SCALE:
        raise ValueError(f"scale must be between 0 and {_MAX_SCALE}")
    return value


def _clean_rounding(value: RoundingMode) -> RoundingMode:
    if not isinstance(value, RoundingMode):
        raise TypeError("rounding must be RoundingMode")
    return value


@total_ordering
@dataclass(frozen=True, slots=True, repr=False)
class Money:
    """Immutable amount + currency pair with explicit rounding semantics."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _canonical_decimal(self.amount))
        object.__setattr__(self, "currency", _clean_currency(self.currency))

    @property
    def canonical_amount(self) -> str:
        """Return a fixed-point decimal string suitable for wire contracts."""
        return format(self.amount, "f")

    def to_wire(self) -> dict[str, str]:
        """Return the canonical JSON-compatible representation without floats."""
        return {
            "amount": self.canonical_amount,
            "currency": self.currency,
        }

    def quantize(self, *, scale: int, rounding: RoundingMode) -> Money:
        """Round explicitly to the requested scale and mode."""
        normalized_scale = _clean_scale(scale)
        normalized_rounding = _clean_rounding(rounding)
        quantum = Decimal(1).scaleb(-normalized_scale)
        with localcontext() as context:
            context.prec = _QUANTIZE_CONTEXT_PRECISION
            rounded = self.amount.quantize(
                quantum,
                rounding=_DECIMAL_ROUNDING[normalized_rounding],
            )
        return Money(rounded, self.currency)

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                "money operation requires matching currencies"
            )

    def __add__(self, other: object) -> Money:
        if not isinstance(other, Money):
            raise TypeError("money addition requires Money")
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: object) -> Money:
        if not isinstance(other, Money):
            raise TypeError("money subtraction requires Money")
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            raise TypeError("money ordering requires Money")
        self._require_same_currency(other)
        return self.amount < other.amount

    def __repr__(self) -> str:
        return f"Money(currency={self.currency!r}, amount=<redacted>)"


__all__ = [
    "CurrencyMismatchError",
    "Money",
    "RoundingMode",
]
