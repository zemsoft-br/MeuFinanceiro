"""Pure proofs for the monthly recurrence calendar, shapes and state machine."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from meufinanceiro_finance import (
    RECURRENCE_GENERATION_HORIZON_MONTHS,
    RECURRENCE_GENERATION_MAX_MONTHS,
    RECURRENCE_LIST_MAX,
    RECURRENCE_OCCURRENCE_LIST_MAX,
    RECURRENCE_WINDOW_MAX_MONTHS,
    FinancialManualEntryType,
    FinancialOccurrenceStatus,
    FinancialRecurrenceDraft,
    FinancialRecurrenceFrequency,
    FinancialRecurrenceOccurrenceRecord,
    FinancialRecurrenceRealizationDraft,
    FinancialRecurrenceRecord,
    FinancialRecurrenceReplacement,
    FinancialRecurrenceStatus,
    FinancialRecurrenceWindow,
    FinancialResultEffect,
    Money,
    add_months,
    can_edit_recurrence,
    can_generate_occurrences,
    can_transition_occurrence,
    generation_window,
    monthly_occurrence_date,
    new_financial_resource_id,
    occurrence_manual_entry,
    occurrences_to_supersede,
    parse_recurrence_period,
    read_window,
    recurrence_replacement_changes_rule,
    scheduled_occurrences,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
BRL = "BRL"


def _money(value: str) -> Money:
    return Money(Decimal(value), BRL)


def _draft(**overrides: object) -> FinancialRecurrenceDraft:
    values: dict[str, object] = {
        "account_id": new_financial_resource_id(),
        "description": "Internet",
        "result_effect": FinancialResultEffect.EXPENSE,
        "expected": _money("120"),
        "start_date": date(2026, 1, 10),
        "day_of_month": 10,
        "end_date": None,
    }
    values.update(overrides)
    return FinancialRecurrenceDraft(**values)  # type: ignore[arg-type]


def _record(**overrides: object) -> FinancialRecurrenceRecord:
    values: dict[str, object] = {
        "id": new_financial_resource_id(),
        "residence_id": uuid4(),
        "account_id": new_financial_resource_id(),
        "owner_operator_id": uuid4(),
        "description": "Internet",
        "result_effect": FinancialResultEffect.EXPENSE,
        "expected": _money("120"),
        "frequency": FinancialRecurrenceFrequency.MONTHLY,
        "start_date": date(2026, 1, 10),
        "day_of_month": 10,
        "end_date": None,
        "status": FinancialRecurrenceStatus.ACTIVE,
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return FinancialRecurrenceRecord(**values)  # type: ignore[arg-type]


def _occurrence(**overrides: object) -> FinancialRecurrenceOccurrenceRecord:
    values: dict[str, object] = {
        "id": new_financial_resource_id(),
        "residence_id": uuid4(),
        "recurrence_id": new_financial_resource_id(),
        "account_id": new_financial_resource_id(),
        "owner_operator_id": uuid4(),
        "period_start": date(2026, 10, 1),
        "scheduled_date": date(2026, 10, 10),
        "rule_version": 1,
        "result_effect": FinancialResultEffect.EXPENSE,
        "expected": _money("120"),
        "description": "Internet",
        "status": FinancialOccurrenceStatus.PENDING,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return FinancialRecurrenceOccurrenceRecord(**values)  # type: ignore[arg-type]


# --- calendar -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "day", "expected"),
    [
        (date(2026, 1, 1), 31, date(2026, 1, 31)),
        (date(2026, 2, 1), 31, date(2026, 2, 28)),
        (date(2026, 2, 1), 30, date(2026, 2, 28)),
        (date(2026, 2, 1), 29, date(2026, 2, 28)),
        (date(2028, 2, 1), 29, date(2028, 2, 29)),  # leap year
        (date(2028, 2, 1), 31, date(2028, 2, 29)),
        (date(2100, 2, 1), 29, date(2100, 2, 28)),  # not a leap year
        (date(2000, 2, 1), 29, date(2000, 2, 29)),  # leap (divisible by 400)
        (date(2026, 4, 1), 30, date(2026, 4, 30)),
        (date(2026, 4, 1), 31, date(2026, 4, 30)),
        (date(2026, 10, 1), 10, date(2026, 10, 10)),
        (date(2026, 12, 1), 31, date(2026, 12, 31)),
        (date(2026, 3, 1), 28, date(2026, 3, 28)),
        (date(2026, 3, 1), 1, date(2026, 3, 1)),
    ],
)
def test_the_scheduled_day_clamps_to_the_last_day_of_the_month(
    period: date, day: int, expected: date
) -> None:
    assert monthly_occurrence_date(period, day) == expected


@pytest.mark.parametrize("day", [0, -1, 32, 100])
def test_day_of_month_outside_1_to_31_is_rejected(day: int) -> None:
    with pytest.raises(ValueError):
        monthly_occurrence_date(date(2026, 10, 1), day)
    with pytest.raises(ValueError):
        _draft(day_of_month=day)


@pytest.mark.parametrize("day", [True, 10.0, "10", None])
def test_day_of_month_must_be_an_integer(day: object) -> None:
    with pytest.raises(TypeError):
        _draft(day_of_month=day)


def test_the_calendar_only_accepts_the_first_day_of_a_month_as_period() -> None:
    with pytest.raises(ValueError):
        monthly_occurrence_date(date(2026, 10, 2), 10)
    with pytest.raises(TypeError):
        monthly_occurrence_date(datetime(2026, 10, 1, tzinfo=UTC), 10)  # type: ignore[arg-type]


def test_add_months_crosses_years_both_ways() -> None:
    assert add_months(date(2026, 11, 1), 1) == date(2026, 12, 1)
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert add_months(date(2026, 10, 1), 24) == date(2028, 10, 1)


@pytest.mark.parametrize("value", ["2026-10", "2028-02", "0001-01"])
def test_period_parsing_accepts_strict_year_month(value: str) -> None:
    assert parse_recurrence_period(value).day == 1


@pytest.mark.parametrize(
    "value", ["2026-13", "2026-00", "2026-1", "26-10", "2026/10", "2026-10-01", ""]
)
def test_period_parsing_rejects_everything_else(value: str) -> None:
    with pytest.raises(ValueError):
        parse_recurrence_period(value)


def _due(
    *, start: date, day: int, end: date | None, first: date, last: date
) -> list[tuple[date, date]]:
    return [
        (item.period_start, item.scheduled_date)
        for item in scheduled_occurrences(
            start_date=start,
            day_of_month=day,
            end_date=end,
            window=FinancialRecurrenceWindow(first, last),
        )
    ]


def test_a_month_before_the_start_date_is_not_due() -> None:
    due = _due(
        start=date(2026, 10, 15),
        day=10,
        end=None,
        first=date(2026, 10, 1),
        last=date(2026, 12, 1),
    )
    # The 10th of October precedes the 15th start; the first due date is November 10.
    assert due == [
        (date(2026, 11, 1), date(2026, 11, 10)),
        (date(2026, 12, 1), date(2026, 12, 10)),
    ]


def test_the_start_date_is_inclusive() -> None:
    due = _due(
        start=date(2026, 10, 10),
        day=10,
        end=None,
        first=date(2026, 10, 1),
        last=date(2026, 10, 1),
    )
    assert due == [(date(2026, 10, 1), date(2026, 10, 10))]


def test_the_end_date_is_inclusive_and_cuts_later_months() -> None:
    due = _due(
        start=date(2026, 1, 1),
        day=10,
        end=date(2026, 11, 10),
        first=date(2026, 10, 1),
        last=date(2026, 12, 1),
    )
    assert due == [
        (date(2026, 10, 1), date(2026, 10, 10)),
        (date(2026, 11, 1), date(2026, 11, 10)),
    ]


def test_an_end_date_before_the_scheduled_day_drops_that_month() -> None:
    due = _due(
        start=date(2026, 1, 1),
        day=10,
        end=date(2026, 11, 9),
        first=date(2026, 10, 1),
        last=date(2026, 12, 1),
    )
    assert due == [(date(2026, 10, 1), date(2026, 10, 10))]


def test_a_day_31_rule_walks_the_whole_year_with_clamping() -> None:
    due = _due(
        start=date(2026, 1, 31),
        day=31,
        end=None,
        first=date(2026, 1, 1),
        last=date(2026, 12, 1),
    )
    assert [scheduled for _, scheduled in due] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
        date(2026, 6, 30),
        date(2026, 7, 31),
        date(2026, 8, 31),
        date(2026, 9, 30),
        date(2026, 10, 31),
        date(2026, 11, 30),
        date(2026, 12, 31),
    ]


def test_a_leap_february_keeps_the_29th() -> None:
    due = _due(
        start=date(2028, 1, 1),
        day=29,
        end=None,
        first=date(2028, 2, 1),
        last=date(2028, 2, 1),
    )
    assert due == [(date(2028, 2, 1), date(2028, 2, 29))]


# --- bounded windows ----------------------------------------------------------


def test_generation_window_is_bounded_in_months_and_horizon() -> None:
    today = date(2026, 10, 6)
    ok = generation_window(
        from_period=date(2026, 10, 1), through_period=date(2027, 9, 1), today=today
    )
    assert ok.months == RECURRENCE_GENERATION_MAX_MONTHS
    with pytest.raises(ValueError, match="exceed"):
        generation_window(
            from_period=date(2026, 10, 1),
            through_period=date(2027, 10, 1),
            today=today,
        )
    with pytest.raises(ValueError, match="precede"):
        generation_window(
            from_period=date(2026, 11, 1),
            through_period=date(2026, 10, 1),
            today=today,
        )
    horizon = add_months(date(2026, 10, 1), RECURRENCE_GENERATION_HORIZON_MONTHS)
    generation_window(from_period=horizon, through_period=horizon, today=today)
    with pytest.raises(ValueError, match="horizon"):
        generation_window(
            from_period=add_months(horizon, 1),
            through_period=add_months(horizon, 1),
            today=today,
        )


def test_read_window_is_bounded() -> None:
    read_window(from_period=date(2026, 1, 1), through_period=date(2026, 12, 1))
    with pytest.raises(ValueError):
        read_window(from_period=date(2026, 1, 1), through_period=date(2027, 1, 1))


# --- rule shapes --------------------------------------------------------------


def test_a_rule_requires_a_positive_expected_amount_in_a_known_effect() -> None:
    with pytest.raises(ValueError):
        _draft(expected=_money("0"))
    with pytest.raises(ValueError):
        _draft(expected=_money("-1"))
    with pytest.raises(ValueError):
        _draft(result_effect=FinancialResultEffect.NEUTRAL)
    with pytest.raises(TypeError):
        _draft(expected=Decimal("1"))


def test_a_rule_description_is_trimmed_and_control_characters_are_rejected() -> None:
    assert _draft(description="  Internet  ").description == "Internet"
    with pytest.raises(ValueError):
        _draft(description="   ")
    with pytest.raises(ValueError):
        _draft(description="a\nb")
    with pytest.raises(ValueError):
        _draft(description="x" * 257)


def test_end_date_cannot_precede_start_date() -> None:
    with pytest.raises(ValueError):
        _draft(start_date=date(2026, 5, 1), end_date=date(2026, 4, 30))
    assert _draft(start_date=date(2026, 5, 1), end_date=date(2026, 5, 1))


def test_dates_must_be_plain_dates_not_datetimes() -> None:
    with pytest.raises(TypeError):
        _draft(start_date=datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(TypeError):
        _draft(end_date=datetime(2026, 12, 1, tzinfo=UTC))


def test_canonical_material_is_stable_and_discriminating() -> None:
    account_id = new_financial_resource_id()
    first = _draft(account_id=account_id)
    assert (
        first.canonical_material() == _draft(account_id=account_id).canonical_material()
    )
    assert (
        first.canonical_material()
        != _draft(account_id=account_id, expected=_money("121")).canonical_material()
    )


def test_replacement_validates_version_amount_and_day() -> None:
    base = {
        "expected_version": 1,
        "description": "Internet",
        "expected_amount": Decimal("130"),
        "day_of_month": 12,
        "end_date": None,
    }
    assert FinancialRecurrenceReplacement(**base)  # type: ignore[arg-type]
    for bad in (
        {"expected_version": 0},
        {"expected_version": True},
        {"expected_amount": Decimal("0")},
        {"expected_amount": Decimal("NaN")},
        {"expected_amount": 130},
        {"day_of_month": 32},
    ):
        with pytest.raises((TypeError, ValueError)):
            FinancialRecurrenceReplacement(**{**base, **bad})  # type: ignore[arg-type]


def test_record_rejects_bad_state() -> None:
    with pytest.raises(ValueError):
        _record(updated_at=datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError):
        _record(created_at=datetime(2026, 1, 1))  # naive
    with pytest.raises(ValueError):
        _record(version=0)


def test_authority_and_generation_flags() -> None:
    owner = uuid4()
    rule = _record(owner_operator_id=owner)
    assert can_edit_recurrence(recurrence=rule, operator_id=owner)
    assert not can_edit_recurrence(recurrence=rule, operator_id=uuid4())
    assert can_generate_occurrences(rule)
    assert not can_generate_occurrences(
        _record(status=FinancialRecurrenceStatus.PAUSED)
    )


# --- occurrence state machine -------------------------------------------------


def test_only_pending_can_move_and_everything_else_is_terminal() -> None:
    pending = FinancialOccurrenceStatus.PENDING
    for target in (
        FinancialOccurrenceStatus.REALIZED,
        FinancialOccurrenceStatus.SKIPPED,
        FinancialOccurrenceStatus.SUPERSEDED,
    ):
        assert can_transition_occurrence(pending, target)
        for terminal in (target,):
            for onward in FinancialOccurrenceStatus:
                assert not can_transition_occurrence(terminal, onward)
    assert not can_transition_occurrence(pending, pending)


def test_a_realized_status_requires_a_realization_and_only_then() -> None:
    with pytest.raises(ValueError):
        _occurrence(status=FinancialOccurrenceStatus.REALIZED)


def test_scheduled_date_must_fall_inside_the_period() -> None:
    with pytest.raises(ValueError):
        _occurrence(scheduled_date=date(2026, 11, 10))


# --- edits, superseded --------------------------------------------------------


def _pending(day: int, month: int = 10, **overrides: object):
    return _occurrence(
        period_start=date(2026, month, 1),
        scheduled_date=date(2026, month, day),
        **overrides,
    )


def test_supersede_picks_future_incompatible_pending_only() -> None:
    today = date(2026, 10, 6)
    overdue = _pending(1, 10)  # scheduled before today: history, untouched
    october = _pending(10, 10)
    november = _pending(10, 11)
    same = _pending(10, 12, expected=_money("130"))

    stale = occurrences_to_supersede(
        pending=[overdue, october, november, same],
        today=today,
        description="Internet",
        expected_amount=Decimal("130"),
        day_of_month=10,
        end_date=None,
    )
    assert {item.id for item in stale} == {october.id, november.id}


def test_supersede_ignores_non_pending() -> None:
    skipped = _pending(10, 11, status=FinancialOccurrenceStatus.SKIPPED)
    assert (
        occurrences_to_supersede(
            pending=[skipped],
            today=date(2026, 10, 6),
            description="Other",
            expected_amount=Decimal("1"),
            day_of_month=10,
            end_date=None,
        )
        == ()
    )


def test_changing_the_day_or_the_end_date_supersedes_the_affected_months() -> None:
    today = date(2026, 10, 6)
    november = _pending(10, 11)
    december = _pending(10, 12)
    moved = occurrences_to_supersede(
        pending=[november, december],
        today=today,
        description="Internet",
        expected_amount=Decimal("120"),
        day_of_month=15,
        end_date=None,
    )
    assert len(moved) == 2
    cut = occurrences_to_supersede(
        pending=[november, december],
        today=today,
        description="Internet",
        expected_amount=Decimal("120"),
        day_of_month=10,
        end_date=date(2026, 11, 30),
    )
    assert [item.id for item in cut] == [december.id]


def test_replacement_change_detection() -> None:
    rule = _record()
    same = FinancialRecurrenceReplacement(
        expected_version=1,
        description="Internet",
        expected_amount=Decimal("120"),
        day_of_month=10,
        end_date=None,
    )
    assert not recurrence_replacement_changes_rule(recurrence=rule, replacement=same)
    other = FinancialRecurrenceReplacement(
        expected_version=1,
        description="Internet",
        expected_amount=Decimal("120.5"),
        day_of_month=10,
        end_date=None,
    )
    assert recurrence_replacement_changes_rule(recurrence=rule, replacement=other)


# --- the canonical writer intent ---------------------------------------------


def test_realization_builds_the_canonical_signed_manual_entry() -> None:
    occurrence = _occurrence()
    draft = FinancialRecurrenceRealizationDraft(
        actual=_money("127.50"),
        effective_date=date(2026, 10, 11),
        competence_date=date(2026, 10, 1),
    )
    entry = occurrence_manual_entry(occurrence=occurrence, draft=draft)
    assert entry.entry_type is FinancialManualEntryType.EXPENSE
    movement = entry.to_movement_draft()
    assert movement.amount == Money(Decimal("-127.50"), BRL)
    assert movement.result_effect is FinancialResultEffect.EXPENSE
    assert movement.description == "Internet"
    assert movement.account_id == occurrence.account_id


def test_income_realization_is_positive() -> None:
    occurrence = _occurrence(result_effect=FinancialResultEffect.INCOME)
    entry = occurrence_manual_entry(
        occurrence=occurrence,
        draft=FinancialRecurrenceRealizationDraft(
            actual=_money("10"),
            effective_date=date(2026, 10, 10),
            competence_date=date(2026, 10, 10),
        ),
    )
    assert entry.to_movement_draft().amount == _money("10")


def test_realization_rejects_zero_negative_foreign_currency_and_non_pending() -> None:
    for bad in ("0", "-1"):
        with pytest.raises(ValueError):
            FinancialRecurrenceRealizationDraft(
                actual=_money(bad),
                effective_date=date(2026, 10, 10),
                competence_date=date(2026, 10, 10),
            )
    draft = FinancialRecurrenceRealizationDraft(
        actual=Money(Decimal("1"), "USD"),
        effective_date=date(2026, 10, 10),
        competence_date=date(2026, 10, 10),
    )
    with pytest.raises(ValueError, match="currency"):
        occurrence_manual_entry(occurrence=_occurrence(), draft=draft)
    good = FinancialRecurrenceRealizationDraft(
        actual=_money("1"),
        effective_date=date(2026, 10, 10),
        competence_date=date(2026, 10, 10),
    )
    with pytest.raises(ValueError, match="PENDING"):
        occurrence_manual_entry(
            occurrence=_occurrence(status=FinancialOccurrenceStatus.SKIPPED),
            draft=good,
        )


def test_the_domain_stays_pure() -> None:
    import inspect

    import meufinanceiro_finance.recurrences as module

    source = inspect.getsource(module)
    for forbidden in ("sqlalchemy", "fastapi", "datetime.now", "date.today", "float("):
        assert forbidden not in source, forbidden


def test_the_occurrence_cap_is_exactly_the_product_of_the_other_bounds() -> None:
    # A window holds one live occurrence per rule and month, so the cap can never
    # silently cut a legitimate window short.
    assert (
        RECURRENCE_OCCURRENCE_LIST_MAX
        == RECURRENCE_LIST_MAX * RECURRENCE_WINDOW_MAX_MONTHS
    )
    assert RECURRENCE_GENERATION_MAX_MONTHS <= RECURRENCE_WINDOW_MAX_MONTHS


def test_a_pending_scheduled_exactly_today_is_still_future_for_an_edit() -> None:
    today = date(2026, 10, 10)
    on_today = _pending(10, 10)
    yesterday = _pending(9, 10)
    stale = occurrences_to_supersede(
        pending=[on_today, yesterday],
        today=today,
        description="Internet",
        expected_amount=Decimal("130"),
        day_of_month=9,
        end_date=None,
    )
    # The 10th is today: it is not overdue, so a stale one is superseded.
    assert [item.id for item in stale] == [on_today.id]
