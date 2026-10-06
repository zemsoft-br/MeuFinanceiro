from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from meufinanceiro_finance import (
    BUDGET_LINES_MAX,
    FinancialBudgetCoverageSlice,
    FinancialBudgetDateBasis,
    FinancialBudgetDraft,
    FinancialBudgetLineDraft,
    FinancialBudgetLineRecord,
    FinancialBudgetLineStatus,
    FinancialBudgetPeriodKind,
    FinancialBudgetRealization,
    FinancialBudgetRealizedRow,
    FinancialBudgetRecord,
    FinancialBudgetReplacement,
    FinancialCategoryRecord,
    FinancialCategoryStatus,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    budget_line_status,
    budget_period_end,
    budget_progress_percent,
    can_edit_budget,
    is_budget_category_compatible,
    parse_budget_period,
    summarize_budget,
)

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
_OWNER = uuid4()
_MARKET = uuid4()
_SALARY = uuid4()


def _line(
    category=None,
    effect=FinancialResultEffect.EXPENSE,
    amount="1000",
    currency="BRL",
) -> FinancialBudgetLineDraft:
    return FinancialBudgetLineDraft(
        category or uuid4(), effect, Money(Decimal(amount), currency)
    )


def _draft(**overrides) -> FinancialBudgetDraft:
    values = {
        "name": "Outubro",
        "visibility_scope": FinancialVisibilityScope.PERSONAL,
        "currency": "BRL",
        "period_start": date(2026, 10, 1),
        "date_basis": FinancialBudgetDateBasis.CASH,
        "lines": (_line(),),
    }
    values.update(overrides)
    return FinancialBudgetDraft(**values)


def _record(*lines: FinancialBudgetLineRecord, **overrides) -> FinancialBudgetRecord:
    values = {
        "id": uuid4(),
        "residence_id": uuid4(),
        "owner_operator_id": _OWNER,
        "visibility_scope": FinancialVisibilityScope.PERSONAL,
        "name": "Outubro",
        "currency": "BRL",
        "period_kind": FinancialBudgetPeriodKind.MONTHLY,
        "period_start": date(2026, 10, 1),
        "date_basis": FinancialBudgetDateBasis.CASH,
        "version": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
        "lines": lines,
    }
    values.update(overrides)
    return FinancialBudgetRecord(**values)


def _category(**overrides) -> FinancialCategoryRecord:
    values = {
        "id": uuid4(),
        "residence_id": uuid4(),
        "owner_operator_id": _OWNER,
        "visibility_scope": FinancialVisibilityScope.PERSONAL,
        "parent_id": None,
        "name": "Mercado",
        "status": FinancialCategoryStatus.ACTIVE,
        "created_at": _NOW,
        "updated_at": _NOW,
        "disabled_at": None,
    }
    values.update(overrides)
    return FinancialCategoryRecord(**values)


@pytest.mark.parametrize("day", [2, 15, 31])
def test_period_start_must_be_the_first_day(day: int) -> None:
    with pytest.raises(ValueError, match="first day"):
        _draft(period_start=date(2026, 10, day))


def test_period_start_rejects_datetimes_and_strings() -> None:
    with pytest.raises(TypeError):
        _draft(period_start=datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(TypeError):
        _draft(period_start="2026-10-01")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 1, 1), date(2026, 2, 1)),
        (date(2026, 2, 1), date(2026, 3, 1)),
        (date(2028, 2, 1), date(2028, 3, 1)),
        (date(2026, 12, 1), date(2027, 1, 1)),
    ],
)
def test_period_end_is_derived_and_exclusive(start: date, end: date) -> None:
    assert budget_period_end(start) == end
    assert _draft(period_start=start).period_end == end


def test_parse_budget_period_is_strict() -> None:
    assert parse_budget_period("2026-10") == date(2026, 10, 1)
    for bad in ("2026-13", "2026-00", "26-10", "2026-1", "2026-10-01", "abcd-ef", ""):
        with pytest.raises(ValueError):
            parse_budget_period(bad)
    with pytest.raises(TypeError):
        parse_budget_period(202610)  # type: ignore[arg-type]


def test_planned_must_be_positive_decimal_money() -> None:
    for amount in ("0", "-1", "-0.01"):
        with pytest.raises(ValueError, match="positive"):
            _line(amount=amount)
    with pytest.raises(TypeError):
        FinancialBudgetLineDraft(
            uuid4(),
            FinancialResultEffect.EXPENSE,
            10.5,  # type: ignore[arg-type]
        )
    assert _line(amount="0.00000001").planned.amount == Decimal("1E-8")


def test_line_effect_is_income_or_expense_only() -> None:
    with pytest.raises(ValueError, match="INCOME or EXPENSE"):
        _line(effect=FinancialResultEffect.NEUTRAL)


def test_currency_is_explicit_and_every_line_must_match_it() -> None:
    with pytest.raises(ValueError, match="currency"):
        _draft(lines=(_line(currency="USD"),))
    with pytest.raises(ValueError):
        _draft(currency="brl")
    with pytest.raises(ValueError):
        _draft(currency="BR")


def test_audience_is_personal_or_household_only() -> None:
    with pytest.raises(ValueError, match="PERSONAL or HOUSEHOLD"):
        _draft(visibility_scope=FinancialVisibilityScope.SHARED)


def test_lines_are_unique_per_category_and_effect() -> None:
    category = uuid4()
    both = (
        _line(category, FinancialResultEffect.EXPENSE),
        _line(category, FinancialResultEffect.INCOME),
    )
    assert len(_draft(lines=both).lines) == 2
    with pytest.raises(ValueError, match="unique"):
        _draft(lines=(_line(category), _line(category, amount="5")))


def test_line_count_bounds() -> None:
    with pytest.raises(ValueError, match="between 1 and"):
        _draft(lines=())
    full = tuple(_line() for _ in range(BUDGET_LINES_MAX))
    assert len(_draft(lines=full).lines) == BUDGET_LINES_MAX
    with pytest.raises(ValueError, match="between 1 and"):
        _draft(lines=(*full, _line()))


def test_name_is_trimmed_and_bounded() -> None:
    assert _draft(name="  Casa  ").name == "Casa"
    for bad in ("", "   ", "x" * 97):
        with pytest.raises(ValueError):
            _draft(name=bad)


def test_digest_material_ignores_line_order_but_not_substance() -> None:
    a, b = _line(_MARKET), _line(_SALARY, FinancialResultEffect.INCOME, "5000")
    first = _draft(lines=(a, b))
    second = _draft(lines=(b, a))
    assert first.canonical_material() == second.canonical_material()
    changed = _draft(lines=(a, _line(_SALARY, FinancialResultEffect.INCOME, "5001")))
    assert changed.canonical_material() != first.canonical_material()
    assert (
        _draft(date_basis=FinancialBudgetDateBasis.COMPETENCE).canonical_material()
        != _draft().canonical_material()
    )


def test_replacement_requires_a_positive_integer_version_and_lines() -> None:
    line = _line()
    assert FinancialBudgetReplacement(1, "Novo", (line,)).expected_version == 1
    for bad in (0, -1):
        with pytest.raises(ValueError):
            FinancialBudgetReplacement(bad, "Novo", (line,))
    for bad in (True, 1.0, "1"):
        with pytest.raises(TypeError):
            FinancialBudgetReplacement(bad, "Novo", (line,))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        FinancialBudgetReplacement(1, "Novo", ())
    with pytest.raises(ValueError, match="unique"):
        FinancialBudgetReplacement(
            1, "Novo", (line, _line(line.category_id, amount="2"))
        )


def test_record_validates_shape() -> None:
    line = FinancialBudgetLineRecord(
        _MARKET, FinancialResultEffect.EXPENSE, Money(Decimal("10"), "BRL")
    )
    record = _record(line)
    assert record.period_end == date(2026, 11, 1)
    with pytest.raises(ValueError):
        _record()
    with pytest.raises(ValueError, match="currency"):
        _record(
            FinancialBudgetLineRecord(
                _MARKET, FinancialResultEffect.EXPENSE, Money(Decimal("10"), "USD")
            )
        )
    with pytest.raises(ValueError):
        _record(line, version=0)
    with pytest.raises(ValueError):
        _record(line, period_start=date(2026, 10, 2))
    with pytest.raises(ValueError):
        _record(line, visibility_scope=FinancialVisibilityScope.SHARED)


def test_category_compatibility_matrix() -> None:
    personal = _category()
    household = _category(visibility_scope=FinancialVisibilityScope.HOUSEHOLD)
    foreign = _category(owner_operator_id=uuid4())
    disabled = _category(status=FinancialCategoryStatus.DISABLED, disabled_at=_NOW)

    def ok(scope, category) -> bool:
        return is_budget_category_compatible(
            budget_visibility_scope=scope,
            budget_owner_operator_id=_OWNER,
            category=category,
        )

    assert ok(FinancialVisibilityScope.PERSONAL, personal)
    assert not ok(FinancialVisibilityScope.PERSONAL, household)
    assert not ok(FinancialVisibilityScope.PERSONAL, foreign)
    assert not ok(FinancialVisibilityScope.PERSONAL, disabled)
    assert ok(FinancialVisibilityScope.HOUSEHOLD, household)
    assert not ok(FinancialVisibilityScope.HOUSEHOLD, personal)
    assert not ok(FinancialVisibilityScope.HOUSEHOLD, disabled)
    assert not ok(FinancialVisibilityScope.SHARED, household)


def test_only_the_owner_can_edit() -> None:
    line = FinancialBudgetLineRecord(
        _MARKET, FinancialResultEffect.EXPENSE, Money(Decimal("10"), "BRL")
    )
    household = _record(line, visibility_scope=FinancialVisibilityScope.HOUSEHOLD)
    assert can_edit_budget(budget=household, operator_id=_OWNER)
    assert not can_edit_budget(budget=household, operator_id=uuid4())


@pytest.mark.parametrize(
    ("planned", "realized", "status"),
    [
        ("1000", "0", FinancialBudgetLineStatus.UNDER),
        ("1000", "999.99999999", FinancialBudgetLineStatus.UNDER),
        ("1000", "1000", FinancialBudgetLineStatus.AT),
        ("1000", "1000.00000000", FinancialBudgetLineStatus.AT),
        ("1000", "1000.00000001", FinancialBudgetLineStatus.OVER),
        ("1000", "-300", FinancialBudgetLineStatus.UNDER),
    ],
)
def test_status_compares_exact_decimals(planned, realized, status) -> None:
    assert budget_line_status(Decimal(planned), Decimal(realized)) is status


def test_progress_percent_is_decimal_half_up_and_fails_closed_on_zero() -> None:
    assert budget_progress_percent(Decimal("1000"), Decimal("300")) == Decimal("30.00")
    assert budget_progress_percent(Decimal("3"), Decimal("1")) == Decimal("33.33")
    assert budget_progress_percent(Decimal("3"), Decimal("2")) == Decimal("66.67")
    assert budget_progress_percent(Decimal("1000"), Decimal("1500")) == Decimal(
        "150.00"
    )
    assert isinstance(budget_progress_percent(Decimal("7"), Decimal("1")), Decimal)
    with pytest.raises(ValueError):
        budget_progress_percent(Decimal("0"), Decimal("1"))


def test_summary_is_pure_decimal_with_remaining_and_coverage() -> None:
    market = FinancialBudgetLineRecord(
        _MARKET, FinancialResultEffect.EXPENSE, Money(Decimal("1000"), "BRL")
    )
    salary = FinancialBudgetLineRecord(
        _SALARY, FinancialResultEffect.INCOME, Money(Decimal("5000"), "BRL")
    )
    budget = _record(market, salary)
    stray = uuid4()
    realization = FinancialBudgetRealization(
        rows=(
            FinancialBudgetRealizedRow(
                _MARKET, FinancialResultEffect.EXPENSE, Decimal("300")
            ),
            FinancialBudgetRealizedRow(
                _SALARY, FinancialResultEffect.INCOME, Decimal("4500")
            ),
            # Same category but another effect, and an unplanned category: ignored.
            FinancialBudgetRealizedRow(
                _MARKET, FinancialResultEffect.INCOME, Decimal("999")
            ),
            FinancialBudgetRealizedRow(
                stray, FinancialResultEffect.EXPENSE, Decimal("1")
            ),
        ),
        unclassified_expense=FinancialBudgetCoverageSlice(1, Decimal("100")),
        unclassified_income=FinancialBudgetCoverageSlice(0, Decimal("0")),
    )

    summary = summarize_budget(budget, realization)

    by_key = {(line.category_id, line.result_effect): line for line in summary.lines}
    expense = by_key[(_MARKET, FinancialResultEffect.EXPENSE)]
    assert expense.planned == Money(Decimal("1000"), "BRL")
    assert expense.realized == Money(Decimal("300"), "BRL")
    assert expense.remaining == Money(Decimal("700"), "BRL")
    assert expense.status is FinancialBudgetLineStatus.UNDER
    assert expense.progress_percent == Decimal("30.00")
    income = by_key[(_SALARY, FinancialResultEffect.INCOME)]
    assert income.remaining == Money(Decimal("500"), "BRL")
    assert len(summary.lines) == 2
    assert summary.coverage.unclassified_expense_count == 1
    assert summary.coverage.unclassified_expense == Money(Decimal("100"), "BRL")
    assert summary.coverage.unclassified_income_count == 0


def test_summary_line_without_realized_is_zero_and_over_is_negative_remaining() -> None:
    market = FinancialBudgetLineRecord(
        _MARKET, FinancialResultEffect.EXPENSE, Money(Decimal("100"), "BRL")
    )
    budget = _record(market)
    empty = FinancialBudgetRealization(
        rows=(),
        unclassified_expense=FinancialBudgetCoverageSlice(0, Decimal("0")),
        unclassified_income=FinancialBudgetCoverageSlice(0, Decimal("0")),
    )
    line = summarize_budget(budget, empty).lines[0]
    assert line.realized == Money(Decimal("0"), "BRL")
    assert line.remaining == Money(Decimal("100"), "BRL")
    assert line.status is FinancialBudgetLineStatus.UNDER

    over = FinancialBudgetRealization(
        rows=(
            FinancialBudgetRealizedRow(
                _MARKET, FinancialResultEffect.EXPENSE, Decimal("130.5")
            ),
        ),
        unclassified_expense=empty.unclassified_expense,
        unclassified_income=empty.unclassified_income,
    )
    line = summarize_budget(budget, over).lines[0]
    assert line.remaining == Money(Decimal("-30.5"), "BRL")
    assert line.status is FinancialBudgetLineStatus.OVER
    assert line.progress_percent == Decimal("130.50")


def test_reprs_do_not_leak_amounts_or_names() -> None:
    draft = _draft(name="Segredo", lines=(_line(amount="123456"),))
    text = repr(draft) + repr(draft.lines[0]) + repr(replace(draft, name="Outro"))
    assert "123456" not in text and "Segredo" not in text
