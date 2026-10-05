"""Application orchestration for deterministic Movement categorization rules.

Preview is read-only and explanatory; it never reserves or guarantees anything.
Apply is explicit: every confirmed ``(Movement, rule)`` pair is re-evaluated from
canonical state by the store, one atomic transaction per Movement, and the result
of each pair is reported so a partial outcome is never presented as full success.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_finance import (
    FinancialAccountRecord,
    FinancialAccountStatus,
    FinancialCategorizationApplyResult,
    FinancialCategorizationApplyStatus,
    FinancialCategorizationEvaluationStatus,
    FinancialCategorizationRuleDraft,
    FinancialCategorizationRuleRecord,
    FinancialCategoryRecord,
    FinancialMovementAllocationRuleOrigin,
    FinancialMovementAllocationSetRecord,
    FinancialMovementRecord,
    evaluate_movement_categorization,
    usable_categorization_rules,
)
from meufinanceiro_persistence.financial_categorization_rule_store import (
    FinancialCategorizationRuleAccessError,
    FinancialCategorizationRuleAccountNotFoundError,
    FinancialCategorizationRulePersistenceError,
)

MAX_APPLY_ITEMS = 200


@runtime_checkable
class CategorizationRuleStoreBoundary(Protocol):
    def create_rule(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialCategorizationRuleDraft,
    ) -> FinancialCategorizationRuleRecord: ...

    def list_rules(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialCategorizationRuleRecord, ...]: ...

    def disable_rule(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        rule_id: UUID,
    ) -> FinancialCategorizationRuleRecord: ...

    def list_current_rule_origins(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialMovementAllocationRuleOrigin, ...]: ...

    def apply_rule_to_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
        movement_id: UUID,
        expected_rule_id: UUID,
    ) -> FinancialCategorizationApplyResult: ...


@runtime_checkable
class CategorizationAccountReadBoundary(Protocol):
    def get_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountRecord: ...


@runtime_checkable
class CategorizationMovementReadBoundary(Protocol):
    def list_movements(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialMovementRecord, ...]: ...


@runtime_checkable
class CategorizationAllocationReadBoundary(Protocol):
    def list_current_allocation_sets(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialMovementAllocationSetRecord, ...]: ...


@runtime_checkable
class CategorizationCategoryReadBoundary(Protocol):
    def list_categories(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialCategoryRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class CategorizationApplyRequestItem:
    """One Movement/rule pair the operator confirmed after a preview."""

    movement_id: UUID
    rule_id: UUID


@dataclass(frozen=True, slots=True, repr=False)
class CategorizationPreviewItem:
    movement_id: UUID
    status: FinancialCategorizationEvaluationStatus
    rule_id: UUID | None
    target_category_id: UUID | None

    def __repr__(self) -> str:
        return f"CategorizationPreviewItem(status={self.status.value!r})"


@dataclass(frozen=True, slots=True, repr=False)
class CategorizationPreview:
    account_id: UUID
    total_movements: int
    counts: dict[FinancialCategorizationEvaluationStatus, int]
    items: tuple[CategorizationPreviewItem, ...]
    # More Movements matched than one apply request can carry
    # (``MAX_APPLY_ITEMS``): confirm the first ones, then preview again.
    applicable_truncated: bool

    def __repr__(self) -> str:
        return f"CategorizationPreview(total_movements={self.total_movements})"


@dataclass(frozen=True, slots=True, repr=False)
class CategorizationApplyOutcome:
    account_id: UUID
    requested: int
    counts: dict[FinancialCategorizationApplyStatus, int]
    results: tuple[FinancialCategorizationApplyResult, ...]

    def __repr__(self) -> str:
        return f"CategorizationApplyOutcome(requested={self.requested})"


class FinancialCategorizationService:
    """Delegate rule operations to the canonical stores; never decide finance here."""

    def __init__(
        self,
        rule_store: CategorizationRuleStoreBoundary,
        account_store: CategorizationAccountReadBoundary,
        movement_store: CategorizationMovementReadBoundary,
        allocation_store: CategorizationAllocationReadBoundary,
        category_store: CategorizationCategoryReadBoundary,
    ) -> None:
        if not isinstance(rule_store, CategorizationRuleStoreBoundary):
            raise TypeError("rule_store must satisfy CategorizationRuleStoreBoundary")
        if not isinstance(account_store, CategorizationAccountReadBoundary):
            raise TypeError(
                "account_store must satisfy CategorizationAccountReadBoundary"
            )
        if not isinstance(movement_store, CategorizationMovementReadBoundary):
            raise TypeError(
                "movement_store must satisfy CategorizationMovementReadBoundary"
            )
        if not isinstance(allocation_store, CategorizationAllocationReadBoundary):
            raise TypeError(
                "allocation_store must satisfy CategorizationAllocationReadBoundary"
            )
        if not isinstance(category_store, CategorizationCategoryReadBoundary):
            raise TypeError(
                "category_store must satisfy CategorizationCategoryReadBoundary"
            )
        self._rules = rule_store
        self._accounts = account_store
        self._movements = movement_store
        self._allocations = allocation_store
        self._categories = category_store

    def create_rule(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialCategorizationRuleDraft,
    ) -> FinancialCategorizationRuleRecord:
        return self._rules.create_rule(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )

    def list_rules(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialCategorizationRuleRecord, ...]:
        return self._rules.list_rules(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
        )

    def disable_rule(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        rule_id: UUID,
    ) -> FinancialCategorizationRuleRecord:
        return self._rules.disable_rule(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            rule_id=rule_id,
        )

    def list_rule_origins(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialMovementAllocationRuleOrigin, ...]:
        return self._rules.list_current_rule_origins(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )

    def preview(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> CategorizationPreview:
        """Evaluate every Movement of an owned account without writing anything.

        A constant number of reads regardless of Movement count: account,
        Movements, current classifications, rules and categories. The preview is
        advisory: it takes no lock, and apply re-evaluates under the rule-set and
        Movement locks.
        """
        scope = {
            "installation_id": installation_id,
            "residence_id": residence_id,
            "operator_id": operator_id,
        }
        account = self._owned_active_account(account_id=account_id, **scope)
        movements = self._movements.list_movements(account_id=account_id, **scope)
        classified = {
            record.movement_id
            for record in self._allocations.list_current_allocation_sets(
                account_id=account_id, **scope
            )
        }
        rules = tuple(
            rule
            for rule in self._rules.list_rules(**scope)
            if rule.is_active and rule.account_id in (None, account.id)
        )
        categories = {
            item.id: item for item in self._categories.list_categories(**scope)
        }
        usable = usable_categorization_rules(
            rules,
            categories=categories,
            account_visibility_scope=account.visibility_scope,
            account_owner_operator_id=account.owner_operator_id,
        )

        status = FinancialCategorizationEvaluationStatus
        counts: Counter[FinancialCategorizationEvaluationStatus] = Counter()
        items: list[CategorizationPreviewItem] = []
        for movement in movements:
            evaluation = evaluate_movement_categorization(
                movement,
                already_classified=movement.id in classified,
                rules=usable,
            )
            counts[evaluation.status] += 1
            # Every Movement is reported with its own state; the rule and target
            # are present only for MATCHED, where they are semantically valid.
            rule = evaluation.rule
            items.append(
                CategorizationPreviewItem(
                    movement_id=movement.id,
                    status=evaluation.status,
                    rule_id=rule.id if rule is not None else None,
                    target_category_id=(
                        rule.target_category_id if rule is not None else None
                    ),
                )
            )
        return CategorizationPreview(
            account_id=account.id,
            total_movements=len(movements),
            counts={item: counts.get(item, 0) for item in status},
            items=tuple(items),
            applicable_truncated=counts[status.MATCHED] > MAX_APPLY_ITEMS,
        )

    def apply(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
        items: Sequence[CategorizationApplyRequestItem],
    ) -> CategorizationApplyOutcome:
        """Apply the confirmed pairs one atomic transaction at a time.

        A store failure for one pair is reported as FAILED for that pair and the
        remaining pairs still run; access/ownership failures abort before any
        write. Nothing is ever retried automatically.
        """
        if not 1 <= len(items) <= MAX_APPLY_ITEMS:
            raise ValueError("apply items out of range")
        if len({item.movement_id for item in items}) != len(items):
            raise ValueError("apply items must name each Movement once")
        scope = {
            "installation_id": installation_id,
            "residence_id": residence_id,
            "operator_id": operator_id,
        }
        self._owned_active_account(account_id=account_id, **scope)

        results: list[FinancialCategorizationApplyResult] = []
        for item in items:
            try:
                results.append(
                    self._rules.apply_rule_to_movement(
                        account_id=account_id,
                        movement_id=item.movement_id,
                        expected_rule_id=item.rule_id,
                        **scope,
                    )
                )
            except (
                FinancialCategorizationRuleAccessError,
                FinancialCategorizationRuleAccountNotFoundError,
            ):
                raise
            except FinancialCategorizationRulePersistenceError:
                results.append(
                    FinancialCategorizationApplyResult(
                        movement_id=item.movement_id,
                        status=FinancialCategorizationApplyStatus.FAILED,
                        rule_id=item.rule_id,
                    )
                )
        counts = Counter(result.status for result in results)
        return CategorizationApplyOutcome(
            account_id=account_id,
            requested=len(items),
            counts={
                item: counts.get(item, 0) for item in FinancialCategorizationApplyStatus
            },
            results=tuple(results),
        )

    def _owned_active_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountRecord:
        """Rules write only where the actor could classify manually: owned, ACTIVE."""
        account = self._accounts.get_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
        if (
            account.owner_operator_id != operator_id
            or account.status is not FinancialAccountStatus.ACTIVE
        ):
            raise FinancialCategorizationRuleAccountNotFoundError(
                "financial account was not found"
            )
        return account


__all__ = [
    "MAX_APPLY_ITEMS",
    "CategorizationAccountReadBoundary",
    "CategorizationAllocationReadBoundary",
    "CategorizationApplyOutcome",
    "CategorizationApplyRequestItem",
    "CategorizationCategoryReadBoundary",
    "CategorizationMovementReadBoundary",
    "CategorizationPreview",
    "CategorizationPreviewItem",
    "CategorizationRuleStoreBoundary",
    "FinancialCategorizationService",
]
