"""PostgreSQL-backed proofs for categorization rules, apply and provenance.

Everything runs under the non-superuser runtime role with forced RLS.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountType,
    FinancialCategorizationApplyStatus as Applied,
)
from meufinanceiro_finance import (
    FinancialCategorizationMatcher,
    FinancialCategorizationRuleDraft,
    FinancialCategorizationRuleStatus,
    FinancialCategoryDraft,
    FinancialMovementAllocationDraft,
    FinancialMovementAllocationRevisionDraft,
    FinancialMovementAllocationSetDraft,
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialResultEffect,
    FinancialTransferDraft,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import delete, event, func, insert, select, text, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence import financial_categorization_rule_store as rule_module
from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_audit_schema import financial_audit_events
from meufinanceiro_persistence.financial_categorization_rule_schema import (
    financial_categorization_rules,
    financial_movement_allocation_rule_origins,
)
from meufinanceiro_persistence.financial_categorization_rule_store import (
    FinancialCategorizationRuleAccountNotFoundError,
    FinancialCategorizationRuleCategoryNotFoundError,
    FinancialCategorizationRuleConflictError,
    FinancialCategorizationRuleNotFoundError,
    FinancialCategorizationRulePersistenceError,
    FinancialCategorizationRuleStore,
)
from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.financial_category_store import FinancialCategoryStore
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
    financial_movement_allocations,
)
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationConflictError,
    FinancialMovementAllocationStore,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_transfer_store import FinancialTransferStore
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

_NOW = datetime(2026, 10, 5, 3, 0, tzinfo=UTC)


@dataclass(frozen=True)
class World:
    engine: Engine
    runtime: Engine
    installation_id: UUID
    residence_id: UUID
    owner_id: UUID
    member_id: UUID
    account_id: UUID
    household_category: UUID
    other_category: UUID

    @property
    def rules(self) -> FinancialCategorizationRuleStore:
        return FinancialCategorizationRuleStore(self.runtime)

    @property
    def allocations(self) -> FinancialMovementAllocationStore:
        return FinancialMovementAllocationStore(self.runtime)

    def scope(self, operator_id: UUID | None = None) -> dict[str, UUID]:
        return {
            "installation_id": self.installation_id,
            "residence_id": self.residence_id,
            "operator_id": operator_id or self.owner_id,
        }


def _household(engine: Engine) -> tuple[UUID, UUID, UUID, UUID]:
    installation_id, residence_id = uuid4(), uuid4()
    owner_id, member_id = uuid4(), uuid4()
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
                name="Synthetic rules residence",
                status="active",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        for index, (operator_id, role) in enumerate(
            ((owner_id, "owner"), (member_id, "member"))
        ):
            connection.execute(
                insert(identity_operators).values(
                    id=operator_id,
                    installation_id=installation_id,
                    login_name=f"rules-{index}",
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
                    is_primary=index == 0,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
    return installation_id, residence_id, owner_id, member_id


def _second_residence(engine: Engine, installation_id: UUID) -> tuple[UUID, UUID]:
    residence_id, owner_id = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(household_residences).values(
                id=residence_id,
                installation_id=installation_id,
                name="Synthetic other residence",
                status="active",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        connection.execute(
            insert(identity_operators).values(
                id=owner_id,
                installation_id=installation_id,
                login_name="rules-other-residence",
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
                operator_id=owner_id,
                role="owner",
                status="active",
                is_primary=True,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
    return residence_id, owner_id


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


def _category(
    runtime: Engine,
    scope: dict[str, UUID],
    *,
    visibility: FinancialVisibilityScope,
    name: str,
) -> UUID:
    return (
        FinancialCategoryStore(runtime)
        .create_category(
            **scope,
            draft=FinancialCategoryDraft(name=name, visibility_scope=visibility),
        )
        .id
    )


def _movement(
    world: World,
    description: str,
    *,
    amount: str = "-50.00",
    account_id: UUID | None = None,
) -> UUID:
    effect = (
        FinancialResultEffect.INCOME
        if Decimal(amount) > 0
        else FinancialResultEffect.EXPENSE
    )
    return (
        FinancialMovementStore(world.runtime)
        .create_movement(
            **world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementDraft(
                account_id=account_id or world.account_id,
                amount=Money(Decimal(amount), "BRL"),
                result_effect=effect,
                effective_date=date(2026, 10, 1),
                competence_date=date(2026, 10, 1),
                description=description,
            ),
        )
        .id
    )


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
        household_category=_category(
            runtime_engine,
            scope,
            visibility=FinancialVisibilityScope.HOUSEHOLD,
            name="Mercado",
        ),
        other_category=_category(
            runtime_engine,
            scope,
            visibility=FinancialVisibilityScope.HOUSEHOLD,
            name="Lazer",
        ),
    )


def _draft(
    category_id: UUID,
    pattern: str = "padaria",
    *,
    matcher: FinancialCategorizationMatcher = FinancialCategorizationMatcher.CONTAINS,
    priority: int = 10,
    account_id: UUID | None = None,
    effect: FinancialResultEffect | None = None,
) -> FinancialCategorizationRuleDraft:
    return FinancialCategorizationRuleDraft(
        description_matcher=matcher,
        description_pattern=pattern,
        target_category_id=category_id,
        priority=priority,
        account_id=account_id,
        result_effect=effect,
    )


def _create_rule(
    world: World, draft: FinancialCategorizationRuleDraft, *, operator_id=None
):
    return world.rules.create_rule(
        **world.scope(operator_id),
        idempotency_key=new_financial_idempotency_key(),
        draft=draft,
    )


def _apply(world: World, movement_id: UUID, rule_id: UUID, *, operator_id=None):
    return world.rules.apply_rule_to_movement(
        **world.scope(operator_id),
        account_id=world.account_id,
        movement_id=movement_id,
        expected_rule_id=rule_id,
    )


def _count(engine: Engine, table: object) -> int:
    with engine.begin() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    assert isinstance(value, int)
    return value


def _snapshot_movement(engine: Engine, movement_id: UUID) -> dict[str, Any]:
    with engine.begin() as connection:
        row = (
            connection.execute(
                select(financial_movements).where(
                    financial_movements.c.id == movement_id
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


def _set_context(connection: Connection, world: World, operator_id: UUID) -> None:
    connection.execute(
        select(
            func.set_config(
                "app.current_installation_id", str(world.installation_id), True
            ),
            func.set_config("app.current_residence_id", str(world.residence_id), True),
            func.set_config("app.current_operator_id", str(operator_id), True),
        )
    )


def _disable_category(engine: Engine, category_id: UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            update(financial_categories)
            .where(financial_categories.c.id == category_id)
            .values(
                status="DISABLED",
                disabled_at=func.transaction_timestamp(),
                updated_at=func.transaction_timestamp(),
            )
        )


# --- lifecycle -------------------------------------------------------------


def test_create_list_disable_and_idempotent_replay(world: World) -> None:
    key = new_financial_idempotency_key()
    draft = _draft(world.household_category, "  Padaria  ", priority=7)
    rule = world.rules.create_rule(**world.scope(), idempotency_key=key, draft=draft)

    assert rule.status is FinancialCategorizationRuleStatus.ACTIVE
    assert rule.description_pattern == "Padaria"
    assert rule.priority == 7 and rule.account_id is None and rule.result_effect is None
    assert rule.created_by_operator_id == world.owner_id

    replay = world.rules.create_rule(**world.scope(), idempotency_key=key, draft=draft)
    assert replay == rule
    assert _count(world.engine, financial_categorization_rules) == 1

    with pytest.raises(FinancialCategorizationRuleConflictError):
        world.rules.create_rule(
            **world.scope(),
            idempotency_key=key,
            draft=_draft(world.household_category, "Padaria", priority=8),
        )

    other = _create_rule(world, _draft(world.other_category, "cinema", priority=3))
    listed = world.rules.list_rules(**world.scope())
    assert [item.id for item in listed] == [rule.id, other.id]

    disabled = world.rules.disable_rule(**world.scope(), rule_id=rule.id)
    assert disabled.status is FinancialCategorizationRuleStatus.DISABLED
    assert disabled.disabled_by_operator_id == world.owner_id
    assert world.rules.disable_rule(**world.scope(), rule_id=rule.id) == disabled
    listed = world.rules.list_rules(**world.scope())
    assert [item.id for item in listed] == [other.id, rule.id]
    # The disabled rule keeps its exact semantics.
    assert listed[1].description_pattern == "Padaria" and listed[1].priority == 7


def test_rule_lifecycle_is_not_part_of_the_closed_financial_audit(world: World) -> None:
    before = _count(world.engine, financial_audit_events)
    rule = _create_rule(world, _draft(world.household_category))
    world.rules.disable_rule(**world.scope(), rule_id=rule.id)
    assert _count(world.engine, financial_audit_events) == before


def test_create_validates_category_account_and_audience(
    world: World, runtime_engine: Engine
) -> None:
    member_personal = _category(
        runtime_engine,
        world.scope(world.member_id),
        visibility=FinancialVisibilityScope.PERSONAL,
        name="Privada do membro",
    )
    owner_personal = _category(
        runtime_engine,
        world.scope(),
        visibility=FinancialVisibilityScope.PERSONAL,
        name="Privada do dono",
    )
    household_account = _account(
        runtime_engine,
        world.scope(),
        visibility=FinancialVisibilityScope.HOUSEHOLD,
        name="Conta da casa",
    )
    member_account = _account(
        runtime_engine, world.scope(world.member_id), name="Conta do membro"
    )
    disabled = _category(
        runtime_engine,
        world.scope(),
        visibility=FinancialVisibilityScope.HOUSEHOLD,
        name="Desligada",
    )
    _disable_category(world.engine, disabled)

    for category_id in (member_personal, disabled, uuid4()):
        with pytest.raises(FinancialCategorizationRuleCategoryNotFoundError):
            _create_rule(world, _draft(category_id))

    # A PERSONAL category can never target a HOUSEHOLD account's Movements.
    with pytest.raises(FinancialCategorizationRuleCategoryNotFoundError):
        _create_rule(world, _draft(owner_personal, account_id=household_account))
    assert _create_rule(world, _draft(owner_personal, account_id=world.account_id))
    assert _create_rule(
        world, _draft(world.household_category, account_id=household_account)
    )

    # Rules only reference accounts whose classification the actor may change.
    with pytest.raises(FinancialCategorizationRuleAccountNotFoundError):
        _create_rule(world, _draft(world.household_category, account_id=member_account))
    with pytest.raises(FinancialCategorizationRuleAccountNotFoundError):
        _create_rule(world, _draft(world.household_category, account_id=uuid4()))


def test_rule_visibility_follows_category_and_account_audience(
    world: World, runtime_engine: Engine
) -> None:
    owner_personal = _category(
        runtime_engine,
        world.scope(),
        visibility=FinancialVisibilityScope.PERSONAL,
        name="Privada do dono",
    )
    shared_rule = _create_rule(world, _draft(world.household_category, "a"))
    private_rule = _create_rule(
        world, _draft(owner_personal, "b", account_id=world.account_id)
    )
    bound_to_private_account = _create_rule(
        world, _draft(world.household_category, "c", account_id=world.account_id)
    )

    owner_view = {item.id for item in world.rules.list_rules(**world.scope())}
    member_view = {
        item.id for item in world.rules.list_rules(**world.scope(world.member_id))
    }
    assert owner_view == {shared_rule.id, private_rule.id, bound_to_private_account.id}
    assert member_view == {shared_rule.id}

    # Knowing a rule id proves nothing: the member cannot disable it.
    with pytest.raises(FinancialCategorizationRuleNotFoundError):
        world.rules.disable_rule(**world.scope(world.member_id), rule_id=shared_rule.id)
    with pytest.raises(FinancialCategorizationRuleNotFoundError):
        world.rules.disable_rule(
            **world.scope(world.member_id), rule_id=private_rule.id
        )
    assert (
        world.rules.list_rules(**world.scope())[0].status
        is FinancialCategorizationRuleStatus.ACTIVE
    )


def test_cross_residence_rules_are_invisible_and_unusable(world: World) -> None:
    other_residence, other_owner = _second_residence(
        world.engine, world.installation_id
    )
    rule = _create_rule(world, _draft(world.household_category))
    foreign = {
        "installation_id": world.installation_id,
        "residence_id": other_residence,
        "operator_id": other_owner,
    }
    assert world.rules.list_rules(**foreign) == ()
    with pytest.raises(FinancialCategorizationRuleNotFoundError):
        world.rules.disable_rule(**foreign, rule_id=rule.id)
    movement_id = _movement(world, "padaria")
    with pytest.raises(FinancialCategorizationRuleAccountNotFoundError):
        world.rules.apply_rule_to_movement(
            **foreign,
            account_id=world.account_id,
            movement_id=movement_id,
            expected_rule_id=rule.id,
        )
    with pytest.raises(FinancialCategorizationRuleCategoryNotFoundError):
        world.rules.create_rule(
            **foreign,
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(world.household_category),
        )


def test_rule_semantics_are_immutable_and_undeletable_for_the_runtime(
    world: World,
) -> None:
    rule = _create_rule(world, _draft(world.household_category, "padaria"))
    table = financial_categorization_rules

    def attempt(statement: Any, *, expect: type[Exception] = DBAPIError) -> None:
        with pytest.raises(expect):
            with world.runtime.begin() as connection:
                _set_context(connection, world, world.owner_id)
                connection.execute(statement)

    for column, value in (
        ("description_pattern", "outro"),
        ("priority", 99),
        ("target_category_id", world.other_category),
        ("description_matcher", "EXACT"),
        ("account_id", world.account_id),
        ("result_effect", "INCOME"),
        ("created_by_operator_id", world.member_id),
    ):
        attempt(update(table).where(table.c.id == rule.id).values({column: value}))
    attempt(delete(table).where(table.c.id == rule.id))

    world.rules.disable_rule(**world.scope(), rule_id=rule.id)
    # A disabled rule cannot be re-enabled by any runtime statement.
    attempt(
        update(table)
        .where(table.c.id == rule.id)
        .values(status="ACTIVE", disabled_at=None, disabled_by_operator_id=None)
    )
    assert _count(world.engine, table) == 1


def test_trigger_blocks_semantic_updates_even_for_the_table_owner(
    world: World,
) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    table = financial_categorization_rules
    with pytest.raises(DBAPIError):
        with world.engine.begin() as connection:
            connection.execute(
                update(table).where(table.c.id == rule.id).values(priority=999)
            )


# --- apply -----------------------------------------------------------------


def test_unique_match_creates_revision_one_with_provenance_and_audit(
    world: World,
) -> None:
    rule = _create_rule(world, _draft(world.household_category, "padaria"))
    movement_id = _movement(world, "Padaria Pão Quente", amount="-37.45")
    before = _snapshot_movement(world.engine, movement_id)
    audit_before = _count(world.engine, financial_audit_events)

    result = _apply(world, movement_id, rule.id)

    assert result.status is Applied.CLASSIFIED
    assert result.rule_id == rule.id and result.allocation_set_id is not None
    current = world.allocations.get_current_allocation_set(
        **world.scope(), movement_id=movement_id
    )
    assert current.id == result.allocation_set_id
    assert current.revision == 1 and current.supersedes_id is None
    assert [item.category_id for item in current.allocations] == [
        world.household_category
    ]
    assert current.allocations[0].amount == Money(Decimal("-37.45"), "BRL")

    origins = world.rules.list_current_rule_origins(
        **world.scope(), account_id=world.account_id
    )
    assert [(o.allocation_set_id, o.movement_id, o.rule_id) for o in origins] == [
        (current.id, movement_id, rule.id)
    ]
    assert _count(world.engine, financial_audit_events) == audit_before + 1
    with world.engine.begin() as connection:
        event_type = connection.scalar(
            select(financial_audit_events.c.event_type).where(
                financial_audit_events.c.subject_id == current.id
            )
        )
    assert event_type == "ALLOCATION_SET_CREATED"
    assert _snapshot_movement(world.engine, movement_id) == before


def test_income_keeps_its_positive_sign(world: World) -> None:
    rule = _create_rule(
        world,
        _draft(
            world.household_category, "salário", effect=FinancialResultEffect.INCOME
        ),
    )
    movement_id = _movement(world, "SALÁRIO outubro", amount="1500.10")
    assert _apply(world, movement_id, rule.id).status is Applied.CLASSIFIED
    current = world.allocations.get_current_allocation_set(
        **world.scope(), movement_id=movement_id
    )
    assert current.allocations[0].amount == Money(Decimal("1500.10"), "BRL")


def test_replay_never_creates_a_new_revision(world: World) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")
    first = _apply(world, movement_id, rule.id)
    for _ in range(3):
        again = _apply(world, movement_id, rule.id)
        assert again.status is Applied.ALREADY_CLASSIFIED
        assert again.allocation_set_id is None
    assert _count(world.engine, financial_movement_allocation_sets) == 1
    assert _count(world.engine, financial_movement_allocation_rule_origins) == 1
    assert _count(world.engine, financial_movement_allocations) == 1
    current = world.allocations.get_current_allocation_set(
        **world.scope(), movement_id=movement_id
    )
    assert current.id == first.allocation_set_id


def test_manual_classification_is_never_overwritten(world: World) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")
    manual = world.allocations.create_allocation_set(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationSetDraft(
            movement_id=movement_id,
            allocations=(
                FinancialMovementAllocationDraft(
                    world.other_category, Money(Decimal("-50.00"), "BRL")
                ),
            ),
        ),
    )
    result = _apply(world, movement_id, rule.id)
    assert result.status is Applied.ALREADY_CLASSIFIED
    assert (
        world.allocations.get_current_allocation_set(
            **world.scope(), movement_id=movement_id
        )
        == manual
    )
    assert _count(world.engine, financial_movement_allocation_sets) == 1
    assert _count(world.engine, financial_movement_allocation_rule_origins) == 0


def test_manual_override_after_rule_stays_current_and_drops_the_origin(
    world: World,
) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")
    applied = _apply(world, movement_id, rule.id)
    revision = world.allocations.revise_allocation_set(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationRevisionDraft(
            movement_id=movement_id,
            supersedes_id=applied.allocation_set_id,
            allocations=(
                FinancialMovementAllocationDraft(
                    world.other_category, Money(Decimal("-50.00"), "BRL")
                ),
            ),
        ),
    )
    assert revision.revision == 2
    assert _apply(world, movement_id, rule.id).status is Applied.ALREADY_CLASSIFIED
    assert (
        world.allocations.get_current_allocation_set(
            **world.scope(), movement_id=movement_id
        )
        == revision
    )
    # Provenance of the superseded set is history, not the current classification.
    assert (
        world.rules.list_current_rule_origins(
            **world.scope(), account_id=world.account_id
        )
        == ()
    )
    assert _count(world.engine, financial_movement_allocation_rule_origins) == 1


def test_priority_resolution_ambiguity_and_stale_confirmation(world: World) -> None:
    low = _create_rule(world, _draft(world.household_category, "padaria", priority=1))
    high = _create_rule(world, _draft(world.other_category, "padaria", priority=9))
    movement_id = _movement(world, "padaria")

    # The operator confirmed the lower-priority rule: the canonical winner differs.
    stale = _apply(world, movement_id, low.id)
    assert stale.status is Applied.CONFLICT and stale.rule_id == high.id
    assert _count(world.engine, financial_movement_allocation_sets) == 0

    tie = _create_rule(world, _draft(world.household_category, "padaria", priority=9))
    for confirmed in (high.id, tie.id):
        result = _apply(world, movement_id, confirmed)
        assert result.status is Applied.AMBIGUOUS
    assert _count(world.engine, financial_movement_allocation_sets) == 0
    assert _count(world.engine, financial_movement_allocation_rule_origins) == 0

    world.rules.disable_rule(**world.scope(), rule_id=tie.id)
    assert _apply(world, movement_id, high.id).status is Applied.CLASSIFIED


def test_disabled_rule_and_unusable_categories_never_write(world: World) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")

    _disable_category(world.engine, world.household_category)
    assert _apply(world, movement_id, rule.id).status is Applied.NO_MATCH

    other = _create_rule(world, _draft(world.other_category, priority=1))
    world.rules.disable_rule(**world.scope(), rule_id=other.id)
    assert _apply(world, movement_id, other.id).status is Applied.NO_MATCH
    assert _count(world.engine, financial_movement_allocation_sets) == 0


def test_account_filter_and_wrong_account_are_ineligible_or_unmatched(
    world: World, runtime_engine: Engine
) -> None:
    second = _account(runtime_engine, world.scope(), name="Segunda")
    rule = _create_rule(world, _draft(world.household_category, account_id=second))
    on_first = _movement(world, "padaria")
    on_second = _movement(world, "padaria", account_id=second)

    assert _apply(world, on_first, rule.id).status is Applied.NO_MATCH
    # Movement of another account than the one in the request is ineligible.
    assert _apply(world, on_second, rule.id).status is Applied.INELIGIBLE
    cross = world.rules.apply_rule_to_movement(
        **world.scope(),
        account_id=second,
        movement_id=on_second,
        expected_rule_id=rule.id,
    )
    assert cross.status is Applied.CLASSIFIED


def test_neutral_reversal_and_unknown_movements_are_ineligible(
    world: World, runtime_engine: Engine
) -> None:
    rule = _create_rule(world, _draft(world.household_category, "transfer|padaria"))
    destination = _account(runtime_engine, world.scope(), name="Destino")
    FinancialTransferStore(runtime_engine).create_transfer(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialTransferDraft(
            source_account_id=world.account_id,
            destination_account_id=destination,
            magnitude=Money(Decimal("20"), "BRL"),
            effective_date=date(2026, 10, 1),
            competence_date=date(2026, 10, 1),
            description="Synthetic neutral transfer",
        ),
    )
    with world.engine.begin() as connection:
        neutral = connection.scalar(
            select(financial_movements.c.id).where(
                financial_movements.c.account_id == world.account_id,
                financial_movements.c.result_effect == "NEUTRAL",
            )
        )
    standard = _movement(world, "padaria")
    reversal = FinancialMovementStore(runtime_engine).reverse_movement(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=standard,
            effective_date=date(2026, 10, 2),
            competence_date=date(2026, 10, 1),
            reason="Synthetic reversal",
        ),
    )
    for movement_id in (neutral, reversal.id, uuid4()):
        assert _apply(world, movement_id, rule.id).status is Applied.INELIGIBLE
    assert _count(world.engine, financial_movement_allocation_sets) == 0


def test_only_the_account_owner_may_apply(world: World) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")
    with pytest.raises(FinancialCategorizationRuleAccountNotFoundError):
        _apply(world, movement_id, rule.id, operator_id=world.member_id)
    assert _count(world.engine, financial_movement_allocation_sets) == 0


def test_a_visible_household_rule_of_another_member_can_be_applied(
    world: World,
) -> None:
    member_rule = _create_rule(
        world, _draft(world.household_category, "padaria"), operator_id=world.member_id
    )
    movement_id = _movement(world, "padaria")
    assert _apply(world, movement_id, member_rule.id).status is Applied.CLASSIFIED


def test_manual_wins_the_preview_to_apply_race(world: World) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")
    # "Preview": the Movement is unclassified and the rule would match...
    assert world.rules.list_rules(**world.scope())[0].id == rule.id
    # ...then a manual classification lands before the confirmed apply arrives.
    manual = world.allocations.create_allocation_set(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationSetDraft(
            movement_id=movement_id,
            allocations=(
                FinancialMovementAllocationDraft(
                    world.other_category, Money(Decimal("-50.00"), "BRL")
                ),
            ),
        ),
    )
    assert _apply(world, movement_id, rule.id).status is Applied.ALREADY_CLASSIFIED
    assert (
        world.allocations.get_current_allocation_set(
            **world.scope(), movement_id=movement_id
        ).id
        == manual.id
    )


def test_concurrent_applies_create_exactly_one_classification(world: World) -> None:
    first = _create_rule(world, _draft(world.household_category, "padaria", priority=5))
    movement_id = _movement(world, "padaria")
    workers = 6
    barrier = Barrier(workers)

    def attempt(_: int) -> Applied:
        barrier.wait()
        return _apply(world, movement_id, first.id).status

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(attempt, range(workers)))

    assert outcomes.count(Applied.CLASSIFIED) == 1
    assert outcomes.count(Applied.ALREADY_CLASSIFIED) == workers - 1
    assert _count(world.engine, financial_movement_allocation_sets) == 1
    assert _count(world.engine, financial_movement_allocation_rule_origins) == 1
    assert _count(world.engine, financial_audit_events) >= 1


def test_concurrent_manual_and_rule_classification_never_fork_or_overwrite(
    world: World,
) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")
    barrier = Barrier(2)

    def by_rule() -> str:
        barrier.wait()
        return _apply(world, movement_id, rule.id).status.value

    def by_hand() -> str:
        barrier.wait()
        try:
            world.allocations.create_allocation_set(
                **world.scope(),
                idempotency_key=new_financial_idempotency_key(),
                draft=FinancialMovementAllocationSetDraft(
                    movement_id=movement_id,
                    allocations=(
                        FinancialMovementAllocationDraft(
                            world.other_category, Money(Decimal("-50.00"), "BRL")
                        ),
                    ),
                ),
            )
            return "MANUAL"
        except FinancialMovementAllocationConflictError:
            return "MANUAL_CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        rule_future, hand_future = pool.submit(by_rule), pool.submit(by_hand)
        rule_outcome, hand_outcome = rule_future.result(), hand_future.result()

    assert _count(world.engine, financial_movement_allocation_sets) == 1
    assert {rule_outcome, hand_outcome} in (
        {"CLASSIFIED", "MANUAL_CONFLICT"},
        {"ALREADY_CLASSIFIED", "MANUAL"},
    )
    origins = _count(world.engine, financial_movement_allocation_rule_origins)
    assert origins == (1 if rule_outcome == "CLASSIFIED" else 0)


def test_concurrent_different_rules_cannot_both_classify(world: World) -> None:
    rules = [
        _create_rule(world, _draft(world.household_category, "padaria", priority=5)),
        _create_rule(world, _draft(world.other_category, "padaria", priority=5)),
    ]
    # Tied rules are ambiguous: neither application may write.
    movement_id = _movement(world, "padaria")
    barrier = Barrier(2)

    def attempt(rule_id: UUID) -> Applied:
        barrier.wait()
        return _apply(world, movement_id, rule_id).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, [rule.id for rule in rules]))
    assert outcomes == [Applied.AMBIGUOUS, Applied.AMBIGUOUS]
    assert _count(world.engine, financial_movement_allocation_sets) == 0


# --- atomicity and provenance integrity ------------------------------------


def _assert_nothing_persisted_for_the_application(
    world: World, audit_before: int
) -> None:
    assert _count(world.engine, financial_movement_allocation_sets) == 0
    assert _count(world.engine, financial_movement_allocations) == 0
    assert _count(world.engine, financial_movement_allocation_rule_origins) == 0
    assert _count(world.engine, financial_audit_events) == audit_before


def test_origin_failure_rolls_back_allocation_and_audit(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")
    audit_before = _count(world.engine, financial_audit_events)

    original = rule_module._append_allocation_set

    def with_unknown_rule(connection: Connection, **kwargs: Any) -> Any:
        kwargs["rule_id"] = uuid4()  # provenance insert violates its FK
        return original(connection, **kwargs)

    monkeypatch.setattr(rule_module, "_append_allocation_set", with_unknown_rule)
    # The provenance insert is refused (the rule is not visible/known): the whole
    # transaction fails and the service reports it as an item-level failure.
    with pytest.raises(FinancialCategorizationRulePersistenceError):
        _apply(world, movement_id, rule.id)

    _assert_nothing_persisted_for_the_application(world, audit_before)


def test_rule_disabled_after_evaluation_cannot_classify(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")
    audit_before = _count(world.engine, financial_audit_events)
    stale_rules = world.rules.list_rules(**world.scope())
    world.rules.disable_rule(**world.scope(), rule_id=rule.id)

    # Simulate the read-then-disable race: evaluation still saw the rule active.
    monkeypatch.setattr(rule_module, "_active_rules", lambda *a, **k: stale_rules)
    result = _apply(world, movement_id, rule.id)

    assert result.status is Applied.CONFLICT
    _assert_nothing_persisted_for_the_application(world, audit_before)


def test_disable_waits_for_an_in_flight_apply_and_never_loses_provenance(
    world: World,
) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")
    barrier = Barrier(2)

    def apply() -> Applied:
        barrier.wait()
        return _apply(world, movement_id, rule.id).status

    def disable() -> None:
        barrier.wait()
        world.rules.disable_rule(**world.scope(), rule_id=rule.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        applied, disabled = pool.submit(apply), pool.submit(disable)
        status = applied.result()
        disabled.result()

    assert status in (Applied.CLASSIFIED, Applied.NO_MATCH, Applied.CONFLICT)
    sets = _count(world.engine, financial_movement_allocation_sets)
    origins = _count(world.engine, financial_movement_allocation_rule_origins)
    assert sets == origins == (1 if status is Applied.CLASSIFIED else 0)
    assert (
        world.rules.list_rules(**world.scope())[0].status
        is FinancialCategorizationRuleStatus.DISABLED
    )


def test_a_visible_rule_can_be_share_locked_by_any_member_and_blocks_disable(
    world: World,
) -> None:
    """The provenance trigger locks the rule FOR SHARE; prove the lock is real."""
    rule = _create_rule(world, _draft(world.household_category))
    table = financial_categorization_rules
    with world.runtime.connect() as holder:
        with holder.begin():
            _set_context(holder, world, world.member_id)
            locked = holder.scalar(
                select(table.c.id)
                .where(table.c.id == rule.id)
                .with_for_update(read=True)
            )
            assert locked == rule.id
            with pytest.raises(DBAPIError):
                with world.runtime.begin() as other:
                    _set_context(other, world, world.owner_id)
                    other.execute(text("SET LOCAL lock_timeout = '300ms'"))
                    other.execute(
                        update(table)
                        .where(table.c.id == rule.id)
                        .values(
                            status="DISABLED",
                            disabled_at=func.transaction_timestamp(),
                            disabled_by_operator_id=world.owner_id,
                        )
                    )
    disabled = world.rules.disable_rule(**world.scope(), rule_id=rule.id)
    assert disabled.status is FinancialCategorizationRuleStatus.DISABLED


def test_origin_is_append_only_for_the_runtime(world: World) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")
    _apply(world, movement_id, rule.id)
    origins = financial_movement_allocation_rule_origins
    for statement in (
        update(origins).values(rule_id=uuid4()),
        delete(origins),
    ):
        with pytest.raises(DBAPIError):
            with world.runtime.begin() as connection:
                _set_context(connection, world, world.owner_id)
                connection.execute(statement)
    assert _count(world.engine, origins) == 1


def _first_set_without_origin(world: World) -> tuple[UUID, UUID]:
    movement_id = _movement(world, "manual one")
    manual = world.allocations.create_allocation_set(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationSetDraft(
            movement_id=movement_id,
            allocations=(
                FinancialMovementAllocationDraft(
                    world.household_category, Money(Decimal("-50.00"), "BRL")
                ),
            ),
        ),
    )
    return movement_id, manual.id


def _insert_origin(
    world: World,
    *,
    set_id: UUID,
    movement_id: UUID,
    rule_id: UUID,
    operator_id: UUID | None = None,
) -> None:
    with world.runtime.begin() as connection:
        _set_context(connection, world, operator_id or world.owner_id)
        connection.execute(
            insert(financial_movement_allocation_rule_origins).values(
                allocation_set_id=set_id,
                installation_id=world.installation_id,
                residence_id=world.residence_id,
                movement_id=movement_id,
                rule_id=rule_id,
                created_at=func.transaction_timestamp(),
            )
        )


def test_direct_sql_cannot_forge_inconsistent_provenance(world: World) -> None:
    matching = _create_rule(world, _draft(world.household_category, "manual"))
    other_target = _create_rule(world, _draft(world.other_category, "manual"))
    wrong_effect = _create_rule(
        world,
        _draft(world.household_category, "manual", effect=FinancialResultEffect.INCOME),
    )
    movement_id, set_id = _first_set_without_origin(world)

    # Wrong category target, wrong effect condition: rejected by the trigger.
    for rule in (other_target, wrong_effect):
        with pytest.raises(IntegrityError):
            _insert_origin(
                world, set_id=set_id, movement_id=movement_id, rule_id=rule.id
            )
    # A different operator did not create the set: rejected by RLS.
    with pytest.raises(DBAPIError):
        _insert_origin(
            world,
            set_id=set_id,
            movement_id=movement_id,
            rule_id=matching.id,
            operator_id=world.member_id,
        )
    assert _count(world.engine, financial_movement_allocation_rule_origins) == 0

    # A coherent origin for a first revision is accepted (proves the guards are tight).
    _insert_origin(world, set_id=set_id, movement_id=movement_id, rule_id=matching.id)
    assert _count(world.engine, financial_movement_allocation_rule_origins) == 1


def test_provenance_requires_a_first_revision_and_an_active_rule(world: World) -> None:
    rule = _create_rule(world, _draft(world.household_category, "manual"))
    movement_id, set_id = _first_set_without_origin(world)
    revision = world.allocations.revise_allocation_set(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementAllocationRevisionDraft(
            movement_id=movement_id,
            supersedes_id=set_id,
            allocations=(
                FinancialMovementAllocationDraft(
                    world.household_category, Money(Decimal("-50.00"), "BRL")
                ),
            ),
        ),
    )
    with pytest.raises(IntegrityError):
        _insert_origin(
            world, set_id=revision.id, movement_id=movement_id, rule_id=rule.id
        )

    world.rules.disable_rule(**world.scope(), rule_id=rule.id)
    with pytest.raises(IntegrityError):
        _insert_origin(world, set_id=set_id, movement_id=movement_id, rule_id=rule.id)
    assert _count(world.engine, financial_movement_allocation_rule_origins) == 0


def test_origins_are_invisible_across_residences_and_to_unrelated_audiences(
    world: World, runtime_engine: Engine
) -> None:
    rule = _create_rule(world, _draft(world.household_category))
    movement_id = _movement(world, "padaria")
    _apply(world, movement_id, rule.id)
    other_residence, other_owner = _second_residence(
        world.engine, world.installation_id
    )
    with runtime_engine.begin() as connection:
        connection.execute(
            select(
                func.set_config(
                    "app.current_installation_id", str(world.installation_id), True
                ),
                func.set_config("app.current_residence_id", str(other_residence), True),
                func.set_config("app.current_operator_id", str(other_owner), True),
            )
        )
        visible = connection.scalar(
            select(func.count()).select_from(financial_movement_allocation_rule_origins)
        )
    assert visible == 0
    # The member cannot see a PERSONAL account's Movements, hence not their origins.
    with runtime_engine.begin() as connection:
        _set_context(connection, world, world.member_id)
        assert (
            connection.scalar(
                select(func.count()).select_from(
                    financial_movement_allocation_rule_origins
                )
            )
            == 0
        )


def test_origin_read_is_one_statement_regardless_of_movement_count(
    world: World,
) -> None:
    rule = _create_rule(world, _draft(world.household_category, "padaria"))
    statements: list[str] = []

    def count(*_: Any) -> None:
        statements.append("x")

    def measure() -> int:
        statements.clear()
        event.listen(world.runtime, "before_cursor_execute", count)
        try:
            world.rules.list_current_rule_origins(
                **world.scope(), account_id=world.account_id
            )
        finally:
            event.remove(world.runtime, "before_cursor_execute", count)
        return len(statements)

    zero = measure()
    for index in range(3):
        _apply(world, _movement(world, f"padaria {index}"), rule.id)
    three = measure()
    for index in range(3, 9):
        _apply(world, _movement(world, f"padaria {index}"), rule.id)
    nine = measure()
    assert zero == three == nine


def test_runtime_privileges_match_the_append_only_contract(world: World) -> None:
    with world.engine.begin() as connection:
        role = connection.scalar(select(text("current_user")))
        assert role == "postgres"
    with world.runtime.begin() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                  has_table_privilege(current_user,
                    'finance.categorization_rules', 'DELETE'),
                  has_table_privilege(current_user,
                    'finance.categorization_rules', 'UPDATE'),
                  has_column_privilege(current_user,
                    'finance.categorization_rules', 'priority', 'UPDATE'),
                  has_column_privilege(current_user,
                    'finance.categorization_rules', 'status', 'UPDATE'),
                  has_table_privilege(current_user,
                    'finance.movement_allocation_rule_origins', 'UPDATE'),
                  has_table_privilege(current_user,
                    'finance.movement_allocation_rule_origins', 'DELETE'),
                  has_table_privilege(current_user,
                    'finance.movement_allocation_rule_origins', 'INSERT')
                """
            )
        ).one()
    table_delete, table_update, priority_update, status_update, o_upd, o_del, o_ins = (
        rows
    )
    assert not table_delete and not priority_update
    assert status_update and o_ins
    assert not o_upd and not o_del
    # TABLE-level UPDATE is false when only some columns are granted.
    assert table_update is False


def test_no_provider_semantics_in_the_rule_schema() -> None:
    names = {column.name for column in financial_categorization_rules.c}
    assert not any("provider" in name or "pluggy" in name for name in names)
    assert names >= {
        "account_id",
        "result_effect",
        "description_matcher",
        "description_pattern",
        "target_category_id",
        "priority",
        "status",
    }
