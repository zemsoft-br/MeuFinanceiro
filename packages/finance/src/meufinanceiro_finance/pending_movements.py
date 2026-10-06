"""Provider-neutral contracts of the derived pending-classification inbox.

A pending Movement is a *derived* fact, never persisted state: at the current
canonical state it is a STANDARD INCOME/EXPENSE Movement, visible to the operator,
with no allocation set. Nothing here is a second authority: the ledger stays in
``finance.movements`` and classification stays in ``movement_allocation_sets``.
The suggestion state is the unchanged #247 evaluation, never a new matcher.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.accounts import FinancialAccountStatus
from meufinanceiro_finance.categories import FinancialCategoryRecord
from meufinanceiro_finance.categorization_rules import (
    FinancialCategorizationEvaluationStatus,
    FinancialCategorizationRuleRecord,
    evaluate_movement_categorization,
    usable_categorization_rules,
)
from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.movements import FinancialResultEffect

PENDING_PAGE_LIMIT_DEFAULT = 50
PENDING_PAGE_LIMIT_MAX = 100

_CURSOR_VERSION = 1
_CURSOR_MAX_LENGTH = 256
_CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{16}$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FinancialPendingRuleStatus(StrEnum):
    """Derived suggestion state of one pending Movement (never persisted)."""

    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    NO_MATCH = "NO_MATCH"


class FinancialPendingCursorError(ValueError):
    """The pagination cursor is malformed or belongs to other filters."""


@dataclass(frozen=True, slots=True, repr=False)
class FinancialPendingMovementKey:
    """Keyset position of a pending Movement: ``effective_date`` then ``id``.

    The order is ``effective_date DESC, id DESC``. The key is an exact ledger
    coordinate, so it stays valid when Movements are appended or classified
    concurrently (unlike an offset).
    """

    effective_date: date
    movement_id: UUID

    def __post_init__(self) -> None:
        if type(self.effective_date) is not date:
            raise TypeError("effective_date must be date")
        validate_financial_resource_id(self.movement_id)

    def __repr__(self) -> str:
        return "FinancialPendingMovementKey(<position-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialPendingMovementCandidate:
    """One unclassified, visible Movement with the account facts that rules need.

    Account facts come from the same row read, so evaluating rules and deciding
    ``can_classify`` never costs another read per Movement or per account.
    """

    movement: FinancialMovementRecord
    account_visibility_scope: FinancialVisibilityScope
    account_owner_operator_id: UUID
    account_status: FinancialAccountStatus

    def __post_init__(self) -> None:
        if not isinstance(self.movement, FinancialMovementRecord):
            raise TypeError("movement must be FinancialMovementRecord")
        if not isinstance(self.account_visibility_scope, FinancialVisibilityScope):
            raise TypeError("account_visibility_scope must be FinancialVisibilityScope")
        if not isinstance(self.account_owner_operator_id, UUID):
            raise TypeError("account_owner_operator_id must be UUID")
        if not isinstance(self.account_status, FinancialAccountStatus):
            raise TypeError("account_status must be FinancialAccountStatus")

    @property
    def key(self) -> FinancialPendingMovementKey:
        return FinancialPendingMovementKey(
            effective_date=self.movement.effective_date,
            movement_id=self.movement.id,
        )

    def can_classify(self, operator_id: UUID) -> bool:
        """Whether the operator could classify it: owner of an ACTIVE account.

        Mirrors the write authority of manual classification and rule apply
        (``_owned_active_account``). A visible item may still be read-only.
        """
        return (
            self.account_owner_operator_id == operator_id
            and self.account_status is FinancialAccountStatus.ACTIVE
        )

    def __repr__(self) -> str:
        return "FinancialPendingMovementCandidate(<movement-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialPendingMovementCandidatePage:
    """A bounded keyset page of candidates, in ``effective_date DESC, id DESC``."""

    candidates: tuple[FinancialPendingMovementCandidate, ...]
    has_more: bool

    def __post_init__(self) -> None:
        if len(self.candidates) > PENDING_PAGE_LIMIT_MAX:
            raise ValueError("pending page exceeds the maximum page size")
        if self.has_more and not self.candidates:
            raise ValueError("an empty page cannot have more candidates")

    def __repr__(self) -> str:
        return (
            f"FinancialPendingMovementCandidatePage(size={len(self.candidates)}, "
            f"has_more={self.has_more})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialPendingMovementItem:
    """One pending Movement with its derived suggestion and write capability.

    ``rule`` is present exactly for ``MATCHED``; an ``AMBIGUOUS`` item never
    carries a rule, so nothing can be applied automatically.
    """

    candidate: FinancialPendingMovementCandidate
    rule_status: FinancialPendingRuleStatus
    rule: FinancialCategorizationRuleRecord | None
    can_classify: bool

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, FinancialPendingMovementCandidate):
            raise TypeError("candidate must be FinancialPendingMovementCandidate")
        if not isinstance(self.rule_status, FinancialPendingRuleStatus):
            raise TypeError("rule_status must be FinancialPendingRuleStatus")
        matched = self.rule_status is FinancialPendingRuleStatus.MATCHED
        if matched != (self.rule is not None):
            raise ValueError("only a MATCHED item carries a rule")

    def __repr__(self) -> str:
        return f"FinancialPendingMovementItem(rule_status={self.rule_status.value!r})"


def evaluate_pending_candidates(
    candidates: Sequence[FinancialPendingMovementCandidate],
    *,
    operator_id: UUID,
    rules: Sequence[FinancialCategorizationRuleRecord],
    categories: Mapping[UUID, FinancialCategoryRecord],
) -> tuple[FinancialPendingMovementItem, ...]:
    """Derive each candidate's suggestion with the exact #247 evaluation.

    Per candidate this is the preview/apply pipeline unchanged: only ACTIVE
    rules for the Movement's account compete, rules whose target category is
    missing, DISABLED or audience-incompatible with that account are discarded
    first, and priority resolution fails closed on a tie. Nothing is matched
    here. A candidate whose evaluation is not a pending state (it became
    ineligible after the read) is dropped. Rule filtering is done once per
    account, so the cost does not grow with the number of Movements.
    """
    evaluated = FinancialCategorizationEvaluationStatus
    usable_by_account: dict[UUID, tuple[FinancialCategorizationRuleRecord, ...]] = {}
    items: list[FinancialPendingMovementItem] = []
    for candidate in candidates:
        account_id = candidate.movement.account_id
        usable = usable_by_account.get(account_id)
        if usable is None:
            usable = usable_categorization_rules(
                [
                    rule
                    for rule in rules
                    if rule.is_active and rule.account_id in (None, account_id)
                ],
                categories=categories,
                account_visibility_scope=candidate.account_visibility_scope,
                account_owner_operator_id=candidate.account_owner_operator_id,
            )
            usable_by_account[account_id] = usable
        evaluation = evaluate_movement_categorization(
            candidate.movement, already_classified=False, rules=usable
        )
        if evaluation.status is evaluated.MATCHED:
            rule_status = FinancialPendingRuleStatus.MATCHED
        elif evaluation.status is evaluated.AMBIGUOUS:
            rule_status = FinancialPendingRuleStatus.AMBIGUOUS
        elif evaluation.status is evaluated.NO_MATCH:
            rule_status = FinancialPendingRuleStatus.NO_MATCH
        else:
            continue
        items.append(
            FinancialPendingMovementItem(
                candidate=candidate,
                rule_status=rule_status,
                rule=evaluation.rule,
                can_classify=candidate.can_classify(operator_id),
            )
        )
    return tuple(items)


def pending_filter_fingerprint(
    *,
    account_id: UUID | None,
    result_effect: FinancialResultEffect | None,
    rule_status: FinancialPendingRuleStatus | None,
) -> str:
    """Fingerprint the active filters so a cursor cannot cross filter sets."""
    material = "|".join(
        (
            "pending:v1",
            str(account_id) if account_id is not None else "-",
            result_effect.value if result_effect is not None else "-",
            rule_status.value if rule_status is not None else "-",
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def encode_pending_cursor(key: FinancialPendingMovementKey, *, fingerprint: str) -> str:
    """Encode a keyset position as an opaque URL-safe cursor.

    The cursor carries a ledger coordinate only. It is not an authorization
    token: visibility is always decided by RLS on the read it feeds.
    """
    if not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
        raise ValueError("fingerprint must be 16 lowercase hex characters")
    payload = json.dumps(
        {
            "v": _CURSOR_VERSION,
            "d": key.effective_date.isoformat(),
            "i": str(key.movement_id),
            "f": fingerprint,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        base64.urlsafe_b64encode(payload.encode("ascii")).rstrip(b"=").decode("ascii")
    )


def decode_pending_cursor(
    cursor: str, *, fingerprint: str
) -> FinancialPendingMovementKey:
    """Decode a cursor, failing closed on any malformation or filter mismatch."""
    invalid = FinancialPendingCursorError("pending cursor is invalid")
    if (
        not isinstance(cursor, str)
        or not 1 <= len(cursor) <= _CURSOR_MAX_LENGTH
        or not _CURSOR_PATTERN.fullmatch(cursor)
    ):
        raise invalid
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw.decode("ascii"))
    except (binascii.Error, UnicodeError, ValueError):
        raise invalid from None
    if not isinstance(payload, dict) or set(payload) != {"v", "d", "i", "f"}:
        raise invalid
    version, day, identity, bound = (
        payload["v"],
        payload["d"],
        payload["i"],
        payload["f"],
    )
    if type(version) is not int or version != _CURSOR_VERSION:
        raise invalid
    if (
        not isinstance(day, str)
        or not _DATE_PATTERN.fullmatch(day)
        or not isinstance(identity, str)
        or not isinstance(bound, str)
        or bound != fingerprint
    ):
        raise invalid
    try:
        movement_id = UUID(identity)
        if str(movement_id) != identity:
            raise invalid
        return FinancialPendingMovementKey(
            effective_date=date.fromisoformat(day), movement_id=movement_id
        )
    except (TypeError, ValueError):
        raise invalid from None


__all__ = [
    "PENDING_PAGE_LIMIT_DEFAULT",
    "PENDING_PAGE_LIMIT_MAX",
    "FinancialPendingCursorError",
    "FinancialPendingMovementCandidate",
    "FinancialPendingMovementCandidatePage",
    "FinancialPendingMovementItem",
    "FinancialPendingMovementKey",
    "FinancialPendingRuleStatus",
    "decode_pending_cursor",
    "encode_pending_cursor",
    "evaluate_pending_candidates",
    "pending_filter_fingerprint",
]
