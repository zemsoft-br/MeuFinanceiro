from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    PluggyInvestmentsExecutionTransport,
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
ITEM_ID = "item-secret-investments"


def _connection_record(
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


def _enabled_credentials(
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
    connection: BankingConnectionRecord = field(default_factory=_connection_record)
    credentials: EnabledProviderCredentials = field(
        default_factory=_enabled_credentials
    )
    allow_residence: bool = True
    connection_calls: list[tuple[UUID, UUID, UUID]] = field(default_factory=list)
    credential_calls: list[tuple[UUID, str]] = field(default_factory=list)

    def get_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        self.connection_calls.append((installation_id, residence_id, connection_id))
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
    invalid_investment: bool = False
    close_failure: bool = False
    closed: bool = False
    investment_calls: list[tuple[str, int, int]] = field(default_factory=list)

    def get_item(self, item_id: str) -> JsonObject:
        return {
            "id": item_id,
            "status": "UPDATED",
            "executionStatus": "SUCCESS",
        }

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

    def get_investments_page(
        self,
        item_id: str,
        *,
        page: int,
        page_size: int,
    ) -> JsonObject:
        self.investment_calls.append((item_id, page, page_size))
        if self.invalid_investment:
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
                    "id": "investment-secret-1",
                    "itemId": item_id,
                    "name": "Synthetic Fund",
                    "type": "MUTUAL_FUND",
                    "balance": "100.00",
                    "currencyCode": "BRL",
                    "date": "2026-09-18T12:00:00.000Z",
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
    failure: Exception | None = None
    credential_pairs: list[tuple[str, str]] = field(default_factory=list)

    def __call__(
        self,
        credentials: PluggyApplicationCredentials,
    ) -> PluggyExecutionTransport:
        self.credential_pairs.append((credentials.client_id, credentials.client_secret))
        if self.failure is not None:
            raise self.failure
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
    factory: RecordingFactory | None = None,
) -> tuple[PluggyReadOnlyExecutionService, FakeStore, FakeTransport, RecordingFactory]:
    resolved_store = store or FakeStore()
    resolved_transport = transport or FakeTransport()
    resolved_factory = factory or RecordingFactory(resolved_transport)
    return (
        PluggyReadOnlyExecutionService(
            resolved_store,
            transport_factory=resolved_factory,
        ),
        resolved_store,
        resolved_transport,
        resolved_factory,
    )


def test_structural_investment_protocol_is_satisfied() -> None:
    assert isinstance(FakeStore(), ContextualBankingStore)
    assert isinstance(FakeTransport(), PluggyExecutionTransport)
    assert isinstance(FakeTransport(), PluggyInvestmentsExecutionTransport)


def test_contextual_investment_read_closes_transport() -> None:
    executor, store, transport, factory = _service()

    investments = executor.list_investments(**_context())

    assert len(investments) == 1
    assert investments[0].external_connection_id == ITEM_ID
    assert transport.investment_calls == [(ITEM_ID, 1, 500)]
    assert transport.closed is True
    assert store.connection_calls == [(INSTALLATION_ID, RESIDENCE_ID, CONNECTION_ID)]
    assert store.credential_calls == [(INSTALLATION_ID, "pluggy")]
    assert factory.credential_pairs == [("synthetic-client", "synthetic-secret")]


def test_residence_mismatch_fails_before_credentials_or_transport() -> None:
    store = FakeStore(allow_residence=False)
    executor, _, transport, factory = _service(store=store)

    with pytest.raises(ConnectionNotFoundError):
        executor.list_investments(**_context())

    assert store.credential_calls == []
    assert factory.credential_pairs == []
    assert transport.investment_calls == []
    assert transport.closed is False


@pytest.mark.parametrize(
    ("connection", "category", "reason_code"),
    [
        (
            _connection_record(provider="other"),
            ProviderErrorCategory.UNSUPPORTED,
            "PROVIDER_NOT_SUPPORTED",
        ),
        (
            _connection_record(status=StoredConnectionStatus.DISCONNECTED),
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
        executor.list_investments(**_context())

    assert raised.value.category is category
    assert raised.value.provider_reason_code == reason_code
    assert store.credential_calls == []
    assert factory.credential_pairs == []
    assert transport.investment_calls == []


def test_credential_provider_mismatch_fails_before_factory() -> None:
    store = FakeStore(credentials=_enabled_credentials(provider="other"))
    executor, _, transport, factory = _service(store=store)

    with pytest.raises(BankingProviderError) as raised:
        executor.list_investments(**_context())

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert raised.value.provider_reason_code == "CREDENTIAL_PROVIDER_MISMATCH"
    assert factory.credential_pairs == []
    assert transport.investment_calls == []


def test_investment_payload_failure_is_sanitized_and_closes_transport() -> None:
    transport = FakeTransport(invalid_investment=True)
    executor, _, _, _ = _service(transport=transport)

    with pytest.raises(BankingProviderError) as raised:
        executor.list_investments(**_context())

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert ITEM_ID not in str(raised.value)
    assert "investment-secret-1" not in str(raised.value)
    assert transport.closed is True


def test_factory_failure_is_sanitized_without_credentials() -> None:
    factory = RecordingFactory(
        FakeTransport(),
        failure=RuntimeError("synthetic-secret raw URL"),
    )
    executor, _, _, _ = _service(factory=factory)

    with pytest.raises(BankingProviderError) as raised:
        executor.list_investments(**_context())

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert raised.value.provider_reason_code == "PROVIDER_EXECUTION_FAILED"
    assert "synthetic-secret" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_close_failure_after_success_is_sanitized() -> None:
    transport = FakeTransport(close_failure=True)
    executor, _, _, _ = _service(transport=transport)

    with pytest.raises(BankingProviderError) as raised:
        executor.list_investments(**_context())

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert raised.value.provider_reason_code == "TRANSPORT_CLOSE_FAILED"
    assert "raw close failure" not in str(raised.value)


def test_helper_can_build_partial_connection_without_exposing_item() -> None:
    record = replace(
        _connection_record(),
        status=StoredConnectionStatus.PARTIAL,
    )

    assert record.id == CONNECTION_ID
    assert ITEM_ID not in repr(PluggyReadOnlyExecutionService)
