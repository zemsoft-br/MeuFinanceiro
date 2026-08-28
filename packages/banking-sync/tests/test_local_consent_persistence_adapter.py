from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from meufinanceiro_persistence import (
    BankingConsentConnectionSnapshot,
    BankingPersistenceError,
    ConnectionNotFoundError,
    StoredConnectionStatus,
)

from meufinanceiro_banking_sync import (
    ConsentConnectionReader,
    ConsentLifecycleEvaluator,
    ConsentLifecyclePolicy,
    ConsentLifecycleState,
    LocalConsentLifecycleError,
    LocalConsentLifecycleService,
    PersistenceConsentConnectionReader,
)
from meufinanceiro_banking_sync.local_consent import ConsentConnectionNotFoundError

NOW = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)


class FakeConsentFactStore:
    def __init__(self, snapshot: BankingConsentConnectionSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[UUID, UUID, UUID, UUID]] = []
        self.error: Exception | None = None

    def get_consent_connection_snapshot(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> BankingConsentConnectionSnapshot:
        self.calls.append(
            (installation_id, residence_id, operator_id, connection_id)
        )
        if self.error is not None:
            raise self.error
        return self.snapshot


def test_persistence_reader_satisfies_actor_aware_reader_and_projects_lifecycle() -> None:
    persisted = BankingConsentConnectionSnapshot(
        status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW + timedelta(days=31),
    )
    store = FakeConsentFactStore(persisted)
    reader = PersistenceConsentConnectionReader(store)
    assert isinstance(reader, ConsentConnectionReader)

    service = LocalConsentLifecycleService(
        reader=reader,
        evaluator=ConsentLifecycleEvaluator(
            policy=ConsentLifecyclePolicy(warning_window=timedelta(days=30)),
            clock=lambda: NOW,
        ),
    )
    scope = (uuid4(), uuid4(), uuid4(), uuid4())

    result = service.evaluate_connection(
        installation_id=scope[0],
        residence_id=scope[1],
        operator_id=scope[2],
        connection_id=scope[3],
    )

    assert result.state is ConsentLifecycleState.VALID
    assert result.renewal_required is False
    assert store.calls == [scope]
    rendered = repr(result)
    assert all(str(identifier) not in rendered for identifier in scope)


def test_persistence_reader_maps_invisible_connection_to_sanitized_not_found() -> None:
    store = FakeConsentFactStore(
        BankingConsentConnectionSnapshot(
            status=StoredConnectionStatus.AVAILABLE,
            consent_expires_at=None,
        )
    )
    store.error = ConnectionNotFoundError("banking connection was not found")
    reader = PersistenceConsentConnectionReader(store)
    scope = (uuid4(), uuid4(), uuid4(), uuid4())

    with pytest.raises(
        ConsentConnectionNotFoundError,
        match="local banking connection was not found",
    ) as raised:
        reader.read_consent_connection(
            installation_id=scope[0],
            residence_id=scope[1],
            operator_id=scope[2],
            connection_id=scope[3],
        )

    rendered = repr(raised.value)
    assert all(str(identifier) not in rendered for identifier in scope)


def test_persistence_reader_maps_database_failure_without_scope_material() -> None:
    store = FakeConsentFactStore(
        BankingConsentConnectionSnapshot(
            status=StoredConnectionStatus.AVAILABLE,
            consent_expires_at=None,
        )
    )
    store.error = BankingPersistenceError("synthetic internal database failure")
    reader = PersistenceConsentConnectionReader(store)
    scope = (uuid4(), uuid4(), uuid4(), uuid4())

    with pytest.raises(
        LocalConsentLifecycleError,
        match="local banking consent facts could not be read",
    ) as raised:
        reader.read_consent_connection(
            installation_id=scope[0],
            residence_id=scope[1],
            operator_id=scope[2],
            connection_id=scope[3],
        )

    rendered = repr(raised.value)
    assert all(str(identifier) not in rendered for identifier in scope)
    assert "synthetic internal database failure" not in rendered
