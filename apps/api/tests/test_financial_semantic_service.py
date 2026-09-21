from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from meufinanceiro_finance import (
    FinancialAccountBalanceSnapshot,
    FinancialAccountDraft,
    FinancialAccountRecord,
    FinancialAccountStatement,
    FinancialAccountStatus,
    FinancialAccountType,
    FinancialManualEntryDraft,
    FinancialManualEntryType,
    FinancialMovementDraft,
    FinancialMovementRecord,
    FinancialMovementReversalDraft,
    FinancialMovementRole,
    FinancialOpeningBalanceDraft,
    FinancialOpeningBalanceRecord,
    FinancialResultEffect,
    FinancialTransferDraft,
    FinancialTransferRecord,
    FinancialTransferReversalDraft,
    FinancialTransferRole,
    FinancialVisibilityScope,
    Money,
)

from app.services.financial_core import FinancialCoreService

INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
OPERATOR_ID = UUID("30000000-0000-4000-8000-000000000003")
ACCOUNT_ID = UUID("40000000-0000-4000-8000-000000000004")
OTHER_ACCOUNT_ID = UUID("50000000-0000-4000-8000-000000000005")
MOVEMENT_ID = UUID("60000000-0000-4000-8000-000000000006")
REVERSAL_ID = UUID("70000000-0000-4000-8000-000000000007")
TRANSFER_ID = UUID("80000000-0000-4000-8000-000000000008")
SOURCE_LEG_ID = UUID("90000000-0000-4000-8000-000000000009")
DESTINATION_LEG_ID = UUID("a0000000-0000-4000-8000-00000000000a")
IDEMPOTENCY_KEY = UUID("b0000000-0000-4000-8000-00000000000b")
NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)


class AccountStore:
    def create_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        draft: FinancialAccountDraft,
    ) -> FinancialAccountRecord:
        return self.get_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=ACCOUNT_ID,
        )

    def list_accounts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialAccountRecord, ...]:
        return (
            self.get_account(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                account_id=ACCOUNT_ID,
            ),
        )

    def get_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountRecord:
        return FinancialAccountRecord(
            id=account_id,
            residence_id=residence_id,
            owner_operator_id=operator_id,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
            account_type=FinancialAccountType.CHECKING,
            custom_type_name=None,
            name="Conta teste",
            currency="BRL",
            status=FinancialAccountStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            archived_at=None,
        )


class OpeningBalanceStore:
    def create_opening_balance(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
        draft: FinancialOpeningBalanceDraft,
    ) -> FinancialOpeningBalanceRecord:
        return FinancialOpeningBalanceRecord(
            id=UUID("c0000000-0000-4000-8000-00000000000c"),
            residence_id=residence_id,
            account_id=account_id,
            amount=draft.amount,
            effective_date=draft.effective_date,
            created_by_operator_id=operator_id,
            created_at=NOW,
        )

    def get_opening_balance(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialOpeningBalanceRecord | None:
        return None


class MovementStore:
    def __init__(self) -> None:
        self.created: FinancialMovementDraft | None = None
        self.reversed: FinancialMovementReversalDraft | None = None

    def create_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialMovementDraft,
    ) -> FinancialMovementRecord:
        self.created = draft
        return FinancialMovementRecord(
            id=MOVEMENT_ID,
            account_id=draft.account_id,
            amount=draft.amount,
            result_effect=draft.result_effect,
            role=FinancialMovementRole.STANDARD,
            effective_date=draft.effective_date,
            competence_date=draft.competence_date,
            description=draft.description,
            reversal_of_id=None,
            reversal_reason=None,
            created_by_operator_id=operator_id,
            created_at=NOW,
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
        self.reversed = draft
        return FinancialMovementRecord(
            id=REVERSAL_ID,
            account_id=ACCOUNT_ID,
            amount=Money(Decimal("-10"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            role=FinancialMovementRole.REVERSAL,
            effective_date=draft.effective_date,
            competence_date=draft.competence_date,
            description=None,
            reversal_of_id=draft.movement_id,
            reversal_reason=draft.reason,
            created_by_operator_id=operator_id,
            created_at=NOW,
        )

    def get_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> FinancialMovementRecord:
        raise AssertionError("not used")

    def list_movements(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialMovementRecord, ...]:
        return ()


class TransferStore:
    def __init__(self) -> None:
        self.created: FinancialTransferDraft | None = None
        self.reversed: FinancialTransferReversalDraft | None = None
        self.listed_account_id: UUID | None = None

    def create_transfer(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialTransferDraft,
    ) -> FinancialTransferRecord:
        self.created = draft
        return _transfer_record(FinancialTransferRole.STANDARD, None)

    def reverse_transfer(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialTransferReversalDraft,
    ) -> FinancialTransferRecord:
        self.reversed = draft
        return _transfer_record(FinancialTransferRole.REVERSAL, draft.transfer_id)

    def list_transfers(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID | None = None,
    ) -> tuple[FinancialTransferRecord, ...]:
        self.listed_account_id = account_id
        return (_transfer_record(FinancialTransferRole.STANDARD, None),)


class BalanceQuery:
    def get_balance_snapshot(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountBalanceSnapshot:
        return FinancialAccountBalanceSnapshot(
            account_id=account_id,
            currency="BRL",
            opening_balance=Money(Decimal("100"), "BRL"),
            movement_net=Money(Decimal("25"), "BRL"),
            current_balance=Money(Decimal("125"), "BRL"),
            movement_count=2,
            calculated_at=NOW,
        )

    def get_statement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountStatement:
        return FinancialAccountStatement(
            account_id=account_id,
            currency="BRL",
            opening_balance=Money(Decimal("100"), "BRL"),
            entries=(),
            closing_balance=Money(Decimal("100"), "BRL"),
            calculated_at=NOW,
        )


def _transfer_record(
    role: FinancialTransferRole,
    reversal_of_id: UUID | None,
) -> FinancialTransferRecord:
    return FinancialTransferRecord(
        id=TRANSFER_ID if role is FinancialTransferRole.STANDARD else REVERSAL_ID,
        source_account_id=ACCOUNT_ID,
        destination_account_id=OTHER_ACCOUNT_ID,
        currency="BRL",
        source_movement_id=SOURCE_LEG_ID,
        destination_movement_id=DESTINATION_LEG_ID,
        role=role,
        reversal_of_id=reversal_of_id,
        created_by_operator_id=OPERATOR_ID,
        created_at=NOW,
    )


def _service() -> tuple[FinancialCoreService, MovementStore, TransferStore]:
    movements = MovementStore()
    transfers = TransferStore()
    service = FinancialCoreService(
        AccountStore(),
        OpeningBalanceStore(),
        movements,
        transfers,
        BalanceQuery(),
    )
    return service, movements, transfers


def test_manual_expense_uses_canonical_manual_entry_translation() -> None:
    service, movements, _ = _service()
    result = service.record_manual_entry(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        operator_id=OPERATOR_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        draft=FinancialManualEntryDraft(
            account_id=ACCOUNT_ID,
            magnitude=Money(Decimal("42.50"), "BRL"),
            entry_type=FinancialManualEntryType.EXPENSE,
            effective_date=date(2026, 9, 20),
            competence_date=date(2026, 9, 20),
            description="Mercado",
        ),
    )

    assert movements.created is not None
    assert movements.created.amount == Money(Decimal("-42.50"), "BRL")
    assert movements.created.result_effect is FinancialResultEffect.EXPENSE
    assert result.amount == movements.created.amount


def test_movement_reversal_delegates_without_caller_amount() -> None:
    service, movements, _ = _service()
    draft = FinancialMovementReversalDraft(
        movement_id=MOVEMENT_ID,
        effective_date=date(2026, 9, 20),
        competence_date=date(2026, 9, 20),
        reason="Correção",
    )

    result = service.reverse_movement(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        operator_id=OPERATOR_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        draft=draft,
    )

    assert movements.reversed == draft
    assert result.role is FinancialMovementRole.REVERSAL
    assert result.reversal_of_id == MOVEMENT_ID


def test_transfer_and_reversal_delegate_to_atomic_transfer_boundary() -> None:
    service, _, transfers = _service()
    transfer = FinancialTransferDraft(
        source_account_id=ACCOUNT_ID,
        destination_account_id=OTHER_ACCOUNT_ID,
        magnitude=Money(Decimal("25"), "BRL"),
        effective_date=date(2026, 9, 20),
        competence_date=date(2026, 9, 20),
        description="Reserva",
    )
    created = service.create_transfer(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        operator_id=OPERATOR_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        draft=transfer,
    )

    reversal = FinancialTransferReversalDraft(
        transfer_id=created.id,
        effective_date=date(2026, 9, 20),
        competence_date=date(2026, 9, 20),
        reason="Correção",
    )
    reversed_record = service.reverse_transfer(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        operator_id=OPERATOR_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        draft=reversal,
    )
    listed = service.list_transfers(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        operator_id=OPERATOR_ID,
        account_id=ACCOUNT_ID,
    )

    assert transfers.created == transfer
    assert transfers.reversed == reversal
    assert transfers.listed_account_id == ACCOUNT_ID
    assert listed[0].id == TRANSFER_ID
    assert reversed_record.role is FinancialTransferRole.REVERSAL


def test_balance_and_statement_delegate_to_derived_query() -> None:
    service, _, _ = _service()

    balance = service.get_balance_snapshot(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        operator_id=OPERATOR_ID,
        account_id=ACCOUNT_ID,
    )
    statement = service.get_statement(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        operator_id=OPERATOR_ID,
        account_id=ACCOUNT_ID,
    )

    assert balance.current_balance == Money(Decimal("125"), "BRL")
    assert statement.closing_balance == Money(Decimal("100"), "BRL")
