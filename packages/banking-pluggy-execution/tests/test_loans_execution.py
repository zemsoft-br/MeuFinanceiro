from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import pytest
from meufinanceiro_banking import BankingProviderError, ProviderErrorCategory
from meufinanceiro_banking_pluggy.transport import (
    JsonObject,
    PluggyApplicationCredentials,
)
from meufinanceiro_banking_pluggy_execution import (
    ContextualBankingStore,
    PluggyExecutionTransport,
    PluggyLoansExecutionTransport,
    PluggyReadOnlyExecutionService,
)
from meufinanceiro_persistence import (
    BankingConnectionRecord,
    ConnectionNotFoundError,
    EnabledProviderCredentials,
    StoredConnectionStatus,
)

NOW = datetime(2026, 9, 19, 3, 0, tzinfo=UTC)
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
CONNECTION_ID = UUID("30000000-0000-4000-8000-000000000003")
CONFIGURATION_ID = UUID("40000000-0000-4000-8000-000000000004")
ITEM_ID = "item-secret-loans"


def _connection(
    *,
    provider: str = "pluggy",
    status: StoredConnectionStatus = StoredConnectionStatus.AVAILABLE,
) -> BankingConnectionRecord:
    return BankingConnectionRecord(
        id=CONNECTION_ID,
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        provider=provider,
        external_connection_id=ITEM_ID,
        status=status,
        requires_user_action=False,
        last_successful_sync_at=NOW,
        last_attempt_at=NOW,
        next_refresh_allowed_at=None,
        consent_expires_at=None,
        provider_reason_code=None,
        disconnected_at=NOW if status is StoredConnectionStatus.DISCONNECTED else None,
        created_at=NOW,
        updated_at=NOW,
    )


def _credentials(
    *,
    provider: str = "pluggy",
) -> EnabledProviderCredentials:
    return EnabledProviderCredentials(
        configuration_id=CONFIGURATION_ID,
        provider=provider,
        configuration_revision=1,
        client_id="synthetic-client",
        client_secret="synthetic-secret",
    )


@dataclass
class FakeStore:
    connection: BankingConnectionRecord = field(default_factory=_connection)
    credentials: EnabledProviderCredentials = field(default_factory=_credentials)
    allow_residence: bool = True
    credential_calls: list[tuple[UUID, str]] = field(default_factory=list)

    def get_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        if (
            not self.allow_residence
            or installation_id != self.connection.installation_id
            or residence_id != self.connection.residence_id
            or connection_id != self.connection.id
        ):
            raise ConnectionNotFoundError("banking connection was not found")
        return self.connection

    def use_enabled_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        operation: object,
    ) -> object:
        self.credential_calls.append((installation_id, provider))
        assert callable(operation)
        return operation(self.credentials)


@dataclass
class FakeTransport:
    invalid_loan: bool = False
    close_failure: bool = False
    closed: bool = False
    calls: list[tuple[str, int, int]] = field(default_factory=list)

    def get_item(self, item_id: str) -> JsonObject:
        return {"id": item_id, "status": "UPDATED", "executionStatus": "SUCCESS"}

    def get_accounts(self, item_id: str) -> JsonObject:
        del item_id
        return {"results": []}

    def get_transactions_page(
        self,
        account_id: str,
        *,
        after: str | None,
        created_at_from: datetime | None,
    ) -> JsonObject:
        del account_id, after, created_at_from
        return {"results": [], "next": None}

    def get_loans_page(
        self,
        item_id: str,
        *,
        page: int,
        page_size: int,
    ) -> JsonObject:
        self.calls.append((item_id, page, page_size))
        if self.invalid_loan:
            return {
                "page": 1,
                "total": 1,
                "totalPages": 1,
                "results": [{"id": "broken"}],
            }
        return {
            "page": 1,
            "total": 1,
            "totalPages": 1,
            "results": [
                {
                    "id": "loan-secret-1",
                    "itemId": item_id,
                    "kind": "LOAN",
                    "date": "2026-09-18T12:00:00.000Z",
                    "currencyCode": "BRL",
                    "payments": {"contractOutstandingBalance": "1000.04"},
                }
            ],
        }

    def close(self) -> None:
        self.closed = True
        if self.close_failure:
            raise RuntimeError("raw close failure")


@dataclass
class RecordingFactory:
    transport: FakeTransport
    credential_pairs: list[tuple[str, str]] = field(default_factory=list)

    def __call__(
        self,
        credentials: PluggyApplicationCredentials,
    ) -> PluggyExecutionTransport:
        self.credential_pairs.append((credentials.client_id, credentials.client_secret))
        return self.transport


def _context() -> dict[str, UUID]:
    return {
        "installation_id": INSTALLATION_ID,
        "residence_id": RESIDENCE_ID,
        "connection_id": CONNECTION_ID,
    }


def _service(
    *,
    store: FakeStore | None = None,
    transport: FakeTransport | None = None,
) -> tuple[PluggyReadOnlyExecutionService, FakeStore, FakeTransport, RecordingFactory]:
    resolved_store = store or FakeStore()
    resolved_transport = transport or FakeTransport()
    factory = RecordingFactory(resolved_transport)
    return (
        PluggyReadOnlyExecutionService(
            resolved_store,
            transport_factory=factory,
        ),
        resolved_store,
        resolved_transport,
        factory,
    )


def test_structural_loan_protocol_is_satisfied() -> None:
    assert isinstance(FakeStore(), ContextualBankingStore)
    assert isinstance(FakeTransport(), PluggyExecutionTransport)
    assert isinstance(FakeTransport(), PluggyLoansExecutionTransport)


def test_contextual_loan_read_closes_transport() -> None:
    executor, store, transport, factory = _service()

    loans = executor.list_loans(**_context())

    assert len(loans) == 1
    assert loans[0].external_connection_id == ITEM_ID
    assert transport.calls == [(ITEM_ID, 1, 500)]
    assert transport.closed is True
    assert store.credential_calls == [(INSTALLATION_ID, "pluggy")]
    assert factory.credential_pairs == [("synthetic-client", "synthetic-secret")]


def test_residence_mismatch_fails_before_credentials_or_transport() -> None:
    store = FakeStore(allow_residence=False)
    executor, _, transport, factory = _service(store=store)

    with pytest.raises(ConnectionNotFoundError):
        executor.list_loans(**_context())

    assert store.credential_calls == []
    assert factory.credential_pairs == []
    assert transport.calls == []
    assert transport.closed is False


@pytest.mark.parametrize(
    ("connection", "category", "reason_code"),
    [
        (
            _connection(provider="other"),
            ProviderErrorCategory.UNSUPPORTED,
            "PROVIDER_NOT_SUPPORTED",
        ),
        (
            _connection(status=StoredConnectionStatus.DISCONNECTED),
            ProviderErrorCategory.INVALID_REQUEST,
            "CONNECTION_DISCONNECTED",
        ),
    ],
)
def test_invalid_connection_blocks_before_credentials(
    connection: BankingConnectionRecord,
    category: ProviderErrorCategory,
    reason_code: str,
) -> None:
    store = FakeStore(connection=connection)
    executor, _, transport, factory = _service(store=store)

    with pytest.raises(BankingProviderError) as raised:
        executor.list_loans(**_context())

    assert raised.value.category is category
    assert raised.value.provider_reason_code == reason_code
    assert store.credential_calls == []
    assert factory.credential_pairs == []
    assert transport.calls == []


def test_loan_payload_failure_is_sanitized_and_closes_transport() -> None:
    transport = FakeTransport(invalid_loan=True)
    executor, _, _, _ = _service(transport=transport)

    with pytest.raises(BankingProviderError) as raised:
        executor.list_loans(**_context())

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert ITEM_ID not in str(raised.value)
    assert "loan-secret-1" not in str(raised.value)
    assert transport.closed is True


def test_close_failure_after_success_is_sanitized() -> None:
    transport = FakeTransport(close_failure=True)
    executor, _, _, _ = _service(transport=transport)

    with pytest.raises(BankingProviderError) as raised:
        executor.list_loans(**_context())

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert raised.value.provider_reason_code == "TRANSPORT_CLOSE_FAILED"
    assert "raw close failure" not in str(raised.value)
