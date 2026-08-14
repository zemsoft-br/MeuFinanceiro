"""Application orchestration for the authenticated financial core API."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountRecord,
    FinancialMovementRecord,
    FinancialOpeningBalanceDraft,
    FinancialOpeningBalanceRecord,
)


@runtime_checkable
class FinancialAccountStoreBoundary(Protocol):
    def create_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        draft: FinancialAccountDraft,
    ) -> FinancialAccountRecord: ...

    def list_accounts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialAccountRecord, ...]: ...

    def get_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountRecord: ...


@runtime_checkable
class FinancialOpeningBalanceStoreBoundary(Protocol):
    def create_opening_balance(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
        draft: FinancialOpeningBalanceDraft,
    ) -> FinancialOpeningBalanceRecord: ...

    def get_opening_balance(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialOpeningBalanceRecord | None: ...


@runtime_checkable
class FinancialMovementStoreBoundary(Protocol):
    def get_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> FinancialMovementRecord: ...

    def list_movements(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialMovementRecord, ...]: ...


class FinancialCoreService:
    """Delegate financial API operations to canonical persistence boundaries."""

    def __init__(
        self,
        account_store: FinancialAccountStoreBoundary,
        opening_balance_store: FinancialOpeningBalanceStoreBoundary,
        movement_store: FinancialMovementStoreBoundary,
    ) -> None:
        if not isinstance(account_store, FinancialAccountStoreBoundary):
            raise TypeError("account_store must satisfy FinancialAccountStoreBoundary")
        if not isinstance(opening_balance_store, FinancialOpeningBalanceStoreBoundary):
            raise TypeError(
                "opening_balance_store must satisfy FinancialOpeningBalanceStoreBoundary"
            )
        if not isinstance(movement_store, FinancialMovementStoreBoundary):
            raise TypeError(
                "movement_store must satisfy FinancialMovementStoreBoundary"
            )
        self._accounts = account_store
        self._opening_balances = opening_balance_store
        self._movements = movement_store

    def create_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        draft: FinancialAccountDraft,
    ) -> FinancialAccountRecord:
        return self._accounts.create_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            draft=draft,
        )

    def list_accounts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialAccountRecord, ...]:
        return self._accounts.list_accounts(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
        )

    def get_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountRecord:
        return self._accounts.get_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )

    def create_opening_balance(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
        draft: FinancialOpeningBalanceDraft,
    ) -> FinancialOpeningBalanceRecord:
        return self._opening_balances.create_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
            draft=draft,
        )

    def get_opening_balance(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialOpeningBalanceRecord | None:
        # Resolve the account first so a missing/invisible account remains a 404
        # instead of being conflated with a visible account that has no anchor.
        self._accounts.get_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
        return self._opening_balances.get_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )

    def get_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> FinancialMovementRecord:
        return self._movements.get_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            movement_id=movement_id,
        )

    def list_movements(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialMovementRecord, ...]:
        return self._movements.list_movements(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )


__all__ = [
    "FinancialAccountStoreBoundary",
    "FinancialCoreService",
    "FinancialMovementStoreBoundary",
    "FinancialOpeningBalanceStoreBoundary",
]
