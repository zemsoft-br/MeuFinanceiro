from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from meufinanceiro_banking import (
    AccountType,
    BankingProvider,
    BankingProviderError,
    Capability,
    CapabilitySource,
    CapabilityState,
    ConnectionCapability,
    ConnectionIntentKind,
    ConnectionState,
    ConnectionStatus,
    ExternalAccount,
    ExternalTransaction,
    FakeBankingProvider,
    ProviderErrorCategory,
    RefreshStatus,
    TransactionStatus,
)

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def build_provider(
    *, next_refresh_allowed_at: datetime | None = None
) -> FakeBankingProvider:
    provider = FakeBankingProvider(clock=lambda: NOW, page_size=2)
    capability = ConnectionCapability(
        capability=Capability.TRANSACTIONS,
        state=CapabilityState.SUPPORTED,
        observed_at=NOW,
        source=CapabilitySource.OBSERVATION,
    )
    state = ConnectionState(
        external_connection_id="connection-1",
        status=ConnectionStatus.AVAILABLE,
        capabilities=(capability,),
        next_refresh_allowed_at=next_refresh_allowed_at,
    )
    account = ExternalAccount(
        external_account_id="account-1",
        external_connection_id="connection-1",
        account_type=AccountType.BANK,
        subtype="checking",
        currency="BRL",
    )
    transactions = tuple(
        ExternalTransaction(
            external_account_id="account-1",
            external_transaction_id=f"transaction-{index}",
            status=TransactionStatus.CONFIRMED,
            effective_date=date(2026, 7, 20 + index),
            provider_updated_at=NOW + timedelta(minutes=index),
            amount=Decimal(str(index * 10)),
            currency="BRL",
        )
        for index in range(1, 4)
    )
    provider.seed_connection(
        state,
        residence_id="residence-1",
        accounts=(account,),
        transactions=transactions,
    )
    return provider


def test_fake_provider_satisfies_runtime_protocol() -> None:
    provider = build_provider()

    assert isinstance(provider, BankingProvider)
    assert provider.provider_name == "fake"
    assert provider.get_connection("connection-1").status is ConnectionStatus.AVAILABLE
    assert (
        provider.get_capabilities("connection-1")[0].capability
        is Capability.TRANSACTIONS
    )


def test_intents_are_deterministic_and_do_not_expose_tokens() -> None:
    provider = build_provider()

    connect = provider.create_connection_intent("residence-2", "actor-1")
    reauth = provider.create_reauthentication_intent("connection-1", "actor-1")

    assert connect.intent_id == "fake-intent-000001"
    assert connect.kind is ConnectionIntentKind.CONNECT
    assert reauth.intent_id == "fake-reauth-000002"
    assert reauth.kind is ConnectionIntentKind.REAUTHENTICATE
    assert reauth.external_connection_id == "connection-1"
    assert "token" not in connect.__dataclass_fields__


def test_transaction_pagination_and_changed_since_are_stable() -> None:
    provider = build_provider()

    first = provider.list_transactions("account-1", None, None)
    second = provider.list_transactions("account-1", first.next_cursor, None)
    changed = provider.list_transactions(
        "account-1",
        None,
        NOW + timedelta(minutes=2),
    )

    assert [item.external_transaction_id for item in first.records] == [
        "transaction-1",
        "transaction-2",
    ]
    assert first.next_cursor == "offset:2"
    assert [item.external_transaction_id for item in second.records] == [
        "transaction-3"
    ]
    assert second.next_cursor is None
    assert [item.external_transaction_id for item in changed.records] == [
        "transaction-2",
        "transaction-3",
    ]


def test_invalid_cursor_uses_sanitized_neutral_error() -> None:
    provider = build_provider()

    with pytest.raises(BankingProviderError) as captured:
        provider.list_transactions("account-1", "provider-secret", None)

    error = captured.value
    assert error.category is ProviderErrorCategory.INVALID_REQUEST
    assert error.retryable is False
    assert str(error) == "cursor is invalid"
    assert "provider-secret" not in str(error)


def test_refresh_respects_known_limit_and_requested_flow() -> None:
    limited_provider = build_provider(
        next_refresh_allowed_at=NOW + timedelta(minutes=15)
    )
    available_provider = build_provider()

    limited = limited_provider.request_refresh("connection-1", "actor-1")
    requested = available_provider.request_refresh("connection-1", "actor-1")

    assert limited.status is RefreshStatus.RATE_LIMITED
    assert limited.next_refresh_allowed_at == NOW + timedelta(minutes=15)
    assert requested.status is RefreshStatus.REQUESTED
    assert requested.next_poll_at == NOW + timedelta(seconds=5)


def test_disconnect_is_explicit_and_preserves_seeded_data() -> None:
    provider = build_provider()

    provider.disconnect("connection-1", "actor-1")

    assert (
        provider.get_connection("connection-1").status is ConnectionStatus.DISCONNECTED
    )
    assert len(provider.list_accounts("connection-1")) == 1
    assert len(provider.list_transactions("account-1", None, None).records) == 2
    with pytest.raises(BankingProviderError) as captured:
        provider.request_refresh("connection-1", "actor-1")
    assert captured.value.category is ProviderErrorCategory.CONFLICT


def test_unknown_resources_never_echo_external_identifiers() -> None:
    provider = build_provider()

    with pytest.raises(BankingProviderError) as captured:
        provider.get_connection("sensitive-external-id")

    assert captured.value.category is ProviderErrorCategory.NOT_FOUND
    assert "sensitive-external-id" not in str(captured.value)
