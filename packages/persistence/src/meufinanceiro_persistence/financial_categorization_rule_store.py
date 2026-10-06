"""Residence/operator-aware persistence for deterministic categorization rules.

Rules never write the ledger. Applying a rule appends the same first allocation
set a manual classification would, plus append-only provenance and the financial
audit event, in one transaction per Movement. Everything that decides a write is
re-evaluated from canonical state inside that transaction, after the Movement
row lock that also serializes manual classification.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from meufinanceiro_finance import (
    FinancialCategorizationApplyResult,
    FinancialCategorizationApplyStatus,
    FinancialCategorizationEvaluationStatus,
    FinancialCategorizationMatcher,
    FinancialCategorizationRuleDraft,
    FinancialCategorizationRuleRecord,
    FinancialCategorizationRuleStatus,
    FinancialCategoryRecord,
    FinancialCategoryStatus,
    FinancialMovementAllocationDraft,
    FinancialMovementAllocationRuleOrigin,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    categorization_apply_idempotency_key,
    evaluate_movement_categorization,
    is_category_audience_compatible_for_movement,
    new_financial_resource_id,
    usable_categorization_rules,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from sqlalchemy import Connection, Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_categorization_rule_schema import (
    financial_categorization_rules,
    financial_movement_allocation_rule_origins,
)
from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.financial_category_store import (
    _record as _category_record,
)
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
)
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationCategoryNotFoundError,
    FinancialMovementAllocationInvalidShapeError,
    _append_allocation_set,
    _current_set_row,
    _lock_eligible_movement,
    _owned_active_account,
    _prepare_connection,
    _request_digest as _allocation_request_digest,
    _validate_categories,
    _validate_economic_shape,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    FinancialMovementPersistenceError,
    _record as _movement_record,
)

_REQUEST_DIGEST_NAMESPACE = "meufinanceiro:categorization-rule-create:v1"
_RULE_SET_LOCK_NAMESPACE = "meufinanceiro:categorization-rule-set-lock:v1"


def categorization_rule_set_lock_key(installation_id: UUID, residence_id: UUID) -> int:
    """Fold (namespace, installation, residence) into a signed 64-bit advisory key.

    Residence-scoped on purpose: a global rule (``account_id IS NULL``) can affect
    any account of the residence, so a per-account lock would not be enough. The
    namespace keeps the key space apart from every other advisory lock (banking).
    """
    digest = hashlib.sha256(
        f"{_RULE_SET_LOCK_NAMESPACE}:{installation_id}:{residence_id}".encode()
    ).digest()
    value = int.from_bytes(digest[:8], "big", signed=True)
    return value


def _acquire_rule_set_lock(
    connection: Connection, *, installation_id: UUID, residence_id: UUID
) -> None:
    """Take the residence rule-set lock for the rest of the transaction.

    One contract for every participant: ``create_rule``, ``disable_rule`` and
    ``apply_rule_to_movement`` all acquire it first (for apply: before reading
    rules and before the Movement row lock), so an apply is linearizable against
    any rule-set mutation. Manual classification does not take it; it stays
    serialized by the Movement lock alone. Preview never takes it.
    """
    connection.execute(
        select(
            func.pg_advisory_xact_lock(
                categorization_rule_set_lock_key(installation_id, residence_id)
            )
        )
    )


class FinancialCategorizationRulePersistenceError(RuntimeError):
    """Sanitized persistence failure for categorization-rule operations."""


class FinancialCategorizationRuleAccessError(
    FinancialCategorizationRulePersistenceError
):
    """Actor has no active membership in the requested residence."""


class FinancialCategorizationRuleNotFoundError(
    FinancialCategorizationRulePersistenceError
):
    """Rule is missing, invisible, or not owned by the actor for disabling."""


class FinancialCategorizationRuleCategoryNotFoundError(
    FinancialCategorizationRulePersistenceError
):
    """Target category is missing, inactive, or incompatible with the audience."""


class FinancialCategorizationRuleAccountNotFoundError(
    FinancialCategorizationRulePersistenceError
):
    """Account is missing, archived, or not owned by the actor."""


class FinancialCategorizationRuleConflictError(
    FinancialCategorizationRulePersistenceError
):
    """Idempotency key was reused with a different rule or state conflicts."""


class FinancialCategorizationRuleStore:
    """Create, disable, list and apply deterministic categorization rules."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def create_rule(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialCategorizationRuleDraft,
    ) -> FinancialCategorizationRuleRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialCategorizationRuleDraft):
            raise TypeError("draft must be FinancialCategorizationRuleDraft")

        request_digest = _create_digest(operator_id, draft)
        try:
            with self._engine.begin() as connection:
                _prepare_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                _acquire_rule_set_lock(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                )
                existing = _rule_by_idempotency(
                    connection,
                    installation_id=installation_id,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    return _require_replay(existing, request_digest)

                category = (
                    connection.execute(
                        select(financial_categories).where(
                            financial_categories.c.id == draft.target_category_id,
                            financial_categories.c.installation_id == installation_id,
                            financial_categories.c.residence_id == residence_id,
                            financial_categories.c.status
                            == FinancialCategoryStatus.ACTIVE.value,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if category is None:
                    raise FinancialCategorizationRuleCategoryNotFoundError(
                        "financial category was not found"
                    )

                category_scope = FinancialVisibilityScope(category["visibility_scope"])
                if draft.account_id is not None:
                    account = _owned_active_account(
                        connection,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        operator_id=operator_id,
                        account_id=draft.account_id,
                    )
                    if account is None:
                        raise FinancialCategorizationRuleAccountNotFoundError(
                            "financial account was not found"
                        )
                    compatible = is_category_audience_compatible_for_movement(
                        movement_visibility_scope=FinancialVisibilityScope(
                            account["visibility_scope"]
                        ),
                        movement_owner_operator_id=account["owner_operator_id"],
                        category_visibility_scope=category_scope,
                        category_owner_operator_id=category["owner_operator_id"],
                    )
                else:
                    compatible = (
                        category_scope is FinancialVisibilityScope.HOUSEHOLD
                        or category["owner_operator_id"] == operator_id
                    )
                if not compatible:
                    raise FinancialCategorizationRuleCategoryNotFoundError(
                        "financial category was not found"
                    )

                inserted = (
                    connection.execute(
                        pg_insert(financial_categorization_rules)
                        .values(
                            id=new_financial_resource_id(),
                            installation_id=installation_id,
                            residence_id=residence_id,
                            created_by_operator_id=operator_id,
                            account_id=draft.account_id,
                            result_effect=(
                                draft.result_effect.value
                                if draft.result_effect is not None
                                else None
                            ),
                            description_matcher=draft.description_matcher.value,
                            description_pattern=draft.description_pattern,
                            target_category_id=draft.target_category_id,
                            priority=draft.priority,
                            status=FinancialCategorizationRuleStatus.ACTIVE.value,
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                            created_at=func.transaction_timestamp(),
                            disabled_at=None,
                            disabled_by_operator_id=None,
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                financial_categorization_rules.c.installation_id,
                                financial_categorization_rules.c.idempotency_key,
                            ]
                        )
                        .returning(*financial_categorization_rules.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if inserted is None:
                    raced = _rule_by_idempotency(
                        connection,
                        installation_id=installation_id,
                        idempotency_key=idempotency_key,
                    )
                    if raced is not None:
                        return _require_replay(raced, request_digest)
                    raise FinancialCategorizationRuleConflictError(
                        "categorization rule conflict"
                    )
                return _rule_record(inserted)
        except FinancialMovementAccessError:
            raise FinancialCategorizationRuleAccessError(
                "categorization rule access denied"
            ) from None
        except FinancialCategorizationRulePersistenceError:
            raise
        except IntegrityError:
            raise FinancialCategorizationRuleConflictError(
                "categorization rule conflict"
            ) from None
        except DBAPIError:
            raise FinancialCategorizationRulePersistenceError(
                "categorization rule could not be persisted"
            ) from None

    def list_rules(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialCategorizationRuleRecord, ...]:
        """Return every visible rule, ACTIVE first, in a deterministic order."""
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        try:
            with self._engine.begin() as connection:
                _prepare_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                rows = (
                    connection.execute(
                        select(financial_categorization_rules)
                        .where(
                            financial_categorization_rules.c.installation_id
                            == installation_id,
                            financial_categorization_rules.c.residence_id
                            == residence_id,
                        )
                        .order_by(
                            financial_categorization_rules.c.status,
                            financial_categorization_rules.c.priority.desc(),
                            financial_categorization_rules.c.created_at,
                            financial_categorization_rules.c.id,
                        )
                    )
                    .mappings()
                    .all()
                )
                return tuple(_rule_record(row) for row in rows)
        except FinancialMovementAccessError:
            raise FinancialCategorizationRuleAccessError(
                "categorization rule access denied"
            ) from None
        except FinancialCategorizationRulePersistenceError:
            raise
        except DBAPIError:
            raise FinancialCategorizationRulePersistenceError(
                "categorization rules could not be read"
            ) from None

    def disable_rule(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        rule_id: UUID,
    ) -> FinancialCategorizationRuleRecord:
        """Disable one rule the actor created. Replaying a disable is a no-op."""
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_resource_id(rule_id)
        rules = financial_categorization_rules
        try:
            with self._engine.begin() as connection:
                _prepare_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                _acquire_rule_set_lock(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                )
                row = (
                    connection.execute(
                        update(rules)
                        .where(
                            rules.c.id == rule_id,
                            rules.c.installation_id == installation_id,
                            rules.c.residence_id == residence_id,
                            rules.c.created_by_operator_id == operator_id,
                            rules.c.status
                            == FinancialCategorizationRuleStatus.ACTIVE.value,
                        )
                        .values(
                            status=FinancialCategorizationRuleStatus.DISABLED.value,
                            disabled_at=func.transaction_timestamp(),
                            disabled_by_operator_id=operator_id,
                        )
                        .returning(*rules.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    row = (
                        connection.execute(
                            select(rules).where(
                                rules.c.id == rule_id,
                                rules.c.installation_id == installation_id,
                                rules.c.residence_id == residence_id,
                                rules.c.created_by_operator_id == operator_id,
                                rules.c.status
                                == FinancialCategorizationRuleStatus.DISABLED.value,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                if row is None:
                    raise FinancialCategorizationRuleNotFoundError(
                        "categorization rule was not found"
                    )
                return _rule_record(row)
        except FinancialMovementAccessError:
            raise FinancialCategorizationRuleAccessError(
                "categorization rule access denied"
            ) from None
        except FinancialCategorizationRulePersistenceError:
            raise
        except DBAPIError:
            raise FinancialCategorizationRulePersistenceError(
                "categorization rule could not be disabled"
            ) from None

    def list_current_rule_origins(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialMovementAllocationRuleOrigin, ...]:
        """Return provenance of the *current* classification of an account's Movements.

        One statement regardless of Movement count. Superseded sets' origins are
        history and are not returned: a manual override leaves the Movement with
        no rule origin.
        """
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_resource_id(account_id)
        origins = financial_movement_allocation_rule_origins
        sets = financial_movement_allocation_sets
        successor = sets.alias("successor")
        try:
            with self._engine.begin() as connection:
                _prepare_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                visible_account = connection.scalar(
                    select(financial_accounts.c.id).where(
                        financial_accounts.c.id == account_id,
                        financial_accounts.c.installation_id == installation_id,
                        financial_accounts.c.residence_id == residence_id,
                    )
                )
                if visible_account is None:
                    raise FinancialCategorizationRuleAccountNotFoundError(
                        "financial account was not found"
                    )
                rows = (
                    connection.execute(
                        select(origins)
                        .select_from(
                            origins.join(
                                sets, sets.c.id == origins.c.allocation_set_id
                            ).join(
                                financial_movements,
                                financial_movements.c.id == origins.c.movement_id,
                            )
                        )
                        .where(
                            origins.c.installation_id == installation_id,
                            origins.c.residence_id == residence_id,
                            financial_movements.c.account_id == account_id,
                            ~select(successor.c.id)
                            .where(successor.c.supersedes_id == sets.c.id)
                            .exists(),
                        )
                        .order_by(origins.c.created_at, origins.c.allocation_set_id)
                    )
                    .mappings()
                    .all()
                )
                return tuple(
                    FinancialMovementAllocationRuleOrigin(
                        allocation_set_id=row["allocation_set_id"],
                        movement_id=row["movement_id"],
                        rule_id=row["rule_id"],
                        created_at=row["created_at"],
                    )
                    for row in rows
                )
        except FinancialMovementAccessError:
            raise FinancialCategorizationRuleAccessError(
                "categorization rule access denied"
            ) from None
        except FinancialCategorizationRulePersistenceError:
            raise
        except DBAPIError:
            raise FinancialCategorizationRulePersistenceError(
                "categorization rule origins could not be read"
            ) from None

    def apply_rule_to_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
        movement_id: UUID,
        expected_rule_id: UUID,
    ) -> FinancialCategorizationApplyResult:
        """Classify one Movement with the rule the operator confirmed, or do nothing.

        Everything is re-derived from canonical state under the Movement row
        lock: a Movement that is already classified (manually or by any rule),
        ineligible, unmatched or ambiguous is never written, and a winning rule
        other than the confirmed one is a CONFLICT. The write is the ordinary
        first allocation set (revision 1) plus provenance and audit, atomically.
        """
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_resource_id(account_id)
        validate_financial_resource_id(movement_id)
        validate_financial_resource_id(expected_rule_id)
        status = FinancialCategorizationApplyStatus

        def result(
            outcome: FinancialCategorizationApplyStatus,
            *,
            rule_id: UUID | None = None,
            allocation_set_id: UUID | None = None,
        ) -> FinancialCategorizationApplyResult:
            return FinancialCategorizationApplyResult(
                movement_id=movement_id,
                status=outcome,
                rule_id=rule_id,
                allocation_set_id=allocation_set_id,
            )

        try:
            with self._engine.begin() as connection:
                _prepare_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                # Lock order is fixed: rule set first, then the Movement row.
                _acquire_rule_set_lock(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                )
                account = _owned_active_account(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    account_id=account_id,
                )
                if account is None:
                    raise FinancialCategorizationRuleAccountNotFoundError(
                        "financial account was not found"
                    )

                movement = _lock_eligible_movement(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    movement_id=movement_id,
                )
                if movement is None or movement["account_id"] != account_id:
                    return result(status.INELIGIBLE)

                current = _current_set_row(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    movement_id=movement_id,
                )
                rules = _active_rules(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    account_id=account_id,
                )
                categories = _categories_by_id(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    category_ids=tuple({rule.target_category_id for rule in rules}),
                )
                usable = usable_categorization_rules(
                    rules,
                    categories=categories,
                    account_visibility_scope=FinancialVisibilityScope(
                        account["visibility_scope"]
                    ),
                    account_owner_operator_id=account["owner_operator_id"],
                )
                evaluation = evaluate_movement_categorization(
                    _movement_record(movement),
                    already_classified=current is not None,
                    rules=usable,
                )
                evaluated = FinancialCategorizationEvaluationStatus
                if evaluation.status is evaluated.ALREADY_CLASSIFIED:
                    return result(status.ALREADY_CLASSIFIED)
                if evaluation.status is evaluated.INELIGIBLE:
                    return result(status.INELIGIBLE)
                if evaluation.status is evaluated.AMBIGUOUS:
                    return result(status.AMBIGUOUS)
                if evaluation.status is evaluated.NO_MATCH:
                    return result(status.NO_MATCH)

                rule = evaluation.rule
                if rule is None or rule.id != expected_rule_id:
                    return result(
                        status.CONFLICT,
                        rule_id=rule.id if rule is not None else None,
                    )

                share = FinancialMovementAllocationDraft(
                    category_id=rule.target_category_id,
                    amount=Money(movement["amount"], movement["currency"]),
                )
                allocations = (share,)
                _validate_economic_shape(movement=movement, allocations=allocations)
                _validate_categories(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    account=account,
                    allocations=allocations,
                )
                inserted = _append_allocation_set(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    idempotency_key=categorization_apply_idempotency_key(
                        rule.id, movement_id
                    ),
                    request_digest=_allocation_request_digest(
                        operator_id=operator_id,
                        movement_id=movement_id,
                        supersedes_id=None,
                        allocations=allocations,
                    ),
                    movement_id=movement_id,
                    supersedes_id=None,
                    revision=1,
                    allocations=allocations,
                    rule_id=rule.id,
                )
                if inserted is None:
                    # The same logical application already exists: nothing new.
                    return result(status.ALREADY_CLASSIFIED)
                return result(
                    status.CLASSIFIED,
                    rule_id=rule.id,
                    allocation_set_id=inserted["id"],
                )
        except FinancialMovementAccessError:
            raise FinancialCategorizationRuleAccessError(
                "categorization rule access denied"
            ) from None
        except (
            FinancialMovementAllocationCategoryNotFoundError,
            FinancialMovementAllocationInvalidShapeError,
            IntegrityError,
        ):
            # Canonical state moved under us (e.g. rule disabled, category changed):
            # the transaction rolled back, nothing was written.
            return result(status.CONFLICT)
        except FinancialCategorizationRulePersistenceError:
            raise
        except (DBAPIError, FinancialMovementPersistenceError):
            raise FinancialCategorizationRulePersistenceError(
                "categorization rule could not be applied"
            ) from None


def _create_digest(operator_id: UUID, draft: FinancialCategorizationRuleDraft) -> str:
    material = "\x1f".join(
        (_REQUEST_DIGEST_NAMESPACE, str(operator_id), *draft.canonical_material())
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _rule_by_idempotency(
    connection: Connection, *, installation_id: UUID, idempotency_key: UUID
) -> RowMapping | None:
    return (
        connection.execute(
            select(financial_categorization_rules).where(
                financial_categorization_rules.c.installation_id == installation_id,
                financial_categorization_rules.c.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )


def _require_replay(
    row: RowMapping, request_digest: str
) -> FinancialCategorizationRuleRecord:
    if row["request_digest"] != request_digest:
        raise FinancialCategorizationRuleConflictError(
            "categorization rule idempotency conflict"
        )
    return _rule_record(row)


def _active_rules(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    account_id: UUID,
) -> tuple[FinancialCategorizationRuleRecord, ...]:
    rules = financial_categorization_rules
    rows = (
        connection.execute(
            select(rules)
            .where(
                rules.c.installation_id == installation_id,
                rules.c.residence_id == residence_id,
                rules.c.status == FinancialCategorizationRuleStatus.ACTIVE.value,
                (rules.c.account_id.is_(None)) | (rules.c.account_id == account_id),
            )
            .order_by(rules.c.priority.desc(), rules.c.created_at, rules.c.id)
        )
        .mappings()
        .all()
    )
    return tuple(_rule_record(row) for row in rows)


def _categories_by_id(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    category_ids: tuple[UUID, ...],
) -> dict[UUID, FinancialCategoryRecord]:
    if not category_ids:
        return {}
    rows = (
        connection.execute(
            select(financial_categories).where(
                financial_categories.c.id.in_(category_ids),
                financial_categories.c.installation_id == installation_id,
                financial_categories.c.residence_id == residence_id,
            )
        )
        .mappings()
        .all()
    )
    records = [_category_record(row) for row in rows]
    return {record.id: record for record in records}


def _rule_record(row: RowMapping) -> FinancialCategorizationRuleRecord:
    try:
        effect = row["result_effect"]
        return FinancialCategorizationRuleRecord(
            id=row["id"],
            residence_id=row["residence_id"],
            created_by_operator_id=row["created_by_operator_id"],
            account_id=row["account_id"],
            result_effect=FinancialResultEffect(effect) if effect is not None else None,
            description_matcher=FinancialCategorizationMatcher(
                row["description_matcher"]
            ),
            description_pattern=row["description_pattern"],
            target_category_id=row["target_category_id"],
            priority=int(row["priority"]),
            status=FinancialCategorizationRuleStatus(row["status"]),
            created_at=row["created_at"],
            disabled_at=row["disabled_at"],
            disabled_by_operator_id=row["disabled_by_operator_id"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialCategorizationRulePersistenceError(
            "categorization rule state is invalid"
        ) from None


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialCategorizationRuleAccessError",
    "FinancialCategorizationRuleAccountNotFoundError",
    "FinancialCategorizationRuleCategoryNotFoundError",
    "FinancialCategorizationRuleConflictError",
    "FinancialCategorizationRuleNotFoundError",
    "FinancialCategorizationRulePersistenceError",
    "FinancialCategorizationRuleStore",
]
