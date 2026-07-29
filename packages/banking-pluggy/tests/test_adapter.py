from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from meufinanceiro_banking import (
    AccountType,
    BankingProvider,
    BankingProviderError,
    Capability,
    CapabilitySource,
    CapabilityState,
    ConnectionStatus,
    ProviderErrorCategory,
    TransactionStatus,
)

from meufinanceiro_banking_pluggy import (
    PluggyAccountKind,
    PluggyAccountSnapshot,
    PluggyBankingProvider,
    PluggyCapability,
    PluggyCapabilityAvailability,
    PluggyCapabilityEvidence,
    PluggyCapabilitySnapshot,
    PluggyConnectionPhase,
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
    PluggyInstallmentSnapshot,
    PluggyItemSnapshot,
    PluggyTransactionPageSnapshot,
    PluggyTransactionSnapshot,
    PluggyTransactionState,
)

NOW = datetime(2026, 7, 29, 1, 0, tzinfo=UTC)
CHANGED_SINCE = datetime(2026, 7, 1, tzinfo=UTC)


def capability(
    name: PluggyCapability,
    availability: PluggyCapabilityAvailability = (
        PluggyCapabilityAvailability.AVAILABLE
    ),
) -> PluggyCapabilitySnapshot:
    return PluggyCapabilitySnapshot(
        capability=name,
        availability=availability,
        observed_at=NOW,
        evidence=PluggyCapabilityEvidence.OBSERVATION,
    )


def item_snapshot(item_id: str = "item-001") -> PluggyItemSnapshot:
    return PluggyItemSnapshot(
        item_id=item_id,
        phase=PluggyConnectionPhase.AVAILABLE,
        capabilities=(
            capability(PluggyCapability.IDENTITY),
            capability(PluggyCapability.BANK_ACCOUNTS),
            capability(PluggyCapability.TRANSACTIONS),
        ),
        last_successful_update_at=NOW,
        last_attempt_at=NOW,
    )


def account_snapshots(item_id: str = "item-001") -> tuple[PluggyAccountSnapshot, ...]:
    return (
        PluggyAccountSnapshot(
            account_id="account-bank",
            item_id=item_id,
            kind=PluggyAccountKind.BANK,
            subtype="CHECKING_ACCOUNT",
            currency="BRL",
            name="Conta corrente",
            number_mask="1234",
        ),
        PluggyAccountSnapshot(
            account_id="account-credit",
            item_id=item_id,
            kind=PluggyAccountKind.CREDIT,
            subtype="CREDIT_CARD",
            currency="BRL",
            name="Cartão",
            number_mask="9876",
        ),
    )


def transaction_page(
    account_id: str = "account-bank",
) -> PluggyTransactionPageSnapshot:
    return PluggyTransactionPageSnapshot(
        records=(
            PluggyTransactionSnapshot(
                account_id=account_id,
                transaction_id="transaction-posted",
                state=PluggyTransactionState.POSTED,
                effective_date=date(2026, 7, 20),
                amount=Decimal("125.40"),
                currency="BRL",
                updated_at=NOW,
                description="Compra confirmada",
                category="Alimentação",
                installment=PluggyInstallmentSnapshot(
                    number=2,
                    count=4,
                    total_amount=Decimal("501.60"),
                ),
            ),
            PluggyTransactionSnapshot(
                account_id=account_id,
                transaction_id="transaction-pending",
                state=PluggyTransactionState.PENDING,
                effective_date=date(2026, 7, 21),
                amount=Decimal("10.00"),
                currency="BRL",
                updated_at=NOW,
                description="Compra pendente",
            ),
        ),
        next_cursor="opaque-next-cursor",
        source_window="synthetic-window-001",
        retrieved_at=NOW,
    )


class GatewayStub:
    def __init__(self) -> None:
        self.item = item_snapshot()
        self.accounts = account_snapshots()
        self.page = transaction_page()
        self.error: Exception | None = None
        self.calls: list[tuple[str, object]] = []

    def _raise_if_configured(self) -> None:
        if self.error is not None:
            raise self.error

    def get_item(self, item_id: str) -> PluggyItemSnapshot:
        self.calls.append(("get_item", item_id))
        self._raise_if_configured()
        return self.item

    def list_accounts(self, item_id: str) -> tuple[PluggyAccountSnapshot, ...]:
        self.calls.append(("list_accounts", item_id))
        self._raise_if_configured()
        return self.accounts

    def list_transactions(
        self,
        account_id: str,
        cursor: str | None,
        changed_since: datetime | None,
    ) -> PluggyTransactionPageSnapshot:
        self.calls.append(("list_transactions", (account_id, cursor, changed_since)))
        self._raise_if_configured()
        return self.page


def test_adapter_satisfies_neutral_provider_contract() -> None:
    provider = PluggyBankingProvider(GatewayStub())

    assert isinstance(provider, BankingProvider)
    assert provider.provider_name == "pluggy"


def test_connection_and_capabilities_are_normalized() -> None:
    gateway = GatewayStub()
    provider = PluggyBankingProvider(gateway)

    connection = provider.get_connection("item-001")

    assert connection.external_connection_id == "item-001"
    assert connection.status is ConnectionStatus.AVAILABLE
    assert connection.requires_user_action is False
    assert connection.last_successful_sync_at == NOW
    assert [entry.capability for entry in connection.capabilities] == [
        Capability.IDENTITY,
        Capability.BANK_ACCOUNTS,
        Capability.TRANSACTIONS,
    ]
    assert all(
        entry.state is CapabilityState.SUPPORTED for entry in connection.capabilities
    )
    assert all(
        entry.source is CapabilitySource.OBSERVATION
        for entry in connection.capabilities
    )
    assert gateway.calls == [("get_item", "item-001")]


def test_user_action_phase_sets_neutral_requirement() -> None:
    gateway = GatewayStub()
    gateway.item = PluggyItemSnapshot(
        item_id="item-001",
        phase=PluggyConnectionPhase.REAUTHENTICATION_REQUIRED,
        capabilities=(
            capability(
                PluggyCapability.TRANSACTIONS,
                PluggyCapabilityAvailability.USER_ACTION_REQUIRED,
            ),
        ),
        provider_reason_code="CONSENT_REQUIRED",
    )
    provider = PluggyBankingProvider(gateway)

    connection = provider.get_connection("item-001")

    assert connection.status is ConnectionStatus.REAUTHENTICATION_REQUIRED
    assert connection.requires_user_action is True
    assert connection.capabilities[0].state is CapabilityState.REQUIRES_USER_ACTION
    assert connection.provider_reason_code == "CONSENT_REQUIRED"


def test_accounts_are_normalized_without_provider_types() -> None:
    provider = PluggyBankingProvider(GatewayStub())

    accounts = provider.list_accounts("item-001")

    assert [account.account_type for account in accounts] == [
        AccountType.BANK,
        AccountType.CREDIT,
    ]
    assert accounts[0].external_account_id == "account-bank"
    assert accounts[0].external_connection_id == "item-001"
    assert accounts[0].currency == "BRL"
    assert accounts[0].number_mask == "1234"


def test_transactions_preserve_status_cursor_and_filter() -> None:
    gateway = GatewayStub()
    provider = PluggyBankingProvider(gateway)

    page = provider.list_transactions(
        "account-bank",
        "opaque-input-cursor",
        CHANGED_SINCE,
    )

    assert [record.status for record in page.records] == [
        TransactionStatus.CONFIRMED,
        TransactionStatus.PENDING,
    ]
    assert page.next_cursor == "opaque-next-cursor"
    assert page.source_window == "synthetic-window-001"
    assert page.records[0].amount == Decimal("125.40")
    assert page.records[0].installment_metadata is not None
    assert page.records[0].installment_metadata.installment_number == 2
    assert gateway.calls == [
        (
            "list_transactions",
            ("account-bank", "opaque-input-cursor", CHANGED_SINCE),
        )
    ]


def test_gateway_error_is_mapped_without_original_chain() -> None:
    gateway = GatewayStub()
    gateway.error = PluggyGatewayError(
        PluggyGatewayErrorCategory.RATE_LIMITED,
        retryable=True,
        provider_reason_code="LIMIT_WINDOW",
    )
    provider = PluggyBankingProvider(gateway)

    with pytest.raises(BankingProviderError) as captured:
        provider.get_connection("item-001")

    assert captured.value.category is ProviderErrorCategory.RATE_LIMITED
    assert captured.value.retryable is True
    assert captured.value.provider_reason_code == "LIMIT_WINDOW"
    assert str(captured.value) == "provider read operation failed"
    assert captured.value.__cause__ is None


def test_unexpected_gateway_failure_is_sanitized() -> None:
    gateway = GatewayStub()
    gateway.error = RuntimeError("sensitive-transport-diagnostic")
    provider = PluggyBankingProvider(gateway)

    with pytest.raises(BankingProviderError) as captured:
        provider.get_connection("item-001")

    assert captured.value.category is ProviderErrorCategory.INTERNAL
    assert "sensitive-transport-diagnostic" not in str(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    "operation",
    [
        "connection",
        "accounts",
        "transactions",
    ],
)
def test_inconsistent_snapshot_fails_closed(operation: str) -> None:
    gateway = GatewayStub()
    provider = PluggyBankingProvider(gateway)

    if operation == "connection":
        gateway.item = item_snapshot("different-item")
        invocation: Callable[[], object] = lambda: provider.get_connection("item-001")
    elif operation == "accounts":
        gateway.accounts = account_snapshots("different-item")
        invocation = lambda: provider.list_accounts("item-001")
    else:
        gateway.page = transaction_page("different-account")
        invocation = lambda: provider.list_transactions("account-bank", None, None)

    with pytest.raises(BankingProviderError) as captured:
        invocation()

    assert captured.value.category is ProviderErrorCategory.INTERNAL
    assert str(captured.value) == "provider snapshot could not be normalized"
    assert captured.value.__cause__ is None


def test_invalid_request_is_rejected_before_gateway() -> None:
    gateway = GatewayStub()
    provider = PluggyBankingProvider(gateway)

    with pytest.raises(BankingProviderError) as captured:
        provider.list_transactions("account\nsecret", None, None)

    assert captured.value.category is ProviderErrorCategory.INVALID_REQUEST
    assert "secret" not in str(captured.value)
    assert gateway.calls == []


def test_unsupported_operations_do_not_call_gateway() -> None:
    gateway = GatewayStub()
    provider = PluggyBankingProvider(gateway)
    operations: tuple[Callable[[], object], ...] = (
        lambda: provider.create_connection_intent("residence", "actor"),
        lambda: provider.create_reauthentication_intent("item-001", "actor"),
        lambda: provider.list_credit_card_bills("account-credit"),
        lambda: provider.list_investments("item-001"),
        lambda: provider.list_loans("item-001"),
        lambda: provider.request_refresh("item-001", "actor"),
        lambda: provider.disconnect("item-001", "actor"),
    )

    for operation in operations:
        with pytest.raises(BankingProviderError) as captured:
            operation()
        assert captured.value.category is ProviderErrorCategory.UNSUPPORTED
        assert captured.value.retryable is False

    assert gateway.calls == []
