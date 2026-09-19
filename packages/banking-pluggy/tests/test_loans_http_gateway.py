from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from meufinanceiro_banking_pluggy.gateway import (
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
)
from meufinanceiro_banking_pluggy.loans import PluggyLoansGateway
from meufinanceiro_banking_pluggy.loans_http_gateway import (
    PluggyLoansGatewayHttpTransport,
    PluggyLoansHttpReadOnlyGateway,
    PluggyLoansPayloadTransport,
)
from meufinanceiro_banking_pluggy.transport import (
    JsonObject,
    PluggyApplicationCredentials,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)

ITEM_ID = "item-1"


def _loan_record(
    loan_id: str,
    *,
    item_id: str = ITEM_ID,
    kind: str = "LOAN",
) -> dict[str, object]:
    return {
        "id": loan_id,
        "itemId": item_id,
        "kind": kind,
        "productName": "must-not-cross-gateway",
        "contractNumber": "must-not-cross-gateway",
        "ipocCode": "must-not-cross-gateway",
        "date": "2026-09-18T12:00:00.000Z",
        "contractDate": "2022-08-01T00:00:00.000Z",
        "dueDate": "2028-01-15T00:00:00.000Z",
        "contractAmount": 50000,
        "currencyCode": "BRL",
        "CET": 0.29,
        "cnpjConsignee": "must-not-cross-gateway",
        "payments": {
            "contractOutstandingBalance": "1000.04",
            "releases": [{"paidAmount": 999}],
        },
        "interestRates": [{"preFixedRate": 0.6}],
        "warranties": [{"amount": 500}],
        "installments": {"dueInstallments": 57},
    }


def _page_payload(
    *,
    page: int,
    total: int,
    total_pages: int,
    results: list[dict[str, object]],
) -> JsonObject:
    return {
        "page": page,
        "total": total,
        "totalPages": total_pages,
        "results": results,
    }


@dataclass
class FakeLoansTransport:
    pages: dict[int, JsonObject] = field(
        default_factory=lambda: {
            1: _page_payload(
                page=1,
                total=1,
                total_pages=1,
                results=[_loan_record("loan-1")],
            )
        }
    )
    failure: Exception | None = None
    calls: list[tuple[str, int, int]] = field(default_factory=list)

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

    def get_loans_page(
        self,
        item_id: str,
        *,
        page: int,
        page_size: int,
    ) -> JsonObject:
        self._maybe_fail()
        self.calls.append((item_id, page, page_size))
        return self.pages[page]


def _gateway(
    transport: FakeLoansTransport | None = None,
    *,
    max_pages: int = 20,
    max_records: int = 10_000,
) -> PluggyLoansHttpReadOnlyGateway:
    return PluggyLoansHttpReadOnlyGateway(
        transport or FakeLoansTransport(),
        max_pages=max_pages,
        max_records=max_records,
    )


def test_loan_gateway_protocol_and_allowlisted_mapping() -> None:
    transport = FakeLoansTransport()
    instance = _gateway(transport)

    assert isinstance(transport, PluggyLoansPayloadTransport)
    assert isinstance(instance, PluggyLoansGateway)

    loans = instance.list_loans(ITEM_ID)

    assert transport.calls == [(ITEM_ID, 1, 500)]
    assert len(loans) == 1
    value = loans[0]
    assert value.loan_id == "loan-1"
    assert value.item_id == ITEM_ID
    assert value.kind == "LOAN"
    assert value.outstanding_balance == Decimal("1000.04")
    assert value.currency == "BRL"
    assert value.as_of == datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    assert value.contracted_at == date(2022, 8, 1)
    assert value.due_date == date(2028, 1, 15)
    rendered = repr(value)
    assert "must-not-cross-gateway" not in rendered
    assert "50000" not in rendered


def test_empty_loan_collection_is_valid() -> None:
    transport = FakeLoansTransport(
        pages={1: _page_payload(page=0, total=0, total_pages=0, results=[])}
    )

    assert _gateway(transport).list_loans(ITEM_ID) == ()


def test_multiple_pages_are_joined_in_order() -> None:
    transport = FakeLoansTransport(
        pages={
            2: _page_payload(
                page=2,
                total=2,
                total_pages=2,
                results=[_loan_record("loan-1")],
            ),
            2: _page_payload(
                page=2,
                total=2,
                total_pages=2,
                results=[_loan_record("loan-2", kind="FINANCING")],
            ),
        }
    )

    loans = _gateway(transport).list_loans(ITEM_ID)

    assert [value.loan_id for value in loans] == ["loan-1", "loan-2"]
    assert transport.calls == [(ITEM_ID, 1, 500), (ITEM_ID, 2, 500)]


def test_contract_amount_is_never_outstanding_balance_fallback() -> None:
    record = _loan_record("loan-1")
    record["payments"] = {}
    record["contractAmount"] = 999999
    transport = FakeLoansTransport(
        pages={
            1: _page_payload(
                page=1,
                total=1,
                total_pages=1,
                results=[record],
            )
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_loans(ITEM_ID)

    assert raised.value.category is PluggyGatewayErrorCategory.INTERNAL
    assert raised.value.provider_reason_code == "INVALID_LOAN_OUTSTANDING_BALANCE"


def test_missing_payments_fails_closed() -> None:
    record = _loan_record("loan-1")
    record.pop("payments")
    transport = FakeLoansTransport(
        pages={
            1: _page_payload(
                page=1,
                total=1,
                total_pages=1,
                results=[record],
            )
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_loans(ITEM_ID)

    assert raised.value.provider_reason_code == "INVALID_LOAN_PAYMENTS"


def test_item_association_mismatch_fails_closed() -> None:
    transport = FakeLoansTransport(
        pages={
            1: _page_payload(
                page=1,
                total=1,
                total_pages=1,
                results=[_loan_record("loan-1", item_id="another-item")],
            )
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_loans(ITEM_ID)

    assert raised.value.provider_reason_code == "LOAN_ASSOCIATION_MISMATCH"
    assert "another-item" not in str(raised.value)


def test_duplicate_loan_id_across_pages_fails_closed() -> None:
    transport = FakeLoansTransport(
        pages={
            2: _page_payload(
                page=2,
                total=2,
                total_pages=2,
                results=[_loan_record("loan-1")],
            ),
            2: _page_payload(
                page=2,
                total=2,
                total_pages=2,
                results=[_loan_record("loan-1")],
            ),
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_loans(ITEM_ID)

    assert raised.value.provider_reason_code == "DUPLICATE_LOAN_ID"


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("balance", -1),
        ("balance", "NaN"),
        ("currency", "REAL"),
        ("date", None),
        ("date", "2026-09-18"),
    ],
)
def test_invalid_loan_payload_fails_closed(target: str, value: object) -> None:
    record = _loan_record("loan-1")
    if target == "balance":
        payments = record["payments"]
        assert isinstance(payments, dict)
        payments["contractOutstandingBalance"] = value
    elif target == "currency":
        record["currencyCode"] = value
    else:
        record["date"] = value

    transport = FakeLoansTransport(
        pages={
            1: _page_payload(
                page=1,
                total=1,
                total_pages=1,
                results=[record],
            )
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_loans(ITEM_ID)

    assert raised.value.category is PluggyGatewayErrorCategory.INTERNAL
    assert ITEM_ID not in str(raised.value)


def test_optional_contract_dates_may_be_absent() -> None:
    record = _loan_record("loan-1")
    record["contractDate"] = None
    record["dueDate"] = None
    transport = FakeLoansTransport(
        pages={
            1: _page_payload(
                page=1,
                total=1,
                total_pages=1,
                results=[record],
            )
        }
    )

    value = _gateway(transport).list_loans(ITEM_ID)[0]

    assert value.contracted_at is None
    assert value.due_date is None


def test_pagination_metadata_cannot_change_between_pages() -> None:
    transport = FakeLoansTransport(
        pages={
            2: _page_payload(
                page=2,
                total=2,
                total_pages=2,
                results=[_loan_record("loan-1")],
            ),
            2: _page_payload(
                page=2,
                total=3,
                total_pages=2,
                results=[_loan_record("loan-2")],
            ),
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_loans(ITEM_ID)

    assert raised.value.provider_reason_code == "INCONSISTENT_LOAN_PAGINATION"


def test_final_collection_must_match_reported_total() -> None:
    transport = FakeLoansTransport(
        pages={
            1: _page_payload(
                page=1,
                total=2,
                total_pages=1,
                results=[_loan_record("loan-1")],
            )
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_loans(ITEM_ID)

    assert raised.value.provider_reason_code == "INCOMPLETE_LOAN_COLLECTION"


def test_pagination_limit_fails_closed() -> None:
    transport = FakeLoansTransport(
        pages={
            2: _page_payload(
                page=2,
                total=2,
                total_pages=2,
                results=[_loan_record("loan-1")],
            )
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport, max_pages=1).list_loans(ITEM_ID)

    assert raised.value.provider_reason_code == "LOAN_PAGE_LIMIT_EXCEEDED"
    assert transport.calls == [(ITEM_ID, 1, 500)]


def test_transport_error_is_mapped_without_external_material() -> None:
    transport = FakeLoansTransport()
    transport.failure = PluggyTransportError(
        PluggyTransportErrorCategory.RATE_LIMITED,
        retryable=True,
        status_code=429,
        provider_reason_code="RATE_LIMITED",
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_loans(ITEM_ID)

    assert raised.value.category is PluggyGatewayErrorCategory.RATE_LIMITED
    assert raised.value.retryable is True
    assert ITEM_ID not in str(raised.value)


def test_http_transport_uses_bounded_item_scoped_endpoint() -> None:
    requests: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, request.url.query.decode()))
        if request.url.path == "/auth":
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"apiKey": "synthetic-api-key"},
            )
        if request.url.path == "/loans":
            assert request.url.params.get("itemId") == ITEM_ID
            assert request.url.params.get("page") == "1"
            assert request.url.params.get("pageSize") == "500"
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"page": 0, "total": 0, "totalPages": 0, "results": []},
            )
        return httpx.Response(500)

    transport = PluggyLoansGatewayHttpTransport(
        PluggyApplicationCredentials("synthetic-client", "synthetic-secret"),
        base_url="http://127.0.0.1:8765",
        http_transport=httpx.MockTransport(handler),
        sleeper=lambda _seconds: None,
        jitter=lambda _delay: 0.0,
    )
    try:
        assert transport.get_loans_page(
            ITEM_ID,
            page=1,
            page_size=500,
        ) == {"page": 0, "total": 0, "totalPages": 0, "results": []}
    finally:
        transport.close()

    assert requests[0][0:2] == ("POST", "/auth")
    assert requests[1][0:2] == ("GET", "/loans")
