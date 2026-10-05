"""Provider-neutral deterministic Movement categorization rule contracts.

A rule only ever *proposes* the first classification of an unclassified STANDARD
INCOME/EXPENSE Movement. It never writes the ledger and is never a second source
of classification authority: applying a rule produces the same append-only
allocation set as a manual classification, plus append-only provenance.

Matching is defined once, here, so preview and apply cannot disagree.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.allocations import (
    is_category_audience_compatible_for_movement,
)
from meufinanceiro_finance.categories import (
    FinancialCategoryRecord,
    FinancialCategoryStatus,
)
from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.movements import (
    FinancialMovementRole,
    FinancialResultEffect,
)

CATEGORIZATION_PATTERN_MAX_LENGTH = 256
CATEGORIZATION_PRIORITY_MIN = 1
CATEGORIZATION_PRIORITY_MAX = 1000

_APPLY_KEY_NAMESPACE = "meufinanceiro:categorization-rule-apply:v1"
_CATEGORIZABLE_EFFECTS = frozenset(
    (FinancialResultEffect.INCOME, FinancialResultEffect.EXPENSE)
)


class FinancialCategorizationMatcher(StrEnum):
    """How a rule compares its pattern with the Movement description."""

    EXACT = "EXACT"
    CONTAINS = "CONTAINS"


class FinancialCategorizationRuleStatus(StrEnum):
    """Lifecycle of one immutable rule version."""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class FinancialCategorizationEvaluationStatus(StrEnum):
    """Deterministic per-Movement result of evaluating the active rule set."""

    MATCHED = "MATCHED"
    NO_MATCH = "NO_MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    INELIGIBLE = "INELIGIBLE"
    ALREADY_CLASSIFIED = "ALREADY_CLASSIFIED"


class FinancialCategorizationApplyStatus(StrEnum):
    """Per-Movement outcome of one explicit rule application attempt."""

    CLASSIFIED = "CLASSIFIED"
    ALREADY_CLASSIFIED = "ALREADY_CLASSIFIED"
    AMBIGUOUS = "AMBIGUOUS"
    NO_MATCH = "NO_MATCH"
    INELIGIBLE = "INELIGIBLE"
    CONFLICT = "CONFLICT"
    FAILED = "FAILED"


def normalize_categorization_text(value: str) -> str:
    """Return the single canonical form used to compare descriptions.

    Outer Unicode whitespace is trimmed and the text is case-folded using
    canonical-equivalence-safe composition (NFC before and after folding).
    Accents, punctuation and inner whitespace are intentionally preserved and
    nothing depends on the client or process locale.
    """
    if not isinstance(value, str):
        raise TypeError("text must be a string")
    composed = unicodedata.normalize("NFC", value.strip())
    return unicodedata.normalize("NFC", composed.casefold())


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCategorizationRuleDraft:
    """Trusted rule creation intent. Semantics are immutable once persisted."""

    description_matcher: FinancialCategorizationMatcher
    description_pattern: str
    target_category_id: UUID
    priority: int
    account_id: UUID | None = None
    result_effect: FinancialResultEffect | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.description_matcher, FinancialCategorizationMatcher):
            raise TypeError(
                "description_matcher must be FinancialCategorizationMatcher"
            )
        object.__setattr__(
            self, "description_pattern", _clean_pattern(self.description_pattern)
        )
        validate_financial_resource_id(self.target_category_id)
        _validate_priority(self.priority)
        if self.account_id is not None:
            validate_financial_resource_id(self.account_id)
        _validate_rule_effect(self.result_effect)

    def canonical_material(self) -> tuple[str, ...]:
        """Return stable material for idempotency request digests."""
        return (
            self.description_matcher.value,
            normalize_categorization_text(self.description_pattern),
            self.description_pattern,
            str(self.target_category_id),
            str(self.priority),
            str(self.account_id) if self.account_id is not None else "ANY_ACCOUNT",
            self.result_effect.value if self.result_effect is not None else "ANY",
        )

    def __repr__(self) -> str:
        return (
            "FinancialCategorizationRuleDraft("
            f"description_matcher={self.description_matcher.value!r}, "
            f"priority={self.priority}, <pattern-and-targets-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCategorizationRuleRecord:
    """One persisted, semantically immutable categorization rule version."""

    id: UUID
    residence_id: UUID
    created_by_operator_id: UUID
    account_id: UUID | None
    result_effect: FinancialResultEffect | None
    description_matcher: FinancialCategorizationMatcher
    description_pattern: str
    target_category_id: UUID
    priority: int
    status: FinancialCategorizationRuleStatus
    created_at: datetime
    disabled_at: datetime | None
    disabled_by_operator_id: UUID | None
    normalized_pattern: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        _require_uuid(self.residence_id, "residence_id")
        _require_uuid(self.created_by_operator_id, "created_by_operator_id")
        if self.account_id is not None:
            validate_financial_resource_id(self.account_id)
        _validate_rule_effect(self.result_effect)
        if not isinstance(self.description_matcher, FinancialCategorizationMatcher):
            raise TypeError(
                "description_matcher must be FinancialCategorizationMatcher"
            )
        object.__setattr__(
            self, "description_pattern", _clean_pattern(self.description_pattern)
        )
        validate_financial_resource_id(self.target_category_id)
        _validate_priority(self.priority)
        if not isinstance(self.status, FinancialCategorizationRuleStatus):
            raise TypeError("status must be FinancialCategorizationRuleStatus")
        _require_aware(self.created_at, "created_at")
        if self.status is FinancialCategorizationRuleStatus.ACTIVE:
            if self.disabled_at is not None or self.disabled_by_operator_id is not None:
                raise ValueError("active rule must not have disable fields")
        else:
            if self.disabled_at is None or self.disabled_by_operator_id is None:
                raise ValueError("disabled rule requires disable fields")
            _require_aware(self.disabled_at, "disabled_at")
            _require_uuid(self.disabled_by_operator_id, "disabled_by_operator_id")
            if self.disabled_at < self.created_at:
                raise ValueError("disabled_at must not precede created_at")
        object.__setattr__(
            self,
            "normalized_pattern",
            normalize_categorization_text(self.description_pattern),
        )

    @property
    def is_active(self) -> bool:
        return self.status is FinancialCategorizationRuleStatus.ACTIVE

    def applies_to(self, movement: FinancialMovementRecord) -> bool:
        """Return whether this ACTIVE rule's conditions all hold for a Movement.

        Category usability is deliberately *not* decided here: it depends on
        canonical category state and is applied by ``usable_categorization_rules``
        before resolution.
        """
        if not isinstance(movement, FinancialMovementRecord):
            raise TypeError("movement must be FinancialMovementRecord")
        if not self.is_active or not is_movement_categorizable(movement):
            return False
        if self.account_id is not None and self.account_id != movement.account_id:
            return False
        if (
            self.result_effect is not None
            and self.result_effect is not movement.result_effect
        ):
            return False
        description = normalize_categorization_text(movement.description or "")
        if self.description_matcher is FinancialCategorizationMatcher.EXACT:
            return description == self.normalized_pattern
        return self.normalized_pattern in description

    def __repr__(self) -> str:
        return (
            "FinancialCategorizationRuleRecord("
            f"description_matcher={self.description_matcher.value!r}, "
            f"status={self.status.value!r}, priority={self.priority}, "
            "<identity-pattern-and-targets-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCategorizationEvaluation:
    """Result of evaluating one Movement. ``rule`` is set only for MATCHED."""

    status: FinancialCategorizationEvaluationStatus
    rule: FinancialCategorizationRuleRecord | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, FinancialCategorizationEvaluationStatus):
            raise TypeError("status must be FinancialCategorizationEvaluationStatus")
        matched = self.status is FinancialCategorizationEvaluationStatus.MATCHED
        if matched != (self.rule is not None):
            raise ValueError("only a MATCHED evaluation carries a rule")

    def __repr__(self) -> str:
        return f"FinancialCategorizationEvaluation(status={self.status.value!r})"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialCategorizationApplyResult:
    """Canonical outcome of applying one expected rule to one Movement."""

    movement_id: UUID
    status: FinancialCategorizationApplyStatus
    rule_id: UUID | None = None
    allocation_set_id: UUID | None = None

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.movement_id)
        if not isinstance(self.status, FinancialCategorizationApplyStatus):
            raise TypeError("status must be FinancialCategorizationApplyStatus")
        if self.rule_id is not None:
            validate_financial_resource_id(self.rule_id)
        if self.allocation_set_id is not None:
            validate_financial_resource_id(self.allocation_set_id)
        classified = self.status is FinancialCategorizationApplyStatus.CLASSIFIED
        if classified != (self.allocation_set_id is not None):
            raise ValueError("only a CLASSIFIED result carries an allocation set")

    def __repr__(self) -> str:
        return (
            f"FinancialCategorizationApplyResult(status={self.status.value!r}, "
            "<identities-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialMovementAllocationRuleOrigin:
    """Append-only provenance linking a first allocation set to the rule applied.

    Evidence only: it never decides which classification is current.
    """

    allocation_set_id: UUID
    movement_id: UUID
    rule_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.allocation_set_id)
        validate_financial_resource_id(self.movement_id)
        validate_financial_resource_id(self.rule_id)
        _require_aware(self.created_at, "created_at")

    def __repr__(self) -> str:
        return "FinancialMovementAllocationRuleOrigin(<identities-redacted>)"


def is_movement_categorizable(movement: FinancialMovementRecord) -> bool:
    """Only STANDARD INCOME/EXPENSE Movements can be classified by a rule."""
    return (
        movement.role is FinancialMovementRole.STANDARD
        and movement.result_effect in _CATEGORIZABLE_EFFECTS
    )


def is_categorization_target_usable(
    category: FinancialCategoryRecord,
    *,
    account_visibility_scope: FinancialVisibilityScope,
    account_owner_operator_id: UUID,
) -> bool:
    """Return whether a category is ACTIVE and audience-compatible with an account."""
    if category.status is not FinancialCategoryStatus.ACTIVE:
        return False
    return is_category_audience_compatible_for_movement(
        movement_visibility_scope=account_visibility_scope,
        movement_owner_operator_id=account_owner_operator_id,
        category_visibility_scope=category.visibility_scope,
        category_owner_operator_id=category.owner_operator_id,
    )


def usable_categorization_rules(
    rules: Sequence[FinancialCategorizationRuleRecord],
    *,
    categories: Mapping[UUID, FinancialCategoryRecord],
    account_visibility_scope: FinancialVisibilityScope,
    account_owner_operator_id: UUID,
) -> tuple[FinancialCategorizationRuleRecord, ...]:
    """Discard rules that cannot produce a valid write before priority resolution.

    A rule whose target category is missing, DISABLED or audience-incompatible
    with the account never competes (it neither wins nor creates a tie).
    """
    usable: list[FinancialCategorizationRuleRecord] = []
    for rule in rules:
        category = categories.get(rule.target_category_id)
        if category is None:
            continue
        if is_categorization_target_usable(
            category,
            account_visibility_scope=account_visibility_scope,
            account_owner_operator_id=account_owner_operator_id,
        ):
            usable.append(rule)
    return tuple(usable)


def evaluate_movement_categorization(
    movement: FinancialMovementRecord,
    *,
    already_classified: bool,
    rules: Sequence[FinancialCategorizationRuleRecord],
) -> FinancialCategorizationEvaluation:
    """Evaluate one Movement against already-usable rules, failing closed.

    Order is part of the contract: ineligible roles/effects first, then an
    existing classification (never revised by a rule), then priority resolution.
    A tie on the highest priority is AMBIGUOUS: no creation time, id or query
    order is ever used to break it.
    """
    status = FinancialCategorizationEvaluationStatus
    if not is_movement_categorizable(movement):
        return FinancialCategorizationEvaluation(status.INELIGIBLE)
    if already_classified:
        return FinancialCategorizationEvaluation(status.ALREADY_CLASSIFIED)

    applicable = [rule for rule in rules if rule.applies_to(movement)]
    if not applicable:
        return FinancialCategorizationEvaluation(status.NO_MATCH)
    top_priority = max(rule.priority for rule in applicable)
    winners = [rule for rule in applicable if rule.priority == top_priority]
    if len(winners) != 1:
        return FinancialCategorizationEvaluation(status.AMBIGUOUS)
    return FinancialCategorizationEvaluation(status.MATCHED, winners[0])


def categorization_apply_idempotency_key(rule_id: UUID, movement_id: UUID) -> UUID:
    """Derive the deterministic per-Movement key of one rule application.

    One rule can classify one Movement at most once, so the pair identifies the
    logical operation. The result is a UUID v4-shaped value so it satisfies the
    allocation idempotency contract; it is derived, never randomly regenerated.
    """
    validate_financial_resource_id(rule_id)
    validate_financial_resource_id(movement_id)
    digest = bytearray(
        hashlib.sha256(
            f"{_APPLY_KEY_NAMESPACE}:{rule_id}:{movement_id}".encode()
        ).digest()[:16]
    )
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(digest))


def _clean_pattern(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("description_pattern must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("description_pattern must not be empty")
    if len(cleaned) > CATEGORIZATION_PATTERN_MAX_LENGTH:
        raise ValueError(
            f"description_pattern exceeds {CATEGORIZATION_PATTERN_MAX_LENGTH} characters"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise ValueError("description_pattern contains control characters")
    return cleaned


def _validate_priority(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("priority must be an integer")
    if not CATEGORIZATION_PRIORITY_MIN <= value <= CATEGORIZATION_PRIORITY_MAX:
        raise ValueError(
            f"priority must be between {CATEGORIZATION_PRIORITY_MIN} "
            f"and {CATEGORIZATION_PRIORITY_MAX}"
        )


def _validate_rule_effect(value: FinancialResultEffect | None) -> None:
    if value is None:
        return
    if not isinstance(value, FinancialResultEffect):
        raise TypeError("result_effect must be FinancialResultEffect")
    if value not in _CATEGORIZABLE_EFFECTS:
        raise ValueError("result_effect must be INCOME or EXPENSE")


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "CATEGORIZATION_PATTERN_MAX_LENGTH",
    "CATEGORIZATION_PRIORITY_MAX",
    "CATEGORIZATION_PRIORITY_MIN",
    "FinancialCategorizationApplyResult",
    "FinancialCategorizationApplyStatus",
    "FinancialCategorizationEvaluation",
    "FinancialCategorizationEvaluationStatus",
    "FinancialCategorizationMatcher",
    "FinancialCategorizationRuleDraft",
    "FinancialCategorizationRuleRecord",
    "FinancialCategorizationRuleStatus",
    "FinancialMovementAllocationRuleOrigin",
    "categorization_apply_idempotency_key",
    "evaluate_movement_categorization",
    "is_categorization_target_usable",
    "is_movement_categorizable",
    "normalize_categorization_text",
    "usable_categorization_rules",
]
