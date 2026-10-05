from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from meufinanceiro_finance import (
    PENDING_PAGE_LIMIT_MAX,
    FinancialAccountStatus,
    FinancialCategorizationEvaluationStatus,
    FinancialCategorizationMatcher,
    FinancialCategorizationRuleRecord,
    FinancialCategorizationRuleStatus,
    FinancialCategoryRecord,
    FinancialCategoryStatus,
    FinancialMovementRecord,
    FinancialMovementRole,
    FinancialPendingCursorError,
    FinancialPendingMovementCandidate,
    FinancialPendingMovementCandidatePage,
    FinancialPendingMovementItem,
    FinancialPendingMovementKey,
    FinancialPendingRuleStatus,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    decode_pending_cursor,
    encode_pending_cursor,
    evaluate_movement_categorization,
    evaluate_pending_candidates,
    pending_filter_fingerprint,
    usable_categorization_rules,
)

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
_OWNER = uuid4()
_OTHER = uuid4()
_RESIDENCE = uuid4()
_ACCOUNT = uuid4()
_FP = pending_filter_fingerprint(account_id=None, result_effect=None, rule_status=None)


def _movement(
    description: str = "Padaria Pão Quente",
    *,
    account_id: UUID = _ACCOUNT,
    amount: str = "-10.00",
    effect: FinancialResultEffect = FinancialResultEffect.EXPENSE,
) -> FinancialMovementRecord:
    return FinancialMovementRecord(
        id=uuid4(),
        account_id=account_id,
        amount=Money(Decimal(amount), "BRL"),
        result_effect=effect,
        role=FinancialMovementRole.STANDARD,
        effective_date=date(2026, 10, 1),
        competence_date=date(2026, 10, 1),
        description=description,
        reversal_of_id=None,
        reversal_reason=None,
        created_by_operator_id=_OWNER,
        created_at=_NOW,
    )


def _candidate(
    description: str = "Padaria Pão Quente",
    *,
    account_id: UUID = _ACCOUNT,
    owner: UUID = _OWNER,
    scope: FinancialVisibilityScope = FinancialVisibilityScope.HOUSEHOLD,
    status: FinancialAccountStatus = FinancialAccountStatus.ACTIVE,
    effect: FinancialResultEffect = FinancialResultEffect.EXPENSE,
    amount: str = "-10.00",
) -> FinancialPendingMovementCandidate:
    return FinancialPendingMovementCandidate(
        movement=_movement(
            description, account_id=account_id, effect=effect, amount=amount
        ),
        account_visibility_scope=scope,
        account_owner_operator_id=owner,
        account_status=status,
    )


def _rule(
    pattern: str = "padaria",
    *,
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
        description_matcher=FinancialCategorizationMatcher.CONTAINS,
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


def _categories(
    *rules: FinancialCategorizationRuleRecord,
) -> dict[UUID, FinancialCategoryRecord]:
    return {
        rule.target_category_id: _category(rule.target_category_id) for rule in rules
    }


def _statuses(candidates, rules, categories, operator=_OWNER):
    return [
        item.rule_status
        for item in evaluate_pending_candidates(
            candidates, operator_id=operator, rules=rules, categories=categories
        )
    ]


Status = FinancialPendingRuleStatus


# --- evaluation ------------------------------------------------------------


def test_matched_ambiguous_and_no_match_are_derived() -> None:
    single = _rule("padaria", priority=5)
    tie_a, tie_b = _rule("mercado", priority=7), _rule("mercado", priority=7)
    rules = [single, tie_a, tie_b]
    categories = _categories(*rules)

    items = evaluate_pending_candidates(
        [_candidate("Padaria X"), _candidate("Mercado Y"), _candidate("Cinema")],
        operator_id=_OWNER,
        rules=rules,
        categories=categories,
    )
    assert [item.rule_status for item in items] == [
        Status.MATCHED,
        Status.AMBIGUOUS,
        Status.NO_MATCH,
    ]
    matched, ambiguous, none = items
    assert matched.rule is single
    assert ambiguous.rule is None and none.rule is None


def test_highest_priority_wins_and_a_tie_on_top_is_ambiguous() -> None:
    low, high = _rule("padaria", priority=1), _rule("padaria", priority=9)
    items = evaluate_pending_candidates(
        [_candidate()],
        operator_id=_OWNER,
        rules=[low, high],
        categories=_categories(low, high),
    )
    assert items[0].rule is high

    twin = _rule("padaria", priority=9)
    assert _statuses(
        [_candidate()], [low, high, twin], _categories(low, high, twin)
    ) == [Status.AMBIGUOUS]


def test_disabled_rule_or_category_changes_the_derived_result() -> None:
    rule = _rule("padaria")
    rules = [rule]
    assert _statuses([_candidate()], rules, _categories(rule)) == [Status.MATCHED]

    disabled_rule = _rule("padaria", status=FinancialCategorizationRuleStatus.DISABLED)
    assert _statuses([_candidate()], [disabled_rule], _categories(disabled_rule)) == [
        Status.NO_MATCH
    ]

    categories = {
        rule.target_category_id: _category(
            rule.target_category_id, status=FinancialCategoryStatus.DISABLED
        )
    }
    assert _statuses([_candidate()], rules, categories) == [Status.NO_MATCH]
    assert _statuses([_candidate()], rules, {}) == [Status.NO_MATCH]

    # A disabled competitor never forms a tie.
    twin = _rule("padaria", status=FinancialCategorizationRuleStatus.DISABLED)
    assert _statuses([_candidate()], [rule, twin], _categories(rule, twin)) == [
        Status.MATCHED
    ]


def test_category_audience_decides_which_rules_compete() -> None:
    private = _rule("padaria")
    categories = {
        private.target_category_id: _category(
            private.target_category_id,
            scope=FinancialVisibilityScope.PERSONAL,
            owner=_OTHER,
        )
    }
    # A PERSONAL category of someone else is never a valid target.
    assert _statuses([_candidate()], [private], categories) == [Status.NO_MATCH]


def test_account_and_effect_scoped_rules_only_apply_where_they_match() -> None:
    other_account = uuid4()
    scoped = _rule("padaria", account_id=other_account)
    income_only = _rule("padaria", effect=FinancialResultEffect.INCOME, priority=50)
    rules = [scoped, income_only]
    assert _statuses([_candidate()], rules, _categories(*rules)) == [Status.NO_MATCH]
    assert _statuses(
        [_candidate(account_id=other_account)], rules, _categories(*rules)
    ) == [Status.MATCHED]


def test_evaluation_is_the_same_pipeline_as_preview_and_apply() -> None:
    """Pending status == usable rules + evaluate_movement_categorization."""
    rules = [
        _rule("padaria", priority=3),
        _rule("padaria", priority=3),
        _rule("mercado", priority=1),
        _rule("cinema", priority=1, status=FinancialCategorizationRuleStatus.DISABLED),
        _rule("padaria", account_id=uuid4(), priority=99),
    ]
    categories = _categories(*rules)
    expected_map = {
        FinancialCategorizationEvaluationStatus.MATCHED: Status.MATCHED,
        FinancialCategorizationEvaluationStatus.AMBIGUOUS: Status.AMBIGUOUS,
        FinancialCategorizationEvaluationStatus.NO_MATCH: Status.NO_MATCH,
    }
    candidates = [
        _candidate(text) for text in ("padaria", "mercado", "cinema", "outra coisa")
    ]
    usable = usable_categorization_rules(
        [r for r in rules if r.is_active and r.account_id in (None, _ACCOUNT)],
        categories=categories,
        account_visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        account_owner_operator_id=_OWNER,
    )
    for candidate, item in zip(
        candidates,
        evaluate_pending_candidates(
            candidates, operator_id=_OWNER, rules=rules, categories=categories
        ),
        strict=True,
    ):
        direct = evaluate_movement_categorization(
            candidate.movement, already_classified=False, rules=usable
        )
        assert item.rule_status is expected_map[direct.status]
        assert item.rule == direct.rule


def test_can_classify_requires_owning_an_active_account() -> None:
    owned = _candidate()
    assert owned.can_classify(_OWNER)
    assert not owned.can_classify(_OTHER)
    archived = _candidate(status=FinancialAccountStatus.ARCHIVED)
    assert not archived.can_classify(_OWNER)

    rule = _rule("padaria")
    items = evaluate_pending_candidates(
        [owned, archived],
        operator_id=_OTHER,
        rules=[rule],
        categories=_categories(rule),
    )
    assert [item.can_classify for item in items] == [False, False]
    # A read-only viewer still sees the derived suggestion state.
    assert [item.rule_status for item in items] == [Status.MATCHED, Status.MATCHED]


def test_rules_are_filtered_once_per_account_not_per_movement() -> None:
    rule = _rule("padaria")
    categories = _categories(rule)

    class CountingRules(list):  # type: ignore[type-arg]
        iterations = 0

        def __iter__(self):  # type: ignore[no-untyped-def]
            CountingRules.iterations += 1
            return super().__iter__()

    rules = CountingRules([rule])
    evaluate_pending_candidates(
        [_candidate() for _ in range(200)],
        operator_id=_OWNER,
        rules=rules,
        categories=categories,
    )
    assert CountingRules.iterations == 1


def test_item_and_page_contracts_fail_closed() -> None:
    candidate = _candidate()
    rule = _rule()
    with pytest.raises(ValueError):
        FinancialPendingMovementItem(candidate, Status.MATCHED, None, True)
    with pytest.raises(ValueError):
        FinancialPendingMovementItem(candidate, Status.AMBIGUOUS, rule, True)
    with pytest.raises(ValueError):
        FinancialPendingMovementCandidatePage((), has_more=True)
    with pytest.raises(ValueError):
        FinancialPendingMovementCandidatePage(
            (candidate,) * (PENDING_PAGE_LIMIT_MAX + 1), has_more=False
        )


# --- cursor ----------------------------------------------------------------


def _key() -> FinancialPendingMovementKey:
    return FinancialPendingMovementKey(date(2026, 9, 30), uuid4())


def test_cursor_round_trips_and_is_opaque() -> None:
    key = _key()
    cursor = encode_pending_cursor(key, fingerprint=_FP)
    assert decode_pending_cursor(cursor, fingerprint=_FP) == key
    assert "=" not in cursor and "/" not in cursor and "+" not in cursor
    assert str(key.movement_id) not in cursor and "2026" not in cursor


def test_cursor_is_bound_to_its_filter_set() -> None:
    key = _key()
    cursor = encode_pending_cursor(key, fingerprint=_FP)
    other = pending_filter_fingerprint(
        account_id=uuid4(), result_effect=None, rule_status=None
    )
    with pytest.raises(FinancialPendingCursorError):
        decode_pending_cursor(cursor, fingerprint=other)
    distinct = {
        pending_filter_fingerprint(
            account_id=None, result_effect=effect, rule_status=status
        )
        for effect in (None, *FinancialResultEffect)
        for status in (None, *FinancialPendingRuleStatus)
    }
    assert len(distinct) == 4 * 4


def _forge(payload: object) -> str:
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "!!!",
        "a" * 300,
        "not base64 at all",
        "e30",  # {}
        "bnVsbA",  # null
        "W10",  # []
        _forge({"v": 1, "d": "2026-09-30", "i": str(uuid4())}),  # no fingerprint
        _forge({"v": 2, "d": "2026-09-30", "i": str(uuid4()), "f": _FP}),
        _forge({"v": True, "d": "2026-09-30", "i": str(uuid4()), "f": _FP}),
        _forge({"v": 1, "d": "2026-9-30", "i": str(uuid4()), "f": _FP}),
        _forge({"v": 1, "d": "2026-13-45", "i": str(uuid4()), "f": _FP}),
        _forge({"v": 1, "d": "2026-09-30", "i": "not-a-uuid", "f": _FP}),
        _forge({"v": 1, "d": "2026-09-30", "i": str(uuid4()).upper(), "f": _FP}),
        _forge(
            {
                "v": 1,
                "d": "2026-09-30",
                "i": "00000000-0000-1000-8000-000000000000",
                "f": _FP,
            }
        ),
        _forge({"v": 1, "d": "2026-09-30", "i": str(uuid4()), "f": _FP, "x": 1}),
        _forge({"v": 1, "d": 20260930, "i": str(uuid4()), "f": _FP}),
    ],
)
def test_malformed_cursors_fail_closed(bad: str) -> None:
    with pytest.raises(FinancialPendingCursorError):
        decode_pending_cursor(bad, fingerprint=_FP)


def test_cursor_decoding_never_raises_anything_else() -> None:
    for junk in ("A", "AAAA", "e30=", "_-_-", "\x00", "ñ", "e" * 255, None, 7):
        with pytest.raises(FinancialPendingCursorError):
            decode_pending_cursor(junk, fingerprint=_FP)  # type: ignore[arg-type]
