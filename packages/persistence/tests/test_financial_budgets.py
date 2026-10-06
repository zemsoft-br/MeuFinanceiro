"""PostgreSQL-backed proofs for monthly budget planning persistence.

Everything runs through the non-superuser runtime role with forced RLS. A budget
is planning only: these proofs also show that no ledger row is ever written.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialBudgetDateBasis,
    FinancialBudgetDraft,
    FinancialBudgetLineDraft,
    FinancialBudgetRecord,
    FinancialBudgetReplacement,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_budget_schema import (
    financial_budget_lines,
    financial_budgets,
)
from meufinanceiro_persistence.financial_budget_store import (
    FinancialBudgetAccessError,
    FinancialBudgetCategoryNotFoundError,
    FinancialBudgetConflictError,
    FinancialBudgetInvalidShapeError,
    FinancialBudgetNotEditableError,
    FinancialBudgetNotFoundError,
    FinancialBudgetStore,
    FinancialBudgetVersionConflictError,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements

if TYPE_CHECKING:
    from conftest import BudgetWorld

_OCT = date(2026, 10, 1)
_EXPENSE = FinancialResultEffect.EXPENSE
_INCOME = FinancialResultEffect.INCOME
_PERSONAL = FinancialVisibilityScope.PERSONAL
_HOUSEHOLD = FinancialVisibilityScope.HOUSEHOLD


def _line(category: UUID, effect=_EXPENSE, amount="1000") -> FinancialBudgetLineDraft:
    return FinancialBudgetLineDraft(category, effect, Money(Decimal(amount), "BRL"))


def _draft(
    lines: tuple[FinancialBudgetLineDraft, ...],
    *,
    scope=_HOUSEHOLD,
    basis=FinancialBudgetDateBasis.CASH,
    period=_OCT,
    currency="BRL",
    name="Outubro",
) -> FinancialBudgetDraft:
    return FinancialBudgetDraft(
        name=name,
        visibility_scope=scope,
        currency=currency,
        period_start=period,
        date_basis=basis,
        lines=lines,
    )


def _create(
    world: BudgetWorld,
    draft: FinancialBudgetDraft,
    operator_id: UUID | None = None,
    key: UUID | None = None,
) -> FinancialBudgetRecord:
    return FinancialBudgetStore(world.runtime).create_budget(
        **world.scope(operator_id),
        idempotency_key=key or new_financial_idempotency_key(),
        draft=draft,
    )


def _store(world: BudgetWorld) -> FinancialBudgetStore:
    return FinancialBudgetStore(world.runtime)


def _count(world: BudgetWorld, table) -> int:
    with world.engine.begin() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    assert isinstance(value, int)
    return value


# --- create / read ------------------------------------------------------------


def test_create_household_budget_persists_planning_only(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    salary = budget_world.category("Salário")
    ledger_before = _count(budget_world, financial_movements)

    record = _create(
        budget_world,
        _draft((_line(market), _line(salary, _INCOME, "5000"))),
    )

    assert record.version == 1
    assert record.visibility_scope is _HOUSEHOLD
    assert record.owner_operator_id == budget_world.owner_id
    assert record.period_start == _OCT and record.period_end == date(2026, 11, 1)
    assert record.currency == "BRL"
    assert {
        (line.category_id, line.result_effect): line.planned.amount
        for line in record.lines
    } == {
        (market, _EXPENSE): Decimal("1000"),
        (salary, _INCOME): Decimal("5000"),
    }
    assert _count(budget_world, financial_movements) == ledger_before == 0
    reread = _store(budget_world).get_budget(
        **budget_world.scope(), budget_id=record.id
    )
    assert reread == record


def test_money_is_exact_decimal_numeric_24_8(budget_world: BudgetWorld) -> None:
    market = budget_world.category("Mercado")
    record = _create(budget_world, _draft((_line(market, amount="1234567.12345678"),)))
    assert record.lines[0].planned.amount == Decimal("1234567.12345678")
    with budget_world.engine.begin() as connection:
        column = connection.scalar(
            text(
                "SELECT data_type || ':' || numeric_precision || ',' || numeric_scale "
                "FROM information_schema.columns "
                "WHERE table_schema='finance' AND table_name='budget_lines' "
                "AND column_name='planned_amount'"
            )
        )
    assert column == "numeric:24,8"


def test_list_by_month_returns_only_that_month_and_audience(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    personal = budget_world.category("Meu mercado", household=False)
    household = _create(budget_world, _draft((_line(market),)))
    mine = _create(
        budget_world,
        _draft((_line(personal),), scope=_PERSONAL, name="Meu mês"),
    )
    _create(
        budget_world,
        _draft((_line(market),), period=date(2026, 11, 1), name="Novembro"),
    )

    owner_view = _store(budget_world).list_budgets(
        **budget_world.scope(), period_start=_OCT
    )
    assert {b.id for b in owner_view} == {household.id, mine.id}

    member_view = _store(budget_world).list_budgets(
        **budget_world.scope(budget_world.member_id), period_start=_OCT
    )
    assert [b.id for b in member_view] == [household.id]


def test_list_costs_two_statements_regardless_of_budget_count(
    budget_world: BudgetWorld,
) -> None:
    from sqlalchemy import event

    market = budget_world.category("Mercado")
    for index, currency in enumerate(("BRL", "USD", "EUR")):
        _create(
            budget_world,
            FinancialBudgetDraft(
                name=f"Orçamento {index}",
                visibility_scope=_HOUSEHOLD,
                currency=currency,
                period_start=_OCT,
                date_basis=FinancialBudgetDateBasis.CASH,
                lines=(
                    FinancialBudgetLineDraft(
                        market, _EXPENSE, Money(Decimal("10"), currency)
                    ),
                ),
            ),
        )
    statements: list[str] = []

    def record(conn, cursor, statement, *args):  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(budget_world.runtime, "before_cursor_execute", record)
    try:
        result = _store(budget_world).list_budgets(
            **budget_world.scope(), period_start=_OCT
        )
    finally:
        event.remove(budget_world.runtime, "before_cursor_execute", record)
    assert len(result) == 3
    data = [s for s in statements if "finance.budget" in s]
    assert len(data) == 2


# --- audience / RLS -----------------------------------------------------------


def test_personal_budget_is_owner_only(budget_world: BudgetWorld) -> None:
    personal = budget_world.category("Meu mercado", household=False)
    record = _create(budget_world, _draft((_line(personal),), scope=_PERSONAL))
    with pytest.raises(FinancialBudgetNotFoundError):
        _store(budget_world).get_budget(
            **budget_world.scope(budget_world.member_id), budget_id=record.id
        )
    with pytest.raises(FinancialBudgetNotFoundError):
        _store(budget_world).replace_budget(
            **budget_world.scope(budget_world.member_id),
            budget_id=record.id,
            replacement=FinancialBudgetReplacement(1, "x", (_line(personal),)),
        )


def test_household_budget_is_readable_by_members_but_writable_only_by_owner(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    record = _create(budget_world, _draft((_line(market),)))
    seen = _store(budget_world).get_budget(
        **budget_world.scope(budget_world.member_id), budget_id=record.id
    )
    assert seen == record
    with pytest.raises(FinancialBudgetNotEditableError):
        _store(budget_world).replace_budget(
            **budget_world.scope(budget_world.member_id),
            budget_id=record.id,
            replacement=FinancialBudgetReplacement(
                1, "Hack", (_line(market, amount="1"),)
            ),
        )
    unchanged = _store(budget_world).get_budget(
        **budget_world.scope(), budget_id=record.id
    )
    assert unchanged.version == 1 and unchanged.name == "Outubro"


def test_cross_residence_is_invisible_and_denied(budget_world: BudgetWorld) -> None:
    market = budget_world.category("Mercado")
    record = _create(budget_world, _draft((_line(market),)))
    outsider_scope = budget_world.scope(
        budget_world.outsider_id, budget_world.other_residence_id
    )
    with pytest.raises(FinancialBudgetNotFoundError):
        _store(budget_world).get_budget(**outsider_scope, budget_id=record.id)
    assert _store(budget_world).list_budgets(**outsider_scope, period_start=_OCT) == ()
    # The outsider cannot even assert membership of the first residence.
    with pytest.raises(FinancialBudgetAccessError):
        _store(budget_world).get_budget(
            **budget_world.scope(budget_world.outsider_id), budget_id=record.id
        )
    with pytest.raises(FinancialBudgetAccessError):
        _create(
            budget_world, _draft((_line(market),)), operator_id=budget_world.outsider_id
        )


def test_rls_is_forced_and_fail_closed_without_context(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    _create(budget_world, _draft((_line(market),)))
    with budget_world.runtime.begin() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(financial_budgets)) == 0
        )
        assert (
            connection.scalar(select(func.count()).select_from(financial_budget_lines))
            == 0
        )
    with budget_world.engine.begin() as connection:
        rows = connection.exec_driver_sql(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'finance' AND c.relname IN ('budgets', 'budget_lines')"
        ).all()
    assert len(rows) == 2 and all(r[1] and r[2] for r in rows)


def test_runtime_has_no_delete_and_only_cas_update_columns(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    record = _create(budget_world, _draft((_line(market),)))
    ctx = (
        "SELECT set_config('app.current_installation_id', :i, true), "
        "set_config('app.current_residence_id', :r, true), "
        "set_config('app.current_operator_id', :o, true)"
    )
    params = {
        "i": str(budget_world.installation_id),
        "r": str(budget_world.residence_id),
        "o": str(budget_world.owner_id),
    }
    forbidden = (
        "DELETE FROM finance.budgets WHERE id = :id",
        "DELETE FROM finance.budget_lines WHERE budget_id = :id",
        "UPDATE finance.budgets SET currency = 'USD' WHERE id = :id",
        "UPDATE finance.budgets SET date_basis = 'COMPETENCE' WHERE id = :id",
        "UPDATE finance.budgets SET period_start = '2026-11-01' WHERE id = :id",
        "UPDATE finance.budgets SET visibility_scope = 'PERSONAL' WHERE id = :id",
        "UPDATE finance.budget_lines SET planned_amount = 1 WHERE budget_id = :id",
    )
    for statement in forbidden:
        with pytest.raises(DBAPIError):
            with budget_world.runtime.begin() as connection:
                connection.execute(text(ctx), params)
                connection.execute(text(statement), {"id": record.id})
    again = _store(budget_world).get_budget(**budget_world.scope(), budget_id=record.id)
    assert again == record


def test_database_rejects_version_skips_and_orphan_budgets(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    record = _create(budget_world, _draft((_line(market),)))
    ctx = (
        "SELECT set_config('app.current_installation_id', :i, true), "
        "set_config('app.current_residence_id', :r, true), "
        "set_config('app.current_operator_id', :o, true)"
    )
    params = {
        "i": str(budget_world.installation_id),
        "r": str(budget_world.residence_id),
        "o": str(budget_world.owner_id),
    }
    with pytest.raises(DBAPIError):  # version must advance by exactly one
        with budget_world.runtime.begin() as connection:
            connection.execute(text(ctx), params)
            connection.execute(
                text("UPDATE finance.budgets SET version = 7 WHERE id = :id"),
                {"id": record.id},
            )
    with pytest.raises(DBAPIError):  # a new version with no lines never commits
        with budget_world.runtime.begin() as connection:
            connection.execute(text(ctx), params)
            connection.execute(
                text(
                    "UPDATE finance.budgets SET version = 2, "
                    "updated_at = transaction_timestamp() WHERE id = :id"
                ),
                {"id": record.id},
            )
    assert (
        _store(budget_world)
        .get_budget(**budget_world.scope(), budget_id=record.id)
        .version
        == 1
    )


def test_lines_cannot_be_appended_to_a_committed_revision(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    other = budget_world.category("Lazer")
    record = _create(budget_world, _draft((_line(market),)))
    ctx = (
        "SELECT set_config('app.current_installation_id', :i, true), "
        "set_config('app.current_residence_id', :r, true), "
        "set_config('app.current_operator_id', :o, true)"
    )
    params = {
        "i": str(budget_world.installation_id),
        "r": str(budget_world.residence_id),
        "o": str(budget_world.owner_id),
    }
    with pytest.raises(DBAPIError):
        with budget_world.runtime.begin() as connection:
            connection.execute(text(ctx), params)
            connection.execute(
                text(
                    "INSERT INTO finance.budget_lines (budget_id, revision, "
                    "category_id, result_effect, installation_id, residence_id, "
                    "currency, planned_amount, created_at) VALUES (:b, 1, :c, "
                    "'EXPENSE', :i, :r, 'BRL', 10, now())"
                ),
                {
                    "b": record.id,
                    "c": other,
                    "i": budget_world.installation_id,
                    "r": budget_world.residence_id,
                },
            )
    reread = _store(budget_world).get_budget(
        **budget_world.scope(), budget_id=record.id
    )
    assert len(reread.lines) == 1


# --- category eligibility -----------------------------------------------------


def test_household_budget_rejects_personal_foreign_and_unknown_categories(
    budget_world: BudgetWorld,
) -> None:
    personal = budget_world.category("Minha", household=False)
    foreign = budget_world.category(
        "Outra",
        household=True,
        operator_id=budget_world.outsider_id,
        residence_id=budget_world.other_residence_id,
    )
    for category in (personal, foreign, uuid4()):
        with pytest.raises(FinancialBudgetCategoryNotFoundError):
            _create(budget_world, _draft((_line(category),)))


def test_personal_budget_requires_the_owners_personal_category(
    budget_world: BudgetWorld,
) -> None:
    household = budget_world.category("Casa")
    members_personal = budget_world.category(
        "Do membro", household=False, operator_id=budget_world.member_id
    )
    for category in (household, members_personal):
        with pytest.raises(FinancialBudgetCategoryNotFoundError):
            _create(budget_world, _draft((_line(category),), scope=_PERSONAL))
    mine = budget_world.category("Minha", household=False)
    assert _create(budget_world, _draft((_line(mine),), scope=_PERSONAL)).version == 1


def test_disabled_category_is_rejected_for_new_lines(budget_world: BudgetWorld) -> None:
    market = budget_world.category("Mercado")
    with budget_world.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE finance.categories SET status = 'DISABLED', "
                "disabled_at = now() WHERE id = :id"
            ),
            {"id": market},
        )
    with pytest.raises(FinancialBudgetCategoryNotFoundError):
        _create(budget_world, _draft((_line(market),)))


def test_invalid_category_write_leaves_no_partial_budget(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    with pytest.raises(FinancialBudgetCategoryNotFoundError):
        _create(budget_world, _draft((_line(market), _line(uuid4(), _INCOME))))
    assert _count(budget_world, financial_budgets) == 0
    assert _count(budget_world, financial_budget_lines) == 0


# --- idempotency / material uniqueness ----------------------------------------


def test_create_replay_returns_the_same_budget(budget_world: BudgetWorld) -> None:
    market = budget_world.category("Mercado")
    key = new_financial_idempotency_key()
    draft = _draft((_line(market),))
    first = _create(budget_world, draft, key=key)
    again = _create(budget_world, draft, key=key)
    assert again == first
    assert _count(budget_world, financial_budgets) == 1


def test_replay_ignores_line_order(budget_world: BudgetWorld) -> None:
    market = budget_world.category("Mercado")
    salary = budget_world.category("Salário")
    key = new_financial_idempotency_key()
    a, b = _line(market), _line(salary, _INCOME, "5000")
    first = _create(budget_world, _draft((a, b)), key=key)
    assert _create(budget_world, _draft((b, a)), key=key) == first


def test_reusing_a_key_with_other_material_fails_closed(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    key = new_financial_idempotency_key()
    _create(budget_world, _draft((_line(market),)), key=key)
    with pytest.raises(FinancialBudgetConflictError):
        _create(budget_world, _draft((_line(market, amount="1001"),)), key=key)
    with pytest.raises(FinancialBudgetConflictError):
        _create(
            budget_world,
            _draft((_line(market),), basis=FinancialBudgetDateBasis.COMPETENCE),
            key=key,
        )


def test_another_operators_replay_of_a_key_is_not_a_replay(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    key = new_financial_idempotency_key()
    _create(budget_world, _draft((_line(market),), scope=_HOUSEHOLD), key=key)
    with pytest.raises(FinancialBudgetConflictError):
        _create(
            budget_world,
            _draft((_line(market),), scope=_HOUSEHOLD),
            operator_id=budget_world.member_id,
            key=key,
        )


def test_one_plan_per_month_scope_currency_and_basis(budget_world: BudgetWorld) -> None:
    market = budget_world.category("Mercado")
    _create(budget_world, _draft((_line(market),)))
    with pytest.raises(FinancialBudgetConflictError):
        _create(budget_world, _draft((_line(market, amount="1"),), name="Outro"))
    # Different basis, month, or currency is a different plan.
    _create(
        budget_world,
        _draft((_line(market),), basis=FinancialBudgetDateBasis.COMPETENCE),
    )
    _create(budget_world, _draft((_line(market),), period=date(2026, 11, 1)))
    assert _count(budget_world, financial_budgets) == 3


def test_personal_plans_of_two_owners_do_not_collide(budget_world: BudgetWorld) -> None:
    mine = budget_world.category("Minha", household=False)
    theirs = budget_world.category(
        "Dele", household=False, operator_id=budget_world.member_id
    )
    _create(budget_world, _draft((_line(mine),), scope=_PERSONAL))
    other = _create(
        budget_world,
        _draft((_line(theirs),), scope=_PERSONAL),
        operator_id=budget_world.member_id,
    )
    assert other.owner_operator_id == budget_world.member_id


def test_concurrent_identical_creates_converge(budget_world: BudgetWorld) -> None:
    market = budget_world.category("Mercado")
    key = new_financial_idempotency_key()
    draft = _draft((_line(market),))
    barrier = Barrier(4)

    def run(_: int) -> FinancialBudgetRecord:
        barrier.wait()
        return _create(budget_world, draft, key=key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert len({r.id for r in results}) == 1
    assert _count(budget_world, financial_budgets) == 1
    assert _count(budget_world, financial_budget_lines) == 1


# --- CAS ----------------------------------------------------------------------


def test_replace_advances_version_and_keeps_history(budget_world: BudgetWorld) -> None:
    market = budget_world.category("Mercado")
    leisure = budget_world.category("Lazer")
    record = _create(budget_world, _draft((_line(market),)))

    updated = _store(budget_world).replace_budget(
        **budget_world.scope(),
        budget_id=record.id,
        replacement=FinancialBudgetReplacement(
            1, "Outubro revisado", (_line(leisure, amount="250"),)
        ),
    )
    assert updated.version == 2 and updated.name == "Outubro revisado"
    assert updated.created_at == record.created_at
    assert updated.updated_at >= record.updated_at
    assert [(x.category_id, x.planned.amount) for x in updated.lines] == [
        (leisure, Decimal("250"))
    ]
    assert (
        _store(budget_world).get_budget(**budget_world.scope(), budget_id=record.id)
        == updated
    )
    # Append-only: the first revision's line is still stored; nothing deleted.
    assert _count(budget_world, financial_budget_lines) == 2
    assert _count(budget_world, financial_budgets) == 1


def test_stale_version_conflicts_without_writing(budget_world: BudgetWorld) -> None:
    market = budget_world.category("Mercado")
    record = _create(budget_world, _draft((_line(market),)))
    store = _store(budget_world)
    store.replace_budget(
        **budget_world.scope(),
        budget_id=record.id,
        replacement=FinancialBudgetReplacement(1, "A", (_line(market, amount="1"),)),
    )
    lines_before = _count(budget_world, financial_budget_lines)
    with pytest.raises(FinancialBudgetVersionConflictError):
        store.replace_budget(
            **budget_world.scope(),
            budget_id=record.id,
            replacement=FinancialBudgetReplacement(
                1, "B", (_line(market, amount="2"),)
            ),
        )
    with pytest.raises(FinancialBudgetVersionConflictError):  # a future version too
        store.replace_budget(
            **budget_world.scope(),
            budget_id=record.id,
            replacement=FinancialBudgetReplacement(
                9, "C", (_line(market, amount="3"),)
            ),
        )
    assert _count(budget_world, financial_budget_lines) == lines_before
    current = store.get_budget(**budget_world.scope(), budget_id=record.id)
    assert current.version == 2 and current.name == "A"


def test_concurrent_replaces_have_exactly_one_winner(budget_world: BudgetWorld) -> None:
    market = budget_world.category("Mercado")
    record = _create(budget_world, _draft((_line(market),)))
    barrier = Barrier(5)

    def run(index: int) -> str:
        barrier.wait()
        try:
            _store(budget_world).replace_budget(
                **budget_world.scope(),
                budget_id=record.id,
                replacement=FinancialBudgetReplacement(
                    1, f"Writer {index}", (_line(market, amount=str(index + 1)),)
                ),
            )
        except FinancialBudgetVersionConflictError:
            return "conflict"
        return "ok"

    with ThreadPoolExecutor(max_workers=5) as pool:
        outcomes = list(pool.map(run, range(5)))
    assert outcomes.count("ok") == 1 and outcomes.count("conflict") == 4
    final = _store(budget_world).get_budget(**budget_world.scope(), budget_id=record.id)
    assert final.version == 2 and len(final.lines) == 1
    assert _count(budget_world, financial_budget_lines) == 2


def test_replace_cannot_change_currency_or_use_ineligible_categories(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    personal = budget_world.category("Minha", household=False)
    record = _create(budget_world, _draft((_line(market),)))
    store = _store(budget_world)
    usd = FinancialBudgetLineDraft(market, _EXPENSE, Money(Decimal("5"), "USD"))
    with pytest.raises(FinancialBudgetInvalidShapeError):
        store.replace_budget(
            **budget_world.scope(),
            budget_id=record.id,
            replacement=FinancialBudgetReplacement(1, "x", (usd,)),
        )
    with pytest.raises(FinancialBudgetCategoryNotFoundError):
        store.replace_budget(
            **budget_world.scope(),
            budget_id=record.id,
            replacement=FinancialBudgetReplacement(1, "x", (_line(personal),)),
        )
    assert store.get_budget(**budget_world.scope(), budget_id=record.id) == record


def test_replace_of_missing_budget_is_not_found(budget_world: BudgetWorld) -> None:
    market = budget_world.category("Mercado")
    with pytest.raises(FinancialBudgetNotFoundError):
        _store(budget_world).replace_budget(
            **budget_world.scope(),
            budget_id=uuid4(),
            replacement=FinancialBudgetReplacement(1, "x", (_line(market),)),
        )


def test_replace_keeps_a_now_disabled_line_category_out(
    budget_world: BudgetWorld,
) -> None:
    market = budget_world.category("Mercado")
    record = _create(budget_world, _draft((_line(market),)))
    with budget_world.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE finance.categories SET status = 'DISABLED', "
                "disabled_at = now() WHERE id = :id"
            ),
            {"id": market},
        )
    # History stays readable...
    assert (
        _store(budget_world)
        .get_budget(**budget_world.scope(), budget_id=record.id)
        .lines
        == record.lines
    )
    # ...but a new revision cannot keep the disabled category.
    with pytest.raises(FinancialBudgetCategoryNotFoundError):
        _store(budget_world).replace_budget(
            **budget_world.scope(),
            budget_id=record.id,
            replacement=FinancialBudgetReplacement(1, "x", (_line(market),)),
        )
