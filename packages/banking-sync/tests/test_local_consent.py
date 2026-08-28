from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from meufinanceiro_persistence import StoredConnectionStatus

from meufinanceiro_banking_sync.consent_lifecycle import (
    ConsentLifecycleEvaluator,
    ConsentLifecyclePolicy,
    ConsentLifecycleState,
)
from meufinanceiro_banking_sync.local_consent import (
    ConsentConnectionNotFoundError,
    ConsentConnectionSnapshot,
    LocalConsentLifecycleService,
)

NOW = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)


class FakeConsentReader:
    def __init__(self, snapshot: ConsentConnectionSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[UUID, UUID, UUID, UUID]] = []
        self.error: Exception | None = None

    def read_consent_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> ConsentConnectionSnapshot:
        self.calls.append(
            (installation_id, residence_id, operator_id, connection_id)
        )
        if self.error is not None:
            raise self.error
        return self.snapshot


def subject(
    snapshot: ConsentConnectionSnapshot,
) -> tuple[LocalConsentLifecycleService, FakeConsentReader]:
    reader = FakeConsentReader(snapshot)
    evaluator = ConsentLifecycleEvaluator(
        policy=ConsentLifecyclePolicy(warning_window=timedelta(days=30)),
        clock=lambda: NOW,
    )
    return LocalConsentLifecycleService(reader=reader, evaluator=evaluator), reader


def evaluate(
    service: LocalConsentLifecycleService,
) -> tuple[object, tuple[UUID, UUID, UUID, UUID]]:
    scope = (uuid4(), uuid4(), uuid4(), uuid4())
    result = service.evaluate_connection(
        installation_id=scope[0],
        residence_id=scope[1],
        operator_id=scope[2],
        connection_id=scope[3],
    )
    return result, scope


def test_available_connection_projects_valid_consent_without_provider_material() -> None:
    service, reader = subject(
        ConsentConnectionSnapshot(
            status=StoredConnectionStatus.AVAILABLE,
            consent_expires_at=NOW + timedelta(days=31),
        )
    )

    result, scope = evaluate(service)

    assert result.state is ConsentLifecycleState.VALID
    assert result.renewal_required is False
    assert result.connection_terminal is False
    assert reader.calls == [scope]
    rendered = repr(result)
    assert all(str(identifier) not in rendered for identifier in scope)
    assert "pluggy" not in rendered.lower()


@pytest.mark.parametrize(
    ("status", "expires_at", "state", "renewal_required", "terminal"),
    [
        (
            StoredConnectionStatus.AVAILABLE,
            NOW + timedelta(days=30),
            ConsentLifecycleState.EXPIRING,
            True,
            False,
        ),
        (
            StoredConnectionStatus.AVAILABLE,
            NOW,
            ConsentLifecycleState.EXPIRED,
            True,
            False,
        ),
        (
            StoredConnectionStatus.REAUTHENTICATION_REQUIRED,
            None,
            ConsentLifecycleState.UNKNOWN,
            False,
            False,
        ),
        (
            StoredConnectionStatus.DISCONNECTED,
            NOW - timedelta(days=1),
            ConsentLifecycleState.EXPIRED,
            False,
            True,
        ),
    ],
)
def test_projection_preserves_consent_classifier_semantics(
    status: StoredConnectionStatus,
    expires_at: datetime | None,
    state: ConsentLifecycleState,
    renewal_required: bool,
    terminal: bool,
) -> None:
    service, _reader = subject(
        ConsentConnectionSnapshot(
            status=status,
            consent_expires_at=expires_at,
        )
    )

    result, _scope = evaluate(service)

    assert result.state is state
    assert result.renewal_required is renewal_required
    assert result.connection_terminal is terminal


def test_reader_failure_is_sanitized_by_reader_contract_and_propagated() -> None:
    service, reader = subject(
        ConsentConnectionSnapshot(
            status=StoredConnectionStatus.AVAILABLE,
            consent_expires_at=None,
        )
    )
    reader.error = ConsentConnectionNotFoundError(
        "local banking connection was not found"
    )

    scope = (uuid4(), uuid4(), uuid4(), uuid4())
    with pytest.raises(
        ConsentConnectionNotFoundError,
        match="local banking connection was not found",
    ) as raised:
        service.evaluate_connection(
            installation_id=scope[0],
            residence_id=scope[1],
            operator_id=scope[2],
            connection_id=scope[3],
        )

    rendered = repr(raised.value)
    assert all(str(identifier) not in rendered for identifier in scope)


def test_invalid_local_identifier_fails_before_reader() -> None:
    service, reader = subject(
        ConsentConnectionSnapshot(
            status=StoredConnectionStatus.AVAILABLE,
            consent_expires_at=None,
        )
    )

    with pytest.raises(ValueError, match="connection_id must be UUIDv4"):
        service.evaluate_connection(
            installation_id=uuid4(),
            residence_id=uuid4(),
            operator_id=uuid4(),
            connection_id=UUID("00000000-0000-0000-0000-000000000000"),
        )

    assert reader.calls == []


def test_snapshot_rejects_naive_consent_timestamp_and_redacts_repr() -> None:
    with pytest.raises(ValueError, match="consent_expires_at must be timezone-aware"):
        ConsentConnectionSnapshot(
            status=StoredConnectionStatus.AVAILABLE,
            consent_expires_at=datetime(2026, 8, 28, 12, 0),
        )

    snapshot = ConsentConnectionSnapshot(
        status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW + timedelta(days=31),
    )
    assert repr(snapshot) == (
        "ConsentConnectionSnapshot(<local-consent-facts-redacted>)"
    )
