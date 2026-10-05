from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountRecord,
    FinancialAccountStatus,
    FinancialAccountType,
    FinancialCategorizationApplyResult,
    FinancialCategorizationApplyStatus,
    FinancialCategorizationEvaluationStatus,
    FinancialCategorizationMatcher,
    FinancialCategorizationRuleRecord,
    FinancialCategorizationRuleStatus,
    FinancialCategoryRecord,
    FinancialCategoryStatus,
    FinancialMovementAllocationRecord,
    FinancialMovementAllocationSetRecord,
    FinancialMovementRecord,
    FinancialMovementRole,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
)
from meufinanceiro_persistence.financial_categorization_rule_store import (
    FinancialCategorizationRuleAccessError,
    FinancialCategorizationRuleAccountNotFoundError,
    FinancialCategorizationRulePersistenceError,
)

from app.services.financial_categorization import (
    MAX_APPLY_ITEMS,
    CategorizationApplyRequestItem,
    FinancialCategorizationService,
)

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
INSTALLATION_ID, RESIDENCE_ID, OWNER_ID = uuid4(), uuid4(), uuid4()
ACCOUNT_ID = uuid4()
SCOPE = {
    "installation_id": INSTALLATION_ID,
    "residence_id": RESIDENCE_ID,
    "operator_id": OWNER_ID,
}
Status = FinancialCategorizationEvaluationStatus
Applied = FinancialCategorizationApplyStatus

_RULE_METHODS = (
    "create_rule",
    "list_rules",
    "disable_rule",
    "list_current_rule_origins",
    "apply_rule_to_movement",
)


class Recorder:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result
        self.error = error

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def _account(
    *,
    owner: UUID = OWNER_ID,
    status: FinancialAccountStatus = FinancialAccountStatus.ACTIVE,
    scope: FinancialVisibilityScope = FinancialVisibilityScope.PERSONAL,
) -> FinancialAccountRecord:
    archived = status is FinancialAccountStatus.ARCHIVED
    return FinancialAccountRecord(
        id=ACCOUNT_ID,
        residence_id=RESIDENCE_ID,
        owner_operator_id=owner,
        visibility_scope=scope,
        account_type=FinancialAccountType.CHECKING,
        custom_type_name=None,
        name="Conta",
        currency="BRL",
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
        archived_at=_NOW if archived else None,
    )


def _movement(
    description: str = "padaria",
    *,
    effect: FinancialResultEffect = FinancialResultEffect.EXPENSE,
    role: FinancialMovementRole = FinancialMovementRole.STANDARD,
) -> FinancialMovementRecord:
    reversal = role is FinancialMovementRole.REVERSAL
    amount = "10" if effect is FinancialResultEffect.INCOME else "-10"
    return FinancialMovementRecord(
        id=uuid4(),
        account_id=ACCOUNT_ID,
        amount=Money(Decimal(amount), "BRL"),
        result_effect=effect,
        role=role,
        effective_date=date(2026, 10, 1),
        competence_date=date(2026, 10, 1),
        description=None if reversal else description,
        reversal_of_id=uuid4() if reversal else None,
        reversal_reason="x" if reversal else None,
        created_by_operator_id=OWNER_ID,
        created_at=_NOW,
    )


def _category(
    *, status: FinancialCategoryStatus = FinancialCategoryStatus.ACTIVE
) -> FinancialCategoryRecord:
    return FinancialCategoryRecord(
        id=uuid4(),
        residence_id=RESIDENCE_ID,
        owner_operator_id=OWNER_ID,
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        parent_id=None,
        name="Categoria",
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
        disabled_at=(_NOW if status is FinancialCategoryStatus.DISABLED else None),
    )


def _rule(
    category: FinancialCategoryRecord,
    pattern: str = "padaria",
    *,
    priority: int = 10,
    account_id: UUID | None = None,
    status: FinancialCategorizationRuleStatus = FinancialCategorizationRuleStatus.ACTIVE,
) -> FinancialCategorizationRuleRecord:
    disabled = status is FinancialCategorizationRuleStatus.DISABLED
    return FinancialCategorizationRuleRecord(
        id=uuid4(),
        residence_id=RESIDENCE_ID,
        created_by_operator_id=OWNER_ID,
        account_id=account_id,
        result_effect=None,
        description_matcher=FinancialCategorizationMatcher.CONTAINS,
        description_pattern=pattern,
        target_category_id=category.id,
        priority=priority,
        status=status,
        created_at=_NOW,
        disabled_at=_NOW if disabled else None,
        disabled_by_operator_id=OWNER_ID if disabled else None,
    )


def _allocation_set(movement_id: UUID) -> FinancialMovementAllocationSetRecord:
    set_id = uuid4()
    return FinancialMovementAllocationSetRecord(
        id=set_id,
        movement_id=movement_id,
        revision=1,
        supersedes_id=None,
        created_by_operator_id=OWNER_ID,
        created_at=_NOW,
        allocations=(
            FinancialMovementAllocationRecord(
                id=uuid4(),
                allocation_set_id=set_id,
                category_id=uuid4(),
                amount=Money(Decimal("-10"), "BRL"),
                created_at=_NOW,
            ),
        ),
    )


class World:
    def __init__(
        self,
        *,
        account: FinancialAccountRecord | None = None,
        movements: tuple[FinancialMovementRecord, ...] = (),
        classified: tuple[UUID, ...] = (),
        rules: tuple[FinancialCategorizationRuleRecord, ...] = (),
        categories: tuple[FinancialCategoryRecord, ...] = (),
        apply: Recorder | None = None,
    ) -> None:
        self.get_account = Recorder(account or _account())
        self.list_movements = Recorder(movements)
        self.list_current_allocation_sets = Recorder(
            tuple(_allocation_set(item) for item in classified)
        )
        self.list_categories = Recorder(categories)
        self.rules = SimpleNamespace(**{name: Recorder() for name in _RULE_METHODS})
        self.rules.list_rules = Recorder(rules)
        self.apply = apply or Recorder()
        self.rules.apply_rule_to_movement = self.apply

    def service(self) -> FinancialCategorizationService:
        return FinancialCategorizationService(
            self.rules,  # type: ignore[arg-type]
            SimpleNamespace(get_account=self.get_account),  # type: ignore[arg-type]
            SimpleNamespace(list_movements=self.list_movements),  # type: ignore[arg-type]
            SimpleNamespace(  # type: ignore[arg-type]
                list_current_allocation_sets=self.list_current_allocation_sets
            ),
            SimpleNamespace(list_categories=self.list_categories),  # type: ignore[arg-type]
        )

    def all_reads(self) -> tuple[Recorder, ...]:
        return (
            self.get_account,
            self.list_movements,
            self.list_current_allocation_sets,
            self.list_categories,
            self.rules.list_rules,
        )


def test_service_refuses_stores_that_do_not_satisfy_the_boundaries() -> None:
    world = World()
    with pytest.raises(TypeError, match="rule_store"):
        FinancialCategorizationService(
            SimpleNamespace(create_rule=Recorder()),  # type: ignore[arg-type]
            SimpleNamespace(get_account=world.get_account),  # type: ignore[arg-type]
            SimpleNamespace(list_movements=world.list_movements),  # type: ignore[arg-type]
            SimpleNamespace(  # type: ignore[arg-type]
                list_current_allocation_sets=world.list_current_allocation_sets
            ),
            SimpleNamespace(list_categories=world.list_categories),  # type: ignore[arg-type]
        )


def test_preview_classifies_every_movement_and_never_writes() -> None:
    category = _category()
    rule = _rule(category)
    matched = _movement("Padaria Pão Quente")
    no_match = _movement("Cinema")
    already = _movement("padaria 2")
    neutral = _movement("padaria 3", effect=FinancialResultEffect.NEUTRAL)
    reversal = _movement(role=FinancialMovementRole.REVERSAL)
    world = World(
        movements=(matched, no_match, already, neutral, reversal),
        classified=(already.id,),
        rules=(rule,),
        categories=(category,),
    )

    preview = world.service().preview(account_id=ACCOUNT_ID, **SCOPE)

    assert preview.total_movements == 5
    assert preview.counts == {
        Status.MATCHED: 1,
        Status.NO_MATCH: 1,
        Status.AMBIGUOUS: 0,
        Status.INELIGIBLE: 2,
        Status.ALREADY_CLASSIFIED: 1,
    }
    # Every Movement is distinguishable, in ledger order; the rule and target are
    # present only where they are semantically valid (MATCHED).
    assert [(i.movement_id, i.status, i.rule_id) for i in preview.items] == [
        (matched.id, Status.MATCHED, rule.id),
        (no_match.id, Status.NO_MATCH, None),
        (already.id, Status.ALREADY_CLASSIFIED, None),
        (neutral.id, Status.INELIGIBLE, None),
        (reversal.id, Status.INELIGIBLE, None),
    ]
    assert [i.target_category_id for i in preview.items] == [
        category.id,
        None,
        None,
        None,
        None,
    ]
    assert not preview.applicable_truncated
    assert world.apply.calls == []
    assert world.rules.create_rule.calls == []
    assert world.rules.disable_rule.calls == []


def test_preview_reads_are_constant_regardless_of_movement_count() -> None:
    category = _category()
    for count in (0, 1, 150):
        world = World(
            movements=tuple(_movement(f"padaria {i}") for i in range(count)),
            rules=(_rule(category),),
            categories=(category,),
        )
        world.service().preview(account_id=ACCOUNT_ID, **SCOPE)
        assert [len(read.calls) for read in world.all_reads()] == [1, 1, 1, 1, 1]


def test_preview_reports_ambiguity_explicitly_and_lists_no_rule() -> None:
    category = _category()
    first, second = _rule(category, priority=5), _rule(category, priority=5)
    movement = _movement()
    world = World(movements=(movement,), rules=(first, second), categories=(category,))
    preview = world.service().preview(account_id=ACCOUNT_ID, **SCOPE)
    assert preview.counts[Status.AMBIGUOUS] == 1 and preview.counts[Status.MATCHED] == 0
    assert preview.items[0].status is Status.AMBIGUOUS
    assert preview.items[0].rule_id is None


def test_preview_ignores_disabled_rules_other_accounts_and_unusable_categories() -> (
    None
):
    usable = _category()
    disabled_category = _category(status=FinancialCategoryStatus.DISABLED)
    rules = (
        _rule(usable, priority=1),
        _rule(usable, priority=99, status=FinancialCategorizationRuleStatus.DISABLED),
        _rule(usable, priority=98, account_id=uuid4()),
        _rule(disabled_category, priority=97),
    )
    world = World(
        movements=(_movement(),), rules=rules, categories=(usable, disabled_category)
    )
    preview = world.service().preview(account_id=ACCOUNT_ID, **SCOPE)
    assert preview.items[0].rule_id == rules[0].id


def test_preview_reports_every_movement_and_flags_when_apply_must_be_split() -> None:
    category = _category()
    total = MAX_APPLY_ITEMS + 25
    world = World(
        movements=tuple(_movement(f"padaria {i}") for i in range(total)),
        rules=(_rule(category),),
        categories=(category,),
    )
    preview = world.service().preview(account_id=ACCOUNT_ID, **SCOPE)
    assert preview.counts[Status.MATCHED] == total
    assert len(preview.items) == total, "no detail limit: every Movement listed"
    assert preview.applicable_truncated


@pytest.mark.parametrize(
    "account",
    [
        _account(owner=uuid4()),
        _account(status=FinancialAccountStatus.ARCHIVED),
    ],
)
def test_only_the_owner_of_an_active_account_can_preview_or_apply(
    account: FinancialAccountRecord,
) -> None:
    world = World(account=account)
    service = world.service()
    with pytest.raises(FinancialCategorizationRuleAccountNotFoundError):
        service.preview(account_id=ACCOUNT_ID, **SCOPE)
    with pytest.raises(FinancialCategorizationRuleAccountNotFoundError):
        service.apply(
            account_id=ACCOUNT_ID,
            items=(CategorizationApplyRequestItem(uuid4(), uuid4()),),
            **SCOPE,
        )
    assert world.apply.calls == []
    assert world.list_movements.calls == []


def _pair() -> CategorizationApplyRequestItem:
    return CategorizationApplyRequestItem(uuid4(), uuid4())


def test_apply_runs_each_confirmed_pair_exactly_once_and_reports_each_result() -> None:
    pairs = [_pair() for _ in range(3)]
    statuses = [Applied.CLASSIFIED, Applied.ALREADY_CLASSIFIED, Applied.CONFLICT]

    def outcome(**kwargs: Any) -> FinancialCategorizationApplyResult:
        status = statuses[[p.movement_id for p in pairs].index(kwargs["movement_id"])]
        return FinancialCategorizationApplyResult(
            movement_id=kwargs["movement_id"],
            status=status,
            rule_id=kwargs["expected_rule_id"],
            allocation_set_id=uuid4() if status is Applied.CLASSIFIED else None,
        )

    calls: list[dict[str, Any]] = []

    def apply(**kwargs: Any) -> FinancialCategorizationApplyResult:
        calls.append(kwargs)
        return outcome(**kwargs)

    world = World(apply=apply)  # type: ignore[arg-type]
    result = world.service().apply(account_id=ACCOUNT_ID, items=pairs, **SCOPE)

    assert [c["movement_id"] for c in calls] == [p.movement_id for p in pairs]
    assert [c["expected_rule_id"] for c in calls] == [p.rule_id for p in pairs]
    assert result.requested == 3
    assert [r.status for r in result.results] == statuses
    assert result.counts[Applied.CLASSIFIED] == 1
    assert result.counts[Applied.CONFLICT] == 1
    # A partial result is visibly not "everything classified".
    assert result.counts[Applied.CLASSIFIED] != result.requested


def test_apply_never_retries_and_isolates_a_failing_pair() -> None:
    pairs = [_pair() for _ in range(3)]
    calls: list[UUID] = []

    def apply(**kwargs: Any) -> FinancialCategorizationApplyResult:
        calls.append(kwargs["movement_id"])
        if kwargs["movement_id"] == pairs[1].movement_id:
            raise FinancialCategorizationRulePersistenceError("boom")
        return FinancialCategorizationApplyResult(
            movement_id=kwargs["movement_id"], status=Applied.NO_MATCH
        )

    world = World(apply=apply)  # type: ignore[arg-type]
    result = world.service().apply(account_id=ACCOUNT_ID, items=pairs, **SCOPE)

    assert calls == [p.movement_id for p in pairs]  # one attempt each, no retry
    assert [r.status for r in result.results] == [
        Applied.NO_MATCH,
        Applied.FAILED,
        Applied.NO_MATCH,
    ]
    assert result.counts[Applied.FAILED] == 1


def test_apply_aborts_on_access_failures_instead_of_masking_them() -> None:
    for error in (
        FinancialCategorizationRuleAccessError("denied"),
        FinancialCategorizationRuleAccountNotFoundError("gone"),
    ):
        world = World(apply=Recorder(error=error))
        with pytest.raises(type(error)):
            world.service().apply(
                account_id=ACCOUNT_ID, items=[_pair(), _pair()], **SCOPE
            )
        assert len(world.apply.calls) == 1


def test_apply_validates_the_request_shape() -> None:
    world = World()
    service = world.service()
    with pytest.raises(ValueError):
        service.apply(account_id=ACCOUNT_ID, items=[], **SCOPE)
    with pytest.raises(ValueError):
        service.apply(
            account_id=ACCOUNT_ID,
            items=[_pair() for _ in range(MAX_APPLY_ITEMS + 1)],
            **SCOPE,
        )
    movement_id = uuid4()
    with pytest.raises(ValueError):
        service.apply(
            account_id=ACCOUNT_ID,
            items=[
                CategorizationApplyRequestItem(movement_id, uuid4()),
                CategorizationApplyRequestItem(movement_id, uuid4()),
            ],
            **SCOPE,
        )
    assert world.apply.calls == []
