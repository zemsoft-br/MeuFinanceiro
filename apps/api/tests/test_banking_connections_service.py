from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from meufinanceiro_persistence import (
    LocalBankingConnectionRecord,
    StoredConnectionStatus,
)

from app.services.banking_connections import BankingConnectionsService

INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
CONNECTION_ID = UUID("30000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 8, 8, tzinfo=UTC)


class FakeStore:
    def __init__(self, records: tuple[LocalBankingConnectionRecord, ...]) -> None:
        self.records = records
        self.calls: list[tuple[UUID, UUID]] = []

    def list_connections(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
    ) -> tuple[LocalBankingConnectionRecord, ...]:
        self.calls.append((installation_id, residence_id))
        return self.records


def _record(
    *,
    provider: str = "pluggy",
    status: StoredConnectionStatus = StoredConnectionStatus.AVAILABLE,
) -> LocalBankingConnectionRecord:
    return LocalBankingConnectionRecord(
        id=CONNECTION_ID,
        provider=provider,
        status=status,
        requires_user_action=(
            status is StoredConnectionStatus.REAUTHENTICATION_REQUIRED
        ),
        last_successful_sync_at=None,
        last_attempt_at=NOW,
        next_refresh_allowed_at=None,
        consent_expires_at=None,
        disconnected_at=(NOW if status is StoredConnectionStatus.DISCONNECTED else None),
        created_at=NOW,
        updated_at=NOW,
    )


def test_reauthentication_availability_is_derived_without_provider_io() -> None:
    store = FakeStore(
        (
            _record(status=StoredConnectionStatus.REAUTHENTICATION_REQUIRED),
        )
    )
    service = BankingConnectionsService(
        store,
        pluggy_reauthentication_available=True,
    )

    summaries = service.list_connections(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
    )

    assert len(summaries) == 1
    assert summaries[0].connection_id == CONNECTION_ID
    assert summaries[0].reauthentication_available is True
    assert store.calls == [(INSTALLATION_ID, RESIDENCE_ID)]


def test_reauthentication_is_unavailable_when_runtime_or_connection_disallows_it() -> None:
    for record, runtime_available in (
        (_record(), False),
        (_record(status=StoredConnectionStatus.DISCONNECTED), True),
        (_record(provider="other_provider"), True),
    ):
        service = BankingConnectionsService(
            FakeStore((record,)),
            pluggy_reauthentication_available=runtime_available,
        )

        summary = service.list_connections(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
        )[0]

        assert summary.reauthentication_available is False
