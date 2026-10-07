"""Application orchestration of assisted recurrence suggestions (ADR-0028).

A suggestion is derived by the store from realized, visible Movements and is never
stored; this service neither detects nor decides anything by itself. The only writes
it can trigger are an explicit dismissal and an explicit acceptance, and the only
clock is the injected ``clock`` (a plain ``date``) that bounds the 12-month window.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_finance import (
    FinancialRecurrenceRecord,
    FinancialRecurrenceSuggestion,
    FinancialRecurrenceSuggestionAcceptance,
    FinancialRecurrenceSuggestionDecisionRecord,
    can_edit_recurrence,
    recurrence_suggestion_window,
)


@runtime_checkable
class RecurrenceSuggestionStoreBoundary(Protocol):
    def list_suggestions(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        today: date,
    ) -> tuple[FinancialRecurrenceSuggestion, ...]: ...

    def dismiss(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        fingerprint: str,
        today: date,
    ) -> tuple[FinancialRecurrenceSuggestionDecisionRecord, bool]: ...

    def accept(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        fingerprint: str,
        idempotency_key: UUID,
        acceptance: FinancialRecurrenceSuggestionAcceptance,
        today: date,
    ) -> tuple[
        FinancialRecurrenceRecord,
        FinancialRecurrenceSuggestionDecisionRecord,
        bool,
    ]: ...


@dataclass(frozen=True, slots=True, repr=False)
class SuggestionView:
    """A suggestion plus what the current operator may do with it (server-decided)."""

    suggestion: FinancialRecurrenceSuggestion
    can_accept: bool

    def __repr__(self) -> str:
        return f"SuggestionView(can_accept={self.can_accept})"


@dataclass(frozen=True, slots=True, repr=False)
class SuggestionListView:
    window_from: date
    window_through: date
    items: tuple[SuggestionView, ...]

    def __repr__(self) -> str:
        return f"SuggestionListView(items={len(self.items)})"


@dataclass(frozen=True, slots=True, repr=False)
class SuggestionDecisionView:
    decision: FinancialRecurrenceSuggestionDecisionRecord
    created: bool

    def __repr__(self) -> str:
        return f"SuggestionDecisionView(created={self.created})"


@dataclass(frozen=True, slots=True, repr=False)
class SuggestionAcceptView:
    recurrence: FinancialRecurrenceRecord
    can_edit: bool
    decision: FinancialRecurrenceSuggestionDecisionRecord
    created: bool

    def __repr__(self) -> str:
        return f"SuggestionAcceptView(created={self.created})"


class FinancialRecurrenceSuggestionService:
    """List, dismiss and accept assisted recurrence suggestions."""

    def __init__(
        self,
        store: RecurrenceSuggestionStoreBoundary,
        *,
        clock: Callable[[], date],
    ) -> None:
        if not isinstance(store, RecurrenceSuggestionStoreBoundary):
            raise TypeError("store must satisfy RecurrenceSuggestionStoreBoundary")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._store = store
        self._clock = clock

    def _today(self) -> date:
        today = self._clock()
        if isinstance(today, datetime) or not isinstance(today, date):
            raise TypeError("clock must return a plain date")
        return today

    def list_suggestions(
        self, *, installation_id: UUID, residence_id: UUID, operator_id: UUID
    ) -> SuggestionListView:
        today = self._today()
        suggestions = self._store.list_suggestions(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            today=today,
        )
        window_from, window_through = recurrence_suggestion_window(today)
        return SuggestionListView(
            window_from=window_from,
            window_through=window_through,
            items=tuple(
                SuggestionView(item, item.can_accept(operator_id))
                for item in suggestions
            ),
        )

    def dismiss(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        fingerprint: str,
    ) -> SuggestionDecisionView:
        decision, created = self._store.dismiss(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            fingerprint=fingerprint,
            today=self._today(),
        )
        return SuggestionDecisionView(decision, created)

    def accept(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        fingerprint: str,
        idempotency_key: UUID,
        acceptance: FinancialRecurrenceSuggestionAcceptance,
    ) -> SuggestionAcceptView:
        """The one explicit act that creates a rule from a suggestion (no Movement)."""
        recurrence, decision, created = self._store.accept(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            fingerprint=fingerprint,
            idempotency_key=idempotency_key,
            acceptance=acceptance,
            today=self._today(),
        )
        return SuggestionAcceptView(
            recurrence=recurrence,
            can_edit=can_edit_recurrence(
                recurrence=recurrence, operator_id=operator_id
            ),
            decision=decision,
            created=created,
        )


__all__ = [
    "FinancialRecurrenceSuggestionService",
    "RecurrenceSuggestionStoreBoundary",
    "SuggestionAcceptView",
    "SuggestionDecisionView",
    "SuggestionListView",
    "SuggestionView",
]
