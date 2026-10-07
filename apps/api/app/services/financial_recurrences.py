"""Application orchestration of manual monthly recurrences.

Recurrences are planning. This service never touches the ledger on its own: the
rule, the occurrences and their lifecycle come from the recurrence store, the
calendar and every bound (generation window, horizon, read window) are the pure
domain functions, and the only clock is the injected ``clock`` (a plain ``date``).
The API and Flutter hold no financial or calendar rule of their own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_finance import (
    FinancialOccurrenceStatus,
    FinancialRecurrenceDraft,
    FinancialRecurrenceEditOutcome,
    FinancialRecurrenceGenerationResult,
    FinancialRecurrenceOccurrenceRecord,
    FinancialRecurrenceRealizationDraft,
    FinancialRecurrenceRecord,
    FinancialRecurrenceReplacement,
    FinancialRecurrenceStatus,
    FinancialRecurrenceWindow,
    can_edit_recurrence,
    generation_window,
    parse_recurrence_period,
    read_window,
)


class RecurrenceRequestError(ValueError):
    """The request cannot be served: bad period, window or malformed intent."""


@runtime_checkable
class RecurrenceStoreBoundary(Protocol):
    def create_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialRecurrenceDraft,
    ) -> FinancialRecurrenceRecord: ...

    def get_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
    ) -> FinancialRecurrenceRecord: ...

    def list_recurrences(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        status: FinancialRecurrenceStatus | None = None,
    ) -> tuple[FinancialRecurrenceRecord, ...]: ...

    def replace_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
        replacement: FinancialRecurrenceReplacement,
        today: date,
    ) -> FinancialRecurrenceEditOutcome: ...

    def pause_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
    ) -> FinancialRecurrenceRecord: ...

    def resume_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
    ) -> FinancialRecurrenceRecord: ...

    def generate_occurrences(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
        window: FinancialRecurrenceWindow,
    ) -> FinancialRecurrenceGenerationResult: ...

    def list_occurrences(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        window: FinancialRecurrenceWindow,
        recurrence_id: UUID | None = None,
        status: FinancialOccurrenceStatus | None = None,
    ) -> tuple[FinancialRecurrenceOccurrenceRecord, ...]: ...

    def skip_occurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        occurrence_id: UUID,
    ) -> FinancialRecurrenceOccurrenceRecord: ...

    def realize_occurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        occurrence_id: UUID,
        idempotency_key: UUID,
        draft: FinancialRecurrenceRealizationDraft,
    ) -> FinancialRecurrenceOccurrenceRecord: ...


@dataclass(frozen=True, slots=True, repr=False)
class RecurrenceView:
    """A rule plus what the current operator may do with it (server-decided)."""

    recurrence: FinancialRecurrenceRecord
    can_edit: bool

    def __repr__(self) -> str:
        return f"RecurrenceView(can_edit={self.can_edit})"


@dataclass(frozen=True, slots=True, repr=False)
class RecurrenceEditView:
    view: RecurrenceView
    superseded_count: int

    def __repr__(self) -> str:
        return f"RecurrenceEditView(superseded_count={self.superseded_count})"


@dataclass(frozen=True, slots=True, repr=False)
class OccurrenceView:
    occurrence: FinancialRecurrenceOccurrenceRecord
    can_edit: bool

    def __repr__(self) -> str:
        return f"OccurrenceView(can_edit={self.can_edit})"


@dataclass(frozen=True, slots=True, repr=False)
class OccurrenceGenerationView:
    created_count: int
    items: tuple[OccurrenceView, ...]

    def __repr__(self) -> str:
        return f"OccurrenceGenerationView(created_count={self.created_count})"


class FinancialRecurrenceService:
    """List, create, edit and run the planning lifecycle of monthly recurrences."""

    def __init__(
        self, store: RecurrenceStoreBoundary, *, clock: Callable[[], date]
    ) -> None:
        if not isinstance(store, RecurrenceStoreBoundary):
            raise TypeError("store must satisfy RecurrenceStoreBoundary")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._store = store
        self._clock = clock

    def _today(self) -> date:
        today = self._clock()
        if isinstance(today, datetime) or not isinstance(today, date):
            raise TypeError("clock must return a plain date")
        return today

    def list_recurrences(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        status: FinancialRecurrenceStatus | None = None,
    ) -> tuple[RecurrenceView, ...]:
        records = self._store.list_recurrences(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            status=status,
        )
        return tuple(_view(record, operator_id) for record in records)

    def create_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialRecurrenceDraft,
    ) -> RecurrenceView:
        record = self._store.create_recurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )
        return _view(record, operator_id)

    def get_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
    ) -> RecurrenceView:
        record = self._store.get_recurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=recurrence_id,
        )
        return _view(record, operator_id)

    def replace_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
        replacement: FinancialRecurrenceReplacement,
    ) -> RecurrenceEditView:
        outcome = self._store.replace_recurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=recurrence_id,
            replacement=replacement,
            today=self._today(),
        )
        return RecurrenceEditView(
            view=_view(outcome.recurrence, operator_id),
            superseded_count=outcome.superseded_count,
        )

    def pause_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
    ) -> RecurrenceView:
        record = self._store.pause_recurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=recurrence_id,
        )
        return _view(record, operator_id)

    def resume_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
    ) -> RecurrenceView:
        record = self._store.resume_recurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=recurrence_id,
        )
        return _view(record, operator_id)

    def generate_occurrences(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
        from_period: str,
        through_period: str,
    ) -> OccurrenceGenerationView:
        try:
            window = generation_window(
                from_period=parse_recurrence_period(from_period),
                through_period=parse_recurrence_period(through_period),
                today=self._today(),
            )
        except (TypeError, ValueError):
            raise RecurrenceRequestError("invalid generation window") from None
        result = self._store.generate_occurrences(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=recurrence_id,
            window=window,
        )
        return OccurrenceGenerationView(
            created_count=result.created_count,
            items=tuple(
                _occurrence_view(item, operator_id) for item in result.occurrences
            ),
        )

    def list_occurrences(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        from_period: str,
        through_period: str,
        recurrence_id: UUID | None = None,
        status: FinancialOccurrenceStatus | None = None,
    ) -> tuple[OccurrenceView, ...]:
        try:
            window = read_window(
                from_period=parse_recurrence_period(from_period),
                through_period=parse_recurrence_period(through_period),
            )
        except (TypeError, ValueError):
            raise RecurrenceRequestError("invalid occurrence window") from None
        records = self._store.list_occurrences(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            window=window,
            recurrence_id=recurrence_id,
            status=status,
        )
        return tuple(_occurrence_view(record, operator_id) for record in records)

    def skip_occurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        occurrence_id: UUID,
    ) -> OccurrenceView:
        record = self._store.skip_occurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            occurrence_id=occurrence_id,
        )
        return _occurrence_view(record, operator_id)

    def realize_occurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        occurrence_id: UUID,
        idempotency_key: UUID,
        draft: FinancialRecurrenceRealizationDraft,
    ) -> OccurrenceView:
        """The one explicit act that produces a fact: exactly one canonical Movement."""
        record = self._store.realize_occurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            occurrence_id=occurrence_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )
        return _occurrence_view(record, operator_id)


def _view(record: FinancialRecurrenceRecord, operator_id: UUID) -> RecurrenceView:
    return RecurrenceView(
        recurrence=record,
        can_edit=can_edit_recurrence(recurrence=record, operator_id=operator_id),
    )


def _occurrence_view(
    record: FinancialRecurrenceOccurrenceRecord, operator_id: UUID
) -> OccurrenceView:
    return OccurrenceView(
        occurrence=record, can_edit=record.owner_operator_id == operator_id
    )


__all__ = [
    "FinancialRecurrenceService",
    "OccurrenceGenerationView",
    "OccurrenceView",
    "RecurrenceEditView",
    "RecurrenceRequestError",
    "RecurrenceStoreBoundary",
    "RecurrenceView",
]
