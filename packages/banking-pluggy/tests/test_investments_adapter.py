from __future__ import annotations

from datetime import UTC, datetime
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
from meufinanceiro_banking_pluggy.investments import PluggyInvestmentSnapshot

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


class InvestmentsGatewayStub:
    def __init__(self) -> None:
        self.investments = (
            PluggyInvestmentSnapshot(
                investment_id="investment-1",
                item_id="item-1",
                name="Synthetic Fund",
                kind="MUTUAL_FUND",
                balance=Decimal("100.50"),
                currency="BRL",
                as_of=NOW,
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

    def list_investments(
        self,
        item_id: str,
    ) -> tuple[PluggyInvestmentSnapshot, ...]:
        self.calls.append(item_id)
        if self.error is not None:
            raise self.error
        return self.investments


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


def test_adapter_maps_investment_snapshot_to_neutral_model() -> None:
    gateway = InvestmentsGatewayStub()

    investments = PluggyBankingProvider(gateway).list_investments("item-1")

    assert gateway.calls == ["item-1"]
    assert len(investments) == 1
    value = investments[0]
    assert value.external_investment_id == "investment-1"
    assert value.external_connection_id == "item-1"
    assert value.name == "Synthetic Fund"
    assert value.kind == "MUTUAL_FUND"
    assert value.balance == Decimal("100.50")
    assert value.currency == "BRL"
    assert value.as_of == NOW
    assert value.external_account_id is None


def test_adapter_preserves_unknown_investment_kind_as_sanitized_text() -> None:
    gateway = InvestmentsGatewayStub()
    gateway.investments = (
        PluggyInvestmentSnapshot(
            investment_id="investment-2",
            item_id="item-1",
            name="Future Asset",
            kind="future_kind",
            balance=Decimal("1"),
            currency="BRL",
            as_of=NOW,
        ),
    )

    value = PluggyBankingProvider(gateway).list_investments("item-1")[0]

    assert value.kind == "FUTURE_KIND"


def test_adapter_rejects_investment_from_another_item() -> None:
    gateway = InvestmentsGatewayStub()
    gateway.investments = (
        PluggyInvestmentSnapshot(
            investment_id="investment-1",
            item_id="another-item",
            name="Synthetic Fund",
            kind="ETF",
            balance=Decimal("1"),
            currency="BRL",
            as_of=NOW,
        ),
    )

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_investments("item-1")

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert "another-item" not in str(raised.value)


def test_adapter_rejects_duplicate_investment_identifiers() -> None:
    gateway = InvestmentsGatewayStub()
    gateway.investments = (
        PluggyInvestmentSnapshot(
            investment_id="investment-1",
            item_id="item-1",
            name="First",
            kind="ETF",
            balance=Decimal("1"),
            currency="BRL",
            as_of=NOW,
        ),
        PluggyInvestmentSnapshot(
            investment_id="investment-1",
            item_id="item-1",
            name="Second",
            kind="OTHER",
            balance=Decimal("2"),
            currency="BRL",
            as_of=NOW,
        ),
    )

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_investments("item-1")

    assert raised.value.category is ProviderErrorCategory.INTERNAL


def test_adapter_maps_gateway_error_without_provider_material() -> None:
    gateway = InvestmentsGatewayStub()
    gateway.error = PluggyGatewayError(
        PluggyGatewayErrorCategory.RATE_LIMITED,
        retryable=True,
        provider_reason_code="RATE_LIMITED",
    )

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_investments("item-1")

    assert raised.value.category is ProviderErrorCategory.RATE_LIMITED
    assert raised.value.retryable is True
    assert "item-1" not in str(raised.value)


def test_adapter_returns_unsupported_without_investment_capability() -> None:
    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(BaseGatewayStub()).list_investments("item-1")

    assert raised.value.category is ProviderErrorCategory.UNSUPPORTED


def test_invalid_item_identifier_fails_before_gateway() -> None:
    gateway = InvestmentsGatewayStub()

    with pytest.raises(BankingProviderError) as raised:
        PluggyBankingProvider(gateway).list_investments("   ")

    assert raised.value.category is ProviderErrorCategory.INVALID_REQUEST
    assert gateway.calls == []
