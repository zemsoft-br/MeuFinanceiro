"""Application orchestration for the authenticated financial core API."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_finance import (
    FinancialAccountBalanceSnapshot,
    FinancialAccountDraft,
    FinancialAccountRecord,
    FinancialAccountStatement,
    FinancialManualEntryDraft,
    FinancialManualEntryService,
    FinancialMovementRecord,
    FinancialMovementReversalDraft,
    FinancialOpeningBalanceDraft,
    FinancialOpeningBalanceRecord,
    FinancialTransferDraft,
    FinancialTransferRecord,
    FinancialTransferReversalDraft,
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
    def create_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: object,
    ) -> FinancialMovementRecord: ...

    def reverse_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialMovementReversalDraft,
    ) -> FinancialMovementRecord: ...

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


@runtime_checkable
class FinancialTransferStoreBoundary(Protocol):
    def create_transfer(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialTransferDraft,
    ) -> FinancialTransferRecord: ...

    def reverse_transfer(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialTransferReversalDraft,
    ) -> FinancialTransferRecord: ...


@runtime_checkable
class FinancialBalanceQueryBoundary(Protocol):
    def get_balance_snapshot(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountBalanceSnapshot: ...

    def get_statement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountStatement: ...


class FinancialCoreService:
    """Delegate financial API operations to canonical domain/persistence boundaries."""

    def __init__(
        self,
        account_store: FinancialAccountStoreBoundary,
        opening_balance_store: FinancialOpeningBalanceStoreBoundary,
        movement_store: FinancialMovementStoreBoundary,
        transfer_store: FinancialTransferStoreBoundary,
        balance_query: FinancialBalanceQueryBoundary,
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
        if not isinstance(transfer_store, FinancialTransferStoreBoundary):
            raise TypeError(
                "transfer_store must satisfy FinancialTransferStoreBoundary"
            )
        if not isinstance(balance_query, FinancialBalanceQueryBoundary):
            raise TypeError(
                "balance_query must satisfy FinancialBalanceQueryBoundary"
            )
        self._accounts = account_store
        self._opening_balances = opening_balance_store
        self._movements = movement_store
        self._manual_entries = FinancialManualEntryService(movement_store)
        self._transfers = transfer_store
        self._balance_query = balance_query

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

    def record_manual_entry(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialManualEntryDraft,
    ) -> FinancialMovementRecord:
        return self._manual_entries.record(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )

    def reverse_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialMovementReversalDraft,
    ) -> FinancialMovementRecord:
        return self._movements.reverse_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
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

    def create_transfer(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialTransferDraft,
    ) -> FinancialTransferRecord:
        return self._transfers.create_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )

    def reverse_transfer(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialTransferReversalDraft,
    ) -> FinancialTransferRecord:
        return self._transfers.reverse_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )

    def get_balance_snapshot(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountBalanceSnapshot:
        return self._balance_query.get_balance_snapshot(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )

    def get_statement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountStatement:
        return self._balance_query.get_statement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )


__all__ = [
    "FinancialAccountStoreBoundary",
    "FinancialBalanceQueryBoundary",
    "FinancialCoreService",
    "FinancialMovementStoreBoundary",
    "FinancialOpeningBalanceStoreBoundary",
    "FinancialTransferStoreBoundary",
]
