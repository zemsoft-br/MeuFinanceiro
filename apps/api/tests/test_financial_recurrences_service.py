from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialOccurrenceStatus,
    FinancialRecurrenceDraft,
    FinancialRecurrenceEditOutcome,
    FinancialRecurrenceFrequency,
    FinancialRecurrenceGenerationResult,
    FinancialRecurrenceOccurrenceRecord,
    FinancialRecurrenceRecord,
    FinancialRecurrenceReplacement,
    FinancialRecurrenceStatus,
    FinancialRecurrenceWindow,
    FinancialResultEffect,
    Money,
    new_financial_resource_id,
)

from app.services.financial_recurrences import (
    FinancialRecurrenceService,
    RecurrenceRequestError,
)

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 6)
_OWNER = uuid4()


def _rule(owner: UUID = _OWNER) -> FinancialRecurrenceRecord:
    return FinancialRecurrenceRecord(
        id=new_financial_resource_id(),
        residence_id=uuid4(),
        account_id=new_financial_resource_id(),
        owner_operator_id=owner,
        description="Internet",
        result_effect=FinancialResultEffect.EXPENSE,
        expected=Money(Decimal("120"), "BRL"),
        frequency=FinancialRecurrenceFrequency.MONTHLY,
        start_date=date(2026, 1, 10),
        day_of_month=10,
        end_date=None,
        status=FinancialRecurrenceStatus.ACTIVE,
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _occurrence(rule: FinancialRecurrenceRecord) -> FinancialRecurrenceOccurrenceRecord:
    return FinancialRecurrenceOccurrenceRecord(
        id=new_financial_resource_id(),
        residence_id=rule.residence_id,
        recurrence_id=rule.id,
        account_id=rule.account_id,
        owner_operator_id=rule.owner_operator_id,
        period_start=date(2026, 10, 1),
        scheduled_date=date(2026, 10, 10),
        rule_version=1,
        result_effect=rule.result_effect,
        expected=rule.expected,
        description=rule.description,
        status=FinancialOccurrenceStatus.PENDING,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _Store:
    """Records calls; returns canned records. No financial rule lives here."""

    def __init__(self) -> None:
        self.rule = _rule()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_recurrence(self, **kwargs: Any) -> FinancialRecurrenceRecord:
        self.calls.append(("create", kwargs))
        return self.rule

    def get_recurrence(self, **kwargs: Any) -> FinancialRecurrenceRecord:
        self.calls.append(("get", kwargs))
        return self.rule

    def list_recurrences(self, **kwargs: Any) -> tuple[FinancialRecurrenceRecord, ...]:
        self.calls.append(("list", kwargs))
        return (self.rule,)

    def replace_recurrence(self, **kwargs: Any) -> FinancialRecurrenceEditOutcome:
        self.calls.append(("replace", kwargs))
        return FinancialRecurrenceEditOutcome(self.rule, 2)

    def pause_recurrence(self, **kwargs: Any) -> FinancialRecurrenceRecord:
        self.calls.append(("pause", kwargs))
        return self.rule

    def resume_recurrence(self, **kwargs: Any) -> FinancialRecurrenceRecord:
        self.calls.append(("resume", kwargs))
        return self.rule

    def generate_occurrences(
        self, **kwargs: Any
    ) -> FinancialRecurrenceGenerationResult:
        self.calls.append(("generate", kwargs))
        return FinancialRecurrenceGenerationResult(1, (_occurrence(self.rule),))

    def list_occurrences(
        self, **kwargs: Any
    ) -> tuple[FinancialRecurrenceOccurrenceRecord, ...]:
        self.calls.append(("list_occurrences", kwargs))
        return (_occurrence(self.rule),)

    def skip_occurrence(self, **kwargs: Any) -> FinancialRecurrenceOccurrenceRecord:
        self.calls.append(("skip", kwargs))
        return _occurrence(self.rule)


def _service(store: _Store | None = None, today: date = _TODAY):
    store = store or _Store()
    return store, FinancialRecurrenceService(store, clock=lambda: today)


_SCOPE: dict[str, UUID] = {
    "installation_id": uuid4(),
    "residence_id": uuid4(),
    "operator_id": _OWNER,
}


def test_the_store_and_the_clock_are_validated() -> None:
    with pytest.raises(TypeError):
        FinancialRecurrenceService(object(), clock=lambda: _TODAY)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        FinancialRecurrenceService(_Store(), clock="today")  # type: ignore[arg-type]


def test_the_clock_must_return_a_plain_date() -> None:
    store = _Store()
    service = FinancialRecurrenceService(
        store,
        clock=lambda: datetime(2026, 10, 6, tzinfo=UTC),  # type: ignore[arg-type,return-value]
    )
    with pytest.raises(TypeError):
        service.replace_recurrence(
            **_SCOPE,
            recurrence_id=store.rule.id,
            replacement=FinancialRecurrenceReplacement(
                expected_version=1,
                description="x",
                expected_amount=Decimal("1"),
                day_of_month=1,
                end_date=None,
            ),
        )
    assert store.calls == []


def test_edit_passes_the_injected_today_and_surfaces_the_superseded_count() -> None:
    store, service = _service(today=date(2027, 2, 3))
    replacement = FinancialRecurrenceReplacement(
        expected_version=1,
        description="Internet",
        expected_amount=Decimal("130"),
        day_of_month=10,
        end_date=None,
    )
    result = service.replace_recurrence(
        **_SCOPE, recurrence_id=store.rule.id, replacement=replacement
    )
    assert result.superseded_count == 2 and result.view.can_edit is True
    ((_, kwargs),) = store.calls
    assert kwargs["today"] == date(2027, 2, 3)
    assert kwargs["replacement"] is replacement


def test_can_edit_is_server_decided() -> None:
    store, service = _service()
    owner_view = service.get_recurrence(**_SCOPE, recurrence_id=store.rule.id)
    other_view = service.get_recurrence(
        **{**_SCOPE, "operator_id": uuid4()}, recurrence_id=store.rule.id
    )
    assert owner_view.can_edit is True and other_view.can_edit is False
    listed = service.list_recurrences(**{**_SCOPE, "operator_id": uuid4()})
    assert [view.can_edit for view in listed] == [False]


def test_generation_uses_the_domain_window_and_the_injected_horizon() -> None:
    store, service = _service(today=date(2026, 10, 6))
    result = service.generate_occurrences(
        **_SCOPE,
        recurrence_id=store.rule.id,
        from_period="2026-10",
        through_period="2026-12",
    )
    assert result.created_count == 1 and len(result.items) == 1
    ((_, kwargs),) = store.calls
    window = kwargs["window"]
    assert isinstance(window, FinancialRecurrenceWindow)
    assert (window.from_period, window.through_period) == (
        date(2026, 10, 1),
        date(2026, 12, 1),
    )


@pytest.mark.parametrize(
    ("first", "last", "today"),
    [
        ("2026-10", "2027-10", _TODAY),  # 13 months
        ("2026-12", "2026-10", _TODAY),  # reversed
        ("2028-11", "2028-11", _TODAY),  # beyond today + 24 months
        ("2026-10", "2026-10", date(2024, 1, 1)),  # the clock moves the horizon
        ("2026-13", "2026-13", _TODAY),
        ("bad", "2026-10", _TODAY),
    ],
)
def test_invalid_generation_windows_never_reach_the_store(
    first: str, last: str, today: date
) -> None:
    store, service = _service(today=today)
    with pytest.raises(RecurrenceRequestError):
        service.generate_occurrences(
            **_SCOPE,
            recurrence_id=store.rule.id,
            from_period=first,
            through_period=last,
        )
    assert store.calls == []


def test_the_horizon_follows_the_injected_clock() -> None:
    store, service = _service(today=date(2028, 6, 20))
    service.generate_occurrences(
        **_SCOPE,
        recurrence_id=store.rule.id,
        from_period="2030-06",
        through_period="2030-06",
    )
    assert [name for name, _ in store.calls] == ["generate"]


def test_invalid_read_windows_never_reach_the_store() -> None:
    store, service = _service()
    for first, last in (("2026-01", "2027-01"), ("2026-12", "2026-10"), ("x", "y")):
        with pytest.raises(RecurrenceRequestError):
            service.list_occurrences(**_SCOPE, from_period=first, through_period=last)
    assert store.calls == []
    items = service.list_occurrences(
        **_SCOPE, from_period="2026-01", through_period="2026-12"
    )
    assert len(items) == 1 and items[0].can_edit is True


def test_lifecycle_commands_delegate_without_reinterpretation() -> None:
    store, service = _service()
    service.pause_recurrence(**_SCOPE, recurrence_id=store.rule.id)
    service.resume_recurrence(**_SCOPE, recurrence_id=store.rule.id)
    skipped = service.skip_occurrence(**_SCOPE, occurrence_id=uuid4())
    assert skipped.can_edit is True
    assert [name for name, _ in store.calls] == ["pause", "resume", "skip"]


def test_create_delegates_the_draft_and_key_untouched() -> None:
    store, service = _service()
    draft = FinancialRecurrenceDraft(
        account_id=store.rule.account_id,
        description="Internet",
        result_effect=FinancialResultEffect.EXPENSE,
        expected=Money(Decimal("120"), "BRL"),
        start_date=date(2026, 1, 10),
        day_of_month=10,
    )
    key = uuid4()
    service.create_recurrence(**_SCOPE, idempotency_key=key, draft=draft)
    ((_, kwargs),) = store.calls
    assert kwargs["draft"] is draft and kwargs["idempotency_key"] == key
