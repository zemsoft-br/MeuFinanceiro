from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from meufinanceiro_banking_pluggy.gateway import (
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
)
from meufinanceiro_banking_pluggy.investments import PluggyInvestmentsGateway
from meufinanceiro_banking_pluggy.investments_http_gateway import (
    PluggyInvestmentsGatewayHttpTransport,
    PluggyInvestmentsHttpReadOnlyGateway,
    PluggyInvestmentsPayloadTransport,
)
from meufinanceiro_banking_pluggy.transport import (
    JsonObject,
    PluggyApplicationCredentials,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)

ITEM_ID = "item-1"


def _investment_record(
    investment_id: str,
    *,
    item_id: str = ITEM_ID,
    kind: str = "MUTUAL_FUND",
) -> dict[str, object]:
    return {
        "id": investment_id,
        "itemId": item_id,
        "name": "Synthetic Asset",
        "type": kind,
        "balance": "125.50",
        "currencyCode": "BRL",
        "date": "2026-09-18T12:00:00.000Z",
        "owner": "must-not-cross-gateway",
        "number": "must-not-cross-gateway",
        "code": "must-not-cross-gateway",
        "taxes": 99,
        "metadata": {"secret": "must-not-cross-gateway"},
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
class FakeInvestmentsTransport:
    pages: dict[int, JsonObject] = field(
        default_factory=lambda: {
            1: _page_payload(
                page=1,
                total=1,
                total_pages=1,
                results=[_investment_record("investment-1")],
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

    def get_investments_page(
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
    transport: FakeInvestmentsTransport | None = None,
    *,
    max_pages: int = 20,
    max_records: int = 10_000,
) -> PluggyInvestmentsHttpReadOnlyGateway:
    return PluggyInvestmentsHttpReadOnlyGateway(
        transport or FakeInvestmentsTransport(),
        max_pages=max_pages,
        max_records=max_records,
    )


def test_investment_gateway_protocol_and_allowlisted_mapping() -> None:
    transport = FakeInvestmentsTransport()
    instance = _gateway(transport)

    assert isinstance(transport, PluggyInvestmentsPayloadTransport)
    assert isinstance(instance, PluggyInvestmentsGateway)

    investments = instance.list_investments(ITEM_ID)

    assert transport.calls == [(ITEM_ID, 1, 500)]
    assert len(investments) == 1
    value = investments[0]
    assert value.investment_id == "investment-1"
    assert value.item_id == ITEM_ID
    assert value.name == "Synthetic Asset"
    assert value.kind == "MUTUAL_FUND"
    assert value.balance == Decimal("125.50")
    assert value.currency == "BRL"
    assert value.as_of == datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    assert "must-not-cross-gateway" not in repr(value)


def test_empty_investment_collection_is_valid() -> None:
    transport = FakeInvestmentsTransport(
        pages={
            1: _page_payload(page=0, total=0, total_pages=0, results=[]),
        }
    )

    assert _gateway(transport).list_investments(ITEM_ID) == ()


def test_multiple_pages_are_joined_in_order() -> None:
    transport = FakeInvestmentsTransport(
        pages={
            1: _page_payload(
                page=1,
                total=2,
                total_pages=2,
                results=[_investment_record("investment-1")],
            ),
            2: _page_payload(
                page=2,
                total=2,
                total_pages=2,
                results=[_investment_record("investment-2", kind="ETF")],
            ),
        }
    )

    investments = _gateway(transport).list_investments(ITEM_ID)

    assert [value.investment_id for value in investments] == [
        "investment-1",
        "investment-2",
    ]
    assert transport.calls == [(ITEM_ID, 1, 500), (ITEM_ID, 2, 500)]


def test_item_association_mismatch_fails_closed() -> None:
    transport = FakeInvestmentsTransport(
        pages={
            1: _page_payload(
                page=1,
                total=1,
                total_pages=1,
                results=[_investment_record("investment-1", item_id="another-item")],
            )
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_investments(ITEM_ID)

    assert raised.value.category is PluggyGatewayErrorCategory.INTERNAL
    assert raised.value.provider_reason_code == "INVESTMENT_ASSOCIATION_MISMATCH"
    assert "another-item" not in str(raised.value)


def test_duplicate_investment_id_across_pages_fails_closed() -> None:
    transport = FakeInvestmentsTransport(
        pages={
            1: _page_payload(
                page=1,
                total=2,
                total_pages=2,
                results=[_investment_record("investment-1")],
            ),
            2: _page_payload(
                page=2,
                total=2,
                total_pages=2,
                results=[_investment_record("investment-1")],
            ),
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_investments(ITEM_ID)

    assert raised.value.provider_reason_code == "DUPLICATE_INVESTMENT_ID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("balance", -1),
        ("balance", "NaN"),
        ("currencyCode", "REAL"),
        ("date", None),
        ("date", "2026-09-18"),
    ],
)
def test_invalid_investment_payload_fails_closed(
    field: str,
    value: object,
) -> None:
    record = _investment_record("investment-1")
    record[field] = value
    transport = FakeInvestmentsTransport(
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
        _gateway(transport).list_investments(ITEM_ID)

    assert raised.value.category is PluggyGatewayErrorCategory.INTERNAL
    assert ITEM_ID not in str(raised.value)


@pytest.mark.parametrize(
    "payload",
    [
        _page_payload(
            page=2,
            total=1,
            total_pages=2,
            results=[_investment_record("investment-1")],
        ),
        _page_payload(
            page=0,
            total=0,
            total_pages=0,
            results=[_investment_record("investment-1")],
        ),
    ],
)
def test_inconsistent_pagination_fails_closed(payload: JsonObject) -> None:
    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(FakeInvestmentsTransport(pages={1: payload})).list_investments(
            ITEM_ID
        )

    assert raised.value.category is PluggyGatewayErrorCategory.INTERNAL


def test_pagination_metadata_cannot_change_between_pages() -> None:
    transport = FakeInvestmentsTransport(
        pages={
            1: _page_payload(
                page=1,
                total=2,
                total_pages=2,
                results=[_investment_record("investment-1")],
            ),
            2: _page_payload(
                page=2,
                total=3,
                total_pages=2,
                results=[_investment_record("investment-2")],
            ),
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_investments(ITEM_ID)

    assert raised.value.provider_reason_code == "INCONSISTENT_INVESTMENT_PAGINATION"


def test_final_collection_must_match_reported_total() -> None:
    transport = FakeInvestmentsTransport(
        pages={
            1: _page_payload(
                page=1,
                total=2,
                total_pages=1,
                results=[_investment_record("investment-1")],
            )
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_investments(ITEM_ID)

    assert raised.value.provider_reason_code == "INCOMPLETE_INVESTMENT_COLLECTION"


def test_pagination_limits_fail_closed_before_unbounded_reads() -> None:
    transport = FakeInvestmentsTransport(
        pages={
            1: _page_payload(
                page=1,
                total=2,
                total_pages=2,
                results=[_investment_record("investment-1")],
            )
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport, max_pages=1).list_investments(ITEM_ID)

    assert raised.value.provider_reason_code == "INVESTMENT_PAGE_LIMIT_EXCEEDED"
    assert transport.calls == [(ITEM_ID, 1, 500)]


def test_record_limit_fails_closed_before_pagination() -> None:
    transport = FakeInvestmentsTransport(
        pages={
            1: _page_payload(
                page=1,
                total=2,
                total_pages=1,
                results=[
                    _investment_record("investment-1"),
                    _investment_record("investment-2"),
                ],
            )
        }
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport, max_records=1).list_investments(ITEM_ID)

    assert raised.value.provider_reason_code == "INVESTMENT_RECORD_LIMIT_EXCEEDED"


def test_transport_error_is_mapped_without_external_material() -> None:
    transport = FakeInvestmentsTransport()
    transport.failure = PluggyTransportError(
        PluggyTransportErrorCategory.RATE_LIMITED,
        retryable=True,
        status_code=429,
        provider_reason_code="RATE_LIMITED",
    )

    with pytest.raises(PluggyGatewayError) as raised:
        _gateway(transport).list_investments(ITEM_ID)

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
        if request.url.path == "/investments":
            assert request.url.params.get("itemId") == ITEM_ID
            assert request.url.params.get("page") == "1"
            assert request.url.params.get("pageSize") == "500"
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"page": 0, "total": 0, "totalPages": 0, "results": []},
            )
        return httpx.Response(500)

    transport = PluggyInvestmentsGatewayHttpTransport(
        PluggyApplicationCredentials("synthetic-client", "synthetic-secret"),
        base_url="http://127.0.0.1:8765",
        http_transport=httpx.MockTransport(handler),
        sleeper=lambda _seconds: None,
        jitter=lambda _delay: 0.0,
    )
    try:
        assert transport.get_investments_page(
            ITEM_ID,
            page=1,
            page_size=500,
        ) == {"page": 0, "total": 0, "totalPages": 0, "results": []}
    finally:
        transport.close()

    assert requests[0][0:2] == ("POST", "/auth")
    assert requests[1][0:2] == ("GET", "/investments")
