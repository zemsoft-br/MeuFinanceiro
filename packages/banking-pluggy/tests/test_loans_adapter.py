from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from meufinanceiro_banking import BankingProviderError, ProviderErrorCategory

from meufinanceiro_banking_pluggy import PluggyBankingProvider
from meufinanceiro_banking_pluggy.gateway import (
    PluggyAccountSnapshot,
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
    PluggyItemSnapshot,
    PluggyTransactionPageSnapshot,
)
from meufinanceiro_banking_pluggy.loans import PluggyLoanSnapshot

NOW = datetime(2026, 9, 19, 2, 0, tzinfo=UTC)


class LoansGatewayStub:
    def __init__(self) -> None:
        self.loans = (
            PluggyLoanSnapshot(
                loan_id="loan-1",
                item_id="item-1",
                kind="LOAN",
                outstanding_balance=Decimal("1000.04"),
                currency="BRL",
                as_of=NOW,
                contracted_at=date(2022, 8, 1),
                due_date=date(2028, 1, 15),
            ),
        )
        self.error: Exception | None = None
        self.calls: list[str] = []

    def get_item(self, item_id: str) -> PluggyItemSnapshot:
        raise AssertionError(f"unexpected get_item call: {item_id}")

    def list_accounts(self, item_id: str) -> tuple[PluggyAccountSnapshot, ...]:
        raise AssertionError(f"unexpected list_accounts call: {item_id}")

    def list_transactions(
        self,
        account_id: str,
        cursor: str | None,
        changed_since: datetime | None,
    ) -> PluggyTransactionPageSnapshot:
        raise AssertionError(
            f"unexpected list_transactions call: {account_id}/{cursor}/{changed_since}"
        )

    def list_loans(self, item_id: str) -> tuple[PluggyLoanSnapshot, ...]:
        self.calls.append(item_id)
        if self.error is not None:
            raise self.error
        return self.loans


class BaseGatewayStub:
    def get_item(self, item_id: str) -> PluggyItemSnapshot:
        raise AssertionError(item_id)

    def list_accounts(self, item_id: str) -> tuple[PluggyAccountSnapshot, ...]:
        del item_id
        return ()

    def list_transactions(
        self,
        account_id: str,
        cursor: str | None,
        changed_since: datetime | None,
    ) -> PluggyTransactionPageSnapshot:
        raise AssertionError((account_id, cursor, changed_since))


def test_adapter_maps_loan_snapshot_to_neutral_model() -> None:
    gateway = LoansGatewayStub()

    loans = PluggyBankingProvider(gateway).list_loans("item-1")

    assert gateway.calls == ["item-1"]
    assert len(loans) == 1
    value = loans[0]
    assert value.external_loan_id == "loan-1"
    assert value.external_connection_id == "item-1"
    assert value.kind == "LOAN"
    assert value.outstanding_balance == Decimal("1000.04")
    assert value.currency == "BRL"
    assert value.as_of == NOW
    assert value.contracted_at == date(2022, 8, 1)
    assert value.due_date == date(2028, 1, 15)


def test_adapter_preserves_unknown_loan_kind_as_sanitized_text() -> None:
    gateway = LoansGatewayStub()
    gateway.loans = (
        PluggyLoanSnapshot(
            loan_id="loan-2",
            item_id="item-1",
            kind="future_credit_family",
            outstanding_balance=Decimal("1"),
            currency="BRL",
            as_of=NOW,
        ),
    )

    value = PluggyBankingProvider(gateway).list_loans("item-1")[0]

    assert value.kind == "FUTURE_CREDIT_FAMILY"


def test_adapter_rejects_loan_from_another_item() -> None:
    gateway = LoansGatewayStub()
    gateway.loans = (
        PluggyLoanSnapshot(
            loan_id="loan-1",
            item_id="another-item",
            kind="LOAN",
            outstanding_balance=Decimal("1"),
            currency="BRL",
            as_of=NOW,
        ),
    )

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_loans("item-1")

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert "another-item" not in str(raised.value)


def test_adapter_rejects_duplicate_loan_identifiers() -> None:
    gateway = LoansGatewayStub()
    gateway.loans = (
        PluggyLoanSnapshot(
            loan_id="loan-1",
            item_id="item-1",
            kind="LOAN",
            outstanding_balance=Decimal("1"),
            currency="BRL",
            as_of=NOW,
        ),
        PluggyLoanSnapshot(
            loan_id="loan-1",
            item_id="item-1",
            kind="FINANCING",
            outstanding_balance=Decimal("2"),
            currency="BRL",
            as_of=NOW,
        ),
    )

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_loans("item-1")

    assert raised.value.category is ProviderErrorCategory.INTERNAL


def test_adapter_maps_gateway_error_without_provider_material() -> None:
    gateway = LoansGatewayStub()
    gateway.error = PluggyGatewayError(
        PluggyGatewayErrorCategory.RATE_LIMITED,
        retryable=True,
        provider_reason_code="RATE_LIMITED",
    )

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_loans("item-1")

    assert raised.value.category is ProviderErrorCategory.RATE_LIMITED
    assert raised.value.retryable is True
    assert "item-1" not in str(raised.value)


def test_adapter_returns_unsupported_without_loan_capability() -> None:
    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(BaseGatewayStub()).list_loans("item-1")

    assert raised.value.category is ProviderErrorCategory.UNSUPPORTED


def test_invalid_item_identifier_fails_before_gateway() -> None:
    gateway = LoansGatewayStub()

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_loans("   ")

    assert raised.value.category is ProviderErrorCategory.INVALID_REQUEST
    assert gateway.calls == []
