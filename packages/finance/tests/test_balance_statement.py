from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from meufinanceiro_finance.accounts import (
    FinancialAccountRecord,
    FinancialAccountStatus,
    FinancialAccountType,
)
from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.balance_statement import (
    FinancialLedgerStateError,
    derive_financial_account_balance_and_statement,
)
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.movements import (
    FinancialMovementRole,
    FinancialResultEffect,
)
from meufinanceiro_finance.opening_balances import FinancialOpeningBalanceRecord

ACCOUNT_ID = UUID("10000000-0000-4000-8000-000000000001")
OTHER_ACCOUNT_ID = UUID("10000000-0000-4000-8000-000000000002")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000001")
OPERATOR_ID = UUID("30000000-0000-4000-8000-000000000001")
OPENING_ID = UUID("40000000-0000-4000-8000-000000000001")
CALCULATED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _account(*, currency: str = "BRL") -> FinancialAccountRecord:
    created_at = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    return FinancialAccountRecord(
        id=ACCOUNT_ID,
        residence_id=RESIDENCE_ID,
        owner_operator_id=OPERATOR_ID,
        visibility_scope=FinancialVisibilityScope.PERSONAL,
        account_type=FinancialAccountType.CHECKING,
        custom_type_name=None,
        name="Conta principal",
        currency=currency,
        status=FinancialAccountStatus.ACTIVE,
        created_at=created_at,
        updated_at=created_at,
        archived_at=None,
    )


def _opening(
    amount: str,
    *,
    currency: str = "BRL",
    account_id: UUID = ACCOUNT_ID,
) -> FinancialOpeningBalanceRecord:
    return FinancialOpeningBalanceRecord(
        id=OPENING_ID,
        residence_id=RESIDENCE_ID,
        account_id=account_id,
        amount=Money(Decimal(amount), currency),
        effective_date=date(2026, 1, 1),
        created_by_operator_id=OPERATOR_ID,
        created_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    )


def _movement(
    sequence: int,
    amount: str,
    effect: FinancialResultEffect,
    *,
    role: FinancialMovementRole = FinancialMovementRole.STANDARD,
    effective_date: date = date(2026, 1, 2),
    created_at: datetime | None = None,
    currency: str = "BRL",
    account_id: UUID = ACCOUNT_ID,
    reversal_of_id: UUID | None = None,
) -> FinancialMovementRecord:
    movement_id = UUID(f"50000000-0000-4000-8000-{sequence:012d}")
    return FinancialMovementRecord(
        id=movement_id,
        account_id=account_id,
        amount=Money(Decimal(amount), currency),
        result_effect=effect,
        role=role,
        effective_date=effective_date,
        competence_date=effective_date,
        description="Movimento canônico" if role is FinancialMovementRole.STANDARD else None,
        reversal_of_id=reversal_of_id,
        reversal_reason="Correção integral" if role is FinancialMovementRole.REVERSAL else None,
        created_by_operator_id=OPERATOR_ID,
        created_at=created_at or datetime(2026, 1, 2, 10, sequence, tzinfo=UTC),
    )


def test_absent_opening_and_no_movements_keep_provenance_distinct_from_zero() -> None:
    snapshot, statement = derive_financial_account_balance_and_statement(
        account=_account(),
        opening_balance=None,
        movements=(),
        calculated_at=CALCULATED_AT,
    )

    assert snapshot.opening_balance is None
    assert snapshot.has_opening_balance is False
    assert snapshot.movement_net == Money(Decimal("0"), "BRL")
    assert snapshot.current_balance == Money(Decimal("0"), "BRL")
    assert snapshot.movement_count == 0
    assert statement.opening_balance is None
    assert statement.entries == ()
    assert statement.closing_balance == Money(Decimal("0"), "BRL")


def test_explicit_zero_opening_remains_observable() -> None:
    snapshot, statement = derive_financial_account_balance_and_statement(
        account=_account(),
        opening_balance=_opening("0"),
        movements=(),
        calculated_at=CALCULATED_AT,
    )

    assert snapshot.has_opening_balance is True
    assert snapshot.opening_balance == Money(Decimal("0"), "BRL")
    assert statement.has_opening_balance is True
    assert statement.opening_balance == Money(Decimal("0"), "BRL")


@pytest.mark.parametrize("opening_amount", ["250.125", "-80.5"])
def test_opening_balance_participates_without_rounding(opening_amount: str) -> None:
    snapshot, statement = derive_financial_account_balance_and_statement(
        account=_account(),
        opening_balance=_opening(opening_amount),
        movements=(),
        calculated_at=CALCULATED_AT,
    )

    expected = Money(Decimal(opening_amount), "BRL")
    assert snapshot.current_balance == expected
    assert statement.closing_balance == expected


def test_standard_reversal_and_neutral_movements_use_signed_amount_only() -> None:
    expense = _movement(2, "-30", FinancialResultEffect.EXPENSE)
    movements = (
        _movement(1, "100", FinancialResultEffect.INCOME),
        expense,
        _movement(
            3,
            "30",
            FinancialResultEffect.EXPENSE,
            role=FinancialMovementRole.REVERSAL,
            effective_date=date(2026, 1, 3),
            reversal_of_id=expense.id,
        ),
        _movement(
            4,
            "20",
            FinancialResultEffect.NEUTRAL,
            effective_date=date(2026, 1, 4),
        ),
    )

    snapshot, statement = derive_financial_account_balance_and_statement(
        account=_account(),
        opening_balance=_opening("50"),
        movements=movements,
        calculated_at=CALCULATED_AT,
    )

    assert snapshot.movement_net == Money(Decimal("120"), "BRL")
    assert snapshot.current_balance == Money(Decimal("170"), "BRL")
    assert snapshot.movement_count == 4
    assert [entry.balance_after.amount for entry in statement.entries] == [
        Decimal("150"),
        Decimal("120"),
        Decimal("150"),
        Decimal("170"),
    ]
    assert statement.entries[1].movement.role is FinancialMovementRole.STANDARD
    assert statement.entries[2].movement.role is FinancialMovementRole.REVERSAL


def test_statement_orders_by_effective_date_created_at_then_id() -> None:
    same_time = datetime(2026, 2, 1, 10, 0, tzinfo=UTC)
    first_id = _movement(
        10,
        "10",
        FinancialResultEffect.INCOME,
        effective_date=date(2026, 2, 1),
        created_at=same_time,
    )
    second_id = _movement(
        11,
        "20",
        FinancialResultEffect.INCOME,
        effective_date=date(2026, 2, 1),
        created_at=same_time,
    )
    earlier_created = _movement(
        12,
        "5",
        FinancialResultEffect.INCOME,
        effective_date=date(2026, 2, 1),
        created_at=datetime(2026, 2, 1, 9, 59, tzinfo=UTC),
    )
    earlier_date = _movement(
        13,
        "1",
        FinancialResultEffect.INCOME,
        effective_date=date(2026, 1, 31),
        created_at=datetime(2026, 2, 2, 12, 0, tzinfo=UTC),
    )

    _, statement = derive_financial_account_balance_and_statement(
        account=_account(),
        opening_balance=None,
        movements=(second_id, first_id, earlier_created, earlier_date),
        calculated_at=CALCULATED_AT,
    )

    assert [entry.movement.id for entry in statement.entries] == [
        earlier_date.id,
        earlier_created.id,
        first_id.id,
        second_id.id,
    ]
    assert [entry.balance_after.amount for entry in statement.entries] == [
        Decimal("1"),
        Decimal("6"),
        Decimal("16"),
        Decimal("36"),
    ]


def test_duplicate_movement_input_fails_closed() -> None:
    movement = _movement(20, "10", FinancialResultEffect.INCOME)

    with pytest.raises(FinancialLedgerStateError, match="duplicate Movement"):
        derive_financial_account_balance_and_statement(
            account=_account(),
            opening_balance=None,
            movements=(movement, movement),
            calculated_at=CALCULATED_AT,
        )


def test_opening_account_mismatch_fails_closed() -> None:
    with pytest.raises(FinancialLedgerStateError, match="opening balance account mismatch"):
        derive_financial_account_balance_and_statement(
            account=_account(),
            opening_balance=_opening("10", account_id=OTHER_ACCOUNT_ID),
            movements=(),
            calculated_at=CALCULATED_AT,
        )


def test_movement_account_mismatch_fails_closed() -> None:
    movement = _movement(
        30,
        "10",
        FinancialResultEffect.INCOME,
        account_id=OTHER_ACCOUNT_ID,
    )

    with pytest.raises(FinancialLedgerStateError, match="Movement account mismatch"):
        derive_financial_account_balance_and_statement(
            account=_account(),
            opening_balance=None,
            movements=(movement,),
            calculated_at=CALCULATED_AT,
        )


@pytest.mark.parametrize("source", ["opening", "movement"])
def test_currency_mismatch_fails_closed(source: str) -> None:
    opening = _opening("10", currency="USD") if source == "opening" else None
    movements = (
        (_movement(40, "10", FinancialResultEffect.INCOME, currency="USD"),)
        if source == "movement"
        else ()
    )

    with pytest.raises(FinancialLedgerStateError, match="currency mismatch"):
        derive_financial_account_balance_and_statement(
            account=_account(currency="BRL"),
            opening_balance=opening,
            movements=movements,
            calculated_at=CALCULATED_AT,
        )


def test_records_redact_money_and_movement_detail_from_repr() -> None:
    movement = _movement(50, "987.654321", FinancialResultEffect.INCOME)
    snapshot, statement = derive_financial_account_balance_and_statement(
        account=_account(),
        opening_balance=_opening("123.45"),
        movements=(movement,),
        calculated_at=CALCULATED_AT,
    )

    for representation in (repr(snapshot), repr(statement), repr(statement.entries[0])):
        assert "987.654321" not in representation
        assert "123.45" not in representation
        assert "Movimento canônico" not in representation
