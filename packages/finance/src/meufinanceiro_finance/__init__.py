"""Canonical financial domain contracts for MeuFinanceiro."""

from meufinanceiro_finance.access import (
    FinancialAccessDeniedError,
    FinancialActorContext,
    FinancialResourceAudience,
    FinancialVisibilityScope,
    can_access_financial_resource,
    require_financial_resource_access,
)
from meufinanceiro_finance.accounts import (
    FinancialAccountDraft,
    FinancialAccountRecord,
    FinancialAccountStatus,
    FinancialAccountType,
)
from meufinanceiro_finance.allocation_records import (
    FinancialMovementAllocationRecord,
    FinancialMovementAllocationSetRecord,
)
from meufinanceiro_finance.allocations import (
    FinancialMovementAllocationDraft,
    FinancialMovementAllocationRevisionDraft,
    FinancialMovementAllocationSetDraft,
    is_category_audience_compatible_for_movement,
)
from meufinanceiro_finance.audit_event_records import FinancialAuditEventRecord
from meufinanceiro_finance.audit_events import (
    FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION,
    FinancialAuditEventDraft,
    FinancialAuditEventType,
    FinancialAuditSubjectType,
    financial_audit_related_subject_type_for_event,
    financial_audit_subject_type_for_event,
)
from meufinanceiro_finance.balance_statement import (
    FinancialAccountBalanceSnapshot,
    FinancialAccountStatement,
    FinancialLedgerStateError,
    FinancialStatementEntry,
    derive_financial_account_balance_and_statement,
)
from meufinanceiro_finance.categories import (
    FinancialCategoryDraft,
    FinancialCategoryRecord,
    FinancialCategoryStatus,
)
from meufinanceiro_finance.ids import (
    new_financial_resource_id,
    validate_financial_resource_id,
)
from meufinanceiro_finance.manual_entries import (
    FinancialManualEntryDraft,
    FinancialManualEntryMovementStore,
    FinancialManualEntryService,
    FinancialManualEntryType,
)
from meufinanceiro_finance.money import (
    CurrencyMismatchError,
    Money,
    RoundingMode,
    validate_currency_code,
)
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.movements import (
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialMovementRole,
    FinancialResultEffect,
)
from meufinanceiro_finance.opening_balances import (
    FinancialOpeningBalanceDraft,
    FinancialOpeningBalanceRecord,
)
from meufinanceiro_finance.operation_ids import (
    new_financial_idempotency_key,
    validate_financial_idempotency_key,
)
from meufinanceiro_finance.transfer_records import FinancialTransferRecord
from meufinanceiro_finance.transfers import (
    FinancialTransferDraft,
    FinancialTransferReversalDraft,
    FinancialTransferRole,
)

__all__ = [
    "FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION",
    "CurrencyMismatchError",
    "FinancialAccessDeniedError",
    "FinancialAccountBalanceSnapshot",
    "FinancialAccountDraft",
    "FinancialAccountRecord",
    "FinancialAccountStatement",
    "FinancialAccountStatus",
    "FinancialAccountType",
    "FinancialActorContext",
    "FinancialAuditEventDraft",
    "FinancialAuditEventRecord",
    "FinancialAuditEventType",
    "FinancialAuditSubjectType",
    "FinancialCategoryDraft",
    "FinancialCategoryRecord",
    "FinancialCategoryStatus",
    "FinancialLedgerStateError",
    "FinancialManualEntryDraft",
    "FinancialManualEntryMovementStore",
    "FinancialManualEntryService",
    "FinancialManualEntryType",
    "FinancialMovementAllocationDraft",
    "FinancialMovementAllocationRecord",
    "FinancialMovementAllocationRevisionDraft",
    "FinancialMovementAllocationSetDraft",
    "FinancialMovementAllocationSetRecord",
    "FinancialMovementDraft",
    "FinancialMovementRecord",
    "FinancialMovementReversalDraft",
    "FinancialMovementRole",
    "FinancialOpeningBalanceDraft",
    "FinancialOpeningBalanceRecord",
    "FinancialResourceAudience",
    "FinancialResultEffect",
    "FinancialStatementEntry",
    "FinancialTransferDraft",
    "FinancialTransferRecord",
    "FinancialTransferReversalDraft",
    "FinancialTransferRole",
    "FinancialVisibilityScope",
    "Money",
    "RoundingMode",
    "can_access_financial_resource",
    "derive_financial_account_balance_and_statement",
    "financial_audit_related_subject_type_for_event",
    "financial_audit_subject_type_for_event",
    "is_category_audience_compatible_for_movement",
    "new_financial_idempotency_key",
    "new_financial_resource_id",
    "require_financial_resource_access",
    "validate_currency_code",
    "validate_financial_idempotency_key",
    "validate_financial_resource_id",
]
