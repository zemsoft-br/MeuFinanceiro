from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from meufinanceiro_banking_pluggy.bills import (
    PluggyCreditCardBillsGateway,
    PluggyCreditCardBillState,
)
from meufinanceiro_banking_pluggy.bills_http_gateway import (
    PluggyBillsGatewayHttpTransport,
    PluggyBillsHttpReadOnlyGateway,
    PluggyBillsPayloadTransport,
)
from meufinanceiro_banking_pluggy.gateway import (
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
)
from meufinanceiro_banking_pluggy.transport import (
    JsonObject,
    PluggyApplicationCredentials,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)


def bills_payload() -> JsonObject:
    return {
        "results": [
            {
                "id": "bill-open",
                "status": "OPEN",
                "dueDate": "2026-09-10T00:00:00.000Z",
                "billClosingDate": "2026-09-03T00:00:00.000Z",
                "totalAmount": "1500.50",
                "totalAmountCurrencyCode": "BRL",
                "minimumPaymentAmount": 150.05,
                "allowsInstallments": True,
                "payments": [{"ignored": "raw-provider-detail"}],
            },
            {
                "id": "bill-unknown",
                "dueDate": "2026-10-10",
                "totalAmount": 20,
                "totalAmountCurrencyCode": "brl",
            },
        ]
    }


@dataclass
class FakeBillsTransport:
    bills: JsonObject = field(default_factory=bills_payload)
    failure: Exception | None = None
    bill_calls: list[str] = field(default_factory=list)

    def _maybe_fail(self) -> None:
        if self.failure is not None:
            raise self.failure

    def get_item(self, item_id: str) -> JsonObject:
        del item_id
        self._maybe_fail()
        return {"id": "unused"}

    def get_accounts(self, item_id: str) -> JsonObject:
        del item_id
        self._maybe_fail()
        return {"results": []}

    def get_transactions_page(
        self,
        account_id: str,
        *,
        after: str | None,
        created_at_from: datetime | None,
    ) -> JsonObject:
        del account_id, after, created_at_from
        self._maybe_fail()
        return {"results": [], "next": None}

    def get_bills(self, account_id: str) -> JsonObject:
        self.bill_calls.append(account_id)
        self._maybe_fail()
        return self.bills


def gateway(
    transport: FakeBillsTransport | None = None,
) -> PluggyBillsHttpReadOnlyGateway:
    return PluggyBillsHttpReadOnlyGateway(transport or FakeBillsTransport())


def test_bill_gateway_protocols_and_allowlisted_mapping() -> None:
    transport = FakeBillsTransport()
    instance = gateway(transport)

    assert isinstance(transport, PluggyBillsPayloadTransport)
    assert isinstance(instance, PluggyCreditCardBillsGateway)

    bills = instance.list_credit_card_bills("account-card")

    assert transport.bill_calls == ["account-card"]
    assert len(bills) == 2
    first, second = bills
    assert first.bill_id == "bill-open"
    assert first.account_id == "account-card"
    assert first.state is PluggyCreditCardBillState.OPEN
    assert first.due_date == date(2026, 9, 10)
    assert first.close_date == date(2026, 9, 3)
    assert first.total_amount == Decimal("1500.50")
    assert first.minimum_payment == Decimal("150.05")
    assert first.currency == "BRL"
    assert second.state is PluggyCreditCardBillState.UNKNOWN
    assert second.close_date is None
    assert second.minimum_payment is None
    assert "payments" not in repr(first)
    assert "raw-provider-detail" not in repr(first)


def test_empty_bill_collection_is_valid() -> None:
    assert gateway(FakeBillsTransport(bills={"results": []})).list_credit_card_bills(
        "account-card"
    ) == ()


def test_unknown_provider_status_is_neutral_unknown() -> None:
    payload = bills_payload()
    results = payload["results"]
    assert isinstance(results, list)
    first = results[0]
    assert isinstance(first, dict)
    first["status"] = "PROVIDER_NEW_STATE"

    bills = gateway(FakeBillsTransport(bills=payload)).list_credit_card_bills(
        "account-card"
    )

    assert bills[0].state is PluggyCreditCardBillState.UNKNOWN


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dueDate", None),
        ("totalAmount", "NaN"),
        ("totalAmount", -1),
        ("totalAmountCurrencyCode", "REAL"),
        ("minimumPaymentAmount", -1),
        ("minimumPaymentAmount", 2000),
    ],
)
def test_invalid_bill_payload_fails_closed(field: str, value: object) -> None:
    payload = bills_payload()
    results = payload["results"]
    assert isinstance(results, list)
    first = results[0]
    assert isinstance(first, dict)
    first[field] = value

    with pytest.raises(PluggyGatewayError) as raised:
        gateway(FakeBillsTransport(bills=payload)).list_credit_card_bills("account-card")

    assert raised.value.category is PluggyGatewayErrorCategory.INTERNAL
    assert raised.value.retryable is False
    assert "bill-open" not in repr(raised.value)
    assert "account-card" not in repr(raised.value)


def test_duplicate_bill_id_fails_closed() -> None:
    payload = bills_payload()
    results = payload["results"]
    assert isinstance(results, list)
    second = results[1]
    assert isinstance(second, dict)
    second["id"] = "bill-open"

    with pytest.raises(PluggyGatewayError) as raised:
        gateway(FakeBillsTransport(bills=payload)).list_credit_card_bills("account-card")

    assert raised.value.category is PluggyGatewayErrorCategory.INTERNAL
    assert raised.value.provider_reason_code == "DUPLICATE_BILL_ID"


def test_transport_error_is_mapped_without_payload_material() -> None:
    transport = FakeBillsTransport()
    transport.failure = PluggyTransportError(
        PluggyTransportErrorCategory.RATE_LIMITED,
        retryable=True,
        status_code=429,
        provider_reason_code="RATE_LIMITED",
    )

    with pytest.raises(PluggyGatewayError) as raised:
        gateway(transport).list_credit_card_bills("account-card")

    assert raised.value.category is PluggyGatewayErrorCategory.RATE_LIMITED
    assert raised.value.retryable is True
    assert str(raised.value) == "pluggy gateway operation failed"


def test_http_transport_uses_only_account_scoped_bills_endpoint() -> None:
    requests: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, request.url.query.decode()))
        if request.url.path == "/auth":
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"apiKey": "synthetic-api-key"},
            )
        if request.url.path == "/bills":
            assert request.url.params.get("accountId") == "account-card"
            assert request.headers.get("X-API-KEY") == "synthetic-api-key"
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"results": []},
            )
        return httpx.Response(500)

    transport = PluggyBillsGatewayHttpTransport(
        PluggyApplicationCredentials("synthetic-client", "synthetic-secret"),
        base_url="http://127.0.0.1:8765",
        http_transport=httpx.MockTransport(handler),
        sleeper=lambda _seconds: None,
        jitter=lambda _delay: 0.0,
    )
    try:
        assert transport.get_bills("account-card") == {"results": []}
    finally:
        transport.close()

    assert requests[0][0:2] == ("POST", "/auth")
    assert requests[1][0:2] == ("GET", "/bills")
    assert "accountId=account-card" in requests[1][2]
