from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from meufinanceiro_banking_pluggy import PluggyReadOnlyGateway
from meufinanceiro_banking_pluggy.gateway import (
    PluggyAccountKind,
    PluggyCapability,
    PluggyCapabilityAvailability,
    PluggyConnectionPhase,
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
    PluggyTransactionState,
)
from meufinanceiro_banking_pluggy.http_gateway import (
    PluggyGatewayHttpTransport,
    PluggyHttpReadOnlyGateway,
    PluggyPayloadTransport,
)
from meufinanceiro_banking_pluggy.transport import (
    JsonObject,
    PluggyApplicationCredentials,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)

NOW = datetime(2026, 8, 4, 3, 0, tzinfo=UTC)


def item_payload(
    *,
    item_id: str = "item-1",
    status: str = "UPDATED",
    execution_status: str = "SUCCESS",
    products: list[str] | None = None,
) -> JsonObject:
    payload: JsonObject = {
        "id": item_id,
        "status": status,
        "executionStatus": execution_status,
        "updatedAt": "2026-08-04T02:59:00.000Z",
        "lastUpdatedAt": "2026-08-04T02:58:00.000Z",
    }
    if products is not None:
        payload["connector"] = {"products": products}
    return payload


def accounts_payload() -> JsonObject:
    return {
        "results": [
            {
                "id": "account-bank",
                "itemId": "item-1",
                "type": "BANK",
                "subtype": "CHECKING_ACCOUNT",
                "currencyCode": "BRL",
                "name": "Conta corrente",
                "number": "0001/12345-0",
                "owner": "must-not-leak",
                "balance": 1234,
            },
            {
                "id": "account-card",
                "itemId": "item-1",
                "type": "CREDIT",
                "subtype": "CREDIT_CARD",
                "currencyCode": "BRL",
                "name": "Cartão",
                "number": "9876",
                "taxNumber": "must-not-leak",
            },
        ]
    }


def transactions_payload() -> JsonObject:
    return {
        "results": [
            {
                "id": "transaction-1",
                "accountId": "account-card",
                "status": "POSTED",
                "date": "2026-08-01T00:00:00.000Z",
                "updatedAt": "2026-08-02T10:00:00.000Z",
                "amount": 125.50,
                "currencyCode": "BRL",
                "description": "Compra",
                "category": "Shopping",
                "creditCardMetadata": {
                    "billId": "bill-1",
                    "installmentNumber": 2,
                    "totalInstallments": 6,
                    "totalAmount": 753,
                },
            },
            {
                "id": "transaction-2",
                "accountId": "account-card",
                "status": "PENDING",
                "date": "2026-08-03",
                "amount": "50.25",
                "currencyCode": "BRL",
                "creditCardMetadata": None,
            },
        ],
        "next": "?accountId=account-card&after=opaque-cursor",
    }


@dataclass
class FakeTransport:
    item: JsonObject = field(default_factory=item_payload)
    accounts: JsonObject = field(default_factory=accounts_payload)
    transactions: JsonObject = field(default_factory=transactions_payload)
    failure: Exception | None = None
    transaction_calls: list[tuple[str, str | None, datetime | None]] = field(
        default_factory=list
    )

    def _maybe_fail(self) -> None:
        if self.failure is not None:
            raise self.failure

    def get_item(self, item_id: str) -> JsonObject:
        del item_id
        self._maybe_fail()
        return self.item

    def get_accounts(self, item_id: str) -> JsonObject:
        del item_id
        self._maybe_fail()
        return self.accounts

    def get_transactions_page(
        self,
        account_id: str,
        *,
        after: str | None,
        created_at_from: datetime | None,
    ) -> JsonObject:
        self._maybe_fail()
        self.transaction_calls.append((account_id, after, created_at_from))
        return self.transactions


def gateway(transport: FakeTransport | None = None) -> PluggyHttpReadOnlyGateway:
    return PluggyHttpReadOnlyGateway(
        transport or FakeTransport(),
        clock=lambda: NOW,
    )


def capability_map(snapshot: object) -> dict[PluggyCapability, object]:
    capabilities = getattr(snapshot, "capabilities")
    return {capability.capability: capability for capability in capabilities}


def test_gateway_satisfies_read_only_protocol() -> None:
    instance = gateway()
    assert isinstance(instance, PluggyReadOnlyGateway)
    assert isinstance(FakeTransport(), PluggyPayloadTransport)


def test_item_success_maps_state_timestamps_and_capabilities() -> None:
    transport = FakeTransport(
        item=item_payload(products=["ACCOUNTS", "TRANSACTIONS", "IDENTITY"])
    )
    snapshot = gateway(transport).get_item("item-1")

    assert snapshot.phase is PluggyConnectionPhase.AVAILABLE
    assert snapshot.last_attempt_at == datetime(2026, 8, 4, 2, 59, tzinfo=UTC)
    assert snapshot.last_successful_update_at == datetime(
        2026, 8, 4, 2, 58, tzinfo=UTC
    )
    assert snapshot.next_refresh_allowed_at is None
    capabilities = capability_map(snapshot)
    assert capabilities[PluggyCapability.IDENTITY].availability is (
        PluggyCapabilityAvailability.AVAILABLE
    )
    assert capabilities[PluggyCapability.TRANSACTIONS].availability is (
        PluggyCapabilityAvailability.AVAILABLE
    )
    assert capabilities[PluggyCapability.BANK_ACCOUNTS].availability is (
        PluggyCapabilityAvailability.UNKNOWN
    )
    assert capabilities[PluggyCapability.CREDIT_ACCOUNTS].availability is (
        PluggyCapabilityAvailability.UNKNOWN
    )


@pytest.mark.parametrize(
    ("status", "execution_status", "expected"),
    [
        ("UPDATED", "PARTIAL_SUCCESS", PluggyConnectionPhase.PARTIAL),
        ("UPDATING", "LOGIN_IN_PROGRESS", PluggyConnectionPhase.SYNCING),
        (
            "WAITING_USER_INPUT",
            "WAITING_USER_INPUT",
            PluggyConnectionPhase.USER_ACTION_REQUIRED,
        ),
        (
            "WAITING_USER_ACTION",
            "WAITING_USER_ACTION",
            PluggyConnectionPhase.USER_ACTION_REQUIRED,
        ),
        (
            "LOGIN_ERROR",
            "INVALID_CREDENTIALS",
            PluggyConnectionPhase.REAUTHENTICATION_REQUIRED,
        ),
        (
            "OUTDATED",
            "SITE_NOT_AVAILABLE",
            PluggyConnectionPhase.TEMPORARILY_UNAVAILABLE,
        ),
        ("DELETED", "SUCCESS", PluggyConnectionPhase.DISCONNECTED),
        ("UNKNOWN", "UNKNOWN", PluggyConnectionPhase.FAILED),
    ],
)
def test_item_status_mapping(
    status: str,
    execution_status: str,
    expected: PluggyConnectionPhase,
) -> None:
    snapshot = gateway(
        FakeTransport(item=item_payload(status=status, execution_status=execution_status))
    ).get_item("item-1")
    assert snapshot.phase is expected


def test_item_without_connector_products_is_conservative() -> None:
    snapshot = gateway().get_item("item-1")
    assert {
        capability.availability for capability in snapshot.capabilities
    } == {PluggyCapabilityAvailability.UNKNOWN}


def test_item_association_mismatch_fails_without_identifier_leak() -> None:
    transport = FakeTransport(item=item_payload(item_id="secret-item"))
    with pytest.raises(PluggyGatewayError) as raised:
        gateway(transport).get_item("item-1")

    assert raised.value.category is PluggyGatewayErrorCategory.INTERNAL
    assert raised.value.provider_reason_code == "ITEM_ASSOCIATION_MISMATCH"
    assert "secret-item" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_accounts_are_sanitized_and_masked() -> None:
    snapshots = gateway().list_accounts("item-1")

    assert [snapshot.kind for snapshot in snapshots] == [
        PluggyAccountKind.BANK,
        PluggyAccountKind.CREDIT,
    ]
    assert snapshots[0].number_mask == "***3450"
    assert snapshots[1].number_mask == "***9876"
    rendered = repr(snapshots)
    assert "must-not-leak" not in rendered
    assert "1234" not in rendered


def test_unknown_account_type_maps_to_other() -> None:
    payload = accounts_payload()
    results = payload["results"]
    assert isinstance(results, list)
    results[0]["type"] = "PAYMENT"
    snapshot = gateway(FakeTransport(accounts=payload)).list_accounts("item-1")[0]
    assert snapshot.kind is PluggyAccountKind.OTHER


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        ("cross_item", "ACCOUNT_ASSOCIATION_MISMATCH"),
        ("duplicate", "DUPLICATE_ACCOUNT_ID"),
        ("missing_results", "INVALID_ACCOUNTS_COLLECTION"),
    ],
)
def test_invalid_account_collections_fail_closed(
    mutation: str,
    reason_code: str,
) -> None:
    payload = accounts_payload()
    results = payload["results"]
    assert isinstance(results, list)
    if mutation == "cross_item":
        results[0]["itemId"] = "other-item"
    elif mutation == "duplicate":
        results[1]["id"] = results[0]["id"]
    else:
        payload.pop("results")

    with pytest.raises(PluggyGatewayError) as raised:
        gateway(FakeTransport(accounts=payload)).list_accounts("item-1")
    assert raised.value.provider_reason_code == reason_code


def test_transactions_preserve_state_installment_and_cursor() -> None:
    page = gateway().list_transactions("account-card", None, None)

    assert len(page.records) == 2
    assert page.records[0].state is PluggyTransactionState.POSTED
    assert page.records[0].amount == Decimal("125.5")
    assert page.records[0].bill_reference == "bill-1"
    assert page.records[0].installment is not None
    assert page.records[0].installment.number == 2
    assert page.records[0].installment.count == 6
    assert page.records[0].installment.total_amount == Decimal("753")
    assert page.records[1].state is PluggyTransactionState.PENDING
    assert page.records[1].amount == Decimal("50.25")
    assert page.next_cursor == "opaque-cursor"
    assert page.source_window == "FULL"
    assert page.retrieved_at == NOW


def test_changed_since_is_forwarded_as_created_window() -> None:
    transport = FakeTransport()
    changed_since = datetime(2026, 8, 1, tzinfo=UTC)
    page = gateway(transport).list_transactions(
        "account-card",
        "cursor-1",
        changed_since,
    )

    assert transport.transaction_calls == [
        ("account-card", "cursor-1", changed_since)
    ]
    assert page.source_window == "CREATED_AT_FROM"


def test_naive_changed_since_is_rejected_before_transport() -> None:
    transport = FakeTransport()
    with pytest.raises(PluggyGatewayError) as raised:
        gateway(transport).list_transactions(
            "account-card",
            None,
            datetime(2026, 8, 1),
        )
    assert raised.value.category is PluggyGatewayErrorCategory.INVALID_REQUEST
    assert transport.transaction_calls == []


@pytest.mark.parametrize(
    "next_value",
    [
        "https://evil.example/v2/transactions?accountId=account-card&after=x",
        "?accountId=other-account&after=x",
        "?accountId=account-card&cursor=x",
        "?accountId=account-card&after=x&after=y",
        "/other?accountId=account-card&after=x",
    ],
)
def test_unsafe_next_cursor_is_rejected(next_value: str) -> None:
    payload = transactions_payload()
    payload["next"] = next_value
    with pytest.raises(PluggyGatewayError) as raised:
        gateway(FakeTransport(transactions=payload)).list_transactions(
            "account-card",
            None,
            None,
        )
    assert raised.value.category is PluggyGatewayErrorCategory.INTERNAL
    assert raised.value.__cause__ is None


def test_cross_account_transaction_is_rejected() -> None:
    payload = transactions_payload()
    results = payload["results"]
    assert isinstance(results, list)
    results[0]["accountId"] = "secret-other-account"
    with pytest.raises(PluggyGatewayError) as raised:
        gateway(FakeTransport(transactions=payload)).list_transactions(
            "account-card",
            None,
            None,
        )
    assert raised.value.provider_reason_code == "TRANSACTION_ASSOCIATION_MISMATCH"
    assert "secret-other-account" not in str(raised.value)


def test_incomplete_installment_metadata_is_rejected() -> None:
    payload = transactions_payload()
    results = payload["results"]
    assert isinstance(results, list)
    metadata = results[0]["creditCardMetadata"]
    assert isinstance(metadata, dict)
    metadata.pop("totalInstallments")
    with pytest.raises(PluggyGatewayError) as raised:
        gateway(FakeTransport(transactions=payload)).list_transactions(
            "account-card",
            None,
            None,
        )
    assert raised.value.provider_reason_code == "INCOMPLETE_INSTALLMENT_METADATA"


def test_transport_error_is_mapped_without_chain_or_diagnostics() -> None:
    failure = PluggyTransportError(
        PluggyTransportErrorCategory.RATE_LIMITED,
        retryable=True,
        status_code=429,
        provider_reason_code="RATE_LIMIT_RETRY_EXHAUSTED",
    )
    transport = FakeTransport(failure=failure)
    with pytest.raises(PluggyGatewayError) as raised:
        gateway(transport).get_item("item-1")

    assert raised.value.category is PluggyGatewayErrorCategory.RATE_LIMITED
    assert raised.value.retryable is True
    assert raised.value.provider_reason_code == "RATE_LIMIT_RETRY_EXHAUSTED"
    assert raised.value.__cause__ is None
    assert str(raised.value) == "pluggy gateway operation failed"


def test_unexpected_transport_failure_is_sanitized() -> None:
    transport = FakeTransport(failure=RuntimeError("secret raw payload"))
    with pytest.raises(PluggyGatewayError) as raised:
        gateway(transport).get_item("item-1")
    assert raised.value.provider_reason_code == "UNEXPECTED_ITEM_GATEWAY_FAILURE"
    assert "secret raw payload" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_concrete_transport_uses_after_and_created_at_from() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth":
            return httpx.Response(
                200,
                json={"apiKey": "ephemeral-key"},
                headers={"Content-Type": "application/json"},
            )
        return httpx.Response(
            200,
            json={"results": [], "next": None},
            headers={"Content-Type": "application/json"},
        )

    transport = PluggyGatewayHttpTransport(
        PluggyApplicationCredentials("client-id", "client-secret"),
        base_url="http://127.0.0.1:8080",
        http_transport=httpx.MockTransport(handler),
    )
    try:
        payload = transport.get_transactions_page(
            "account-card",
            after="opaque-cursor",
            created_at_from=datetime(2026, 8, 1, 12, 30, tzinfo=UTC),
        )
    finally:
        transport.close()

    assert payload == {"results": [], "next": None}
    query = requests[-1].url.params
    assert query["accountId"] == "account-card"
    assert query["after"] == "opaque-cursor"
    assert query["createdAtFrom"] == "2026-08-01T12:30:00.000Z"
    assert "cursor" not in query


def test_concrete_transport_rejects_naive_created_at_from() -> None:
    transport = PluggyGatewayHttpTransport(
        PluggyApplicationCredentials("client-id", "client-secret"),
        base_url="http://127.0.0.1:8080",
        http_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                500,
                json={},
                headers={"Content-Type": "application/json"},
            )
        ),
    )
    try:
        with pytest.raises(ValueError, match="timezone-aware"):
            transport.get_transactions_page(
                "account-card",
                after=None,
                created_at_from=datetime(2026, 8, 1),
            )
    finally:
        transport.close()
