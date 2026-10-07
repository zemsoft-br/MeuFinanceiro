"""Provider-neutral, deterministic detection of monthly recurrence suggestions.

A suggestion is a *derived* fact: it is neither a Movement, nor an occurrence, nor a
recurrence. It is computed at read time from realized, visible ``STANDARD EXPENSE``
Movements, never persisted, never accepted automatically and never a source of
balance. The only thing a user can do with it is explicitly create a canonical
recurrence (ADR-0027) or dismiss it (ADR-0028).

The v1 detector is a closed set of explainable rules. There is no fuzzy matching,
merchant or provider metadata, learning or opaque score:

* group *within one account* by ``(account, EXPENSE, currency, normalized description)``
  where normalization is the categorization contract (trim -> NFC -> casefold -> NFC);
* the evaluated *run* is the trailing sequence of consecutive calendar months that
  ends at the latest observation, with **exactly one** observation in every month;
* the run must have at least ``SUGGESTION_MIN_MONTHS`` months and end in the current
  or the previous month (a pattern that stopped is not an ongoing subscription);
* the days of month must fit a billing window of ``SUGGESTION_DAY_WINDOW_DAYS`` days
  around one anchor day (month-end clamping is understood: 31 -> 28/29/30);
* an amount may vary; it is exposed as evidence and labelled ``FIXED`` or ``VARIABLE``.

Every date is a plain ``date`` and nothing here reads a clock: callers inject
``today``. Money is ``Decimal`` end to end.
"""

from __future__ import annotations

import calendar
import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.categorization_rules import normalize_categorization_text
from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import Money, validate_currency_code
from meufinanceiro_finance.movements import FinancialResultEffect
from meufinanceiro_finance.recurrences import (
    FinancialRecurrenceDraft,
    add_months,
    month_start,
    validate_day_of_month,
)

SUGGESTION_MIN_OBSERVATIONS = 3
SUGGESTION_MIN_MONTHS = 3
SUGGESTION_WINDOW_MONTHS = 12
SUGGESTION_DAY_WINDOW_DAYS = 3
# A scan over the window reads at most this many Movements and a viewer is shown at
# most this many suggestions; going beyond either is an explicit failure, never a
# silent cut.
SUGGESTION_SCAN_MAX = 20000
SUGGESTION_LIST_MAX = 100

_FINGERPRINT_NAMESPACE = "meufinanceiro:recurrence-suggestion:v1"
_EVIDENCE_NAMESPACE = "meufinanceiro:recurrence-suggestion-evidence:v1"
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class FinancialRecurrenceSuggestionReason(StrEnum):
    """Closed, enumerated explanations. There is no numeric confidence."""

    EXACT_DESCRIPTION = "EXACT_DESCRIPTION"
    CONSECUTIVE_MONTHS = "CONSECUTIVE_MONTHS"
    ONE_PER_MONTH = "ONE_PER_MONTH"
    DAY_WINDOW = "DAY_WINDOW"
    AMOUNT_FIXED = "AMOUNT_FIXED"
    AMOUNT_VARIABLE = "AMOUNT_VARIABLE"


class FinancialRecurrenceSuggestionAmountBehavior(StrEnum):
    """Deterministic: every observed amount equal -> FIXED, otherwise VARIABLE."""

    FIXED = "FIXED"
    VARIABLE = "VARIABLE"


class FinancialRecurrenceSuggestionDecision(StrEnum):
    """Persisted, append-only feedback about one suggestion."""

    ACCEPTED = "ACCEPTED"
    DISMISSED = "DISMISSED"


# --- identity -------------------------------------------------------------------------


def normalize_recurrence_description(value: str) -> str:
    """The categorization normalization; ``""`` means "no usable description"."""
    return normalize_categorization_text(value)


def recurrence_suggestion_fingerprint(
    *,
    installation_id: UUID,
    residence_id: UUID,
    account_id: UUID,
    currency: str,
    normalized_description: str,
) -> str:
    """Stable, server-derived identity of *what* is suggested.

    A versioned-namespace SHA-256 over installation, residence, account, the fixed
    ``EXPENSE`` effect, currency and the normalized description. It deliberately
    excludes Movement ids and dates so feedback survives new observations. It is not
    a resource id and knowing it proves nothing: accept and dismiss always
    re-run the detector for the caller and only act on a fingerprint it yields.
    """
    for name, value in (
        ("installation_id", installation_id),
        ("residence_id", residence_id),
    ):
        if not isinstance(value, UUID):
            raise TypeError(f"{name} must be UUID")
    validate_financial_resource_id(account_id)
    validate_currency_code(currency)
    if not isinstance(normalized_description, str) or not normalized_description:
        raise ValueError("normalized_description must not be empty")
    return _digest(
        _FINGERPRINT_NAMESPACE,
        str(installation_id),
        str(residence_id),
        str(account_id),
        FinancialResultEffect.EXPENSE.value,
        currency,
        normalized_description,
    )


def validate_recurrence_suggestion_fingerprint(value: str) -> str:
    if not isinstance(value, str) or not _FINGERPRINT_PATTERN.fullmatch(value):
        raise ValueError("fingerprint must be 64 lowercase hexadecimal characters")
    return value


def _digest(*parts: str) -> str:
    # Length-prefixed so no concatenation of two different tuples collides.
    hasher = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        hasher.update(len(encoded).to_bytes(4, "big"))
        hasher.update(encoded)
    return hasher.hexdigest()


def _canonical_amount(amount: Decimal) -> str:
    return format(amount.normalize(), "f")


# --- inputs ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, repr=False)
class FinancialRecurrenceObservation:
    """One realized, economically active expense the caller has already filtered.

    ``amount`` is the positive magnitude of the expense. The caller is responsible
    for the Movement-level exclusions (role, effect, reversed, linked to an
    occurrence); this value only carries what the grouping needs.
    """

    movement_id: UUID
    account_id: UUID
    currency: str
    description: str | None
    effective_date: date
    amount: Decimal

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.movement_id)
        validate_financial_resource_id(self.account_id)
        validate_currency_code(self.currency)
        if self.description is not None and not isinstance(self.description, str):
            raise TypeError("description must be a string")
        if isinstance(self.effective_date, datetime) or not isinstance(
            self.effective_date, date
        ):
            raise TypeError("effective_date must be date")
        Money(self.amount, self.currency)  # validates Decimal, scale and currency
        if self.amount <= 0:
            raise ValueError("amount must be the positive magnitude of the expense")

    def __repr__(self) -> str:
        return "FinancialRecurrenceObservation(<identities-amounts-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialRecurrenceRuleKey:
    """What an existing recurrence says about the suggestion it already covers."""

    account_id: UUID
    currency: str
    result_effect: FinancialResultEffect
    description: str

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.account_id)
        validate_currency_code(self.currency)
        if not isinstance(self.result_effect, FinancialResultEffect):
            raise TypeError("result_effect must be FinancialResultEffect")
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")

    def __repr__(self) -> str:
        return "FinancialRecurrenceRuleKey(<identities-redacted>)"


# --- window ---------------------------------------------------------------------------


def recurrence_suggestion_window(today: date) -> tuple[date, date]:
    """``(first_day, last_day)`` of the observation window: 12 calendar months.

    It starts on the first day of the month 11 months before ``today``'s month and
    ends on ``today``: later dates are not realized yet.
    """
    if isinstance(today, datetime) or not isinstance(today, date):
        raise TypeError("today must be date")
    return add_months(month_start(today), -(SUGGESTION_WINDOW_MONTHS - 1)), today


# --- result ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FinancialRecurrenceSuggestionEvidence:
    """One Movement that supports a suggestion."""

    movement_id: UUID
    effective_date: date
    amount: Decimal


@dataclass(frozen=True, slots=True, repr=False)
class FinancialRecurrenceSuggestion:
    """A deterministic, explainable monthly-pattern candidate (never persisted)."""

    fingerprint: str
    account_id: UUID
    account_owner_operator_id: UUID
    description: str
    normalized_description: str
    currency: str
    evidence: tuple[FinancialRecurrenceSuggestionEvidence, ...]
    suggested_day_of_month: int
    suggested_expected_amount: Money
    amount_behavior: FinancialRecurrenceSuggestionAmountBehavior
    min_amount: Money
    max_amount: Money
    last_amount: Money
    reason_codes: tuple[FinancialRecurrenceSuggestionReason, ...]

    def __post_init__(self) -> None:
        validate_recurrence_suggestion_fingerprint(self.fingerprint)
        validate_financial_resource_id(self.account_id)
        if not isinstance(self.account_owner_operator_id, UUID):
            raise TypeError("account_owner_operator_id must be UUID")
        if not self.normalized_description:
            raise ValueError("normalized_description must not be empty")
        if len(self.evidence) < SUGGESTION_MIN_OBSERVATIONS:
            raise ValueError("a suggestion needs enough evidence")
        validate_day_of_month(self.suggested_day_of_month)

    @property
    def observed_dates(self) -> tuple[date, ...]:
        return tuple(item.effective_date for item in self.evidence)

    @property
    def observed_amounts(self) -> tuple[Money, ...]:
        return tuple(Money(item.amount, self.currency) for item in self.evidence)

    @property
    def movement_ids(self) -> tuple[UUID, ...]:
        return tuple(item.movement_id for item in self.evidence)

    @property
    def evidence_digest(self) -> str:
        """Digest of exactly what the user was shown, for decision provenance."""
        parts = [
            _EVIDENCE_NAMESPACE,
            self.fingerprint,
            str(self.suggested_day_of_month),
            _canonical_amount(self.suggested_expected_amount.amount),
            self.amount_behavior.value,
        ]
        for item in self.evidence:
            parts.extend(
                (
                    str(item.movement_id),
                    item.effective_date.isoformat(),
                    _canonical_amount(item.amount),
                )
            )
        return _digest(*parts)

    def can_accept(self, operator_id: UUID) -> bool:
        """Read access is the account audience; accepting is the owner's alone."""
        return operator_id == self.account_owner_operator_id

    def __repr__(self) -> str:
        return (
            "FinancialRecurrenceSuggestion("
            f"behavior={self.amount_behavior.value!r}, "
            f"observations={len(self.evidence)}, <identities-amounts-redacted>)"
        )


# --- detector -------------------------------------------------------------------------


def detect_recurrence_suggestions(
    observations: Iterable[FinancialRecurrenceObservation],
    *,
    installation_id: UUID,
    residence_id: UUID,
    today: date,
    account_owner_by_id: Mapping[UUID, UUID],
    existing_rules: Iterable[FinancialRecurrenceRuleKey] = (),
) -> tuple[FinancialRecurrenceSuggestion, ...]:
    """Pure, deterministic detector. The same input gives the same output.

    ``observations`` must already be the operator's visible, realized, economically
    active expenses inside the window. Groups whose recurrence is already
    represented by ``existing_rules`` (same account, EXPENSE, currency and
    normalized description, whatever the rule status) produce no suggestion.
    Output order is the latest observation first, then fingerprint.
    """
    window_first, window_last = recurrence_suggestion_window(today)
    covered = {
        (
            rule.account_id,
            rule.currency,
            normalize_recurrence_description(rule.description),
        )
        for rule in existing_rules
        if rule.result_effect is FinancialResultEffect.EXPENSE
    }
    current_month = _month_index(today)

    groups: dict[tuple[UUID, str, str], list[FinancialRecurrenceObservation]] = (
        defaultdict(list)
    )
    for observation in observations:
        if not window_first <= observation.effective_date <= window_last:
            continue
        normalized = normalize_recurrence_description(observation.description or "")
        if not normalized:
            continue
        groups[(observation.account_id, observation.currency, normalized)].append(
            observation
        )

    suggestions: list[FinancialRecurrenceSuggestion] = []
    for (account_id, currency, normalized), members in groups.items():
        if len(members) < SUGGESTION_MIN_OBSERVATIONS:
            continue
        if (account_id, currency, normalized) in covered:
            continue
        owner = account_owner_by_id.get(account_id)
        if owner is None:
            continue
        run = _trailing_run(members, current_month=current_month)
        if run is None:
            continue
        anchor = suggest_day_of_month([item.effective_date for item in run])
        if anchor is None:
            continue
        suggestions.append(
            _build_suggestion(
                installation_id=installation_id,
                residence_id=residence_id,
                account_id=account_id,
                owner_operator_id=owner,
                currency=currency,
                normalized=normalized,
                run=run,
                day_of_month=anchor,
            )
        )
    suggestions.sort(key=lambda item: (_neg_ordinal(item), item.fingerprint))
    return tuple(suggestions)


def _neg_ordinal(suggestion: FinancialRecurrenceSuggestion) -> int:
    return -suggestion.observed_dates[-1].toordinal()


def _month_index(value: date) -> int:
    return value.year * 12 + (value.month - 1)


def _trailing_run(
    members: Sequence[FinancialRecurrenceObservation], *, current_month: int
) -> tuple[FinancialRecurrenceObservation, ...] | None:
    """Trailing consecutive months with exactly one observation each, or ``None``.

    Conservative on purpose: an ambiguous latest month (two observations), a stale
    pattern (latest observation older than the previous month) and a run shorter
    than ``SUGGESTION_MIN_MONTHS`` all yield no suggestion. A gap or an ambiguous
    month *before* the run only ends the run: the evidence is the months after it.
    """
    by_month: dict[int, list[FinancialRecurrenceObservation]] = defaultdict(list)
    for item in members:
        by_month[_month_index(item.effective_date)].append(item)
    latest = max(by_month)
    if latest < current_month - 1 or len(by_month[latest]) != 1:
        return None
    month = latest
    run: list[FinancialRecurrenceObservation] = []
    while month in by_month and len(by_month[month]) == 1:
        run.append(by_month[month][0])
        month -= 1
    run.reverse()
    if len(run) < SUGGESTION_MIN_MONTHS:
        return None
    return tuple(run)


def suggest_day_of_month(dates: Sequence[date]) -> int | None:
    """Anchor day that explains every date inside the billing window, or ``None``.

    A candidate anchor ``D`` explains a date in month ``M`` on day ``d`` with a
    deviation of ``abs(min(D, last_day(M)) - d)``, so a day-31 rule that bills on
    Feb 28 or Apr 30 has deviation zero. The anchor is accepted only if its largest
    deviation is at most ``SUGGESTION_DAY_WINDOW_DAYS``. Among acceptable anchors
    the one with the smallest largest deviation wins, then the smallest total
    deviation, then the smallest day: a fully determined, explainable choice.
    """
    if not dates:
        return None
    best: tuple[int, int, int] | None = None
    for anchor in range(1, 32):
        deviations = [
            abs(
                min(anchor, calendar.monthrange(value.year, value.month)[1]) - value.day
            )
            for value in dates
        ]
        worst = max(deviations)
        if worst > SUGGESTION_DAY_WINDOW_DAYS:
            continue
        candidate = (worst, sum(deviations), anchor)
        if best is None or candidate < best:
            best = candidate
    return None if best is None else best[2]


def _build_suggestion(
    *,
    installation_id: UUID,
    residence_id: UUID,
    account_id: UUID,
    owner_operator_id: UUID,
    currency: str,
    normalized: str,
    run: Sequence[FinancialRecurrenceObservation],
    day_of_month: int,
) -> FinancialRecurrenceSuggestion:
    amounts = [item.amount for item in run]
    fixed = all(amount == amounts[0] for amount in amounts)
    behavior = (
        FinancialRecurrenceSuggestionAmountBehavior.FIXED
        if fixed
        else FinancialRecurrenceSuggestionAmountBehavior.VARIABLE
    )
    reasons = (
        FinancialRecurrenceSuggestionReason.EXACT_DESCRIPTION,
        FinancialRecurrenceSuggestionReason.CONSECUTIVE_MONTHS,
        FinancialRecurrenceSuggestionReason.ONE_PER_MONTH,
        FinancialRecurrenceSuggestionReason.DAY_WINDOW,
        FinancialRecurrenceSuggestionReason.AMOUNT_FIXED
        if fixed
        else FinancialRecurrenceSuggestionReason.AMOUNT_VARIABLE,
    )
    last = run[-1]
    return FinancialRecurrenceSuggestion(
        fingerprint=recurrence_suggestion_fingerprint(
            installation_id=installation_id,
            residence_id=residence_id,
            account_id=account_id,
            currency=currency,
            normalized_description=normalized,
        ),
        account_id=account_id,
        account_owner_operator_id=owner_operator_id,
        description=(last.description or "").strip(),
        normalized_description=normalized,
        currency=currency,
        evidence=tuple(
            FinancialRecurrenceSuggestionEvidence(
                item.movement_id, item.effective_date, item.amount
            )
            for item in run
        ),
        suggested_day_of_month=day_of_month,
        suggested_expected_amount=Money(last.amount, currency),
        amount_behavior=behavior,
        min_amount=Money(min(amounts), currency),
        max_amount=Money(max(amounts), currency),
        last_amount=Money(last.amount, currency),
        reason_codes=reasons,
    )


# --- acceptance -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True, repr=False)
class FinancialRecurrenceSuggestionAcceptance:
    """The user's reviewed fields. Account, effect and currency are not theirs."""

    description: str
    expected_amount: Decimal
    start_date: date
    day_of_month: int
    end_date: date | None = None

    def __repr__(self) -> str:
        return "FinancialRecurrenceSuggestionAcceptance(<fields-redacted>)"

    def to_draft(
        self, suggestion: FinancialRecurrenceSuggestion
    ) -> FinancialRecurrenceDraft:
        """Build the canonical #254 draft; the suggestion fixes what the user cannot."""
        if not isinstance(suggestion, FinancialRecurrenceSuggestion):
            raise TypeError("suggestion must be FinancialRecurrenceSuggestion")
        return FinancialRecurrenceDraft(
            account_id=suggestion.account_id,
            description=self.description,
            result_effect=FinancialResultEffect.EXPENSE,
            expected=Money(self.expected_amount, suggestion.currency),
            start_date=self.start_date,
            day_of_month=self.day_of_month,
            end_date=self.end_date,
        )


__all__ = [
    "SUGGESTION_DAY_WINDOW_DAYS",
    "SUGGESTION_LIST_MAX",
    "SUGGESTION_MIN_MONTHS",
    "SUGGESTION_MIN_OBSERVATIONS",
    "SUGGESTION_SCAN_MAX",
    "SUGGESTION_WINDOW_MONTHS",
    "FinancialRecurrenceObservation",
    "FinancialRecurrenceRuleKey",
    "FinancialRecurrenceSuggestion",
    "FinancialRecurrenceSuggestionAcceptance",
    "FinancialRecurrenceSuggestionAmountBehavior",
    "FinancialRecurrenceSuggestionDecision",
    "FinancialRecurrenceSuggestionEvidence",
    "FinancialRecurrenceSuggestionReason",
    "detect_recurrence_suggestions",
    "normalize_recurrence_description",
    "recurrence_suggestion_fingerprint",
    "recurrence_suggestion_window",
    "suggest_day_of_month",
    "validate_recurrence_suggestion_fingerprint",
]
