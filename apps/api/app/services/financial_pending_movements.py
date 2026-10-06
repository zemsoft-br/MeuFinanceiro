"""Application orchestration of the derived pending-classification inbox.

The inbox is a read model. This service never writes, never persists inbox state
and never decides a financial rule: candidates come from the keyset store,
suggestions come from the unchanged #247 evaluation in the finance domain, and
classification itself stays with the #245 and #247 write paths.

Cost per request is bounded and independent of the number of Movements, accounts,
allocations, rules and categories: one rule read, one category read and, without
a rule-status filter, exactly one page read. A rule-status filter cannot be pushed
into SQL (matching lives only in the domain), so it scans at most
``MAX_SCAN_BATCHES`` keyset batches of ``SCAN_BATCH_SIZE`` candidates and then
stops: the page may be short, in which case a cursor is still returned.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_finance import (
    PENDING_PAGE_LIMIT_DEFAULT,
    PENDING_PAGE_LIMIT_MAX,
    FinancialCategorizationRuleRecord,
    FinancialCategoryRecord,
    FinancialPendingCursorError,
    FinancialPendingMovementCandidatePage,
    FinancialPendingMovementItem,
    FinancialPendingMovementKey,
    FinancialPendingRuleStatus,
    FinancialResultEffect,
    decode_pending_cursor,
    encode_pending_cursor,
    evaluate_pending_candidates,
    pending_filter_fingerprint,
    validate_financial_resource_id,
)

SCAN_BATCH_SIZE = PENDING_PAGE_LIMIT_MAX
MAX_SCAN_BATCHES = 5


class PendingMovementsRequestError(ValueError):
    """The request cannot be served: bad limit, filter or cursor."""


@runtime_checkable
class PendingMovementReadBoundary(Protocol):
    def list_pending_candidates(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        limit: int,
        after: FinancialPendingMovementKey | None = None,
        account_id: UUID | None = None,
        result_effect: FinancialResultEffect | None = None,
    ) -> FinancialPendingMovementCandidatePage: ...


@runtime_checkable
class PendingRuleReadBoundary(Protocol):
    def list_rules(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialCategorizationRuleRecord, ...]: ...


@runtime_checkable
class PendingCategoryReadBoundary(Protocol):
    def list_categories(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialCategoryRecord, ...]: ...


@dataclass(frozen=True, slots=True, repr=False)
class PendingMovementsPage:
    """One bounded page. ``next_cursor`` is set when more candidates may exist.

    With a rule-status filter the page can be shorter than requested (or empty)
    while ``next_cursor`` is still set: the scan budget ended, not the inbox.
    """

    items: tuple[FinancialPendingMovementItem, ...]
    next_cursor: str | None

    def __repr__(self) -> str:
        return f"PendingMovementsPage(size={len(self.items)})"


class FinancialPendingMovementService:
    """Page through unclassified Movements with their derived suggestion state."""

    def __init__(
        self,
        pending_store: PendingMovementReadBoundary,
        rule_store: PendingRuleReadBoundary,
        category_store: PendingCategoryReadBoundary,
    ) -> None:
        if not isinstance(pending_store, PendingMovementReadBoundary):
            raise TypeError("pending_store must satisfy PendingMovementReadBoundary")
        if not isinstance(rule_store, PendingRuleReadBoundary):
            raise TypeError("rule_store must satisfy PendingRuleReadBoundary")
        if not isinstance(category_store, PendingCategoryReadBoundary):
            raise TypeError("category_store must satisfy PendingCategoryReadBoundary")
        self._pending = pending_store
        self._rules = rule_store
        self._categories = category_store

    def list_pending(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        limit: int = PENDING_PAGE_LIMIT_DEFAULT,
        cursor: str | None = None,
        account_id: UUID | None = None,
        result_effect: FinancialResultEffect | None = None,
        rule_status: FinancialPendingRuleStatus | None = None,
    ) -> PendingMovementsPage:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise PendingMovementsRequestError("limit must be an integer")
        if not 1 <= limit <= PENDING_PAGE_LIMIT_MAX:
            raise PendingMovementsRequestError("limit is out of range")
        try:
            if account_id is not None:
                validate_financial_resource_id(account_id)
            if result_effect is not None and result_effect not in (
                FinancialResultEffect.INCOME,
                FinancialResultEffect.EXPENSE,
            ):
                raise ValueError("result_effect must be INCOME or EXPENSE")
            fingerprint = pending_filter_fingerprint(
                account_id=account_id,
                result_effect=result_effect,
                rule_status=rule_status,
            )
            after = (
                decode_pending_cursor(cursor, fingerprint=fingerprint)
                if cursor is not None
                else None
            )
        except (TypeError, ValueError, FinancialPendingCursorError):
            raise PendingMovementsRequestError("invalid pending request") from None

        scope = {
            "installation_id": installation_id,
            "residence_id": residence_id,
            "operator_id": operator_id,
        }
        # Read once per request, never per Movement, account or rule.
        rules = self._rules.list_rules(**scope)
        categories = {
            category.id: category
            for category in self._categories.list_categories(**scope)
        }

        if rule_status is None:
            page = self._pending.list_pending_candidates(
                limit=limit,
                after=after,
                account_id=account_id,
                result_effect=result_effect,
                **scope,
            )
            items = evaluate_pending_candidates(
                page.candidates,
                operator_id=operator_id,
                rules=rules,
                categories=categories,
            )
            return PendingMovementsPage(
                items=items,
                next_cursor=(
                    self._cursor(page.candidates[-1].key, fingerprint)
                    if page.has_more
                    else None
                ),
            )

        return self._filtered_page(
            scope=scope,
            limit=limit,
            after=after,
            account_id=account_id,
            result_effect=result_effect,
            rule_status=rule_status,
            fingerprint=fingerprint,
            rules=rules,
            categories=categories,
        )

    def _filtered_page(
        self,
        *,
        scope: dict[str, UUID],
        limit: int,
        after: FinancialPendingMovementKey | None,
        account_id: UUID | None,
        result_effect: FinancialResultEffect | None,
        rule_status: FinancialPendingRuleStatus,
        fingerprint: str,
        rules: Sequence[FinancialCategorizationRuleRecord],
        categories: dict[UUID, FinancialCategoryRecord],
    ) -> PendingMovementsPage:
        """Fill a page by scanning keyset batches under a fixed scan budget."""
        collected: list[FinancialPendingMovementItem] = []
        position = after
        for _ in range(MAX_SCAN_BATCHES):
            batch = self._pending.list_pending_candidates(
                limit=SCAN_BATCH_SIZE,
                after=position,
                account_id=account_id,
                result_effect=result_effect,
                **scope,
            )
            if not batch.candidates:
                return PendingMovementsPage(items=tuple(collected), next_cursor=None)
            evaluated = {
                item.candidate.movement.id: item
                for item in evaluate_pending_candidates(
                    batch.candidates,
                    operator_id=scope["operator_id"],
                    rules=rules,
                    categories=categories,
                )
            }
            for index, candidate in enumerate(batch.candidates):
                item = evaluated.get(candidate.movement.id)
                if item is None or item.rule_status is not rule_status:
                    continue
                collected.append(item)
                if len(collected) == limit:
                    # Resume right after the last returned item: the rest of the
                    # batch is rescanned by the next request, nothing is skipped.
                    more = batch.has_more or index + 1 < len(batch.candidates)
                    return PendingMovementsPage(
                        items=tuple(collected),
                        next_cursor=(
                            self._cursor(candidate.key, fingerprint) if more else None
                        ),
                    )
            position = batch.candidates[-1].key
            if not batch.has_more:
                return PendingMovementsPage(items=tuple(collected), next_cursor=None)
        # Scan budget spent with more candidates left: return what matched so far.
        return PendingMovementsPage(
            items=tuple(collected), next_cursor=self._cursor(position, fingerprint)
        )

    @staticmethod
    def _cursor(
        key: FinancialPendingMovementKey | None, fingerprint: str
    ) -> str | None:
        if key is None:
            return None
        return encode_pending_cursor(key, fingerprint=fingerprint)


__all__ = [
    "MAX_SCAN_BATCHES",
    "SCAN_BATCH_SIZE",
    "FinancialPendingMovementService",
    "PendingCategoryReadBoundary",
    "PendingMovementReadBoundary",
    "PendingMovementsPage",
    "PendingMovementsRequestError",
    "PendingRuleReadBoundary",
]
