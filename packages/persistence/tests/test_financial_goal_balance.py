"""The balance a goal allocation depends on is the canonical one, not a copy."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from meufinanceiro_finance import (
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialOpeningBalanceDraft,
    FinancialResultEffect,
    FinancialTransferDraft,
    Money,
    new_financial_idempotency_key,
)

from meufinanceiro_persistence.financial_account_store import (
    FinancialAccountStore,
    get_account_in_transaction,
)
from meufinanceiro_persistence.financial_balance_query import (
    FinancialBalanceQueryService,
)
from meufinanceiro_persistence.financial_balance_transaction import (
    read_account_balance_in_transaction,
)
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementStore,
    _set_context,
)
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceStore,
)
from meufinanceiro_persistence.financial_transfer_store import FinancialTransferStore

if TYPE_CHECKING:
    from conftest import BudgetWorld


def _money(amount: str) -> Money:
    return Money(Decimal(amount), "BRL")


def _move(world: BudgetWorld, account_id: UUID, amount: str, day: int) -> UUID:
    effect = (
        FinancialResultEffect.INCOME
        if Decimal(amount) > 0
        else FinancialResultEffect.EXPENSE
    )
    return (
        FinancialMovementStore(world.runtime)
        .create_movement(
            **world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementDraft(
                account_id=account_id,
                amount=_money(amount),
                result_effect=effect,
                effective_date=date(2026, 10, day),
                competence_date=date(2026, 10, day),
                description="Sintético",
            ),
        )
        .id
    )


def test_transactional_balance_equals_the_canonical_query_service(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    source = world.account()
    destination = world.account()
    FinancialOpeningBalanceStore(world.runtime).create_opening_balance(
        **world.scope(),
        account_id=source,
        draft=FinancialOpeningBalanceDraft(
            amount=_money("1234.56"), effective_date=date(2026, 1, 1)
        ),
    )
    spent = _move(world, source, "-100.25", 3)
    _move(world, source, "75.10", 4)
    _move(world, source, "-0.00000001", 5)
    FinancialMovementStore(world.runtime).reverse_movement(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=spent,
            effective_date=date(2026, 10, 8),
            competence_date=date(2026, 10, 8),
            reason="Sintético",
        ),
    )
    FinancialTransferStore(world.runtime).create_transfer(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialTransferDraft(
            source_account_id=source,
            destination_account_id=destination,
            magnitude=_money("300"),
            effective_date=date(2026, 10, 9),
            competence_date=date(2026, 10, 9),
            description="Sintético",
        ),
    )
    _move(world, destination, "20", 10)

    service = FinancialBalanceQueryService(
        FinancialAccountStore(world.runtime),
        FinancialOpeningBalanceStore(world.runtime),
        FinancialMovementStore(world.runtime),
    )
    for account_id in (source, destination):
        canonical = service.get_balance_snapshot(**world.scope(), account_id=account_id)
        with world.runtime.begin() as connection:
            _set_context(connection, **world.scope())
            account = get_account_in_transaction(
                connection,
                installation_id=world.installation_id,
                residence_id=world.residence_id,
                account_id=account_id,
            )
            assert account is not None
            snapshot = read_account_balance_in_transaction(
                connection,
                installation_id=world.installation_id,
                residence_id=world.residence_id,
                account=account,
                calculated_at=datetime.now(UTC),
            )
        assert snapshot.current_balance == canonical.current_balance
        assert snapshot.movement_count == canonical.movement_count
        assert snapshot.opening_balance == canonical.opening_balance

    # 1234.56 - 100.25 + 75.10 - 0.00000001 + 100.25 (reversal) - 300 (transfer)
    assert service.get_balance_snapshot(
        **world.scope(), account_id=source
    ).current_balance == _money("1009.65999999")
