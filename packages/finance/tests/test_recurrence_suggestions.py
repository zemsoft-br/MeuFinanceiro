from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    SUGGESTION_DAY_WINDOW_DAYS,
    FinancialRecurrenceObservation,
    FinancialRecurrenceRuleKey,
    FinancialRecurrenceSuggestionAcceptance,
    FinancialRecurrenceSuggestionAmountBehavior,
    FinancialRecurrenceSuggestionReason,
    FinancialResultEffect,
    Money,
    detect_recurrence_suggestions,
    normalize_recurrence_description,
    recurrence_suggestion_fingerprint,
    recurrence_suggestion_window,
    suggest_day_of_month,
    validate_recurrence_suggestion_fingerprint,
)
from meufinanceiro_finance.recurrence_suggestions import _digest

INSTALLATION = uuid4()
RESIDENCE = uuid4()
ACCOUNT = uuid4()
OWNER = uuid4()
TODAY = date(2026, 10, 20)


def _obs(
    when: date,
    amount: str = "39.90",
    description: str | None = "Streaming",
    *,
    account: UUID = ACCOUNT,
    currency: str = "BRL",
) -> FinancialRecurrenceObservation:
    return FinancialRecurrenceObservation(
        movement_id=uuid4(),
        account_id=account,
        currency=currency,
        description=description,
        effective_date=when,
        amount=Decimal(amount),
    )


def _detect(
    observations: list[FinancialRecurrenceObservation],
    *,
    today: date = TODAY,
    rules: tuple[FinancialRecurrenceRuleKey, ...] = (),
) -> tuple:
    return detect_recurrence_suggestions(
        observations,
        installation_id=INSTALLATION,
        residence_id=RESIDENCE,
        today=today,
        account_owner_by_id={ACCOUNT: OWNER},
        existing_rules=rules,
    )


def _three() -> list[FinancialRecurrenceObservation]:
    return [
        _obs(date(2026, 8, 10)),
        _obs(date(2026, 9, 10)),
        _obs(date(2026, 10, 10)),
    ]


# --- positive ---------------------------------------------------------------------


def test_three_consecutive_months_with_one_charge_each_is_suggested() -> None:
    (suggestion,) = _detect(_three())

    assert suggestion.description == "Streaming"
    assert suggestion.normalized_description == "streaming"
    assert suggestion.account_id == ACCOUNT and suggestion.currency == "BRL"
    assert suggestion.suggested_day_of_month == 10
    assert suggestion.suggested_expected_amount == Money(Decimal("39.90"), "BRL")
    assert (
        suggestion.amount_behavior is FinancialRecurrenceSuggestionAmountBehavior.FIXED
    )
    assert suggestion.observed_dates == (
        date(2026, 8, 10),
        date(2026, 9, 10),
        date(2026, 10, 10),
    )
    assert [m.amount for m in suggestion.observed_amounts] == [Decimal("39.90")] * 3
    assert suggestion.min_amount == suggestion.max_amount == suggestion.last_amount
    assert suggestion.reason_codes == (
        FinancialRecurrenceSuggestionReason.EXACT_DESCRIPTION,
        FinancialRecurrenceSuggestionReason.CONSECUTIVE_MONTHS,
        FinancialRecurrenceSuggestionReason.ONE_PER_MONTH,
        FinancialRecurrenceSuggestionReason.DAY_WINDOW,
        FinancialRecurrenceSuggestionReason.AMOUNT_FIXED,
    )
    assert suggestion.can_accept(OWNER) and not suggestion.can_accept(uuid4())
    validate_recurrence_suggestion_fingerprint(suggestion.fingerprint)


def test_the_run_may_end_in_the_previous_month() -> None:
    assert len(_detect(_three(), today=date(2026, 11, 5))) == 1
    assert _detect(_three(), today=date(2026, 12, 1)) == ()  # stopped: not ongoing


def test_a_longer_run_uses_every_consecutive_month() -> None:
    observations = _three() + [_obs(date(2026, 7, 10)), _obs(date(2026, 6, 11))]
    (suggestion,) = _detect(observations)
    assert len(suggestion.evidence) == 5
    assert suggestion.observed_dates[0] == date(2026, 6, 11)


# --- negative ---------------------------------------------------------------------


def test_two_months_is_not_enough() -> None:
    assert _detect(_three()[1:]) == ()


def test_a_monthly_gap_breaks_the_run() -> None:
    gap = [_obs(date(2026, 6, 10)), _obs(date(2026, 8, 10)), _obs(date(2026, 10, 10))]
    assert _detect(gap) == ()
    # Months before a gap do not count; the three after it do.
    after_gap = [_obs(date(2026, 5, 10))] + _three()
    (suggestion,) = _detect(after_gap)
    assert len(suggestion.evidence) == 3


def test_two_charges_in_the_latest_month_are_ambiguous() -> None:
    assert _detect(_three() + [_obs(date(2026, 10, 15))]) == ()


def test_two_charges_in_an_older_month_end_the_run_before_it() -> None:
    double = [_obs(date(2026, 7, 9)), _obs(date(2026, 7, 10))] + _three()
    (suggestion,) = _detect(double)
    assert len(suggestion.evidence) == 3  # only Aug, Sep, Oct are the run
    short = [_obs(date(2026, 8, 9)), _obs(date(2026, 8, 10))] + _three()[1:]
    assert _detect(short) == ()  # the double month leaves a run of two


def test_blank_or_missing_descriptions_never_group() -> None:
    for description in (None, "", "   \t "):
        assert _detect([_obs(d, description=description) for d in _dates()]) == ()


def _dates() -> list[date]:
    return [date(2026, 8, 10), date(2026, 9, 10), date(2026, 10, 10)]


def test_observations_outside_the_twelve_month_window_are_ignored() -> None:
    first, last = recurrence_suggestion_window(TODAY)
    assert (first, last) == (date(2025, 11, 1), TODAY)
    old = [_obs(date(2025, 10, 10)), _obs(date(2025, 9, 10)), _obs(date(2025, 8, 10))]
    assert len(_detect(old, today=date(2025, 11, 20))) == 1  # the window moves
    assert _detect(old) == ()
    assert (
        _detect(_three() + [_obs(date(2026, 10, 25))], today=date(2026, 10, 20)) != ()
    )
    # A date after ``today`` is not realized yet and is ignored.
    assert len(_detect(_three() + [_obs(date(2026, 10, 25))])[0].evidence) == 3


# --- identity / normalization -----------------------------------------------------


def test_normalization_is_the_categorization_contract() -> None:
    assert normalize_recurrence_description("  STREAMING \t") == "streaming"
    assert normalize_recurrence_description(
        "Straße"
    ) == normalize_recurrence_description("STRASSE")
    assert normalize_recurrence_description("Pão") == normalize_recurrence_description(
        "Pão".replace("ã", "ã")
    )
    assert normalize_recurrence_description("a  b") != normalize_recurrence_description(
        "a b"
    )  # inner spacing is preserved
    assert normalize_recurrence_description("pao") != normalize_recurrence_description(
        "pão"
    )


def test_exact_normalized_descriptions_group_and_similar_ones_do_not() -> None:
    mixed = [
        _obs(date(2026, 8, 10), description="Streaming"),
        _obs(date(2026, 9, 10), description="  STREAMING"),
        _obs(date(2026, 10, 10), description="streaming "),
    ]
    assert len(_detect(mixed)) == 1
    similar = [
        _obs(date(2026, 8, 10), description="Streaming"),
        _obs(date(2026, 9, 10), description="Streaming+"),
        _obs(date(2026, 10, 10), description="Streamingg"),
    ]
    assert _detect(similar) == ()  # no fuzzy matching: three different groups


def test_groups_never_cross_account_or_currency() -> None:
    other = uuid4()
    mixed = [
        _obs(date(2026, 8, 10)),
        _obs(date(2026, 9, 10), account=other),
        _obs(date(2026, 10, 10)),
    ]
    assert _detect(mixed) == ()
    currencies = [
        _obs(date(2026, 8, 10)),
        _obs(date(2026, 9, 10), currency="USD"),
        _obs(date(2026, 10, 10)),
    ]
    assert _detect(currencies) == ()


def test_fingerprint_is_stable_scoped_and_blind_to_evidence() -> None:
    base = {
        "installation_id": INSTALLATION,
        "residence_id": RESIDENCE,
        "account_id": ACCOUNT,
        "currency": "BRL",
        "normalized_description": "streaming",
    }
    fingerprint = recurrence_suggestion_fingerprint(**base)
    assert fingerprint == recurrence_suggestion_fingerprint(**base)
    validate_recurrence_suggestion_fingerprint(fingerprint)
    for key, other in (
        ("installation_id", uuid4()),
        ("residence_id", uuid4()),
        ("account_id", uuid4()),
        ("currency", "USD"),
        ("normalized_description", "streaming "),
    ):
        assert recurrence_suggestion_fingerprint(**{**base, key: other}) != fingerprint
    # New observations and amounts never change the identity.
    (first,) = _detect(_three())
    (second,) = _detect(_three() + [_obs(date(2026, 7, 10), "50")])
    assert first.fingerprint == second.fingerprint == fingerprint
    assert first.evidence_digest != second.evidence_digest
    assert first.evidence_digest == first.evidence_digest
    # No Movement id or date can leak into the identity.
    assert str(first.movement_ids[0]) not in first.fingerprint


@pytest.mark.parametrize(
    "value", ["", "abc", "A" * 64, "g" * 64, "a" * 63, "a" * 65, None, 5]
)
def test_a_forged_fingerprint_shape_is_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        validate_recurrence_suggestion_fingerprint(value)  # type: ignore[arg-type]


def test_the_digest_is_length_prefixed_so_parts_cannot_collide() -> None:
    assert _digest("ab", "c") != _digest("a", "bc")
    assert _digest("a", "") != _digest("", "a")
    with pytest.raises(ValueError):
        recurrence_suggestion_fingerprint(
            installation_id=INSTALLATION,
            residence_id=RESIDENCE,
            account_id=ACCOUNT,
            currency="BRL",
            normalized_description="",
        )


# --- amounts ----------------------------------------------------------------------


def test_variable_amounts_are_exposed_not_hidden() -> None:
    observations = [
        _obs(date(2026, 8, 10), "100.00"),
        _obs(date(2026, 9, 10), "120.50"),
        _obs(date(2026, 10, 10), "110.25"),
    ]
    (suggestion,) = _detect(observations)
    assert (
        suggestion.amount_behavior
        is FinancialRecurrenceSuggestionAmountBehavior.VARIABLE
    )
    assert (
        suggestion.reason_codes[-1]
        is FinancialRecurrenceSuggestionReason.AMOUNT_VARIABLE
    )
    assert suggestion.min_amount.amount == Decimal("100.00")
    assert suggestion.max_amount.amount == Decimal("120.50")
    assert suggestion.last_amount.amount == Decimal("110.25")
    assert suggestion.suggested_expected_amount.amount == Decimal("110.25")
    assert [m.amount for m in suggestion.observed_amounts] == [
        Decimal("100.00"),
        Decimal("120.50"),
        Decimal("110.25"),
    ]


def test_equal_amounts_with_different_scale_are_fixed() -> None:
    observations = [
        _obs(date(2026, 8, 10), "40"),
        _obs(date(2026, 9, 10), "40.00"),
        _obs(date(2026, 10, 10), "40.0000"),
    ]
    (suggestion,) = _detect(observations)
    assert (
        suggestion.amount_behavior is FinancialRecurrenceSuggestionAmountBehavior.FIXED
    )
    assert isinstance(suggestion.suggested_expected_amount.amount, Decimal)


def test_amounts_are_exact_decimals_never_floats() -> None:
    (suggestion,) = _detect(
        [
            _obs(date(2026, 8, 10), "0.1"),
            _obs(date(2026, 9, 10), "0.2"),
            _obs(date(2026, 10, 10), "0.30000001"),
        ]
    )
    assert suggestion.max_amount.amount == Decimal("0.30000001")
    with pytest.raises(TypeError):
        FinancialRecurrenceObservation(
            movement_id=uuid4(),
            account_id=ACCOUNT,
            currency="BRL",
            description="x",
            effective_date=date(2026, 10, 1),
            amount=0.1,  # type: ignore[arg-type]
        )


# --- day window -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dates", "expected"),
    [
        ([date(2026, 8, 10), date(2026, 9, 10), date(2026, 10, 10)], 10),
        ([date(2026, 8, 10), date(2026, 9, 11), date(2026, 10, 12)], 11),
        ([date(2026, 8, 10), date(2026, 9, 12)], 11),
        # month-end clamping: a day-31 rule bills on 31, 30 and 28/29
        ([date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30)], 31),
        ([date(2026, 12, 31), date(2027, 1, 31), date(2027, 2, 28)], 31),
        ([date(2027, 12, 31), date(2028, 1, 31), date(2028, 2, 29)], 31),
        ([date(2027, 1, 30), date(2027, 2, 28), date(2027, 3, 30)], 30),
        ([date(2027, 1, 29), date(2027, 2, 28), date(2027, 3, 29)], 29),
        ([date(2026, 12, 28), date(2027, 1, 28), date(2027, 2, 28)], 28),
    ],
)
def test_the_anchor_day_is_deterministic_and_month_end_aware(
    dates: list[date], expected: int
) -> None:
    assert suggest_day_of_month(dates) == expected


def test_dates_too_scattered_for_a_billing_window_give_no_suggestion() -> None:
    assert SUGGESTION_DAY_WINDOW_DAYS == 3
    spread = [date(2026, 8, 5), date(2026, 9, 20), date(2026, 10, 5)]
    assert suggest_day_of_month(spread) is None
    assert _detect([_obs(d) for d in spread]) == ()
    # The window is three days either side of one anchor: a spread of six fits
    # (anchor 8), a spread of seven does not.
    assert suggest_day_of_month([date(2026, 8, 5), date(2026, 9, 11)]) == 8
    assert suggest_day_of_month([date(2026, 8, 5), date(2026, 9, 12)]) is None


def test_the_anchor_tiebreak_is_total() -> None:
    # Both 10 and 11 have a worst deviation of 1 over 10/11; the smaller total, then
    # the smaller day, decides, so the answer never depends on input order.
    forward = suggest_day_of_month([date(2026, 8, 10), date(2026, 9, 11)])
    backward = suggest_day_of_month([date(2026, 9, 11), date(2026, 8, 10)])
    assert forward == backward == 10
    assert suggest_day_of_month([]) is None


def test_end_to_end_month_end_pattern_suggests_the_last_day_anchor() -> None:
    observations = [
        _obs(date(2026, 7, 31)),
        _obs(date(2026, 8, 31)),
        _obs(date(2026, 9, 30)),
    ]
    (suggestion,) = _detect(observations, today=date(2026, 10, 3))
    assert suggestion.suggested_day_of_month == 31


# --- suppression / determinism ----------------------------------------------------


def test_an_equivalent_recurrence_suppresses_the_suggestion() -> None:
    def rule(**overrides: object) -> FinancialRecurrenceRuleKey:
        values: dict[str, object] = {
            "account_id": ACCOUNT,
            "currency": "BRL",
            "result_effect": FinancialResultEffect.EXPENSE,
            "description": " STREAMING ",
        }
        values.update(overrides)
        return FinancialRecurrenceRuleKey(**values)  # type: ignore[arg-type]

    assert _detect(_three(), rules=(rule(),)) == ()
    # Different account, currency, effect or description does not suppress.
    for other in (
        rule(account_id=uuid4()),
        rule(currency="USD"),
        rule(result_effect=FinancialResultEffect.INCOME),
        rule(description="Streaming plus"),
    ):
        assert len(_detect(_three(), rules=(other,))) == 1


def test_detection_is_deterministic_and_order_independent() -> None:
    observations = _three()
    other = [
        _obs(date(2026, 8, 3), "9", "Gym"),
        _obs(date(2026, 9, 3), "9", "Gym"),
        _obs(date(2026, 10, 3), "9", "Gym"),
    ]
    forward = _detect(observations + other)
    backward = _detect(list(reversed(other + observations)))
    assert [s.fingerprint for s in forward] == [s.fingerprint for s in backward]
    assert [s.observed_dates for s in forward] == [s.observed_dates for s in backward]
    # Latest observation first, then fingerprint.
    assert forward[0].description == "Streaming"


def test_accounts_the_caller_cannot_attribute_are_dropped() -> None:
    assert (
        detect_recurrence_suggestions(
            _three(),
            installation_id=INSTALLATION,
            residence_id=RESIDENCE,
            today=TODAY,
            account_owner_by_id={},
        )
        == ()
    )


# --- acceptance -------------------------------------------------------------------


def test_acceptance_builds_a_draft_the_client_cannot_widen() -> None:
    (suggestion,) = _detect(_three())
    draft = FinancialRecurrenceSuggestionAcceptance(
        description="  Streaming Premium ",
        expected_amount=Decimal("44.90"),
        start_date=date(2026, 11, 10),
        day_of_month=12,
        end_date=None,
    ).to_draft(suggestion)
    assert draft.account_id == suggestion.account_id
    assert draft.result_effect is FinancialResultEffect.EXPENSE
    assert draft.expected == Money(Decimal("44.90"), "BRL")
    assert draft.description == "Streaming Premium"
    assert (draft.start_date, draft.day_of_month) == (date(2026, 11, 10), 12)
    for bad in (
        {"expected_amount": Decimal("0")},
        {"expected_amount": Decimal("-1")},
        {"description": "   "},
        {"day_of_month": 32},
        {"end_date": date(2026, 1, 1)},
    ):
        values = {
            "description": "x",
            "expected_amount": Decimal("1"),
            "start_date": date(2026, 11, 10),
            "day_of_month": 10,
            "end_date": None,
            **bad,
        }
        with pytest.raises((ValueError, TypeError)):
            FinancialRecurrenceSuggestionAcceptance(**values).to_draft(suggestion)  # type: ignore[arg-type]


def test_observation_validation_and_redaction() -> None:
    with pytest.raises(ValueError):
        _obs(date(2026, 10, 1), "-5")
    with pytest.raises(ValueError):
        _obs(date(2026, 10, 1), "0")
    with pytest.raises(ValueError):
        _obs(date(2026, 10, 1), currency="brl")
    observation = _obs(date(2026, 10, 1))
    assert "Streaming" not in repr(observation)
    (suggestion,) = _detect(_three())
    assert "Streaming" not in repr(suggestion) and "39" not in repr(suggestion)


def test_a_run_longer_than_the_window_only_uses_the_twelve_months() -> None:
    start = date(2025, 8, 10)
    long_run = [
        _obs(
            date(
                start.year + (start.month - 1 + i) // 12,
                (start.month - 1 + i) % 12 + 1,
                10,
            )
        )
        for i in range(15)
    ]  # Aug 2025 .. Oct 2026
    (suggestion,) = _detect(long_run)
    assert len(suggestion.evidence) == 12
    assert suggestion.observed_dates[0] == date(2025, 11, 10)


def test_the_evidence_digest_covers_every_amount_date_and_movement() -> None:
    ids = [uuid4(), uuid4(), uuid4()]

    def build(
        days: tuple[int, int, int], amounts: tuple[str, str, str], movements: list[UUID]
    ) -> object:
        observations = [
            FinancialRecurrenceObservation(
                movement_id=movements[index],
                account_id=ACCOUNT,
                currency="BRL",
                description="Streaming",
                effective_date=date(2026, 8 + index, days[index]),
                amount=Decimal(amounts[index]),
            )
            for index in range(3)
        ]
        (suggestion,) = _detect(observations)
        return suggestion

    first = build((10, 10, 10), ("39.90", "40.00", "39.90"), ids)
    again = build((10, 10, 10), ("39.90", "40.00", "39.90"), ids)
    assert first.evidence_digest == again.evidence_digest  # type: ignore[attr-defined]
    # Same identity, same suggested day and amount: only the evidence differs.
    middle_amount = build((10, 10, 10), ("39.90", "41.00", "39.90"), ids)
    middle_date = build((10, 11, 10), ("39.90", "40.00", "39.90"), ids)
    middle_movement = build(
        (10, 10, 10), ("39.90", "40.00", "39.90"), [ids[0], uuid4(), ids[2]]
    )
    digests = {
        item.evidence_digest  # type: ignore[attr-defined]
        for item in (first, middle_amount, middle_date, middle_movement)
    }
    assert len(digests) == 4
    assert {
        item.fingerprint
        for item in (first, middle_amount, middle_date, middle_movement)
    } == {first.fingerprint}  # type: ignore[attr-defined]
