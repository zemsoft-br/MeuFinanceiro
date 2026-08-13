"""Pure derivation of account balance and statement from the canonical ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from meufinanceiro_finance.accounts import FinancialAccountRecord
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.opening_balances import FinancialOpeningBalanceRecord


class FinancialLedgerStateError(ValueError):
    """Canonical resources are inconsistent for deterministic balance derivation."""


@dataclass(frozen=True, slots=True, repr=False)
class FinancialAccountBalanceSnapshot:
    """Read-only balance derived from one account's canonical resources."""

    account_id: UUID
    currency: str
    opening_balance: Money | None
    movement_net: Money
    current_balance: Money
    movement_count: int
    calculated_at: datetime

    def __post_init__(self) -> None:
        _require_currency(self.movement_net, self.currency, "movement_net")
        _require_currency(self.current_balance, self.currency, "current_balance")
        if self.opening_balance is not None:
            _require_currency(self.opening_balance, self.currency, "opening_balance")
        if not isinstance(self.movement_count, int) or self.movement_count < 0:
            raise ValueError("movement_count must be a non-negative integer")
        _require_aware_datetime(self.calculated_at, "calculated_at")

    @property
    def has_opening_balance(self) -> bool:
        """Keep absence of an opening balance distinct from an explicit zero."""
        return self.opening_balance is not None

    def __repr__(self) -> str:
        return (
            "FinancialAccountBalanceSnapshot("
            f"movement_count={self.movement_count}, "
            f"has_opening_balance={self.has_opening_balance}, "
            "<identity-and-money-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialStatementEntry:
    """One real Movement plus the deterministic balance immediately after it."""

    movement: FinancialMovementRecord
    balance_after: Money

    def __post_init__(self) -> None:
        if not isinstance(self.movement, FinancialMovementRecord):
            raise TypeError("movement must be FinancialMovementRecord")
        _require_currency(
            self.balance_after,
            self.movement.amount.currency,
            "balance_after",
        )

    def __repr__(self) -> str:
        return "FinancialStatementEntry(<movement-and-balance-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialAccountStatement:
    """Canonical cash statement composed only of real Movement events."""

    account_id: UUID
    currency: str
    opening_balance: Money | None
    entries: tuple[FinancialStatementEntry, ...]
    closing_balance: Money
    calculated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise TypeError("entries must be tuple")
        if self.opening_balance is not None:
            _require_currency(self.opening_balance, self.currency, "opening_balance")
        _require_currency(self.closing_balance, self.currency, "closing_balance")
        _require_aware_datetime(self.calculated_at, "calculated_at")
        for entry in self.entries:
            if not isinstance(entry, FinancialStatementEntry):
                raise TypeError("entries must contain FinancialStatementEntry")
            if entry.movement.account_id != self.account_id:
                raise FinancialLedgerStateError("statement Movement account mismatch")
            _require_currency(entry.movement.amount, self.currency, "movement amount")
            _require_currency(entry.balance_after, self.currency, "balance_after")

    @property
    def has_opening_balance(self) -> bool:
        return self.opening_balance is not None

    def __repr__(self) -> str:
        return (
            "FinancialAccountStatement("
            f"entries={len(self.entries)}, "
            f"has_opening_balance={self.has_opening_balance}, "
            "<identity-and-money-redacted>)"
        )


def derive_financial_account_balance_and_statement(
    *,
    account: FinancialAccountRecord,
    opening_balance: FinancialOpeningBalanceRecord | None,
    movements: tuple[FinancialMovementRecord, ...],
    calculated_at: datetime,
) -> tuple[FinancialAccountBalanceSnapshot, FinancialAccountStatement]:
    """Derive snapshot and running statement without mutating or inventing ledger rows."""
    if not isinstance(account, FinancialAccountRecord):
        raise TypeError("account must be FinancialAccountRecord")
    if opening_balance is not None and not isinstance(
        opening_balance, FinancialOpeningBalanceRecord
    ):
        raise TypeError("opening_balance must be FinancialOpeningBalanceRecord or None")
    if not isinstance(movements, tuple):
        raise TypeError("movements must be tuple")
    _require_aware_datetime(calculated_at, "calculated_at")

    currency = account.currency
    if opening_balance is not None:
        if opening_balance.account_id != account.id:
            raise FinancialLedgerStateError("opening balance account mismatch")
        _require_currency(opening_balance.amount, currency, "opening balance")

    seen_ids: set[UUID] = set()
    ordered: list[FinancialMovementRecord] = []
    for movement in movements:
        if not isinstance(movement, FinancialMovementRecord):
            raise TypeError("movements must contain FinancialMovementRecord")
        if movement.id in seen_ids:
            raise FinancialLedgerStateError("duplicate Movement in statement input")
        seen_ids.add(movement.id)
        if movement.account_id != account.id:
            raise FinancialLedgerStateError("Movement account mismatch")
        _require_currency(movement.amount, currency, "Movement amount")
        ordered.append(movement)

    ordered.sort(
        key=lambda movement: (
            movement.effective_date,
            movement.created_at,
            movement.id.int,
        )
    )

    zero = Money(Decimal("0"), currency)
    running = opening_balance.amount if opening_balance is not None else zero
    movement_net = zero
    entries: list[FinancialStatementEntry] = []

    for movement in ordered:
        movement_net = movement_net + movement.amount
        running = running + movement.amount
        entries.append(
            FinancialStatementEntry(
                movement=movement,
                balance_after=running,
            )
        )

    opening_money = opening_balance.amount if opening_balance is not None else None
    snapshot = FinancialAccountBalanceSnapshot(
        account_id=account.id,
        currency=currency,
        opening_balance=opening_money,
        movement_net=movement_net,
        current_balance=running,
        movement_count=len(ordered),
        calculated_at=calculated_at,
    )
    statement = FinancialAccountStatement(
        account_id=account.id,
        currency=currency,
        opening_balance=opening_money,
        entries=tuple(entries),
        closing_balance=running,
        calculated_at=calculated_at,
    )
    return snapshot, statement


def _require_currency(money: Money, currency: str, field_name: str) -> None:
    if not isinstance(money, Money):
        raise TypeError(f"{field_name} must be Money")
    if money.currency != currency:
        raise FinancialLedgerStateError(f"{field_name} currency mismatch")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "FinancialAccountBalanceSnapshot",
    "FinancialAccountStatement",
    "FinancialLedgerStateError",
    "FinancialStatementEntry",
    "derive_financial_account_balance_and_statement",
]
