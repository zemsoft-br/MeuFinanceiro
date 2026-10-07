"""PostgreSQL-backed proofs for assisted recurrence suggestions (ADR-0028).

Everything runs through the non-superuser runtime role with forced RLS. A suggestion
is derived and never stored: these proofs also show that reading writes nothing, and
that accepting creates exactly one recurrence and no Movement or occurrence.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialRecurrenceDraft,
    FinancialRecurrenceRealizationDraft,
    FinancialRecurrenceSuggestion,
    FinancialRecurrenceSuggestionAcceptance,
    FinancialRecurrenceSuggestionAmountBehavior,
    FinancialRecurrenceSuggestionDecision,
    FinancialRecurrenceWindow,
    FinancialResultEffect,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import delete, event, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

import meufinanceiro_persistence.financial_recurrence_suggestion_store as store_module
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementStore,
    _set_context,
)
from meufinanceiro_persistence.financial_recurrence_schema import (
    financial_recurrence_occurrences,
    financial_recurrence_revisions,
    financial_recurrences,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceAccessError,
    FinancialRecurrenceConflictError,
    FinancialRecurrenceStore,
)
from meufinanceiro_persistence.financial_recurrence_suggestion_schema import (
    financial_recurrence_suggestion_decisions,
)
from meufinanceiro_persistence.financial_recurrence_suggestion_store import (
    FinancialRecurrenceSuggestionConflictError,
    FinancialRecurrenceSuggestionLimitError,
    FinancialRecurrenceSuggestionNotAvailableError,
    FinancialRecurrenceSuggestionNotEditableError,
    FinancialRecurrenceSuggestionStore,
)

if TYPE_CHECKING:
    from conftest import BudgetWorld

_TODAY = date(2026, 10, 20)
_DECISIONS = financial_recurrence_suggestion_decisions


def _store(world: BudgetWorld) -> FinancialRecurrenceSuggestionStore:
    return FinancialRecurrenceSuggestionStore(world.runtime)


def _expense(
    world: BudgetWorld,
    account_id: UUID,
    when: date,
    amount: str = "39.90",
    description: str = "Streaming",
    *,
    operator_id: UUID | None = None,
) -> UUID:
    return (
        FinancialMovementStore(world.runtime)
        .create_movement(
            **world.scope(operator_id),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementDraft(
                account_id=account_id,
                amount=Money(-Decimal(amount), "BRL"),
                result_effect=FinancialResultEffect.EXPENSE,
                effective_date=when,
                competence_date=when,
                description=description,
            ),
        )
        .id
    )


def _streaming(
    world: BudgetWorld,
    account_id: UUID,
    months: tuple[int, ...] = (8, 9, 10),
    description: str = "Streaming",
    amount: str = "39.90",
) -> list[UUID]:
    return [
        _expense(world, account_id, date(2026, month, 10), amount, description)
        for month in months
    ]


def _list(
    world: BudgetWorld, operator_id: UUID | None = None, **scope: Any
) -> tuple[FinancialRecurrenceSuggestion, ...]:
    return _store(world).list_suggestions(
        **world.scope(operator_id, **scope), today=_TODAY
    )


def _count(world: BudgetWorld, table: Any) -> int:
    with world.engine.begin() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    assert isinstance(value, int)
    return value


def _acceptance(**overrides: Any) -> FinancialRecurrenceSuggestionAcceptance:
    values: dict[str, Any] = {
        "description": "Streaming",
        "expected_amount": Decimal("39.90"),
        "start_date": date(2026, 11, 10),
        "day_of_month": 10,
        "end_date": None,
    }
    values.update(overrides)
    return FinancialRecurrenceSuggestionAcceptance(**values)


def _accept(
    world: BudgetWorld,
    suggestion: FinancialRecurrenceSuggestion,
    *,
    key: UUID | None = None,
    operator_id: UUID | None = None,
    **overrides: Any,
) -> Any:
    return _store(world).accept(
        **world.scope(operator_id),
        fingerprint=suggestion.fingerprint,
        idempotency_key=key or new_financial_idempotency_key(),
        acceptance=_acceptance(**overrides),
        today=_TODAY,
    )


def _dismiss(
    world: BudgetWorld, fingerprint: str, operator_id: UUID | None = None
) -> Any:
    return _store(world).dismiss(
        **world.scope(operator_id), fingerprint=fingerprint, today=_TODAY
    )


def _world_counts(world: BudgetWorld) -> tuple[int, ...]:
    return tuple(
        _count(world, table)
        for table in (
            financial_movements,
            financial_recurrences,
            financial_recurrence_revisions,
            financial_recurrence_occurrences,
            _DECISIONS,
        )
    )


# --- detection ------------------------------------------------------------------


def test_three_consecutive_months_are_suggested_with_their_evidence(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    ids = _streaming(budget_world, account)

    (suggestion,) = _list(budget_world)

    assert suggestion.account_id == account and suggestion.currency == "BRL"
    assert suggestion.description == "Streaming"
    assert suggestion.suggested_day_of_month == 10
    assert suggestion.suggested_expected_amount == Money(Decimal("39.90"), "BRL")
    assert suggestion.movement_ids == tuple(ids)
    assert suggestion.observed_dates == (
        date(2026, 8, 10),
        date(2026, 9, 10),
        date(2026, 10, 10),
    )
    assert (
        suggestion.amount_behavior is FinancialRecurrenceSuggestionAmountBehavior.FIXED
    )
    assert suggestion.can_accept(budget_world.owner_id)
    assert not suggestion.can_accept(budget_world.member_id)


def test_reading_suggestions_never_writes(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    before = _world_counts(budget_world)
    for _ in range(3):
        assert len(_list(budget_world)) == 1
        assert len(_list(budget_world, budget_world.member_id)) == 1
    assert _world_counts(budget_world) == before
    assert before[1:] == (0, 0, 0, 0)  # no recurrence, revision, occurrence, decision


def test_two_months_a_gap_and_a_duplicate_month_are_not_suggested(
    budget_world: BudgetWorld,
) -> None:
    two = budget_world.account()
    _streaming(budget_world, two, (9, 10))
    gap = budget_world.account(name="Gap")
    _streaming(budget_world, gap, (7, 9, 10))
    duplicate = budget_world.account(name="Duplicate")
    _streaming(budget_world, duplicate)
    _expense(budget_world, duplicate, date(2026, 10, 15))
    assert _list(budget_world) == ()


def test_normalization_groups_equal_text_and_keeps_similar_text_apart(
    budget_world: BudgetWorld,
) -> None:
    grouped = budget_world.account(name="Grouped")
    for month, description in (
        (8, "Streaming"),
        (9, "  STREAMING"),
        (10, "streaming "),
    ):
        _expense(budget_world, grouped, date(2026, month, 10), description=description)
    similar = budget_world.account(name="Similar")
    for month, description in ((8, "Streaming"), (9, "Streaming+"), (10, "Streamingg")):
        _expense(budget_world, similar, date(2026, month, 10), description=description)

    suggestions = _list(budget_world)

    assert [s.account_id for s in suggestions] == [grouped]
    assert suggestions[0].normalized_description == "streaming"


def test_variable_amounts_and_the_last_value_are_exposed(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    for month, amount in ((8, "100.00"), (9, "120.50"), (10, "110.25")):
        _expense(budget_world, account, date(2026, month, 10), amount)

    (suggestion,) = _list(budget_world)

    assert (
        suggestion.amount_behavior
        is FinancialRecurrenceSuggestionAmountBehavior.VARIABLE
    )
    assert suggestion.min_amount.amount == Decimal("100.00")
    assert suggestion.max_amount.amount == Decimal("120.50")
    assert suggestion.last_amount.amount == Decimal("110.25")
    assert suggestion.suggested_expected_amount.amount == Decimal("110.25")


def test_month_end_billing_days_28_to_31(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    for when in (date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30)):
        _expense(budget_world, account, when)
    (suggestion,) = _store(budget_world).list_suggestions(
        **budget_world.scope(), today=date(2026, 10, 3)
    )
    assert suggestion.suggested_day_of_month == 31


def test_income_reversed_and_reversal_movements_never_count(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    ids = _streaming(budget_world, account, (7, 8, 9, 10))
    (suggestion,) = _list(budget_world)
    assert len(suggestion.evidence) == 4

    # Reversing the September charge removes it from the evidence: the run is now
    # just October, so there is nothing to suggest (and the reversal is not a charge).
    FinancialMovementStore(budget_world.runtime).reverse_movement(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=ids[2],
            effective_date=date(2026, 10, 12),
            competence_date=date(2026, 10, 12),
            reason="Sintético",
        ),
    )
    assert _list(budget_world) == ()

    income = budget_world.account(name="Income")
    for month in (8, 9, 10):
        FinancialMovementStore(budget_world.runtime).create_movement(
            **budget_world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementDraft(
                account_id=income,
                amount=Money(Decimal("39.90"), "BRL"),
                result_effect=FinancialResultEffect.INCOME,
                effective_date=date(2026, month, 10),
                competence_date=date(2026, month, 10),
                description="Streaming",
            ),
        )
    assert _list(budget_world) == ()


def test_archived_accounts_are_not_suggested(budget_world: BudgetWorld) -> None:
    archived = budget_world.account(name="Archived")
    _streaming(budget_world, archived)
    assert len(_list(budget_world)) == 1
    budget_world.archive_account(archived)
    assert _list(budget_world) == ()


def test_movements_linked_to_an_occurrence_are_excluded_from_the_scan(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rules = FinancialRecurrenceStore(budget_world.runtime)
    rule = rules.create_recurrence(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialRecurrenceDraft(
            account_id=account,
            description="Aluguel",
            result_effect=FinancialResultEffect.EXPENSE,
            expected=Money(Decimal("900"), "BRL"),
            start_date=date(2026, 1, 10),
            day_of_month=10,
        ),
    )
    linked: list[UUID] = []
    for month in (8, 9, 10):
        window = FinancialRecurrenceWindow(date(2026, month, 1), date(2026, month, 1))
        (occurrence,) = rules.generate_occurrences(
            **budget_world.scope(), recurrence_id=rule.id, window=window
        ).occurrences
        done = rules.realize_occurrence(
            **budget_world.scope(),
            occurrence_id=occurrence.id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialRecurrenceRealizationDraft(
                actual=Money(Decimal("900"), "BRL"),
                effective_date=date(2026, month, 10),
                competence_date=date(2026, month, 1),
            ),
        )
        assert done.realization is not None
        linked.append(done.realization.movement_id)
    standalone = _expense(budget_world, account, date(2026, 10, 3), description="Outro")

    with budget_world.runtime.begin() as connection:
        _set_context(connection, **budget_world.scope())
        _owners, observations = _store(budget_world)._scan(
            connection,
            budget_world.installation_id,
            budget_world.residence_id,
            _TODAY,
        )
    scanned = {item.movement_id for item in observations}
    assert standalone in scanned
    assert not scanned & set(linked)


def test_an_equivalent_recurrence_suppresses_the_suggestion(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    other = budget_world.account(name="Other")
    _streaming(budget_world, account)
    _streaming(budget_world, other)
    assert len(_list(budget_world)) == 2

    FinancialRecurrenceStore(budget_world.runtime).create_recurrence(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialRecurrenceDraft(
            account_id=account,
            description=" STREAMING ",
            result_effect=FinancialResultEffect.EXPENSE,
            expected=Money(Decimal("40"), "BRL"),
            start_date=date(2026, 11, 1),
            day_of_month=10,
        ),
    )

    assert [s.account_id for s in _list(budget_world)] == [other]


def test_old_months_outside_the_window_do_not_form_a_suggestion(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    for when in (date(2025, 3, 10), date(2025, 4, 10), date(2025, 5, 10)):
        _expense(budget_world, account, when)
    assert _list(budget_world) == ()


# --- audience -------------------------------------------------------------------


def test_household_suggestions_are_visible_to_members_but_not_acceptable(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)

    (suggestion,) = _list(budget_world, budget_world.member_id)

    assert suggestion.account_id == account
    assert not suggestion.can_accept(budget_world.member_id)
    with pytest.raises(FinancialRecurrenceSuggestionNotEditableError):
        _accept(budget_world, suggestion, operator_id=budget_world.member_id)
    assert _world_counts(budget_world)[1:] == (0, 0, 0, 0)


def test_personal_suggestions_never_leak_to_other_members(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account(household=False)
    _streaming(budget_world, account)

    assert len(_list(budget_world)) == 1
    assert _list(budget_world, budget_world.member_id) == ()
    # A member cannot probe the fingerprint of an invisible suggestion either.
    (mine,) = _list(budget_world)
    with pytest.raises(FinancialRecurrenceSuggestionNotAvailableError):
        _dismiss(budget_world, mine.fingerprint, budget_world.member_id)
    with pytest.raises(FinancialRecurrenceSuggestionNotAvailableError):
        _accept(budget_world, mine, operator_id=budget_world.member_id)


def test_shared_suggestions_follow_the_account_grant(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account(shared=True)
    _streaming(budget_world, account)

    assert _list(budget_world, budget_world.member_id) == ()
    budget_world.grant_account(account, budget_world.member_id)
    (seen,) = _list(budget_world, budget_world.member_id)
    assert seen.account_id == account and not seen.can_accept(budget_world.member_id)


def test_cross_residence_and_non_members_fail_closed(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)

    outsider = {
        "operator_id": budget_world.outsider_id,
        "residence_id": budget_world.other_residence_id,
    }
    assert _list(budget_world, **outsider) == ()
    with pytest.raises(FinancialRecurrenceSuggestionNotAvailableError):
        _store(budget_world).dismiss(
            **budget_world.scope(
                budget_world.outsider_id, residence_id=budget_world.other_residence_id
            ),
            fingerprint=suggestion.fingerprint,
            today=_TODAY,
        )
    with pytest.raises(FinancialRecurrenceAccessError):
        _list(budget_world, budget_world.outsider_id)  # not a member of this residence


# --- dismiss --------------------------------------------------------------------


def test_dismiss_hides_only_for_the_dismissing_operator(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)

    decision, created = _dismiss(
        budget_world, suggestion.fingerprint, budget_world.member_id
    )

    assert (
        created and decision.decision is FinancialRecurrenceSuggestionDecision.DISMISSED
    )
    assert (
        decision.operator_id == budget_world.member_id
        and decision.recurrence_id is None
    )
    assert decision.evidence_digest == suggestion.evidence_digest
    assert _list(budget_world, budget_world.member_id) == ()
    assert len(_list(budget_world)) == 1  # the owner still sees it
    assert _world_counts(budget_world)[:2] == (3, 0)  # ledger and rules untouched


def test_dismiss_is_idempotent_and_survives_new_observations(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account, (8, 9))
    _expense(budget_world, account, date(2026, 10, 10))
    (suggestion,) = _list(budget_world)

    first, created = _dismiss(budget_world, suggestion.fingerprint)
    again, created_again = _dismiss(budget_world, suggestion.fingerprint)

    assert created and not created_again and first.id == again.id
    assert _count(budget_world, _DECISIONS) == 1
    # The fingerprint is blind to evidence, so a new observation stays dismissed.
    _expense(budget_world, account, date(2026, 11, 10))
    later = _store(budget_world).list_suggestions(
        **budget_world.scope(), today=date(2026, 11, 20)
    )
    assert later == ()


def test_dismiss_rejects_forged_and_unavailable_fingerprints(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    with pytest.raises(FinancialRecurrenceSuggestionNotAvailableError):
        _dismiss(budget_world, "0" * 64)
    with pytest.raises(FinancialRecurrenceSuggestionNotAvailableError):
        _dismiss(budget_world, uuid4().hex + uuid4().hex)
    with pytest.raises(ValueError):
        _dismiss(budget_world, "not-a-fingerprint")
    assert _count(budget_world, _DECISIONS) == 0


# --- accept ---------------------------------------------------------------------


def test_accept_creates_one_recurrence_and_provenance_but_no_movement_or_occurrence(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)
    movements_before = _count(budget_world, financial_movements)

    recurrence, decision, created = _accept(
        budget_world,
        suggestion,
        description="Streaming Premium",
        expected_amount=Decimal("44.90"),
        start_date=date(2026, 11, 12),
        day_of_month=12,
    )

    assert created
    assert recurrence.account_id == account
    assert recurrence.result_effect is FinancialResultEffect.EXPENSE
    assert recurrence.expected == Money(Decimal("44.90"), "BRL")
    assert recurrence.description == "Streaming Premium"
    assert (recurrence.day_of_month, recurrence.start_date) == (12, date(2026, 11, 12))
    assert recurrence.owner_operator_id == budget_world.owner_id
    assert decision.decision is FinancialRecurrenceSuggestionDecision.ACCEPTED
    assert decision.recurrence_id == recurrence.id
    assert decision.fingerprint == suggestion.fingerprint
    assert decision.evidence_digest == suggestion.evidence_digest
    assert _count(budget_world, financial_movements) == movements_before
    assert _world_counts(budget_world)[1:] == (1, 1, 0, 1)  # rule, revision 1, decision
    # The suggestion is gone for everyone with the audience, even if renamed.
    assert _list(budget_world) == ()
    assert _list(budget_world, budget_world.member_id) == ()


def test_accept_is_replay_safe_and_fails_closed_on_incompatible_retries(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)
    key = new_financial_idempotency_key()

    first, decision, created = _accept(budget_world, suggestion, key=key)
    again, same_decision, created_again = _accept(budget_world, suggestion, key=key)

    assert created and not created_again
    assert again.id == first.id and same_decision.id == decision.id
    assert _world_counts(budget_world)[1:] == (1, 1, 0, 1)
    with pytest.raises(FinancialRecurrenceConflictError):
        _accept(budget_world, suggestion, key=key, expected_amount=Decimal("1"))
    with pytest.raises(FinancialRecurrenceSuggestionConflictError):
        _accept(budget_world, suggestion)  # another key: already accepted
    with pytest.raises(FinancialRecurrenceSuggestionConflictError):
        _dismiss(budget_world, suggestion.fingerprint)
    assert _world_counts(budget_world)[1:] == (1, 1, 0, 1)


def test_accept_after_dismiss_fails_closed(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)
    _dismiss(budget_world, suggestion.fingerprint)
    with pytest.raises(FinancialRecurrenceSuggestionConflictError):
        _accept(budget_world, suggestion)
    assert _world_counts(budget_world)[1:] == (0, 0, 0, 1)


def test_a_stale_candidate_is_refused_with_nothing_written(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    ids = _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)
    FinancialMovementStore(budget_world.runtime).reverse_movement(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=ids[-1],
            effective_date=date(2026, 10, 12),
            competence_date=date(2026, 10, 12),
            reason="Sintético",
        ),
    )
    before = _world_counts(budget_world)

    with pytest.raises(FinancialRecurrenceSuggestionNotAvailableError):
        _accept(budget_world, suggestion)
    with pytest.raises(FinancialRecurrenceSuggestionNotAvailableError):
        _dismiss(budget_world, suggestion.fingerprint)

    assert _world_counts(budget_world) == before


def test_a_recurrence_made_in_between_makes_the_candidate_stale(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)
    FinancialRecurrenceStore(budget_world.runtime).create_recurrence(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialRecurrenceDraft(
            account_id=account,
            description="streaming",
            result_effect=FinancialResultEffect.EXPENSE,
            expected=Money(Decimal("40"), "BRL"),
            start_date=date(2026, 11, 1),
            day_of_month=10,
        ),
    )
    with pytest.raises(FinancialRecurrenceSuggestionNotAvailableError):
        _accept(budget_world, suggestion)
    assert _count(budget_world, financial_recurrences) == 1


def test_concurrent_accepts_never_duplicate_the_recurrence(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)
    shared_key = new_financial_idempotency_key()
    barrier = Barrier(6)

    def attempt(index: int) -> str:
        barrier.wait()
        key = shared_key if index % 2 == 0 else new_financial_idempotency_key()
        try:
            _accept(budget_world, suggestion, key=key)
        except (
            FinancialRecurrenceSuggestionConflictError,
            FinancialRecurrenceSuggestionNotAvailableError,
            FinancialRecurrenceConflictError,
        ):
            return "refused"
        return "ok"

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = [f.result() for f in [pool.submit(attempt, i) for i in range(6)]]

    assert "ok" in results
    assert _world_counts(budget_world)[1:] == (1, 1, 0, 1)  # exactly one of each


def test_a_failure_after_the_recurrence_rolls_back_rule_revision_and_decision(
    budget_world: BudgetWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)

    def explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("injected failure after the recurrence insert")

    monkeypatch.setattr(store_module, "_insert_accepted", explode)
    with pytest.raises(RuntimeError, match="injected"):
        _accept(budget_world, suggestion)
    monkeypatch.undo()

    assert _world_counts(budget_world)[1:] == (0, 0, 0, 0)
    assert len(_list(budget_world)) == 1  # nothing was decided: still suggested


def test_the_account_must_stay_owned_and_active_at_accept_time(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)
    budget_world.archive_account(account)
    with pytest.raises(FinancialRecurrenceSuggestionNotAvailableError):
        _accept(budget_world, suggestion)
    assert _world_counts(budget_world)[1:] == (0, 0, 0, 0)


# --- database enforcement -------------------------------------------------------


def _decision_values(
    world: BudgetWorld, suggestion: Any, **overrides: Any
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": uuid4(),
        "installation_id": world.installation_id,
        "residence_id": world.residence_id,
        "account_id": suggestion.account_id,
        "operator_id": world.owner_id,
        "currency": "BRL",
        "fingerprint": suggestion.fingerprint,
        "decision": "DISMISSED",
        "recurrence_id": None,
        "evidence_digest": suggestion.evidence_digest,
        "decided_at": func.transaction_timestamp(),
    }
    values.update(overrides)
    return values


def _runtime(
    world: BudgetWorld, statement: Any, operator_id: UUID | None = None
) -> Any:
    with world.runtime.begin() as connection:
        _set_context(connection, **world.scope(operator_id))
        return connection.execute(statement)


def test_decisions_are_append_only_for_the_runtime_and_for_everyone_else(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)
    _dismiss(budget_world, suggestion.fingerprint)

    for statement in (
        update(_DECISIONS).values(decision="DISMISSED"),
        delete(_DECISIONS),
        text("TRUNCATE finance.recurrence_suggestion_decisions"),
    ):
        with pytest.raises(DBAPIError):
            _runtime(budget_world, statement)
    with pytest.raises(DBAPIError, match="append-only"):
        with budget_world.engine.begin() as connection:
            connection.execute(update(_DECISIONS).values(evidence_digest="f" * 64))
    assert _count(budget_world, _DECISIONS) == 1


def test_the_database_refuses_forged_or_misattributed_decisions(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)
    old_rule = FinancialRecurrenceStore(budget_world.runtime).create_recurrence(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialRecurrenceDraft(
            account_id=account,
            description="Outro",
            result_effect=FinancialResultEffect.EXPENSE,
            expected=Money(Decimal("1"), "BRL"),
            start_date=date(2026, 11, 1),
            day_of_month=10,
        ),
    )

    forged = (
        # ACCEPTED for a recurrence that was not created in this transaction
        _decision_values(
            budget_world, suggestion, decision="ACCEPTED", recurrence_id=old_rule.id
        ),
        # shape: DISMISSED must not carry a recurrence, ACCEPTED must
        _decision_values(budget_world, suggestion, recurrence_id=old_rule.id),
        _decision_values(budget_world, suggestion, decision="ACCEPTED"),
        # someone else's decision, and a forged instant
        _decision_values(budget_world, suggestion, operator_id=budget_world.member_id),
        _decision_values(budget_world, suggestion, decided_at=date(2020, 1, 1)),
        # malformed identity
        _decision_values(budget_world, suggestion, fingerprint="abc"),
        _decision_values(budget_world, suggestion, decision="MAYBE"),
    )
    for values in forged:
        with pytest.raises(DBAPIError):
            _runtime(budget_world, insert(_DECISIONS).values(**values))
    assert _count(budget_world, _DECISIONS) == 0

    # The same row, honestly shaped, is accepted by the policy and the triggers.
    _runtime(
        budget_world,
        insert(_DECISIONS).values(**_decision_values(budget_world, suggestion)),
    )
    assert _count(budget_world, _DECISIONS) == 1
    with pytest.raises(DBAPIError):  # one decision per operator and fingerprint
        _runtime(
            budget_world,
            insert(_DECISIONS).values(**_decision_values(budget_world, suggestion)),
        )


def test_a_decision_on_an_invisible_account_is_refused_by_the_policy(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account(household=False)
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)
    with pytest.raises(DBAPIError):
        _runtime(
            budget_world,
            insert(_DECISIONS).values(
                **_decision_values(
                    budget_world, suggestion, operator_id=budget_world.member_id
                )
            ),
            operator_id=budget_world.member_id,
        )
    assert _count(budget_world, _DECISIONS) == 0


def test_dismissals_are_personal_and_acceptances_follow_the_audience_in_sql(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    (suggestion,) = _list(budget_world)
    _dismiss(budget_world, suggestion.fingerprint, budget_world.member_id)

    assert (
        len(_runtime(budget_world, select(_DECISIONS), budget_world.member_id).all())
        == 1
    )
    assert _runtime(budget_world, select(_DECISIONS)).all() == []  # owner: not theirs

    other = budget_world.account(name="Other")
    _streaming(budget_world, other)
    (second,) = [s for s in _list(budget_world) if s.account_id == other]
    _accept(budget_world, second)
    # An acceptance is provenance of a shared rule: the member sees it too.
    rows = _runtime(budget_world, select(_DECISIONS), budget_world.member_id).all()
    assert {row.decision for row in rows} == {"DISMISSED", "ACCEPTED"}
    outsider = budget_world.scope(
        budget_world.outsider_id, residence_id=budget_world.other_residence_id
    )
    with budget_world.runtime.begin() as connection:
        _set_context(connection, **outsider)
        assert connection.execute(select(_DECISIONS)).all() == []


# --- bounds ---------------------------------------------------------------------


def test_the_scan_cap_fails_explicitly_and_the_exact_cap_succeeds(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    scope = budget_world.scope()

    exact = FinancialRecurrenceSuggestionStore(budget_world.runtime, scan_max=3)
    assert len(exact.list_suggestions(**scope, today=_TODAY)) == 1
    tight = FinancialRecurrenceSuggestionStore(budget_world.runtime, scan_max=2)
    with pytest.raises(FinancialRecurrenceSuggestionLimitError):
        tight.list_suggestions(**scope, today=_TODAY)
    with pytest.raises(ValueError):
        FinancialRecurrenceSuggestionStore(budget_world.runtime, scan_max=0)


class _Counter:
    def __init__(self, world: BudgetWorld) -> None:
        self._engine = world.runtime
        self.count = 0

    def _on(self, *_: Any) -> None:
        self.count += 1

    def __enter__(self) -> _Counter:
        event.listen(self._engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *_: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._on)


def test_the_statement_count_is_fixed_whatever_the_amount_of_data(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    scope = budget_world.scope()

    def statements() -> int:
        with _Counter(budget_world) as counter:
            _store(budget_world).list_suggestions(**scope, today=_TODAY)
        return counter.count

    empty = statements()
    _streaming(budget_world, account)
    one = statements()
    for index in range(6):
        other = budget_world.account(name=f"Conta {index}")
        _streaming(budget_world, other, description=f"Servico {index}")
        _expense(budget_world, other, date(2026, 10, 3), description="Avulso")
    many = statements()

    assert empty == 4  # context, membership, scan, rules (no suggestion, no decisions)
    assert one == many == 5  # plus exactly one decisions lookup, never one per row
    assert len(_list(budget_world)) == 7


def test_the_scan_is_served_by_the_partial_index(budget_world: BudgetWorld) -> None:
    account = budget_world.account()
    _streaming(budget_world, account)
    with budget_world.engine.begin() as connection:
        connection.execute(text("ANALYZE finance.movements"))
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in connection.execute(
                text(
                    "EXPLAIN SELECT id FROM finance.movements "
                    "WHERE residence_id = :r AND role = 'STANDARD' "
                    "AND result_effect = 'EXPENSE' "
                    "AND effective_date BETWEEN '2025-11-01' AND '2026-10-20'"
                ),
                {"r": budget_world.residence_id},
            )
        )
    assert "ix_finance_movements_expense_scan" in plan
