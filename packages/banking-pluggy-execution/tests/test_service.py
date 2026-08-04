from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from meufinanceiro_banking import (
    BankingProviderError,
    ConnectionStatus,
    ProviderErrorCategory,
    TransactionStatus,
)
from meufinanceiro_banking_pluggy.transport import (
    JsonObject,
    PluggyApplicationCredentials,
)
from meufinanceiro_banking_pluggy_execution import (
    ContextualBankingStore,
    PluggyExecutionTransport,
    PluggyReadOnlyExecutionService,
)
from meufinanceiro_persistence import (
    BankingConnectionRecord,
    ConnectionNotFoundError,
    EnabledProviderCredentials,
    StoredConnectionStatus,
)

NOW = datetime(2026, 8, 4, 4, 30, tzinfo=UTC)
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
CONNECTION_ID = UUID("30000000-0000-4000-8000-000000000003")
CONFIGURATION_ID = UUID("40000000-0000-4000-8000-000000000004")
ITEM_ID = "item-secret-1"
ACCOUNT_ID = "account-secret-1"


def connection_record(
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


def enabled_credentials(
    *,
    provider: str = "pluggy",
) -> EnabledProviderCredentials:
    return EnabledProviderCredentials(
        configuration_id=CONFIGURATION_ID,
        provider=provider,
        configuration_revision=2,
        client_id="test-client-id",
        client_secret="test-client-secret",
    )


@dataclass
class FakeStore:
    connection: BankingConnectionRecord = field(default_factory=connection_record)
    credentials: EnabledProviderCredentials = field(default_factory=enabled_credentials)
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
        self.connection_calls.append(
            (installation_id, residence_id, connection_id)
        )
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
    item_payload: JsonObject = field(
        default_factory=lambda: {
            "id": ITEM_ID,
            "status": "UPDATED",
            "executionStatus": "SUCCESS",
            "updatedAt": "2026-08-04T04:29:00.000Z",
            "lastUpdatedAt": "2026-08-04T04:28:00.000Z",
            "connector": {"products": ["ACCOUNTS", "TRANSACTIONS"]},
        }
    )
    accounts_payload: JsonObject = field(
        default_factory=lambda: {
            "results": [
                {
                    "id": ACCOUNT_ID,
                    "itemId": ITEM_ID,
                    "type": "BANK",
                    "subtype": "CHECKING_ACCOUNT",
                    "currencyCode": "BRL",
                    "name": "Conta",
                    "number": "1234",
                }
            ]
        }
    )
    transactions_payload: JsonObject = field(
        default_factory=lambda: {
            "results": [
                {
                    "id": "transaction-secret-1",
                    "accountId": ACCOUNT_ID,
                    "status": "POSTED",
                    "date": "2026-08-03",
                    "updatedAt": "2026-08-04T04:00:00.000Z",
                    "amount": "10.50",
                    "currencyCode": "BRL",
                    "description": "Teste",
                }
            ],
            "next": None,
        }
    )
    close_failure: bool = False
    closed: bool = False
    item_calls: list[str] = field(default_factory=list)
    account_calls: list[str] = field(default_factory=list)
    transaction_calls: list[tuple[str, str | None, datetime | None]] = field(
        default_factory=list
    )

    def get_item(self, item_id: str) -> JsonObject:
        self.item_calls.append(item_id)
        return self.item_payload

    def get_accounts(self, item_id: str) -> JsonObject:
        self.account_calls.append(item_id)
        return self.accounts_payload

    def get_transactions_page(
        self,
        account_id: str,
        *,
        after: str | None,
        created_at_from: datetime | None,
    ) -> JsonObject:
        self.transaction_calls.append((account_id, after, created_at_from))
        return self.transactions_payload

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
        self.credential_pairs.append(
            (credentials.client_id, credentials.client_secret)
        )
        if self.failure is not None:
            raise self.failure
        return self.transport


def service(
    *,
    store: FakeStore | None = None,
    transport: FakeTransport | None = None,
    factory: RecordingFactory | None = None,
) -> tuple[
    PluggyReadOnlyExecutionService,
    FakeStore,
    FakeTransport,
    RecordingFactory,
]:
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


def context() -> dict[str, UUID]:
    return {
        "installation_id": INSTALLATION_ID,
        "residence_id": RESIDENCE_ID,
        "connection_id": CONNECTION_ID,
    }


def test_structural_protocols_are_satisfied() -> None:
    assert isinstance(FakeStore(), ContextualBankingStore)
    assert isinstance(FakeTransport(), PluggyExecutionTransport)


def test_connection_state_uses_internal_context_and_closes_transport() -> None:
    executor, store, transport, factory = service()

    state = executor.get_connection_state(**context())

    assert state.status is ConnectionStatus.AVAILABLE
    assert store.connection_calls == [
        (INSTALLATION_ID, RESIDENCE_ID, CONNECTION_ID)
    ]
    assert store.credential_calls == [(INSTALLATION_ID, "pluggy")]
    assert transport.item_calls == [ITEM_ID]
    assert transport.closed is True
    assert factory.credential_pairs == [("test-client-id", "test-client-secret")]


def test_capabilities_and_accounts_return_neutral_dtos() -> None:
    executor, _, transport, _ = service()

    capabilities = executor.get_capabilities(**context())
    accounts = executor.list_accounts(**context())

    assert capabilities
    assert accounts[0].external_account_id == ACCOUNT_ID
    assert accounts[0].external_connection_id == ITEM_ID
    assert transport.closed is True


def test_transactions_validate_membership_and_forward_window() -> None:
    executor, _, transport, _ = service()
    changed_since = datetime(2026, 8, 1, tzinfo=UTC)

    page = executor.list_transactions(
        **context(),
        external_account_id=ACCOUNT_ID,
        cursor="opaque-cursor",
        changed_since=changed_since,
    )

    assert page.records[0].status is TransactionStatus.CONFIRMED
    assert transport.account_calls == [ITEM_ID]
    assert transport.transaction_calls == [
        (ACCOUNT_ID, "opaque-cursor", changed_since)
    ]
    assert transport.closed is True


def test_unknown_account_fails_without_transaction_call_or_identifier_leak() -> None:
    executor, _, transport, _ = service()

    with pytest.raises(BankingProviderError) as raised:
        executor.list_transactions(
            **context(),
            external_account_id="unknown-secret-account",
        )

    assert raised.value.category is ProviderErrorCategory.NOT_FOUND
    assert raised.value.provider_reason_code == "ACCOUNT_NOT_IN_CONNECTION"
    assert "unknown-secret-account" not in str(raised.value)
    assert transport.transaction_calls == []
    assert transport.closed is True


def test_residence_mismatch_fails_before_credentials_and_transport() -> None:
    store = FakeStore(allow_residence=False)
    executor, _, _, factory = service(store=store)

    with pytest.raises(ConnectionNotFoundError):
        executor.get_connection_state(**context())

    assert store.credential_calls == []
    assert factory.credential_pairs == []


@pytest.mark.parametrize(
    ("connection", "category", "reason_code"),
    [
        (
            connection_record(provider="other"),
            ProviderErrorCategory.UNSUPPORTED,
            "PROVIDER_NOT_SUPPORTED",
        ),
        (
            connection_record(status=StoredConnectionStatus.DISCONNECTED),
            ProviderErrorCategory.INVALID_REQUEST,
            "CONNECTION_DISCONNECTED",
        ),
    ],
)
def test_invalid_connection_is_blocked_before_credentials(
    connection: BankingConnectionRecord,
    category: ProviderErrorCategory,
    reason_code: str,
) -> None:
    store = FakeStore(connection=connection)
    executor, _, _, factory = service(store=store)

    with pytest.raises(BankingProviderError) as raised:
        executor.get_connection_state(**context())

    assert raised.value.category is category
    assert raised.value.provider_reason_code == reason_code
    assert store.credential_calls == []
    assert factory.credential_pairs == []


def test_credential_provider_mismatch_fails_before_factory() -> None:
    store = FakeStore(credentials=enabled_credentials(provider="other"))
    executor, _, _, factory = service(store=store)

    with pytest.raises(BankingProviderError) as raised:
        executor.get_connection_state(**context())

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert raised.value.provider_reason_code == "CREDENTIAL_PROVIDER_MISMATCH"
    assert factory.credential_pairs == []


def test_factory_failure_is_sanitized_without_credentials() -> None:
    factory = RecordingFactory(
        FakeTransport(),
        failure=RuntimeError("test-client-secret raw URL"),
    )
    executor, _, _, _ = service(factory=factory)

    with pytest.raises(BankingProviderError) as raised:
        executor.get_connection_state(**context())

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert raised.value.provider_reason_code == "PROVIDER_EXECUTION_FAILED"
    assert "test-client-secret" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_transport_closes_when_provider_payload_fails() -> None:
    transport = FakeTransport(item_payload={"id": ITEM_ID})
    executor, _, _, _ = service(transport=transport)

    with pytest.raises(BankingProviderError) as raised:
        executor.get_connection_state(**context())

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert transport.closed is True


def test_close_failure_after_success_is_sanitized() -> None:
    transport = FakeTransport(close_failure=True)
    executor, _, _, _ = service(transport=transport)

    with pytest.raises(BankingProviderError) as raised:
        executor.get_connection_state(**context())

    assert raised.value.category is ProviderErrorCategory.INTERNAL
    assert raised.value.provider_reason_code == "TRANSPORT_CLOSE_FAILED"
    assert "raw close failure" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_close_failure_does_not_mask_provider_error() -> None:
    transport = FakeTransport(
        item_payload={"id": ITEM_ID},
        close_failure=True,
    )
    executor, _, _, _ = service(transport=transport)

    with pytest.raises(BankingProviderError) as raised:
        executor.get_connection_state(**context())

    assert raised.value.provider_reason_code != "TRANSPORT_CLOSE_FAILED"
    assert transport.closed is True


def test_invalid_changed_since_fails_before_store_and_transport() -> None:
    executor, store, _, factory = service()

    with pytest.raises(ValueError, match="timezone-aware"):
        executor.list_transactions(
            **context(),
            external_account_id=ACCOUNT_ID,
            changed_since=datetime(2026, 8, 1),
        )

    assert store.connection_calls == []
    assert factory.credential_pairs == []


def test_constructor_rejects_invalid_dependencies() -> None:
    with pytest.raises(TypeError, match="store"):
        PluggyReadOnlyExecutionService(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="transport_factory"):
        PluggyReadOnlyExecutionService(
            FakeStore(),
            transport_factory=None,  # type: ignore[arg-type]
        )


def test_connection_record_helper_can_change_status_without_item_exposure() -> None:
    record = replace(
        connection_record(),
        status=StoredConnectionStatus.PARTIAL,
    )
    assert record.id == CONNECTION_ID
    assert ITEM_ID not in repr(PluggyReadOnlyExecutionService)
