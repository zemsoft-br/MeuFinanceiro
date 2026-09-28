"""Read-only orchestration for derived account balance and statement."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from meufinanceiro_finance import (
    FinancialAccountRecord,
    FinancialMovementRecord,
    FinancialOpeningBalanceRecord,
    validate_financial_resource_id,
)
from meufinanceiro_finance.balance_statement import (
    FinancialAccountBalanceSnapshot,
    FinancialAccountStatement,
    derive_financial_account_balance_and_statement,
)


class FinancialAccountReader(Protocol):
    def get_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountRecord: ...


class FinancialOpeningBalanceReader(Protocol):
    def get_opening_balance(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialOpeningBalanceRecord | None: ...


class FinancialMovementReader(Protocol):
    def list_movements(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialMovementRecord, ...]: ...


class FinancialBalanceQueryService:
    """Load canonical resources through existing RLS-aware stores and derive reads."""

    def __init__(
        self,
        account_store: FinancialAccountReader,
        opening_balance_store: FinancialOpeningBalanceReader,
        movement_store: FinancialMovementReader,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._account_store = account_store
        self._opening_balance_store = opening_balance_store
        self._movement_store = movement_store
        self._clock = clock or _utc_now

    def read_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialAccountBalanceSnapshot, FinancialAccountStatement]:
        """Return one deterministic snapshot + statement from the same read sequence."""
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_resource_id(account_id)

        account = self._account_store.get_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
        opening_balance = self._opening_balance_store.get_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
        movements = self._movement_store.list_movements(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
        calculated_at = self._clock()
        if (
            not isinstance(calculated_at, datetime)
            or calculated_at.tzinfo is None
            or calculated_at.utcoffset() is None
        ):
            raise ValueError("clock must return a timezone-aware datetime")

        return derive_financial_account_balance_and_statement(
            account=account,
            opening_balance=opening_balance,
            movements=movements,
            calculated_at=calculated_at,
        )

    def get_balance_snapshot(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountBalanceSnapshot:
        snapshot, _ = self.read_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
        return snapshot

    def get_statement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountStatement:
        _, statement = self.read_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
        return statement


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialAccountReader",
    "FinancialBalanceQueryService",
    "FinancialMovementReader",
    "FinancialOpeningBalanceReader",
]
