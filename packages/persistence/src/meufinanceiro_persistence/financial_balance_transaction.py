"""The canonical account balance, read inside the caller's transaction.

Same sources and same pure derivation as ``FinancialBalanceQueryService`` (opening
balance + every Movement of the account, reversals and transfer legs included),
read through the same transactional readers the stores use. The caller owns the
RLS context and the transaction; this module never commits and never writes. It
exists so a write that depends on the balance (a goal allocation, ADR-0029) can
read it atomically with that write without a second implementation of balance.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from meufinanceiro_finance import FinancialAccountRecord
from meufinanceiro_finance.balance_statement import (
    FinancialAccountBalanceSnapshot,
    derive_financial_account_balance_and_statement,
)
from sqlalchemy import Connection

from meufinanceiro_persistence.financial_movement_store import (
    list_account_movements_in_transaction,
)
from meufinanceiro_persistence.financial_opening_balance_store import (
    get_opening_balance_in_transaction,
)


def read_account_balance_in_transaction(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    account: FinancialAccountRecord,
    calculated_at: datetime,
) -> FinancialAccountBalanceSnapshot:
    """The canonical balance snapshot of ``account`` inside ``connection``."""
    opening_balance = get_opening_balance_in_transaction(
        connection,
        installation_id=installation_id,
        residence_id=residence_id,
        account_id=account.id,
    )
    movements = list_account_movements_in_transaction(
        connection,
        installation_id=installation_id,
        residence_id=residence_id,
        account_id=account.id,
    )
    snapshot, _ = derive_financial_account_balance_and_statement(
        account=account,
        opening_balance=opening_balance,
        movements=movements,
        calculated_at=calculated_at,
    )
    return snapshot


__all__ = ["read_account_balance_in_transaction"]
