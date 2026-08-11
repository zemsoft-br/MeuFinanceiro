from __future__ import annotations

from decimal import Decimal

import pytest

from meufinanceiro_finance import (
    CurrencyMismatchError,
    Money,
    RoundingMode,
)


def test_money_preserves_decimal_without_implicit_rounding() -> None:
    money = Money(Decimal("123.45678900"), "BRL")

    assert money.amount == Decimal("123.456789")
    assert money.canonical_amount == "123.456789"
    assert money.currency == "BRL"


def test_money_rejects_float_and_non_finite_values() -> None:
    with pytest.raises(TypeError):
        Money(1.23, "BRL")  # type: ignore[arg-type]

    for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(ValueError):
            Money(value, "BRL")


def test_money_enforces_numeric_24_8_boundary() -> None:
    maximum = Money(Decimal("9999999999999999.99999999"), "BRL")
    assert maximum.canonical_amount == "9999999999999999.99999999"

    with pytest.raises(ValueError):
        Money(Decimal("10000000000000000"), "BRL")

    with pytest.raises(ValueError):
        Money(Decimal("0.000000001"), "BRL")


def test_money_canonicalizes_zero_and_trailing_zeroes() -> None:
    assert Money(Decimal("-0.00000000"), "BRL").canonical_amount == "0"
    assert Money(Decimal("100.00000000"), "BRL").canonical_amount == "100"


def test_money_requires_uppercase_ascii_currency() -> None:
    for currency in ("brl", "BR", "BRLL", "B1L", "R$L", "ÉUR"):
        with pytest.raises(ValueError):
            Money(Decimal("1"), currency)

    with pytest.raises(TypeError):
        Money(Decimal("1"), 986)  # type: ignore[arg-type]


def test_same_currency_arithmetic_is_exact() -> None:
    left = Money(Decimal("10.125"), "BRL")
    right = Money(Decimal("2.375"), "BRL")

    assert (left + right).amount == Decimal("12.5")
    assert (left - right).amount == Decimal("7.75")
    assert (-right).amount == Decimal("-2.375")
    assert abs(-right) == right


def test_cross_currency_arithmetic_and_ordering_fail_closed() -> None:
    brl = Money(Decimal("1"), "BRL")
    usd = Money(Decimal("1"), "USD")

    with pytest.raises(CurrencyMismatchError):
        _ = brl + usd
    with pytest.raises(CurrencyMismatchError):
        _ = brl - usd
    with pytest.raises(CurrencyMismatchError):
        _ = brl < usd


def test_ordering_works_for_same_currency() -> None:
    assert Money(Decimal("1"), "BRL") < Money(Decimal("2"), "BRL")
    assert Money(Decimal("2"), "BRL") >= Money(Decimal("2"), "BRL")


def test_quantization_requires_explicit_scale_and_rounding() -> None:
    amount = Money(Decimal("1.005"), "BRL")

    assert amount.quantize(scale=2, rounding=RoundingMode.HALF_EVEN).amount == Decimal(
        "1"
    )
    assert amount.quantize(scale=2, rounding=RoundingMode.HALF_UP).amount == Decimal(
        "1.01"
    )
    assert amount.quantize(scale=2, rounding=RoundingMode.DOWN).amount == Decimal("1")

    with pytest.raises(TypeError):
        amount.quantize(scale=2, rounding="HALF_UP")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        amount.quantize(scale=9, rounding=RoundingMode.HALF_UP)


def test_wire_contract_uses_decimal_string_and_separate_currency() -> None:
    money = Money(Decimal("123.45"), "BRL")

    assert money.to_wire() == {"amount": "123.45", "currency": "BRL"}
    assert isinstance(money.to_wire()["amount"], str)


def test_repr_and_str_redact_financial_amount() -> None:
    money = Money(Decimal("987654.32"), "BRL")

    assert "987654.32" not in repr(money)
    assert "987654.32" not in str(money)
    assert "<redacted>" in repr(money)
    assert "BRL" in repr(money)
