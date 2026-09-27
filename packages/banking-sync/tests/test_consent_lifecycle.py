from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta, timezone

import pytest
from meufinanceiro_persistence import StoredConnectionStatus

from meufinanceiro_banking_sync import (
    BankingConnectionDisconnectionService,
    ConnectionDisconnectionError,
    ConnectionDisconnectionErrorCode,
    ConnectionDisconnectionOutcome,
    ConnectionDisconnectionResult,
    ConnectionDisconnectionStore,
    ConsentLifecycleEvaluator,
    ConsentLifecyclePolicy,
    ConsentLifecycleResult,
    ConsentLifecycleState,
)

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
POLICY = ConsentLifecyclePolicy(warning_window=timedelta(days=30))


def evaluator(
    *, now: datetime = NOW, policy: ConsentLifecyclePolicy = POLICY
) -> ConsentLifecycleEvaluator:
    return ConsentLifecycleEvaluator(policy=policy, clock=lambda: now)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (StoredConnectionStatus.SYNC_REQUESTED, ConsentLifecycleState.NON_EXPIRING),
        (StoredConnectionStatus.SYNCING, ConsentLifecycleState.NON_EXPIRING),
        (StoredConnectionStatus.AVAILABLE, ConsentLifecycleState.NON_EXPIRING),
        (StoredConnectionStatus.PARTIAL, ConsentLifecycleState.NON_EXPIRING),
        (
            StoredConnectionStatus.TEMPORARILY_UNAVAILABLE,
            ConsentLifecycleState.NON_EXPIRING,
        ),
        (StoredConnectionStatus.RATE_LIMITED, ConsentLifecycleState.NON_EXPIRING),
        (StoredConnectionStatus.PENDING_USER_ACTION, ConsentLifecycleState.UNKNOWN),
        (
            StoredConnectionStatus.REAUTHENTICATION_REQUIRED,
            ConsentLifecycleState.UNKNOWN,
        ),
        (StoredConnectionStatus.FAILED, ConsentLifecycleState.UNKNOWN),
        (StoredConnectionStatus.DISCONNECTED, ConsentLifecycleState.UNKNOWN),
    ],
)
def test_missing_expiry_requires_evidence_of_established_consent(
    status: StoredConnectionStatus, expected: ConsentLifecycleState
) -> None:
    result = evaluator().classify(connection_status=status, consent_expires_at=None)

    assert result.state is expected
    assert result.renewal_required is False
    assert result.connection_terminal is (status is StoredConnectionStatus.DISCONNECTED)


@pytest.mark.parametrize(
    ("offset", "expected", "renewal_required"),
    [
        (timedelta(days=31), ConsentLifecycleState.VALID, False),
        (timedelta(days=10), ConsentLifecycleState.EXPIRING, True),
        (timedelta(days=30), ConsentLifecycleState.EXPIRING, True),
        (timedelta(0), ConsentLifecycleState.EXPIRED, True),
        (timedelta(seconds=-1), ConsentLifecycleState.EXPIRED, True),
    ],
)
def test_temporal_boundaries(
    offset: timedelta, expected: ConsentLifecycleState, renewal_required: bool
) -> None:
    result = evaluator().classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW + offset,
    )

    assert result.state is expected
    assert result.renewal_required is renewal_required
    assert result.connection_terminal is False


def test_utc_and_offset_timestamps_classify_identically() -> None:
    expiry_utc = NOW + timedelta(days=30)
    expiry_offset = expiry_utc.astimezone(timezone(timedelta(hours=-3)))
    subject = evaluator()

    utc_result = subject.classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=expiry_utc,
    )
    offset_result = subject.classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=expiry_offset,
    )

    assert utc_result == offset_result
    assert utc_result.state is ConsentLifecycleState.EXPIRING


def test_naive_expiry_fails_closed() -> None:
    with pytest.raises(ValueError, match="consent_expires_at must be timezone-aware"):
        evaluator().classify(
            connection_status=StoredConnectionStatus.AVAILABLE,
            consent_expires_at=NOW.replace(tzinfo=None),
        )


@pytest.mark.parametrize("expiry", [None, NOW + timedelta(days=1)])
def test_naive_clock_fails_closed_even_without_expiry(expiry: datetime | None) -> None:
    with pytest.raises(ValueError, match="clock result must be timezone-aware"):
        evaluator(now=NOW.replace(tzinfo=None)).classify(
            connection_status=StoredConnectionStatus.AVAILABLE,
            consent_expires_at=expiry,
        )


def test_injected_clock_is_read_once_per_classification() -> None:
    calls = 0

    def clock() -> datetime:
        nonlocal calls
        calls += 1
        return NOW

    subject = ConsentLifecycleEvaluator(policy=POLICY, clock=clock)
    first = subject.classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW + timedelta(days=31),
    )
    second = subject.classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW + timedelta(days=31),
    )

    assert first == second
    assert calls == 2


def test_zero_warning_window_has_no_positive_expiring_interval() -> None:
    subject = evaluator(policy=ConsentLifecyclePolicy(warning_window=timedelta(0)))

    future = subject.classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW + timedelta(microseconds=1),
    )
    at_now = subject.classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW,
    )

    assert (future.state, future.renewal_required) == (
        ConsentLifecycleState.VALID,
        False,
    )
    assert (at_now.state, at_now.renewal_required) == (
        ConsentLifecycleState.EXPIRED,
        True,
    )


def test_negative_warning_window_is_rejected() -> None:
    with pytest.raises(ValueError, match="warning_window must not be negative"):
        ConsentLifecyclePolicy(warning_window=timedelta(microseconds=-1))


@pytest.mark.parametrize(
    ("expiry", "expected"),
    [
        (NOW + timedelta(days=31), ConsentLifecycleState.VALID),
        (NOW + timedelta(days=1), ConsentLifecycleState.EXPIRING),
        (NOW, ConsentLifecycleState.EXPIRED),
        (NOW - timedelta(days=1), ConsentLifecycleState.EXPIRED),
    ],
)
def test_disconnected_preserves_temporal_state_without_requesting_renewal(
    expiry: datetime, expected: ConsentLifecycleState
) -> None:
    result = evaluator().classify(
        connection_status=StoredConnectionStatus.DISCONNECTED,
        consent_expires_at=expiry,
    )

    assert result.state is expected
    assert result.connection_terminal is True
    assert result.renewal_required is False


def test_result_contains_only_state_and_operational_signals() -> None:
    result = evaluator().classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW + timedelta(days=31),
    )

    assert {field.name for field in fields(ConsentLifecycleResult)} == {
        "state",
        "renewal_required",
        "connection_terminal",
    }
    assert repr(result) == (
        "ConsentLifecycleResult("
        "state='VALID', renewal_required=False, connection_terminal=False)"
    )
    assert not hasattr(result, "__dict__")


def test_result_rejects_inconsistent_renewal_signal() -> None:
    with pytest.raises(ValueError, match="renewal_required conflicts"):
        ConsentLifecycleResult(
            state=ConsentLifecycleState.EXPIRED,
            renewal_required=False,
            connection_terminal=False,
        )


def test_public_exports_keep_disconnection_contract() -> None:
    assert BankingConnectionDisconnectionService is not None
    assert ConnectionDisconnectionError is not None
    assert ConnectionDisconnectionErrorCode is not None
    assert ConnectionDisconnectionOutcome is not None
    assert ConnectionDisconnectionResult is not None
    assert ConnectionDisconnectionStore is not None


def test_no_revoked_lifecycle_state() -> None:
    assert {state.name for state in ConsentLifecycleState} == {
        "UNKNOWN",
        "NON_EXPIRING",
        "VALID",
        "EXPIRING",
        "EXPIRED",
    }
