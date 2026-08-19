from datetime import UTC, datetime, timedelta, timezone

import pytest
from meufinanceiro_persistence import StoredConnectionStatus

from meufinanceiro_banking_sync import (
    ConsentLifecycleEvaluator,
    ConsentLifecyclePolicy,
    ConsentLifecycleState,
)

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
POLICY = ConsentLifecyclePolicy(warning_window=timedelta(days=30))


def evaluator(*, now: datetime = NOW) -> ConsentLifecycleEvaluator:
    return ConsentLifecycleEvaluator(policy=POLICY, clock=lambda: now)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (StoredConnectionStatus.AVAILABLE, ConsentLifecycleState.NON_EXPIRING),
        (StoredConnectionStatus.PENDING_USER_ACTION, ConsentLifecycleState.UNKNOWN),
        (
            StoredConnectionStatus.REAUTHENTICATION_REQUIRED,
            ConsentLifecycleState.UNKNOWN,
        ),
        (StoredConnectionStatus.FAILED, ConsentLifecycleState.UNKNOWN),
    ],
)
def test_missing_expiration_uses_only_sufficient_local_evidence(
    status: StoredConnectionStatus,
    expected: ConsentLifecycleState,
) -> None:
    result = evaluator().classify(
        connection_status=status,
        consent_expires_at=None,
    )

    assert result.state is expected
    assert result.renewal_required is False
    assert result.connection_terminal is False


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
def test_temporal_boundaries_are_explicit(
    offset: timedelta,
    expected: ConsentLifecycleState,
    renewal_required: bool,
) -> None:
    result = evaluator().classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW + offset,
    )

    assert result.state is expected
    assert result.renewal_required is renewal_required


def test_timezone_offset_is_normalized_to_utc() -> None:
    sao_paulo = timezone(timedelta(hours=-3))
    expires_at = (NOW + timedelta(days=31)).astimezone(sao_paulo)

    result = evaluator().classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=expires_at,
    )

    assert result.state is ConsentLifecycleState.VALID


def test_naive_expiration_is_rejected_fail_closed() -> None:
    with pytest.raises(ValueError, match="consent_expires_at must be timezone-aware"):
        evaluator().classify(
            connection_status=StoredConnectionStatus.AVAILABLE,
            consent_expires_at=datetime(2026, 8, 19, 12, 0),
        )


def test_naive_clock_is_rejected_fail_closed() -> None:
    with pytest.raises(ValueError, match="clock result must be timezone-aware"):
        evaluator(now=datetime(2026, 8, 18, 12, 0)).classify(
            connection_status=StoredConnectionStatus.AVAILABLE,
            consent_expires_at=None,
        )


@pytest.mark.parametrize(
    ("expires_at", "expected"),
    [
        (None, ConsentLifecycleState.NON_EXPIRING),
        (NOW - timedelta(days=1), ConsentLifecycleState.EXPIRED),
    ],
)
def test_disconnected_is_terminal_and_never_requests_renewal(
    expires_at: datetime | None,
    expected: ConsentLifecycleState,
) -> None:
    result = evaluator().classify(
        connection_status=StoredConnectionStatus.DISCONNECTED,
        consent_expires_at=expires_at,
    )

    assert result.state is expected
    assert result.renewal_required is False
    assert result.connection_terminal is True


def test_clock_is_injected_and_read_once() -> None:
    calls = 0

    def clock() -> datetime:
        nonlocal calls
        calls += 1
        return NOW

    subject = ConsentLifecycleEvaluator(policy=POLICY, clock=clock)
    subject.classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW + timedelta(days=31),
    )

    assert calls == 1


def test_warning_window_policy_accepts_zero_and_rejects_negative() -> None:
    zero_policy = ConsentLifecyclePolicy(warning_window=timedelta(0))
    subject = ConsentLifecycleEvaluator(policy=zero_policy, clock=lambda: NOW)

    result = subject.classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW + timedelta(microseconds=1),
    )
    assert result.state is ConsentLifecycleState.VALID

    with pytest.raises(ValueError, match="warning_window must not be negative"):
        ConsentLifecyclePolicy(warning_window=timedelta(seconds=-1))


def test_result_repr_contains_no_identifier_material() -> None:
    result = evaluator().classify(
        connection_status=StoredConnectionStatus.AVAILABLE,
        consent_expires_at=NOW + timedelta(days=31),
    )

    assert repr(result) == (
        "ConsentLifecycleResult("
        "state='VALID', renewal_required=False, connection_terminal=False)"
    )
