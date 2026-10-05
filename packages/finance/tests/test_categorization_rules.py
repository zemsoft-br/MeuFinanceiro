from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from meufinanceiro_finance import (
    FinancialCategorizationEvaluationStatus as Status,
)
from meufinanceiro_finance import (
    FinancialCategorizationMatcher,
    FinancialCategorizationRuleDraft,
    FinancialCategorizationRuleRecord,
    FinancialCategorizationRuleStatus,
    FinancialCategoryRecord,
    FinancialCategoryStatus,
    FinancialMovementRecord,
    FinancialMovementRole,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    categorization_apply_idempotency_key,
    evaluate_movement_categorization,
    normalize_categorization_text,
    usable_categorization_rules,
    validate_financial_idempotency_key,
)

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
_ACCOUNT = uuid4()
_OWNER = uuid4()
_RESIDENCE = uuid4()


def _movement(
    description: str | None = "Padaria Pão Quente",
    *,
    amount: str = "-10.00",
    effect: FinancialResultEffect = FinancialResultEffect.EXPENSE,
    role: FinancialMovementRole = FinancialMovementRole.STANDARD,
    account_id: UUID = _ACCOUNT,
) -> FinancialMovementRecord:
    reversal = role is FinancialMovementRole.REVERSAL
    return FinancialMovementRecord(
        id=uuid4(),
        account_id=account_id,
        amount=Money(Decimal(amount), "BRL"),
        result_effect=effect,
        role=role,
        effective_date=date(2026, 10, 1),
        competence_date=date(2026, 10, 1),
        description=None if reversal else description,
        reversal_of_id=uuid4() if reversal else None,
        reversal_reason="motivo" if reversal else None,
        created_by_operator_id=_OWNER,
        created_at=_NOW,
    )


def _rule(
    pattern: str = "padaria",
    *,
    matcher: FinancialCategorizationMatcher = FinancialCategorizationMatcher.CONTAINS,
    priority: int = 10,
    account_id: UUID | None = None,
    effect: FinancialResultEffect | None = None,
    status: FinancialCategorizationRuleStatus = FinancialCategorizationRuleStatus.ACTIVE,
    category_id: UUID | None = None,
) -> FinancialCategorizationRuleRecord:
    disabled = status is FinancialCategorizationRuleStatus.DISABLED
    return FinancialCategorizationRuleRecord(
        id=uuid4(),
        residence_id=_RESIDENCE,
        created_by_operator_id=_OWNER,
        account_id=account_id,
        result_effect=effect,
        description_matcher=matcher,
        description_pattern=pattern,
        target_category_id=category_id or uuid4(),
        priority=priority,
        status=status,
        created_at=_NOW,
        disabled_at=_NOW if disabled else None,
        disabled_by_operator_id=_OWNER if disabled else None,
    )


def _category(
    category_id: UUID,
    *,
    scope: FinancialVisibilityScope = FinancialVisibilityScope.HOUSEHOLD,
    owner: UUID = _OWNER,
    status: FinancialCategoryStatus = FinancialCategoryStatus.ACTIVE,
) -> FinancialCategoryRecord:
    disabled = status is FinancialCategoryStatus.DISABLED
    return FinancialCategoryRecord(
        id=category_id,
        residence_id=_RESIDENCE,
        owner_operator_id=owner,
        visibility_scope=scope,
        parent_id=None,
        name="Categoria",
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
        disabled_at=_NOW if disabled else None,
    )


def _evaluate(movement, rules, *, classified: bool = False):
    return evaluate_movement_categorization(
        movement, already_classified=classified, rules=tuple(rules)
    )


# --- normalization ---------------------------------------------------------


def test_normalization_trims_unicode_whitespace_and_casefolds() -> None:
    assert normalize_categorization_text(" \t PADARIA  ") == "padaria"
    assert normalize_categorization_text("Straße") == normalize_categorization_text(
        "STRASSE"
    )


def test_normalization_does_not_strip_accents_punctuation_or_inner_spacing() -> None:
    assert normalize_categorization_text("Pão  Quente!") == "pão  quente!"
    assert normalize_categorization_text("pao") != normalize_categorization_text("pão")


def test_normalization_composes_canonically_equivalent_text() -> None:
    assert normalize_categorization_text("Pão") == normalize_categorization_text("Pão")


def test_normalization_rejects_non_text() -> None:
    with pytest.raises(TypeError):
        normalize_categorization_text(b"x")  # type: ignore[arg-type]


# --- drafts and records ----------------------------------------------------


def test_draft_trims_and_preserves_case_and_accents_for_ux() -> None:
    draft = FinancialCategorizationRuleDraft(
        description_matcher=FinancialCategorizationMatcher.EXACT,
        description_pattern="  Padaria Pão  ",
        target_category_id=uuid4(),
        priority=5,
    )
    assert draft.description_pattern == "Padaria Pão"
    assert draft.account_id is None and draft.result_effect is None


@pytest.mark.parametrize("pattern", ["", "   ", "a\nb", "x" * 257, "tab\there"])
def test_draft_rejects_invalid_patterns(pattern: str) -> None:
    with pytest.raises(ValueError):
        FinancialCategorizationRuleDraft(
            description_matcher=FinancialCategorizationMatcher.EXACT,
            description_pattern=pattern,
            target_category_id=uuid4(),
            priority=5,
        )


@pytest.mark.parametrize("priority", [0, -1, 1001])
def test_draft_rejects_out_of_range_priority(priority: int) -> None:
    with pytest.raises(ValueError, match="priority"):
        FinancialCategorizationRuleDraft(
            description_matcher=FinancialCategorizationMatcher.EXACT,
            description_pattern="x",
            target_category_id=uuid4(),
            priority=priority,
        )


@pytest.mark.parametrize("priority", [True, 1.5, "10"])
def test_draft_rejects_non_integer_priority(priority: object) -> None:
    with pytest.raises(TypeError, match="priority"):
        FinancialCategorizationRuleDraft(
            description_matcher=FinancialCategorizationMatcher.EXACT,
            description_pattern="x",
            target_category_id=uuid4(),
            priority=priority,  # type: ignore[arg-type]
        )


def test_draft_rejects_neutral_effect_and_non_v4_ids() -> None:
    with pytest.raises(ValueError, match="INCOME or EXPENSE"):
        FinancialCategorizationRuleDraft(
            description_matcher=FinancialCategorizationMatcher.EXACT,
            description_pattern="x",
            target_category_id=uuid4(),
            priority=1,
            result_effect=FinancialResultEffect.NEUTRAL,
        )
    with pytest.raises(ValueError):
        FinancialCategorizationRuleDraft(
            description_matcher=FinancialCategorizationMatcher.EXACT,
            description_pattern="x",
            target_category_id=UUID(int=1),
            priority=1,
        )


def test_draft_material_is_stable_and_sensitive_to_every_condition() -> None:
    category_id, account_id = uuid4(), uuid4()

    def build(**override: object) -> FinancialCategorizationRuleDraft:
        values: dict[str, object] = {
            "description_matcher": FinancialCategorizationMatcher.CONTAINS,
            "description_pattern": "Padaria",
            "target_category_id": category_id,
            "priority": 10,
            "account_id": account_id,
            "result_effect": FinancialResultEffect.EXPENSE,
        }
        values.update(override)
        return FinancialCategorizationRuleDraft(**values)  # type: ignore[arg-type]

    base = build().canonical_material()
    assert base == build().canonical_material()
    for override in (
        {"description_matcher": FinancialCategorizationMatcher.EXACT},
        {"description_pattern": "PADARIA"},
        {"target_category_id": uuid4()},
        {"priority": 11},
        {"account_id": None},
        {"result_effect": None},
    ):
        assert build(**override).canonical_material() != base


def test_record_enforces_disable_shape() -> None:
    with pytest.raises(ValueError, match="active rule"):
        FinancialCategorizationRuleRecord(
            id=uuid4(),
            residence_id=_RESIDENCE,
            created_by_operator_id=_OWNER,
            account_id=None,
            result_effect=None,
            description_matcher=FinancialCategorizationMatcher.EXACT,
            description_pattern="x",
            target_category_id=uuid4(),
            priority=1,
            status=FinancialCategorizationRuleStatus.ACTIVE,
            created_at=_NOW,
            disabled_at=_NOW,
            disabled_by_operator_id=None,
        )
    with pytest.raises(ValueError, match="disabled rule"):
        FinancialCategorizationRuleRecord(
            id=uuid4(),
            residence_id=_RESIDENCE,
            created_by_operator_id=_OWNER,
            account_id=None,
            result_effect=None,
            description_matcher=FinancialCategorizationMatcher.EXACT,
            description_pattern="x",
            target_category_id=uuid4(),
            priority=1,
            status=FinancialCategorizationRuleStatus.DISABLED,
            created_at=_NOW,
            disabled_at=None,
            disabled_by_operator_id=None,
        )


def test_reprs_do_not_leak_patterns_or_identities() -> None:
    rule = _rule("segredo-do-usuario")
    assert "segredo" not in repr(rule)
    assert str(rule.id) not in repr(rule)
    draft = FinancialCategorizationRuleDraft(
        description_matcher=FinancialCategorizationMatcher.EXACT,
        description_pattern="segredo-do-usuario",
        target_category_id=uuid4(),
        priority=1,
    )
    assert "segredo" not in repr(draft)


# --- matching --------------------------------------------------------------


def test_exact_compares_the_whole_normalized_description() -> None:
    movement = _movement("  PADARIA pão quente ")
    exact = _rule("Padaria Pão Quente", matcher=FinancialCategorizationMatcher.EXACT)
    assert _evaluate(movement, [exact]).status is Status.MATCHED
    assert (
        _evaluate(
            movement,
            [_rule("padaria", matcher=FinancialCategorizationMatcher.EXACT)],
        ).status
        is Status.NO_MATCH
    )


def test_contains_is_a_normalized_substring_test() -> None:
    movement = _movement("COMPRA Padaria Pão Quente 123")
    assert _evaluate(movement, [_rule("  pão QUENTE ")]).status is Status.MATCHED
    assert _evaluate(movement, [_rule("pao quente")]).status is Status.NO_MATCH
    assert _evaluate(movement, [_rule("Pão  Quente")]).status is Status.NO_MATCH


def test_account_and_effect_filters_are_optional_and_exact() -> None:
    movement = _movement()
    other_account = uuid4()
    assert _evaluate(movement, [_rule(account_id=_ACCOUNT)]).status is Status.MATCHED
    assert (
        _evaluate(movement, [_rule(account_id=other_account)]).status is Status.NO_MATCH
    )
    assert (
        _evaluate(movement, [_rule(effect=FinancialResultEffect.EXPENSE)]).status
        is Status.MATCHED
    )
    assert (
        _evaluate(movement, [_rule(effect=FinancialResultEffect.INCOME)]).status
        is Status.NO_MATCH
    )


def test_disabled_rules_never_participate() -> None:
    disabled = _rule(status=FinancialCategorizationRuleStatus.DISABLED, priority=999)
    assert _evaluate(_movement(), [disabled]).status is Status.NO_MATCH
    active = _rule(priority=1)
    result = _evaluate(_movement(), [disabled, active])
    assert result.status is Status.MATCHED and result.rule == active


# --- priority and ambiguity ------------------------------------------------


def test_highest_priority_wins_when_unique() -> None:
    low, high = _rule(priority=1), _rule(priority=2)
    result = _evaluate(_movement(), [low, high])
    assert result.status is Status.MATCHED and result.rule == high
    assert _evaluate(_movement(), [high, low]).rule == high


def test_tie_on_highest_priority_is_ambiguous_regardless_of_order_or_target() -> None:
    first, second = _rule(priority=5), _rule(priority=5)
    lower = _rule(priority=4)
    for rules in ([first, second, lower], [lower, second, first]):
        result = _evaluate(_movement(), rules)
        assert result.status is Status.AMBIGUOUS and result.rule is None


def test_identical_rules_with_same_target_still_tie() -> None:
    category_id = uuid4()
    rules = [_rule(priority=5, category_id=category_id) for _ in range(2)]
    assert _evaluate(_movement(), rules).status is Status.AMBIGUOUS


def test_tie_below_the_top_priority_is_not_ambiguous() -> None:
    top = _rule(priority=9)
    rules = [top, _rule(priority=3), _rule(priority=3)]
    assert _evaluate(_movement(), rules).rule == top


# --- eligibility and classification state ----------------------------------


@pytest.mark.parametrize(
    "movement",
    [
        _movement(amount="10", effect=FinancialResultEffect.NEUTRAL),
        _movement(
            effect=FinancialResultEffect.EXPENSE, role=FinancialMovementRole.REVERSAL
        ),
        _movement(
            amount="10",
            effect=FinancialResultEffect.INCOME,
            role=FinancialMovementRole.REVERSAL,
        ),
    ],
)
def test_neutral_and_reversal_movements_are_ineligible(movement) -> None:
    assert _evaluate(movement, [_rule()]).status is Status.INELIGIBLE
    assert _evaluate(movement, [_rule()], classified=True).status is Status.INELIGIBLE


def test_an_existing_classification_is_never_re_evaluated() -> None:
    result = _evaluate(_movement(), [_rule()], classified=True)
    assert result.status is Status.ALREADY_CLASSIFIED and result.rule is None


def test_income_and_expense_keep_their_own_sign_semantics() -> None:
    income = _movement("Salário", amount="1000", effect=FinancialResultEffect.INCOME)
    rule = _rule("salário", effect=FinancialResultEffect.INCOME)
    assert _evaluate(income, [rule]).status is Status.MATCHED
    assert _evaluate(_movement("Salário"), [rule]).status is Status.NO_MATCH


# --- category usability ----------------------------------------------------


def test_rules_with_unusable_categories_are_discarded_before_resolution() -> None:
    household, disabled_target = uuid4(), uuid4()
    categories = {
        household: _category(household),
        disabled_target: _category(
            disabled_target, status=FinancialCategoryStatus.DISABLED
        ),
    }
    winner_by_priority = _rule(priority=50, category_id=disabled_target)
    usable = _rule(priority=1, category_id=household)
    unknown = _rule(priority=70, category_id=uuid4())

    kept = usable_categorization_rules(
        [winner_by_priority, usable, unknown],
        categories=categories,
        account_visibility_scope=FinancialVisibilityScope.PERSONAL,
        account_owner_operator_id=_OWNER,
    )
    assert kept == (usable,)
    assert _evaluate(_movement(), kept).rule == usable


def test_personal_category_of_another_owner_is_never_a_valid_target() -> None:
    other_owner, mine, theirs = uuid4(), uuid4(), uuid4()
    categories = {
        mine: _category(mine, scope=FinancialVisibilityScope.PERSONAL, owner=_OWNER),
        theirs: _category(
            theirs, scope=FinancialVisibilityScope.PERSONAL, owner=other_owner
        ),
    }
    rules = [_rule(category_id=mine), _rule(category_id=theirs)]
    personal = usable_categorization_rules(
        rules,
        categories=categories,
        account_visibility_scope=FinancialVisibilityScope.PERSONAL,
        account_owner_operator_id=_OWNER,
    )
    assert [rule.target_category_id for rule in personal] == [mine]
    household_account = usable_categorization_rules(
        rules,
        categories=categories,
        account_visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        account_owner_operator_id=_OWNER,
    )
    assert household_account == ()


# --- derived idempotency ---------------------------------------------------


def test_apply_key_is_deterministic_v4_and_pair_specific() -> None:
    rule_id, movement_id = uuid4(), uuid4()
    key = categorization_apply_idempotency_key(rule_id, movement_id)
    assert key == categorization_apply_idempotency_key(rule_id, movement_id)
    assert validate_financial_idempotency_key(key) == key
    assert key != categorization_apply_idempotency_key(movement_id, rule_id)
    assert key != categorization_apply_idempotency_key(rule_id, uuid4())
    assert key != categorization_apply_idempotency_key(uuid4(), movement_id)
