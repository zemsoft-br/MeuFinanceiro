"""PostgreSQL-backed proofs for the derived pending-classification read model.

Everything runs under the non-superuser runtime role with forced RLS. The store
is read-only: no pending state exists anywhere, so every proof is about what the
canonical ledger and classification tables imply.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    PENDING_PAGE_LIMIT_MAX,
    FinancialAccountDraft,
    FinancialAccountStatus,
    FinancialAccountType,
    FinancialCategorizationMatcher,
    FinancialCategorizationRuleDraft,
    FinancialCategoryDraft,
    FinancialMovementAllocationDraft,
    FinancialMovementAllocationSetDraft,
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialPendingMovementKey,
    FinancialResultEffect,
    FinancialTransferDraft,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import event, func, insert, select, text, update
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_audit_schema import financial_audit_events
from meufinanceiro_persistence.financial_categorization_rule_store import (
    FinancialCategorizationRuleStore,
)
from meufinanceiro_persistence.financial_category_store import FinancialCategoryStore
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
)
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationStore,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_pending_movement_store import (
    FinancialPendingMovementAccessError,
    FinancialPendingMovementAccountNotFoundError,
    FinancialPendingMovementStore,
)
from meufinanceiro_persistence.financial_transfer_store import FinancialTransferStore
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

_NOW = datetime(2026, 10, 5, 3, 0, tzinfo=UTC)
_BASE_DATE = date(2026, 9, 1)


@dataclass(frozen=True)
class World:
    engine: Engine
    runtime: Engine
    installation_id: UUID
    residence_id: UUID
    owner_id: UUID
    member_id: UUID
    account_id: UUID
    category_id: UUID

    @property
    def pending(self) -> FinancialPendingMovementStore:
        return FinancialPendingMovementStore(self.runtime)

    def scope(self, operator_id: UUID | None = None) -> dict[str, UUID]:
        return {
            "installation_id": self.installation_id,
            "residence_id": self.residence_id,
            "operator_id": operator_id or self.owner_id,
        }

    def page(self, *, operator_id: UUID | None = None, limit: int = 100, **kwargs: Any):
        return self.pending.list_pending_candidates(
            **self.scope(operator_id), limit=limit, **kwargs
        )

    def ids(self, **kwargs: Any) -> list[UUID]:
        return [item.movement.id for item in self.page(**kwargs).candidates]


def _add_operator(
    connection: Any,
    installation_id: UUID,
    residence_id: UUID,
    *,
    role: str,
    primary: bool,
    login: str,
) -> UUID:
    operator_id = uuid4()
    connection.execute(
        insert(identity_operators).values(
            id=operator_id,
            installation_id=installation_id,
            login_name=login,
            password_hash="synthetic-password-hash-material-000000000000",
            role="installation_admin",
            status="active",
            failed_attempts=0,
            locked_until=None,
            last_authenticated_at=None,
            password_changed_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    connection.execute(
        insert(household_memberships).values(
            id=uuid4(),
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            role=role,
            status="active",
            is_primary=primary,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    return operator_id


def _household(engine: Engine) -> tuple[UUID, UUID, UUID, UUID]:
    installation_id, residence_id = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(identity_installation).values(
                singleton=True, id=installation_id, created_at=_NOW, updated_at=_NOW
            )
        )
        connection.execute(
            insert(household_residences).values(
                id=residence_id,
                installation_id=installation_id,
                name="Synthetic pending residence",
                status="active",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        owner_id = _add_operator(
            connection,
            installation_id,
            residence_id,
            role="owner",
            primary=True,
            login=f"pending-{uuid4().hex[:8]}",
        )
        member_id = _add_operator(
            connection,
            installation_id,
            residence_id,
            role="member",
            primary=False,
            login=f"pending-{uuid4().hex[:8]}",
        )
    return installation_id, residence_id, owner_id, member_id


def _account(
    runtime: Engine,
    scope: dict[str, UUID],
    *,
    visibility: FinancialVisibilityScope = FinancialVisibilityScope.PERSONAL,
    name: str = "Conta",
) -> UUID:
    return (
        FinancialAccountStore(runtime)
        .create_account(
            **scope,
            draft=FinancialAccountDraft(
                name=name,
                currency="BRL",
                account_type=FinancialAccountType.CHECKING,
                visibility_scope=visibility,
            ),
        )
        .id
    )


def _category(runtime: Engine, scope: dict[str, UUID], name: str) -> UUID:
    return (
        FinancialCategoryStore(runtime)
        .create_category(
            **scope,
            draft=FinancialCategoryDraft(
                name=name, visibility_scope=FinancialVisibilityScope.HOUSEHOLD
            ),
        )
        .id
    )


def _movement(
    world: World,
    description: str = "Synthetic pending",
    *,
    amount: str = "-50.00",
    day: int = 0,
    account_id: UUID | None = None,
    operator_id: UUID | None = None,
) -> UUID:
    effect = (
        FinancialResultEffect.INCOME
        if Decimal(amount) > 0
        else FinancialResultEffect.EXPENSE
    )
    when = _BASE_DATE + timedelta(days=day)
    return (
        FinancialMovementStore(world.runtime)
        .create_movement(
            **world.scope(operator_id),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementDraft(
                account_id=account_id or world.account_id,
                amount=Money(Decimal(amount), "BRL"),
                result_effect=effect,
                effective_date=when,
                competence_date=when,
                description=description,
            ),
        )
        .id
    )


def _classify(world: World, movement_id: UUID, amount: str = "-50.00") -> None:
    FinancialMovementAllocationStore(world.runtime).create_allocation_set(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationSetDraft(
            movement_id=movement_id,
            allocations=(
                FinancialMovementAllocationDraft(
                    world.category_id, Money(Decimal(amount), "BRL")
                ),
            ),
        ),
    )


def _count(engine: Engine, table: Any) -> int:
    with engine.begin() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    assert isinstance(value, int)
    return value


@pytest.fixture
def world(engine: Engine, runtime_engine: Engine) -> World:
    installation_id, residence_id, owner_id, member_id = _household(engine)
    scope = {
        "installation_id": installation_id,
        "residence_id": residence_id,
        "operator_id": owner_id,
    }
    return World(
        engine=engine,
        runtime=runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        owner_id=owner_id,
        member_id=member_id,
        account_id=_account(runtime_engine, scope),
        category_id=_category(runtime_engine, scope, "Mercado"),
    )


# --- derivation ------------------------------------------------------------


def test_lists_only_unclassified_standard_income_and_expense(world: World) -> None:
    expense = _movement(world, "despesa", amount="-10.00", day=1)
    income = _movement(world, "receita", amount="25.00", day=2)
    manual = _movement(world, "manual", day=3)
    _classify(world, manual)

    rule_target = _movement(world, "padaria", day=4)
    rule_store = FinancialCategorizationRuleStore(world.runtime)
    rule = rule_store.create_rule(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialCategorizationRuleDraft(
            description_matcher=FinancialCategorizationMatcher.CONTAINS,
            description_pattern="padaria",
            target_category_id=world.category_id,
            priority=5,
        ),
    )
    applied = rule_store.apply_rule_to_movement(
        **world.scope(),
        account_id=world.account_id,
        movement_id=rule_target,
        expected_rule_id=rule.id,
    )
    assert applied.allocation_set_id is not None

    destination = _account(world.runtime, world.scope(), name="Destino")
    FinancialTransferStore(world.runtime).create_transfer(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialTransferDraft(
            source_account_id=world.account_id,
            destination_account_id=destination,
            magnitude=Money(Decimal("20"), "BRL"),
            effective_date=_BASE_DATE + timedelta(days=5),
            competence_date=_BASE_DATE + timedelta(days=5),
            description="Synthetic neutral transfer",
        ),
    )
    reversed_original = _movement(world, "estornada", day=6)
    FinancialMovementStore(world.runtime).reverse_movement(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=reversed_original,
            effective_date=_BASE_DATE + timedelta(days=7),
            competence_date=_BASE_DATE + timedelta(days=6),
            reason="Synthetic reversal",
        ),
    )

    page = world.page()
    listed = {item.movement.id for item in page.candidates}
    # NEUTRAL transfer legs, the REVERSAL, manual and rule classifications are out.
    # A reversed STANDARD original stays classifiable (ADR-0022), so it stays in.
    assert listed == {expense, income, reversed_original}
    assert not page.has_more
    assert all(
        item.movement.result_effect
        in (FinancialResultEffect.INCOME, FinancialResultEffect.EXPENSE)
        for item in page.candidates
    )


def test_a_classification_removes_the_item_on_the_next_read(world: World) -> None:
    movement = _movement(world, "agora classificada")
    assert world.ids() == [movement]
    _classify(world, movement)
    assert world.ids() == []


def test_candidate_carries_account_facts_and_can_classify(
    world: World, engine: Engine
) -> None:
    shared = _account(
        world.runtime,
        world.scope(),
        visibility=FinancialVisibilityScope.HOUSEHOLD,
        name="Conta da casa",
    )
    mine = _movement(world, "minha", day=1)
    shared_movement = _movement(world, "da casa", day=2, account_id=shared)

    owner_view = {item.movement.id: item for item in world.page().candidates}
    assert owner_view[mine].can_classify(world.owner_id)
    assert (
        owner_view[mine].account_visibility_scope is FinancialVisibilityScope.PERSONAL
    )
    assert owner_view[shared_movement].account_visibility_scope is (
        FinancialVisibilityScope.HOUSEHOLD
    )

    member_view = {
        item.movement.id: item
        for item in world.page(operator_id=world.member_id).candidates
    }
    # The member sees the household account's Movement but cannot classify it,
    # and never sees the owner's PERSONAL account Movement.
    assert set(member_view) == {shared_movement}
    assert not member_view[shared_movement].can_classify(world.member_id)
    assert member_view[shared_movement].account_owner_operator_id == world.owner_id

    with engine.begin() as connection:
        connection.execute(
            update(financial_accounts)
            .where(financial_accounts.c.id == shared)
            .values(status="ARCHIVED", archived_at=func.transaction_timestamp())
        )
    archived = {item.movement.id: item for item in world.page().candidates}
    assert archived[shared_movement].account_status is FinancialAccountStatus.ARCHIVED
    assert not archived[shared_movement].can_classify(world.owner_id)


def test_classified_household_movement_is_not_pending_for_other_members(
    world: World,
) -> None:
    shared = _account(
        world.runtime,
        world.scope(),
        visibility=FinancialVisibilityScope.HOUSEHOLD,
        name="Conta da casa",
    )
    classified = _movement(world, "ja classificada", day=1, account_id=shared)
    open_item = _movement(world, "ainda aberta", day=2, account_id=shared)
    _classify(world, classified)

    # The allocation set is visible exactly when its Movement is, so a member who
    # sees the Movement also sees that it is classified: no false pending.
    assert world.ids(operator_id=world.member_id) == [open_item]
    assert world.ids() == [open_item]


# --- ordering, keyset pagination ------------------------------------------


def test_order_is_effective_date_desc_then_id_desc(world: World) -> None:
    created = [
        _movement(world, f"m{index}", day=day)
        for index, day in enumerate((3, 1, 3, 2, 3, 1))
    ]
    with world.engine.begin() as connection:
        rows = connection.execute(
            select(financial_movements.c.id, financial_movements.c.effective_date)
            .where(financial_movements.c.id.in_(created))
            .order_by(
                financial_movements.c.effective_date.desc(),
                financial_movements.c.id.desc(),
            )
        ).all()
    assert world.ids() == [row.id for row in rows]
    dates = [row.effective_date for row in rows]
    assert dates == sorted(dates, reverse=True)


def test_a_page_that_exactly_fits_has_no_next_page(world: World) -> None:
    for index in range(3):
        _movement(world, f"m{index}", day=index)
    exact = world.page(limit=3)
    assert len(exact.candidates) == 3 and not exact.has_more
    shorter = world.page(limit=2)
    assert len(shorter.candidates) == 2 and shorter.has_more
    assert world.page(limit=100).has_more is False


def test_keyset_pages_never_repeat_or_skip(world: World) -> None:
    created = {_movement(world, f"m{index}", day=index % 4) for index in range(11)}
    seen: list[UUID] = []
    after: FinancialPendingMovementKey | None = None
    pages = 0
    while True:
        page = world.page(limit=3, after=after)
        pages += 1
        assert len(page.candidates) <= 3
        seen.extend(item.movement.id for item in page.candidates)
        if not page.has_more:
            break
        after = page.candidates[-1].key
    assert pages == 4
    assert len(seen) == len(set(seen)) == len(created)
    assert set(seen) == created
    assert seen == world.ids()


def test_keyset_is_stable_under_concurrent_appends_and_classification(
    world: World,
) -> None:
    created = [_movement(world, f"m{index}", day=10 + index) for index in range(6)]
    first = world.page(limit=3)
    ordered = world.ids()
    assert [item.movement.id for item in first.candidates] == ordered[:3]
    after = first.candidates[-1].key

    newer = _movement(world, "newer than the cursor", day=99)
    older = _movement(world, "older than the cursor", day=0)
    _classify(world, ordered[3])  # classified between pages: must not reappear

    rest = world.ids(after=after)
    assert newer not in rest  # the cursor never moves backwards: no duplicate
    assert ordered[3] not in rest
    assert rest == [*ordered[4:], older]
    assert set(created) == {*ordered}


# --- filters ---------------------------------------------------------------


def test_account_and_result_effect_filters(world: World) -> None:
    other = _account(world.runtime, world.scope(), name="Outra")
    expense = _movement(world, "d", amount="-1.00", day=1)
    income = _movement(world, "r", amount="2.00", day=2)
    other_expense = _movement(world, "o", amount="-3.00", day=3, account_id=other)

    assert set(world.ids()) == {expense, income, other_expense}
    assert world.ids(account_id=other) == [other_expense]
    assert set(world.ids(account_id=world.account_id)) == {expense, income}
    assert world.ids(result_effect=FinancialResultEffect.INCOME) == [income]
    assert set(world.ids(result_effect=FinancialResultEffect.EXPENSE)) == {
        expense,
        other_expense,
    }
    assert world.ids(
        account_id=world.account_id, result_effect=FinancialResultEffect.EXPENSE
    ) == [expense]


def test_account_filter_hides_invisible_and_unknown_accounts(world: World) -> None:
    _movement(world, "privada")
    for account_id in (world.account_id, uuid4()):
        with pytest.raises(FinancialPendingMovementAccountNotFoundError):
            world.page(operator_id=world.member_id, account_id=account_id)


def test_neutral_effect_filter_and_bad_limits_are_rejected(world: World) -> None:
    with pytest.raises(ValueError):
        world.page(result_effect=FinancialResultEffect.NEUTRAL)
    for limit in (0, -1, PENDING_PAGE_LIMIT_MAX + 1):
        with pytest.raises(ValueError):
            world.page(limit=limit)
    with pytest.raises(TypeError):
        world.page(limit=True)  # type: ignore[arg-type]


# --- authorization / isolation --------------------------------------------


def test_residence_and_membership_isolation(
    world: World, engine: Engine, runtime_engine: Engine
) -> None:
    _movement(world, "da residencia A")

    other_residence, outsider = uuid4(), None
    with engine.begin() as connection:
        connection.execute(
            insert(household_residences).values(
                id=other_residence,
                installation_id=world.installation_id,
                name="Synthetic other residence",
                status="active",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        outsider = _add_operator(
            connection,
            world.installation_id,
            other_residence,
            role="owner",
            primary=True,
            login=f"outsider-{uuid4().hex[:8]}",
        )
    other_scope = {
        "installation_id": world.installation_id,
        "residence_id": other_residence,
        "operator_id": outsider,
    }
    other_account = _account(runtime_engine, other_scope)
    other_movement = (
        FinancialMovementStore(runtime_engine)
        .create_movement(
            **other_scope,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementDraft(
                account_id=other_account,
                amount=Money(Decimal("-9.00"), "BRL"),
                result_effect=FinancialResultEffect.EXPENSE,
                effective_date=_BASE_DATE,
                competence_date=_BASE_DATE,
                description="da residencia B",
            ),
        )
        .id
    )

    # Each residence sees only its own Movements.
    other_ids = [
        item.movement.id
        for item in world.pending.list_pending_candidates(
            **other_scope, limit=100
        ).candidates
    ]
    assert other_ids == [other_movement]
    assert other_movement not in world.ids()

    # An operator from another residence cannot read this one: fail closed.
    with pytest.raises(FinancialPendingMovementAccessError):
        world.pending.list_pending_candidates(
            installation_id=world.installation_id,
            residence_id=world.residence_id,
            operator_id=outsider,
            limit=10,
        )
    with pytest.raises(FinancialPendingMovementAccessError):
        world.pending.list_pending_candidates(
            installation_id=world.installation_id,
            residence_id=world.residence_id,
            operator_id=uuid4(),
            limit=10,
        )


def test_runtime_role_cannot_write_the_read_model_sources(
    world: World, runtime_engine: Engine
) -> None:
    # The read model has no table of its own and the store only issues SELECTs.
    with runtime_engine.begin() as connection:
        tables = connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'finance' AND table_name ILIKE '%pending%'"
            )
        ).all()
    assert tables == []


# --- read-only, zero economic change ---------------------------------------


def test_listing_is_read_only_and_changes_nothing(world: World) -> None:
    ids = [_movement(world, f"m{i}", day=i) for i in range(4)]
    _classify(world, ids[0])
    with world.engine.begin() as connection:
        before_rows = connection.execute(
            select(financial_movements).order_by(financial_movements.c.id)
        ).all()
    before = (
        _count(world.engine, financial_movements),
        _count(world.engine, financial_movement_allocation_sets),
        _count(world.engine, financial_audit_events),
    )
    for _ in range(3):
        world.page(limit=2)
        world.page(account_id=world.account_id)
    after = (
        _count(world.engine, financial_movements),
        _count(world.engine, financial_movement_allocation_sets),
        _count(world.engine, financial_audit_events),
    )
    with world.engine.begin() as connection:
        after_rows = connection.execute(
            select(financial_movements).order_by(financial_movements.c.id)
        ).all()
    assert before == after
    assert before_rows == after_rows


# --- bounded cost ----------------------------------------------------------


def _statements(world: World, **kwargs: Any) -> int:
    counter = [0]

    def count(*_args: Any) -> None:
        counter[0] += 1

    event.listen(world.runtime, "before_cursor_execute", count)
    try:
        world.page(**kwargs)
    finally:
        event.remove(world.runtime, "before_cursor_execute", count)
    return counter[0]


def test_statement_count_is_constant_per_page(world: World) -> None:
    accounts = [
        world.account_id,
        *(_account(world.runtime, world.scope(), name=f"Conta {i}") for i in range(3)),
    ]
    empty = _statements(world, limit=20)
    for index in range(40):
        movement = _movement(
            world, f"m{index}", day=index, account_id=accounts[index % len(accounts)]
        )
        if index % 3 == 0:
            _classify(world, movement)
    small = _statements(world, limit=2)
    full = _statements(world, limit=100)
    filtered = _statements(world, limit=100, account_id=world.account_id)
    # context + membership + one page statement; the account filter adds one
    # existence check. Independent of Movements, accounts and allocations.
    assert empty == small == full == 3
    assert filtered == 4


# --- plan: the page walks the keyset index and stops -----------------------


def _seed_bulk(world: World, rows: int) -> None:
    """Insert ``rows`` classifiable Movements (30% still pending) as the owner role.

    Raw SQL with triggers off (``session_replication_role = replica``) only to
    build volume quickly; the proofs read through the runtime role and RLS.
    """
    with world.engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                """
                INSERT INTO finance.movements (
                    id, installation_id, residence_id, account_id, currency, amount,
                    result_effect, role, effective_date, competence_date, description,
                    created_by_operator_id, idempotency_key, request_digest, created_at
                )
                SELECT gen_random_uuid(), :i, :r, :a, 'BRL',
                       CASE WHEN g % 4 = 0 THEN 10 ELSE -10 END,
                       CASE WHEN g % 4 = 0 THEN 'INCOME' ELSE 'EXPENSE' END,
                       'STANDARD', date '2024-01-01' + (g % 1000),
                       date '2024-01-01' + (g % 1000), 'bulk ' || g, :o,
                       gen_random_uuid(), md5(g::text) || md5(g::text), now()
                FROM generate_series(1, :n) g
                """
            ),
            {
                "i": world.installation_id,
                "r": world.residence_id,
                "a": world.account_id,
                "o": world.owner_id,
                "n": rows,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO finance.movement_allocation_sets (
                    id, installation_id, residence_id, movement_id, revision,
                    supersedes_id, created_by_operator_id, idempotency_key,
                    request_digest, created_at
                )
                SELECT gen_random_uuid(), installation_id, residence_id, id, 1, NULL,
                       created_by_operator_id, gen_random_uuid(),
                       md5(id::text) || md5(id::text), now()
                FROM finance.movements
                WHERE residence_id = :r AND (hashtext(id::text) % 10) < 7
                """
            ),
            {"r": world.residence_id},
        )
        connection.execute(text("ANALYZE finance.movements"))
        connection.execute(text("ANALYZE finance.movement_allocation_sets"))


def _explain_page(world: World, **kwargs: Any) -> dict[str, Any]:
    captured: list[tuple[str, Any]] = []

    def capture(_conn: Any, _cursor: Any, statement: str, params: Any, *_rest: Any):
        if "pending_page" in statement:
            captured.append((statement, params))

    event.listen(world.runtime, "before_cursor_execute", capture)
    try:
        world.page(limit=50, **kwargs)
    finally:
        event.remove(world.runtime, "before_cursor_execute", capture)
    assert len(captured) == 1
    statement, params = captured[0]
    with world.runtime.begin() as connection:
        connection.execute(
            text(
                "SELECT set_config('app.current_installation_id', :i, true), "
                "set_config('app.current_residence_id', :r, true), "
                "set_config('app.current_operator_id', :o, true)"
            ),
            {
                "i": str(world.installation_id),
                "r": str(world.residence_id),
                "o": str(world.owner_id),
            },
        )
        row = connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, params
        ).scalar_one()
    plan = row[0] if isinstance(row, list) else row
    assert isinstance(plan, dict)
    return plan


def _nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    found = [node]
    for child in node.get("Plans", []):
        found.extend(_nodes(child))
    return found


@pytest.mark.parametrize(
    ("variant", "index"),
    [
        ("first", "ix_finance_movements_pending_scan"),
        ("deep", "ix_finance_movements_pending_scan"),
        # With a single account either keyset index serves the same ordered walk.
        ("account", "ix_finance_movements_pending_"),
    ],
)
def test_page_walks_the_keyset_index_and_stops_early(
    world: World, variant: str, index: str
) -> None:
    _seed_bulk(world, 30_000)
    params: dict[str, Any] = {}
    if variant == "deep":
        params["after"] = FinancialPendingMovementKey(
            date(2025, 3, 1), UUID("80000000-0000-4000-8000-000000000000")
        )
    if variant == "account":
        params["account_id"] = world.account_id

    plan = _explain_page(world, **params)["Plan"]
    nodes = _nodes(plan)
    scans = [
        node for node in nodes if str(node.get("Index Name", "")).startswith(index)
    ]
    assert scans, f"expected {index} in plan"
    assert not [
        node
        for node in nodes
        if node["Node Type"] == "Seq Scan" and node.get("Relation Name") == "movements"
    ]
    # ~30% of 30k Movements are pending (~9k); one page of 50 may only touch a
    # small ordered prefix of them, never the residence.
    scanned = max(
        int(node["Actual Rows"]) * int(node.get("Actual Loops", 1)) for node in scans
    )
    assert scanned < 1_000
    assert int(plan["Actual Rows"]) == 51
