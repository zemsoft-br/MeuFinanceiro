from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from meufinanceiro_banking import (
    BankingProviderError,
    CreditCardBillStatus,
    ProviderErrorCategory,
)

from meufinanceiro_banking_pluggy import PluggyBankingProvider
from meufinanceiro_banking_pluggy.bills import (
    PluggyCreditCardBillSnapshot,
    PluggyCreditCardBillState,
)
from meufinanceiro_banking_pluggy.gateway import (
    PluggyAccountSnapshot,
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
    PluggyItemSnapshot,
    PluggyTransactionPageSnapshot,
)


class BillsGatewayStub:
    def __init__(self) -> None:
        self.bills = (
            PluggyCreditCardBillSnapshot(
                bill_id="bill-1",
                account_id="account-card",
                state=PluggyCreditCardBillState.PAID,
                due_date=date(2026, 9, 10),
                close_date=date(2026, 9, 3),
                total_amount=Decimal("100.00"),
                minimum_payment=Decimal("20.00"),
                currency="BRL",
            ),
        )
        self.bill_error: Exception | None = None
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

    def list_credit_card_bills(
        self,
        account_id: str,
    ) -> tuple[PluggyCreditCardBillSnapshot, ...]:
        self.calls.append(account_id)
        if self.bill_error is not None:
            raise self.bill_error
        return self.bills


def test_adapter_maps_bill_snapshot_to_neutral_model() -> None:
    gateway = BillsGatewayStub()
    provider = PluggyBankingProvider(gateway)

    bills = provider.list_credit_card_bills("account-card")

    assert gateway.calls == ["account-card"]
    assert len(bills) == 1
    bill = bills[0]
    assert bill.external_bill_id == "bill-1"
    assert bill.external_account_id == "account-card"
    assert bill.status is CreditCardBillStatus.PAID
    assert bill.due_date == date(2026, 9, 10)
    assert bill.close_date == date(2026, 9, 3)
    assert bill.total_amount == Decimal("100.00")
    assert bill.minimum_payment == Decimal("20.00")
    assert bill.currency == "BRL"


def test_adapter_maps_provider_unknown_status_without_inference() -> None:
    gateway = BillsGatewayStub()
    gateway.bills = (
        PluggyCreditCardBillSnapshot(
            bill_id="bill-unknown",
            account_id="account-card",
            state=PluggyCreditCardBillState.UNKNOWN,
            due_date=date(2026, 9, 10),
            total_amount=Decimal("10"),
            currency="BRL",
        ),
    )

    bill = PluggyBankingProvider(gateway).list_credit_card_bills("account-card")[0]

    assert bill.status is CreditCardBillStatus.UNKNOWN


def test_adapter_rejects_bill_associated_with_another_account() -> None:
    gateway = BillsGatewayStub()
    gateway.bills = (
        PluggyCreditCardBillSnapshot(
            bill_id="bill-1",
            account_id="another-account",
            state=PluggyCreditCardBillState.OPEN,
            due_date=date(2026, 9, 10),
            total_amount=Decimal("10"),
            currency="BRL",
        ),
    )

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_credit_card_bills("account-card")

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert "another-account" not in repr(raised.value)
    assert "bill-1" not in repr(raised.value)


def test_adapter_rejects_duplicate_bill_identifiers() -> None:
    gateway = BillsGatewayStub()
    gateway.bills = (
        PluggyCreditCardBillSnapshot(
            bill_id="bill-1",
            account_id="account-card",
            state=PluggyCreditCardBillState.OPEN,
            due_date=date(2026, 9, 10),
            total_amount=Decimal("10"),
            currency="BRL",
        ),
        PluggyCreditCardBillSnapshot(
            bill_id="bill-1",
            account_id="account-card",
            state=PluggyCreditCardBillState.CLOSED,
            due_date=date(2026, 8, 10),
            total_amount=Decimal("5"),
            currency="BRL",
        ),
    )

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_credit_card_bills("account-card")

    assert raised.value.category is ProviderErrorCategory.INTERNAL


def test_adapter_maps_gateway_error_without_external_material() -> None:
    gateway = BillsGatewayStub()
    gateway.bill_error = PluggyGatewayError(
        PluggyGatewayErrorCategory.RATE_LIMITED,
        retryable=True,
        provider_reason_code="RATE_LIMITED",
    )

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_credit_card_bills("account-card")

    assert raised.value.category is ProviderErrorCategory.RATE_LIMITED
    assert raised.value.retryable is True
    assert "account-card" not in repr(raised.value)


def test_adapter_rejects_invalid_account_identifier_before_gateway() -> None:
    gateway = BillsGatewayStub()

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_credit_card_bills("   ")

    assert raised.value.category is ProviderErrorCategory.INVALID_REQUEST
    assert gateway.calls == []


def test_bill_api_does_not_require_provider_time_or_network_state() -> None:
    gateway = BillsGatewayStub()
    bill = PluggyBankingProvider(gateway).list_credit_card_bills("account-card")[0]

    assert bill.due_date == date(2026, 9, 10)
    assert datetime(2026, 9, 10, tzinfo=UTC).date() == bill.due_date
