from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

import pytest
from meufinanceiro_banking_sync import (
    ManualBankingSyncReconciliationService,
    ManualSyncReconciliationExecutionError,
    ManualSyncResult,
    ManualSyncStopReason,
)
from meufinanceiro_persistence import (
    StoredSyncStatus,
    TransactionReconciliationError,
    TransactionReconciliationResult,
)

INSTALLATION_ID = UUID("00000000-0000-4000-8000-000000000201")
RESIDENCE_ID = UUID("00000000-0000-4000-8000-000000000202")
CONNECTION_ID = UUID("00000000-0000-4000-8000-000000000203")
RUN_ID = UUID("00000000-0000-4000-8000-000000000204")
IDEMPOTENCY_KEY = "manual-sync-post-reconciliation-001"


def _sync_result(
    *,
    status: StoredSyncStatus,
    stop_reason: ManualSyncStopReason,
) -> ManualSyncResult:
    return ManualSyncResult(
        sync_run_id=RUN_ID,
        status=status,
        records_seen=3,
        records_applied=2,
        accounts_seen=1,
        pages_committed=1,
        stop_reason=stop_reason,
    )


def _reconciliation_result(*, has_more: bool = False) -> TransactionReconciliationResult:
    return TransactionReconciliationResult(
        observations_seen=3,
        identities_created=1,
        identities_updated=1,
        identities_unchanged=1,
        has_more=has_more,
    )


class FakeSyncRunner:
    def __init__(self, results: Iterable[ManualSyncResult]) -> None:
        self.results = list(results)
        self.calls = 0

    def run(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        idempotency_key: str,
    ) -> ManualSyncResult:
        assert installation_id == INSTALLATION_ID
        assert residence_id == RESIDENCE_ID
        assert connection_id == CONNECTION_ID
        assert idempotency_key == IDEMPOTENCY_KEY
        self.calls += 1
        return self.results.pop(0)


class FakeReconciliationStore:
    def __init__(
        self,
        outcomes: Iterable[TransactionReconciliationResult | Exception],
    ) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[int] = []

    def reconcile_transaction_observations(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        limit: int = 500,
    ) -> TransactionReconciliationResult:
        assert installation_id == INSTALLATION_ID
        assert residence_id == RESIDENCE_ID
        assert connection_id == CONNECTION_ID
        self.calls.append(limit)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _run(service: ManualBankingSyncReconciliationService):
    return service.run(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        connection_id=CONNECTION_ID,
        idempotency_key=IDEMPOTENCY_KEY,
    )


@pytest.mark.parametrize(
    ("status", "stop_reason"),
    (
        (StoredSyncStatus.SUCCEEDED, ManualSyncStopReason.COMPLETED),
        (StoredSyncStatus.PARTIAL, ManualSyncStopReason.PAGE_LIMIT),
    ),
)
def test_eligible_terminal_sync_runs_exactly_one_reconciliation_batch(
    status: StoredSyncStatus,
    stop_reason: ManualSyncStopReason,
) -> None:
    sync_runner = FakeSyncRunner(
        (_sync_result(status=status, stop_reason=stop_reason),)
    )
    store = FakeReconciliationStore((_reconciliation_result(),))
    service = ManualBankingSyncReconciliationService(sync_runner, store)

    result = _run(service)

    assert result.sync_result.status is status
    assert result.reconciliation_attempted
    assert result.reconciliation_result == _reconciliation_result()
    assert sync_runner.calls == 1
    assert store.calls == [500]


@pytest.mark.parametrize(
    "status",
    (StoredSyncStatus.SUCCEEDED, StoredSyncStatus.PARTIAL),
)
def test_terminal_replay_remains_eligible_for_local_reconciliation(
    status: StoredSyncStatus,
) -> None:
    sync_runner = FakeSyncRunner(
        (
            _sync_result(
                status=status,
                stop_reason=ManualSyncStopReason.REPLAYED,
            ),
        )
    )
    store = FakeReconciliationStore((_reconciliation_result(),))

    result = _run(ManualBankingSyncReconciliationService(sync_runner, store))

    assert result.sync_result.stop_reason is ManualSyncStopReason.REPLAYED
    assert result.reconciliation_attempted
    assert store.calls == [500]


@pytest.mark.parametrize(
    ("status", "stop_reason"),
    (
        (StoredSyncStatus.FAILED, ManualSyncStopReason.INTERNAL_ERROR),
        (StoredSyncStatus.RUNNING, ManualSyncStopReason.ALREADY_RUNNING),
        (StoredSyncStatus.CANCELLED, ManualSyncStopReason.REPLAYED),
    ),
)
def test_ineligible_sync_states_never_reconcile(
    status: StoredSyncStatus,
    stop_reason: ManualSyncStopReason,
) -> None:
    sync_runner = FakeSyncRunner(
        (_sync_result(status=status, stop_reason=stop_reason),)
    )
    store = FakeReconciliationStore(())

    result = _run(ManualBankingSyncReconciliationService(sync_runner, store))

    assert result.sync_result.status is status
    assert not result.reconciliation_attempted
    assert result.reconciliation_result is None
    assert store.calls == []


def test_has_more_is_preserved_without_implicit_second_batch() -> None:
    sync_runner = FakeSyncRunner(
        (
            _sync_result(
                status=StoredSyncStatus.SUCCEEDED,
                stop_reason=ManualSyncStopReason.COMPLETED,
            ),
        )
    )
    store = FakeReconciliationStore((_reconciliation_result(has_more=True),))

    result = _run(ManualBankingSyncReconciliationService(sync_runner, store))

    assert result.reconciliation_result is not None
    assert result.reconciliation_result.has_more
    assert store.calls == [500]


def test_custom_reconciliation_limit_is_forwarded_once() -> None:
    sync_runner = FakeSyncRunner(
        (
            _sync_result(
                status=StoredSyncStatus.PARTIAL,
                stop_reason=ManualSyncStopReason.RECORD_LIMIT,
            ),
        )
    )
    store = FakeReconciliationStore((_reconciliation_result(),))

    _run(
        ManualBankingSyncReconciliationService(
            sync_runner,
            store,
            reconciliation_limit=37,
        )
    )

    assert store.calls == [37]


@pytest.mark.parametrize("value", (0, -1, 1001))
def test_reconciliation_limit_rejects_values_outside_supported_range(value: int) -> None:
    sync_runner = FakeSyncRunner(())
    store = FakeReconciliationStore(())

    with pytest.raises(ValueError):
        ManualBankingSyncReconciliationService(
            sync_runner,
            store,
            reconciliation_limit=value,
        )


@pytest.mark.parametrize("value", (True, False, "500", 500.0))
def test_reconciliation_limit_rejects_non_integer_values(value: object) -> None:
    sync_runner = FakeSyncRunner(())
    store = FakeReconciliationStore(())

    with pytest.raises(TypeError):
        ManualBankingSyncReconciliationService(
            sync_runner,
            store,
            reconciliation_limit=value,  # type: ignore[arg-type]
        )


def test_reconciliation_failure_is_sanitized_and_terminal_sync_can_be_replayed() -> None:
    completed = _sync_result(
        status=StoredSyncStatus.SUCCEEDED,
        stop_reason=ManualSyncStopReason.COMPLETED,
    )
    replayed = _sync_result(
        status=StoredSyncStatus.SUCCEEDED,
        stop_reason=ManualSyncStopReason.REPLAYED,
    )
    sync_runner = FakeSyncRunner((completed, replayed))
    store = FakeReconciliationStore(
        (
            TransactionReconciliationError(
                "sensitive-provider-id amount=999.99 description=private"
            ),
            _reconciliation_result(),
        )
    )
    service = ManualBankingSyncReconciliationService(sync_runner, store)

    with pytest.raises(ManualSyncReconciliationExecutionError) as captured:
        _run(service)

    rendered_error = str(captured.value)
    assert rendered_error == (
        "manual banking synchronization post-processing could not be completed"
    )
    assert "sensitive-provider-id" not in rendered_error
    assert "999.99" not in rendered_error
    assert "private" not in rendered_error
    assert sync_runner.calls == 1
    assert store.calls == [500]

    recovered = _run(service)

    assert recovered.sync_result.stop_reason is ManualSyncStopReason.REPLAYED
    assert recovered.reconciliation_attempted
    assert sync_runner.calls == 2
    assert store.calls == [500, 500]


def test_composed_result_repr_redacts_sync_run_identity() -> None:
    sync_runner = FakeSyncRunner(
        (
            _sync_result(
                status=StoredSyncStatus.SUCCEEDED,
                stop_reason=ManualSyncStopReason.COMPLETED,
            ),
        )
    )
    store = FakeReconciliationStore((_reconciliation_result(has_more=True),))

    result = _run(ManualBankingSyncReconciliationService(sync_runner, store))
    rendered = repr(result)

    assert str(RUN_ID) not in rendered
    assert "sensitive-provider-id" not in rendered
    assert "identity_digest" not in rendered
    assert "cursor" not in rendered
    assert "amount" not in rendered
    assert "description" not in rendered
    assert "succeeded" in rendered
    assert "has_more=True" in rendered
