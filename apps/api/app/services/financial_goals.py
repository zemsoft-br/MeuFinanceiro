"""Application orchestration of financial goals (virtual destination of balance).

Goals are planning and an allocation is a virtual, append-only event. This service
never touches the ledger: the plan and the events come from the goal store (which
reads the canonical balance under a per-account lock when it must), and every
derived number (remaining, progress, backing) is a pure domain function. The API and
Flutter hold no financial rule of their own (ADR-0029).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_finance import (
    FinancialGoalAccountInput,
    FinancialGoalAllocationDraft,
    FinancialGoalDraft,
    FinancialGoalEventRecord,
    FinancialGoalProgressStatus,
    FinancialGoalRecord,
    FinancialGoalReplacement,
    FinancialGoalSummary,
    Money,
    can_edit_goal,
    goal_progress_percent,
    goal_progress_status,
    summarize_goal,
    validate_goal_target_date,
)


class GoalRequestError(ValueError):
    """The request cannot be served: malformed intent or an out-of-range date."""


@runtime_checkable
class GoalStoreBoundary(Protocol):
    def create_goal(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialGoalDraft,
        new_goal_guard: Callable[[FinancialGoalDraft], None] | None = None,
    ) -> FinancialGoalRecord: ...

    def get_goal(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
    ) -> FinancialGoalRecord: ...

    def list_goals(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[tuple[FinancialGoalRecord, Money], ...]: ...

    def replace_goal(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
        replacement: FinancialGoalReplacement,
    ) -> FinancialGoalRecord: ...

    def allocate(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
        idempotency_key: UUID,
        draft: FinancialGoalAllocationDraft,
    ) -> FinancialGoalEventRecord: ...

    def read_goal_facts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
    ) -> tuple[
        FinancialGoalRecord,
        tuple[FinancialGoalEventRecord, ...],
        tuple[FinancialGoalAccountInput, ...],
    ]: ...


@dataclass(frozen=True, slots=True, repr=False)
class GoalView:
    """A goal plus what the current operator may do with it (server-decided)."""

    goal: FinancialGoalRecord
    can_edit: bool

    def __repr__(self) -> str:
        return f"GoalView(can_edit={self.can_edit})"


@dataclass(frozen=True, slots=True, repr=False)
class GoalListItem:
    """A goal with what it holds, derived from its events by the store."""

    goal: FinancialGoalRecord
    allocated: Money
    remaining_target: Money
    progress_percent: Decimal
    progress_status: FinancialGoalProgressStatus
    can_edit: bool

    def __repr__(self) -> str:
        return f"GoalListItem(progress_status={self.progress_status.value!r})"


@dataclass(frozen=True, slots=True, repr=False)
class GoalSummaryView:
    summary: FinancialGoalSummary
    can_edit: bool

    def __repr__(self) -> str:
        return f"GoalSummaryView(can_edit={self.can_edit})"


def _utc_today() -> date:
    return datetime.now(UTC).date()


class FinancialGoalService:
    """List, create, read, CAS-edit, allocate to and summarize financial goals."""

    def __init__(
        self,
        store: GoalStoreBoundary,
        *,
        clock: Callable[[], date] = _utc_today,
    ) -> None:
        if not isinstance(store, GoalStoreBoundary):
            raise TypeError("store must satisfy GoalStoreBoundary")
        self._store = store
        self._clock = clock

    def list_goals(
        self, *, installation_id: UUID, residence_id: UUID, operator_id: UUID
    ) -> tuple[GoalListItem, ...]:
        rows = self._store.list_goals(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
        )
        items = []
        for goal, allocated in rows:
            target = goal.target.amount
            held = allocated.amount
            items.append(
                GoalListItem(
                    goal=goal,
                    allocated=allocated,
                    remaining_target=Money(
                        max(target - held, Decimal(0)), goal.currency
                    ),
                    progress_percent=goal_progress_percent(target, held),
                    progress_status=goal_progress_status(target, held),
                    can_edit=can_edit_goal(goal=goal, operator_id=operator_id),
                )
            )
        return tuple(items)

    def create_goal(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialGoalDraft,
    ) -> GoalView:
        # The window applies to a goal that is really new, never to a replay: the
        # store decides which it is (atomically, by the idempotency key) and calls the
        # guard only for a fresh insert, so an aged-out date cannot break a replay.
        record = self._store.create_goal(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
            new_goal_guard=lambda fresh: self._require_valid_date(fresh.target_date),
        )
        return _view(record, operator_id)

    def get_goal(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
    ) -> GoalView:
        record = self._store.get_goal(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            goal_id=goal_id,
        )
        return _view(record, operator_id)

    def replace_goal(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
        replacement: FinancialGoalReplacement,
    ) -> GoalView:
        # Keeping the stored date never revalidates it: an old goal stays editable.
        current = self._store.get_goal(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            goal_id=goal_id,
        )
        if replacement.target_date != current.target_date:
            self._require_valid_date(replacement.target_date)
        record = self._store.replace_goal(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            goal_id=goal_id,
            replacement=replacement,
        )
        return _view(record, operator_id)

    def allocate(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
        idempotency_key: UUID,
        draft: FinancialGoalAllocationDraft,
    ) -> FinancialGoalEventRecord:
        return self._store.allocate(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            goal_id=goal_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )

    def summary(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
    ) -> GoalSummaryView:
        """Target, allocated, remaining, progress and backing from one snapshot."""
        goal, events, accounts = self._store.read_goal_facts(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            goal_id=goal_id,
        )
        return GoalSummaryView(
            summary=summarize_goal(goal, events, accounts),
            can_edit=can_edit_goal(goal=goal, operator_id=operator_id),
        )

    def _require_valid_date(self, target_date: date | None) -> None:
        try:
            validate_goal_target_date(target_date, today=self._clock())
        except (TypeError, ValueError):
            raise GoalRequestError("invalid goal target date") from None


def _view(record: FinancialGoalRecord, operator_id: UUID) -> GoalView:
    return GoalView(
        goal=record, can_edit=can_edit_goal(goal=record, operator_id=operator_id)
    )


__all__ = [
    "FinancialGoalService",
    "GoalListItem",
    "GoalRequestError",
    "GoalStoreBoundary",
    "GoalSummaryView",
    "GoalView",
]
