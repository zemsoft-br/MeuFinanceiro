from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from meufinanceiro_banking import (
    AccountType,
    Capability,
    CapabilitySource,
    CapabilityState,
    ConnectionCapability,
    ConnectionIntent,
    ConnectionIntentKind,
    ConnectionState,
    ConnectionStatus,
    ExternalAccount,
    ExternalPage,
    ExternalTransaction,
    InstallmentMetadata,
    RefreshRequest,
    RefreshStatus,
    TransactionStatus,
)

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def test_models_are_immutable_and_normalize_safe_values() -> None:
    account = ExternalAccount(
        external_account_id=" account-1 ",
        external_connection_id="connection-1",
        account_type=AccountType.BANK,
        subtype="checking",
        currency="brl",
        name=" Conta principal ",
        number_mask="•••• 1234",
    )

    assert account.external_account_id == "account-1"
    assert account.currency == "BRL"
    assert account.name == "Conta principal"
    with pytest.raises(FrozenInstanceError):
        account.currency = "USD"  # type: ignore[misc]


def test_connection_state_requires_consistent_user_action_flag() -> None:
    capability = ConnectionCapability(
        capability=Capability.TRANSACTIONS,
        state=CapabilityState.REQUIRES_USER_ACTION,
        observed_at=NOW,
        source=CapabilitySource.OPERATION,
    )

    with pytest.raises(ValueError, match="requires_user_action"):
        ConnectionState(
            external_connection_id="connection-1",
            status=ConnectionStatus.REAUTHENTICATION_REQUIRED,
            capabilities=(capability,),
            requires_user_action=False,
        )


def test_connection_state_rejects_duplicate_capabilities() -> None:
    capability = ConnectionCapability(
        capability=Capability.BANK_ACCOUNTS,
        state=CapabilityState.SUPPORTED,
        observed_at=NOW,
        source=CapabilitySource.OBSERVATION,
    )

    with pytest.raises(ValueError, match="duplicates"):
        ConnectionState(
            external_connection_id="connection-1",
            status=ConnectionStatus.AVAILABLE,
            capabilities=(capability, capability),
        )


def test_intent_requires_timezone_and_connection_for_reauthentication() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ConnectionIntent(
            intent_id="intent-1",
            kind=ConnectionIntentKind.CONNECT,
            residence_id="residence-1",
            actor_id="actor-1",
            expires_at=datetime(2026, 7, 28, 12, 5),
        )

    with pytest.raises(ValueError, match="external_connection_id"):
        ConnectionIntent(
            intent_id="intent-2",
            kind=ConnectionIntentKind.REAUTHENTICATE,
            residence_id="residence-1",
            actor_id="actor-1",
            expires_at=NOW,
        )


def test_transaction_requires_decimal_and_respects_inferred_semantics() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        ExternalTransaction(
            external_account_id="account-1",
            status=TransactionStatus.CONFIRMED,
            effective_date=date(2026, 7, 28),
            amount=10.0,  # type: ignore[arg-type]
            currency="BRL",
        )

    with pytest.raises(ValueError, match="inferred"):
        ExternalTransaction(
            external_account_id="account-1",
            status=TransactionStatus.INFERRED,
            effective_date=date(2026, 7, 28),
            amount=Decimal("10.00"),
            currency="BRL",
            external_transaction_id="provider-id",
        )


def test_installment_and_refresh_invariants_are_enforced() -> None:
    with pytest.raises(ValueError, match="installment_count"):
        InstallmentMetadata(
            installment_number=3,
            installment_count=2,
        )

    with pytest.raises(ValueError, match="next_refresh_allowed_at"):
        RefreshRequest(
            request_id="refresh-1",
            external_connection_id="connection-1",
            status=RefreshStatus.RATE_LIMITED,
            requested_at=NOW,
        )


def test_external_page_freezes_records_and_validates_cursor() -> None:
    records = [
        ExternalTransaction(
            external_account_id="account-1",
            status=TransactionStatus.PENDING,
            effective_date=date(2026, 7, 28),
            amount=Decimal("-12.34"),
            currency="BRL",
        )
    ]

    page = ExternalPage(
        records=records,  # type: ignore[arg-type]
        next_cursor="offset:1",
        source_window="offset:0:1",
        retrieved_at=NOW,
    )

    records.clear()
    assert len(page.records) == 1
    assert isinstance(page.records, tuple)


def test_currency_and_control_characters_are_rejected() -> None:
    with pytest.raises(ValueError, match="three-letter"):
        ExternalAccount(
            external_account_id="account-1",
            external_connection_id="connection-1",
            account_type=AccountType.BANK,
            subtype="checking",
            currency="REAL",
        )

    with pytest.raises(ValueError, match="control characters"):
        ExternalAccount(
            external_account_id="account-1\nsecret",
            external_connection_id="connection-1",
            account_type=AccountType.BANK,
            subtype="checking",
            currency="BRL",
        )
