"""Pluggy-specific read-only implementation of the neutral banking boundary."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import NoReturn, TypeVar

from meufinanceiro_banking import (
    AccountType,
    BankingProviderError,
    Capability,
    CapabilitySource,
    CapabilityState,
    ConnectionCapability,
    ConnectionIntent,
    ConnectionState,
    ConnectionStatus,
    ExternalAccount,
    ExternalCreditCardBill,
    ExternalInvestment,
    ExternalLoan,
    ExternalPage,
    ExternalTransaction,
    InstallmentMetadata,
    ProviderErrorCategory,
    RefreshRequest,
    TransactionStatus,
)

from .gateway import (
    PluggyAccountKind,
    PluggyAccountSnapshot,
    PluggyCapability,
    PluggyCapabilityAvailability,
    PluggyCapabilityEvidence,
    PluggyCapabilitySnapshot,
    PluggyConnectionPhase,
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
    PluggyInstallmentSnapshot,
    PluggyItemSnapshot,
    PluggyReadOnlyGateway,
    PluggyTransactionPageSnapshot,
    PluggyTransactionSnapshot,
    PluggyTransactionState,
)

Result = TypeVar("Result")

_PHASE_TO_STATUS = {
    PluggyConnectionPhase.CONNECTING: ConnectionStatus.PENDING_USER_ACTION,
    PluggyConnectionPhase.SYNCING: ConnectionStatus.SYNCING,
    PluggyConnectionPhase.AVAILABLE: ConnectionStatus.AVAILABLE,
    PluggyConnectionPhase.PARTIAL: ConnectionStatus.PARTIAL,
    PluggyConnectionPhase.USER_ACTION_REQUIRED: ConnectionStatus.PENDING_USER_ACTION,
    PluggyConnectionPhase.REAUTHENTICATION_REQUIRED: (
        ConnectionStatus.REAUTHENTICATION_REQUIRED
    ),
    PluggyConnectionPhase.TEMPORARILY_UNAVAILABLE: (
        ConnectionStatus.TEMPORARILY_UNAVAILABLE
    ),
    PluggyConnectionPhase.RATE_LIMITED: ConnectionStatus.RATE_LIMITED,
    PluggyConnectionPhase.DISCONNECTED: ConnectionStatus.DISCONNECTED,
    PluggyConnectionPhase.FAILED: ConnectionStatus.FAILED,
}

_CAPABILITY_TO_NEUTRAL = {
    PluggyCapability.IDENTITY: Capability.IDENTITY,
    PluggyCapability.BANK_ACCOUNTS: Capability.BANK_ACCOUNTS,
    PluggyCapability.CREDIT_ACCOUNTS: Capability.CREDIT_ACCOUNTS,
    PluggyCapability.TRANSACTIONS: Capability.TRANSACTIONS,
}

_AVAILABILITY_TO_STATE = {
    PluggyCapabilityAvailability.AVAILABLE: CapabilityState.SUPPORTED,
    PluggyCapabilityAvailability.UNAVAILABLE: CapabilityState.NOT_AVAILABLE,
    PluggyCapabilityAvailability.USER_ACTION_REQUIRED: (
        CapabilityState.REQUIRES_USER_ACTION
    ),
    PluggyCapabilityAvailability.NOT_OBSERVED: CapabilityState.NOT_OBSERVED,
    PluggyCapabilityAvailability.UNKNOWN: CapabilityState.UNKNOWN,
}

_EVIDENCE_TO_SOURCE = {
    PluggyCapabilityEvidence.CONTRACT: CapabilitySource.CONTRACT,
    PluggyCapabilityEvidence.OBSERVATION: CapabilitySource.OBSERVATION,
    PluggyCapabilityEvidence.OPERATION: CapabilitySource.OPERATION,
}

_ACCOUNT_KIND_TO_TYPE = {
    PluggyAccountKind.BANK: AccountType.BANK,
    PluggyAccountKind.CREDIT: AccountType.CREDIT,
    PluggyAccountKind.OTHER: AccountType.OTHER,
}

_TRANSACTION_STATE_TO_STATUS = {
    PluggyTransactionState.POSTED: TransactionStatus.CONFIRMED,
    PluggyTransactionState.PENDING: TransactionStatus.PENDING,
}

_GATEWAY_ERROR_TO_PROVIDER = {
    PluggyGatewayErrorCategory.AUTHENTICATION: ProviderErrorCategory.AUTHENTICATION,
    PluggyGatewayErrorCategory.AUTHORIZATION: ProviderErrorCategory.AUTHORIZATION,
    PluggyGatewayErrorCategory.NOT_FOUND: ProviderErrorCategory.NOT_FOUND,
    PluggyGatewayErrorCategory.INVALID_REQUEST: ProviderErrorCategory.INVALID_REQUEST,
    PluggyGatewayErrorCategory.REQUIRES_USER_ACTION: (
        ProviderErrorCategory.REQUIRES_USER_ACTION
    ),
    PluggyGatewayErrorCategory.RATE_LIMITED: ProviderErrorCategory.RATE_LIMITED,
    PluggyGatewayErrorCategory.TEMPORARILY_UNAVAILABLE: (
        ProviderErrorCategory.TEMPORARILY_UNAVAILABLE
    ),
    PluggyGatewayErrorCategory.CONFLICT: ProviderErrorCategory.CONFLICT,
    PluggyGatewayErrorCategory.INTERNAL: ProviderErrorCategory.INTERNAL,
}


class PluggyBankingProvider:
    """Translate sanitized Pluggy snapshots into provider-neutral DTOs."""

    def __init__(self, gateway: PluggyReadOnlyGateway) -> None:
        self._gateway = gateway

    @property
    def provider_name(self) -> str:
        return "pluggy"

    def create_connection_intent(
        self,
        residence_id: str,
        actor_id: str,
    ) -> ConnectionIntent:
        del residence_id, actor_id
        self._unsupported()

    def create_reauthentication_intent(
        self,
        external_connection_id: str,
        actor_id: str,
    ) -> ConnectionIntent:
        del external_connection_id, actor_id
        self._unsupported()

    def get_connection(self, external_connection_id: str) -> ConnectionState:
        item_id = self._clean_identifier(external_connection_id, "external_connection_id")
        item = self._call_gateway(lambda: self._gateway.get_item(item_id))
        if item.item_id != item_id:
            self._invalid_snapshot()
        return self._normalize(lambda: self._map_item(item))

    def get_capabilities(
        self,
        external_connection_id: str,
    ) -> tuple[ConnectionCapability, ...]:
        return self.get_connection(external_connection_id).capabilities

    def list_accounts(
        self,
        external_connection_id: str,
    ) -> tuple[ExternalAccount, ...]:
        item_id = self._clean_identifier(external_connection_id, "external_connection_id")
        snapshots = self._call_gateway(lambda: self._gateway.list_accounts(item_id))
        if any(snapshot.item_id != item_id for snapshot in snapshots):
            self._invalid_snapshot()
        return self._normalize(
            lambda: tuple(self._map_account(snapshot) for snapshot in snapshots)
        )

    def list_transactions(
        self,
        external_account_id: str,
        cursor: str | None,
        changed_since: datetime | None,
    ) -> ExternalPage[ExternalTransaction]:
        account_id = self._clean_identifier(external_account_id, "external_account_id")
        normalized_cursor = self._clean_optional_identifier(cursor, "cursor")
        self._require_aware(changed_since, "changed_since")
        snapshot = self._call_gateway(
            lambda: self._gateway.list_transactions(
                account_id,
                normalized_cursor,
                changed_since,
            )
        )
        if any(record.account_id != account_id for record in snapshot.records):
            self._invalid_snapshot()
        return self._normalize(lambda: self._map_transaction_page(snapshot))

    def list_credit_card_bills(
        self,
        external_account_id: str,
    ) -> tuple[ExternalCreditCardBill, ...]:
        del external_account_id
        self._unsupported()

    def list_investments(
        self,
        external_connection_id: str,
    ) -> tuple[ExternalInvestment, ...]:
        del external_connection_id
        self._unsupported()

    def list_loans(
        self,
        external_connection_id: str,
    ) -> tuple[ExternalLoan, ...]:
        del external_connection_id
        self._unsupported()

    def request_refresh(
        self,
        external_connection_id: str,
        actor_id: str,
    ) -> RefreshRequest:
        del external_connection_id, actor_id
        self._unsupported()

    def disconnect(self, external_connection_id: str, actor_id: str) -> None:
        del external_connection_id, actor_id
        self._unsupported()

    @staticmethod
    def _map_item(item: PluggyItemSnapshot) -> ConnectionState:
        status = _PHASE_TO_STATUS[item.phase]
        return ConnectionState(
            external_connection_id=item.item_id,
            status=status,
            capabilities=tuple(
                PluggyBankingProvider._map_capability(snapshot)
                for snapshot in item.capabilities
            ),
            last_successful_sync_at=item.last_successful_update_at,
            last_attempt_at=item.last_attempt_at,
            next_refresh_allowed_at=item.next_refresh_allowed_at,
            consent_expires_at=item.consent_expires_at,
            requires_user_action=status
            in {
                ConnectionStatus.PENDING_USER_ACTION,
                ConnectionStatus.REAUTHENTICATION_REQUIRED,
            },
            provider_reason_code=item.provider_reason_code,
        )

    @staticmethod
    def _map_capability(
        snapshot: PluggyCapabilitySnapshot,
    ) -> ConnectionCapability:
        return ConnectionCapability(
            capability=_CAPABILITY_TO_NEUTRAL[snapshot.capability],
            state=_AVAILABILITY_TO_STATE[snapshot.availability],
            observed_at=snapshot.observed_at,
            source=_EVIDENCE_TO_SOURCE[snapshot.evidence],
            provider_reason_code=snapshot.provider_reason_code,
        )

    @staticmethod
    def _map_account(snapshot: PluggyAccountSnapshot) -> ExternalAccount:
        return ExternalAccount(
            external_account_id=snapshot.account_id,
            external_connection_id=snapshot.item_id,
            account_type=_ACCOUNT_KIND_TO_TYPE[snapshot.kind],
            subtype=snapshot.subtype,
            currency=snapshot.currency,
            name=snapshot.name,
            number_mask=snapshot.number_mask,
        )

    @staticmethod
    def _map_transaction_page(
        snapshot: PluggyTransactionPageSnapshot,
    ) -> ExternalPage[ExternalTransaction]:
        return ExternalPage(
            records=tuple(
                PluggyBankingProvider._map_transaction(record)
                for record in snapshot.records
            ),
            next_cursor=snapshot.next_cursor,
            source_window=snapshot.source_window,
            retrieved_at=snapshot.retrieved_at,
        )

    @staticmethod
    def _map_transaction(
        snapshot: PluggyTransactionSnapshot,
    ) -> ExternalTransaction:
        installment = snapshot.installment
        return ExternalTransaction(
            external_account_id=snapshot.account_id,
            status=_TRANSACTION_STATE_TO_STATUS[snapshot.state],
            effective_date=snapshot.effective_date,
            amount=snapshot.amount,
            currency=snapshot.currency,
            external_transaction_id=snapshot.transaction_id,
            provider_updated_at=snapshot.updated_at,
            description=snapshot.description,
            category=snapshot.category,
            bill_reference=snapshot.bill_reference,
            installment_metadata=(
                PluggyBankingProvider._map_installment(installment)
                if installment is not None
                else None
            ),
        )

    @staticmethod
    def _map_installment(
        snapshot: PluggyInstallmentSnapshot,
    ) -> InstallmentMetadata:
        return InstallmentMetadata(
            installment_number=snapshot.number,
            installment_count=snapshot.count,
            total_amount=snapshot.total_amount,
        )

    @staticmethod
    def _call_gateway(operation: Callable[[], Result]) -> Result:
        try:
            return operation()
        except PluggyGatewayError as error:
            raise BankingProviderError(
                _GATEWAY_ERROR_TO_PROVIDER[error.category],
                retryable=error.retryable,
                provider_reason_code=error.provider_reason_code,
                safe_message="provider read operation failed",
            ) from None
        except Exception:
            raise BankingProviderError(
                ProviderErrorCategory.INTERNAL,
                retryable=False,
                safe_message="provider gateway failed",
            ) from None

    @staticmethod
    def _normalize(operation: Callable[[], Result]) -> Result:
        try:
            return operation()
        except (KeyError, TypeError, ValueError):
            PluggyBankingProvider._invalid_snapshot()

    @staticmethod
    def _clean_identifier(value: str, field_name: str) -> str:
        if not isinstance(value, str):
            PluggyBankingProvider._invalid_request()
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 512
            or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
        ):
            PluggyBankingProvider._invalid_request()
        return normalized

    @staticmethod
    def _clean_optional_identifier(value: str | None, field_name: str) -> str | None:
        if value is None:
            return None
        return PluggyBankingProvider._clean_identifier(value, field_name)

    @staticmethod
    def _require_aware(value: datetime | None, field_name: str) -> None:
        del field_name
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            PluggyBankingProvider._invalid_request()

    @staticmethod
    def _invalid_request() -> NoReturn:
        raise BankingProviderError(
            ProviderErrorCategory.INVALID_REQUEST,
            retryable=False,
            safe_message="provider read request is invalid",
        ) from None

    @staticmethod
    def _invalid_snapshot() -> NoReturn:
        raise BankingProviderError(
            ProviderErrorCategory.INTERNAL,
            retryable=False,
            safe_message="provider snapshot could not be normalized",
        ) from None

    @staticmethod
    def _unsupported() -> NoReturn:
        raise BankingProviderError(
            ProviderErrorCategory.UNSUPPORTED,
            retryable=False,
            safe_message="operation is not supported by the read-only adapter",
        ) from None
