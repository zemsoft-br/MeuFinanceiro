"""Pure local classification of a banking consent's temporal lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TypeAlias

from meufinanceiro_persistence import StoredConnectionStatus

ConsentClock: TypeAlias = Callable[[], datetime]

# These states imply that a connection reached an established operational stage.
# DISCONNECTED alone does not: an unfinished connection can also be disconnected.
_ESTABLISHED_CONSENT_STATUSES = frozenset(
    {
        StoredConnectionStatus.SYNC_REQUESTED,
        StoredConnectionStatus.SYNCING,
        StoredConnectionStatus.AVAILABLE,
        StoredConnectionStatus.PARTIAL,
        StoredConnectionStatus.TEMPORARILY_UNAVAILABLE,
        StoredConnectionStatus.RATE_LIMITED,
    }
)


class ConsentLifecycleState(StrEnum):
    UNKNOWN = "UNKNOWN"
    NON_EXPIRING = "NON_EXPIRING"
    VALID = "VALID"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class ConsentLifecyclePolicy:
    """Caller-provided warning window; no global renewal default is assumed."""

    warning_window: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.warning_window, timedelta):
            raise TypeError("warning_window must be timedelta")
        if self.warning_window < timedelta(0):
            raise ValueError("warning_window must not be negative")


@dataclass(frozen=True, slots=True, repr=False)
class ConsentLifecycleResult:
    """Temporal state and operational signals, without identifiers or provider data."""

    state: ConsentLifecycleState
    renewal_required: bool
    connection_terminal: bool

    def __post_init__(self) -> None:
        if not isinstance(self.state, ConsentLifecycleState):
            raise TypeError("state must be ConsentLifecycleState")
        if not isinstance(self.renewal_required, bool):
            raise TypeError("renewal_required must be bool")
        if not isinstance(self.connection_terminal, bool):
            raise TypeError("connection_terminal must be bool")
        expected_renewal = not self.connection_terminal and self.state in {
            ConsentLifecycleState.EXPIRING,
            ConsentLifecycleState.EXPIRED,
        }
        if self.renewal_required != expected_renewal:
            raise ValueError(
                "renewal_required conflicts with lifecycle and terminal state"
            )

    def __repr__(self) -> str:
        return (
            "ConsentLifecycleResult("
            f"state={self.state.value!r}, "
            f"renewal_required={self.renewal_required!r}, "
            f"connection_terminal={self.connection_terminal!r})"
        )


class ConsentLifecycleEvaluator:
    """Evaluate only status and expiry already obtained by a separate caller."""

    def __init__(
        self,
        *,
        policy: ConsentLifecyclePolicy,
        clock: ConsentClock,
    ) -> None:
        if not isinstance(policy, ConsentLifecyclePolicy):
            raise TypeError("policy must be ConsentLifecyclePolicy")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._policy = policy
        self._clock = clock

    def classify(
        self,
        *,
        connection_status: StoredConnectionStatus,
        consent_expires_at: datetime | None,
    ) -> ConsentLifecycleResult:
        if not isinstance(connection_status, StoredConnectionStatus):
            raise TypeError("connection_status must be StoredConnectionStatus")

        now = _as_utc(self._clock(), "clock result")
        expires_at = (
            None
            if consent_expires_at is None
            else _as_utc(consent_expires_at, "consent_expires_at")
        )
        connection_terminal = connection_status is StoredConnectionStatus.DISCONNECTED

        if expires_at is None:
            state = (
                ConsentLifecycleState.NON_EXPIRING
                if connection_status in _ESTABLISHED_CONSENT_STATUSES
                else ConsentLifecycleState.UNKNOWN
            )
        else:
            remaining = expires_at - now
            if remaining <= timedelta(0):
                state = ConsentLifecycleState.EXPIRED
            elif remaining <= self._policy.warning_window:
                state = ConsentLifecycleState.EXPIRING
            else:
                state = ConsentLifecycleState.VALID

        return ConsentLifecycleResult(
            state=state,
            renewal_required=(
                not connection_terminal
                and state
                in {ConsentLifecycleState.EXPIRING, ConsentLifecycleState.EXPIRED}
            ),
            connection_terminal=connection_terminal,
        )


def _as_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "ConsentClock",
    "ConsentLifecycleEvaluator",
    "ConsentLifecyclePolicy",
    "ConsentLifecycleResult",
    "ConsentLifecycleState",
]
