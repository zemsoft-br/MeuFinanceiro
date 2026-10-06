"""Residence/operator-aware persistence for monthly category budgets.

Budgets are planning: this store never reads or writes the ledger. Create is
replay-safe through an explicit idempotency key (plus material uniqueness of the
plan); edit is a compare-and-swap on ``version`` that appends a complete new set of
lines and never deletes anything. Authorization is double-checked: the store
verifies what it can explain, forced RLS and database triggers decide the rest.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from uuid import UUID

from meufinanceiro_finance import (
    FinancialBudgetDateBasis,
    FinancialBudgetDraft,
    FinancialBudgetLineDraft,
    FinancialBudgetLineRecord,
    FinancialBudgetPeriodKind,
    FinancialBudgetRecord,
    FinancialBudgetReplacement,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    is_budget_category_compatible,
    new_financial_resource_id,
    validate_budget_period_start,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from sqlalchemy import Connection, Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_budget_schema import (
    financial_budget_lines,
    financial_budgets,
)
from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.financial_category_store import (
    _record as _category_record,
)
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    _require_active_membership,
    _set_context,
)

_REQUEST_DIGEST_NAMESPACE = "meufinanceiro:budget-create:v1"


class FinancialBudgetPersistenceError(RuntimeError):
    """Sanitized persistence failure for budget operations."""


class FinancialBudgetAccessError(FinancialBudgetPersistenceError):
    """Actor has no active membership in the requested residence."""


class FinancialBudgetNotFoundError(FinancialBudgetPersistenceError):
    """Budget is missing or invisible to the actor (indistinguishable)."""


class FinancialBudgetNotEditableError(FinancialBudgetPersistenceError):
    """Budget is visible but the actor is not its owner."""


class FinancialBudgetCategoryNotFoundError(FinancialBudgetPersistenceError):
    """A line category is missing, inactive or incompatible with the audience."""


class FinancialBudgetInvalidShapeError(FinancialBudgetPersistenceError):
    """The request is well-typed but contradicts the stored budget identity."""


class FinancialBudgetConflictError(FinancialBudgetPersistenceError):
    """Idempotency key reused with other material, or the month already has a plan."""


class FinancialBudgetVersionConflictError(FinancialBudgetPersistenceError):
    """``expectedVersion`` is stale: the budget changed since the caller read it."""


class FinancialBudgetStore:
    """Create, read, list and CAS-edit monthly category budgets."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def create_budget(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialBudgetDraft,
    ) -> FinancialBudgetRecord:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialBudgetDraft):
            raise TypeError("draft must be FinancialBudgetDraft")

        request_digest = _create_digest(operator_id, draft)
        budgets = financial_budgets
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                existing = _by_idempotency(connection, installation_id, idempotency_key)
                if existing is not None:
                    return self._replay(connection, existing, request_digest)

                _require_eligible_categories(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    visibility_scope=draft.visibility_scope,
                    owner_operator_id=operator_id,
                    category_ids=[line.category_id for line in draft.lines],
                )
                inserted = (
                    connection.execute(
                        pg_insert(budgets)
                        .values(
                            id=new_financial_resource_id(),
                            installation_id=installation_id,
                            residence_id=residence_id,
                            owner_operator_id=operator_id,
                            visibility_scope=draft.visibility_scope.value,
                            name=draft.name,
                            currency=draft.currency,
                            period_kind=FinancialBudgetPeriodKind.MONTHLY.value,
                            period_start=draft.period_start,
                            date_basis=draft.date_basis.value,
                            version=1,
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                            updated_by_operator_id=operator_id,
                            created_at=func.transaction_timestamp(),
                            updated_at=func.transaction_timestamp(),
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                budgets.c.installation_id,
                                budgets.c.idempotency_key,
                            ]
                        )
                        .returning(*budgets.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if inserted is None:
                    raced = _by_idempotency(
                        connection, installation_id, idempotency_key
                    )
                    if raced is not None:
                        return self._replay(connection, raced, request_digest)
                    raise FinancialBudgetConflictError("budget conflict")
                _insert_lines(connection, inserted, draft.lines)
                return _record(inserted, _lines_from_drafts(draft.lines))
        except FinancialMovementAccessError:
            raise FinancialBudgetAccessError("budget access denied") from None
        except FinancialBudgetPersistenceError:
            raise
        except IntegrityError:
            raise FinancialBudgetConflictError("budget conflict") from None
        except DBAPIError:
            raise FinancialBudgetPersistenceError(
                "budget could not be persisted"
            ) from None

    def get_budget(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        budget_id: UUID,
    ) -> FinancialBudgetRecord:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(budget_id)
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                row = _visible_row(connection, installation_id, residence_id, budget_id)
                if row is None:
                    raise FinancialBudgetNotFoundError("budget was not found")
                return _load_records(connection, [row])[0]
        except FinancialMovementAccessError:
            raise FinancialBudgetAccessError("budget access denied") from None
        except FinancialBudgetPersistenceError:
            raise
        except DBAPIError:
            raise FinancialBudgetPersistenceError("budget could not be read") from None

    def list_budgets(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        period_start: date,
    ) -> tuple[FinancialBudgetRecord, ...]:
        """Visible budgets of one month: two statements, independent of the count."""
        _require_scope(installation_id, residence_id, operator_id)
        validate_budget_period_start(period_start)
        budgets = financial_budgets
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                rows = (
                    connection.execute(
                        select(budgets)
                        .where(
                            budgets.c.installation_id == installation_id,
                            budgets.c.residence_id == residence_id,
                            budgets.c.period_start == period_start,
                        )
                        .order_by(
                            budgets.c.visibility_scope,
                            budgets.c.date_basis,
                            budgets.c.currency,
                            budgets.c.created_at,
                            budgets.c.id,
                        )
                    )
                    .mappings()
                    .all()
                )
                return _load_records(connection, rows)
        except FinancialMovementAccessError:
            raise FinancialBudgetAccessError("budget access denied") from None
        except FinancialBudgetPersistenceError:
            raise
        except DBAPIError:
            raise FinancialBudgetPersistenceError("budgets could not be read") from None

    def replace_budget(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        budget_id: UUID,
        replacement: FinancialBudgetReplacement,
    ) -> FinancialBudgetRecord:
        """Replace name and lines iff ``expected_version`` is still current (CAS).

        A stale version raises ``FinancialBudgetVersionConflictError`` and writes
        nothing; the caller must re-read and decide. The previous revision's lines
        stay stored: nothing is updated or deleted besides the CAS columns.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(budget_id)
        if not isinstance(replacement, FinancialBudgetReplacement):
            raise TypeError("replacement must be FinancialBudgetReplacement")
        budgets = financial_budgets
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                current = _visible_row(
                    connection, installation_id, residence_id, budget_id
                )
                if current is None:
                    raise FinancialBudgetNotFoundError("budget was not found")
                if current["owner_operator_id"] != operator_id:
                    raise FinancialBudgetNotEditableError("budget is read-only")
                if current["version"] != replacement.expected_version:
                    raise FinancialBudgetVersionConflictError("budget version is stale")
                if replacement.lines[0].planned.currency != current["currency"]:
                    raise FinancialBudgetInvalidShapeError(
                        "line currency must match the budget currency"
                    )
                _require_eligible_categories(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    visibility_scope=FinancialVisibilityScope(
                        current["visibility_scope"]
                    ),
                    owner_operator_id=current["owner_operator_id"],
                    category_ids=[line.category_id for line in replacement.lines],
                )
                updated = (
                    connection.execute(
                        update(budgets)
                        .where(
                            budgets.c.id == budget_id,
                            budgets.c.installation_id == installation_id,
                            budgets.c.residence_id == residence_id,
                            budgets.c.owner_operator_id == operator_id,
                            budgets.c.version == replacement.expected_version,
                        )
                        .values(
                            name=replacement.name,
                            version=replacement.expected_version + 1,
                            updated_at=func.transaction_timestamp(),
                            updated_by_operator_id=operator_id,
                        )
                        .returning(*budgets.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if updated is None:
                    # Lost the race between the read above and the CAS.
                    raise FinancialBudgetVersionConflictError("budget version is stale")
                _insert_lines(connection, updated, replacement.lines)
                return _record(updated, _lines_from_drafts(replacement.lines))
        except FinancialMovementAccessError:
            raise FinancialBudgetAccessError("budget access denied") from None
        except FinancialBudgetPersistenceError:
            raise
        except IntegrityError:
            raise FinancialBudgetConflictError("budget conflict") from None
        except DBAPIError:
            raise FinancialBudgetPersistenceError(
                "budget could not be persisted"
            ) from None

    def _replay(
        self, connection: Connection, row: RowMapping, request_digest: str
    ) -> FinancialBudgetRecord:
        if row["request_digest"] != request_digest:
            raise FinancialBudgetConflictError("budget idempotency conflict")
        return _load_records(connection, [row])[0]


def _require_scope(
    installation_id: UUID, residence_id: UUID, operator_id: UUID
) -> None:
    for name, value in (
        ("installation_id", installation_id),
        ("residence_id", residence_id),
        ("operator_id", operator_id),
    ):
        if not isinstance(value, UUID):
            raise TypeError(f"{name} must be UUID")


def _prepare(
    connection: Connection,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> None:
    _set_context(
        connection,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
    )
    _require_active_membership(
        connection,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
    )


def _create_digest(operator_id: UUID, draft: FinancialBudgetDraft) -> str:
    material = json.dumps(
        [_REQUEST_DIGEST_NAMESPACE, str(operator_id), draft.canonical_material()],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _by_idempotency(
    connection: Connection, installation_id: UUID, idempotency_key: UUID
) -> RowMapping | None:
    budgets = financial_budgets
    return (
        connection.execute(
            select(budgets).where(
                budgets.c.installation_id == installation_id,
                budgets.c.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )


def _visible_row(
    connection: Connection,
    installation_id: UUID,
    residence_id: UUID,
    budget_id: UUID,
) -> RowMapping | None:
    budgets = financial_budgets
    return (
        connection.execute(
            select(budgets).where(
                budgets.c.id == budget_id,
                budgets.c.installation_id == installation_id,
                budgets.c.residence_id == residence_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _require_eligible_categories(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    visibility_scope: FinancialVisibilityScope,
    owner_operator_id: UUID,
    category_ids: list[UUID],
) -> None:
    """Every line category must be visible, ACTIVE and audience-compatible.

    One statement for all lines. A missing, invisible, inactive or incompatible
    category is the same sanitized error: ids never prove authorization.
    """
    wanted = set(category_ids)
    categories = financial_categories
    rows = (
        connection.execute(
            select(categories).where(
                categories.c.installation_id == installation_id,
                categories.c.residence_id == residence_id,
                categories.c.id.in_(wanted),
            )
        )
        .mappings()
        .all()
    )
    found = {row["id"]: _category_record(row) for row in rows}
    for category_id in wanted:
        category = found.get(category_id)
        if category is None or not is_budget_category_compatible(
            budget_visibility_scope=visibility_scope,
            budget_owner_operator_id=owner_operator_id,
            category=category,
        ):
            raise FinancialBudgetCategoryNotFoundError(
                "financial category was not found"
            )


def _insert_lines(
    connection: Connection,
    budget_row: RowMapping,
    lines: tuple[FinancialBudgetLineDraft, ...],
) -> None:
    connection.execute(
        financial_budget_lines.insert().values(
            [
                {
                    "budget_id": budget_row["id"],
                    "revision": budget_row["version"],
                    "category_id": line.category_id,
                    "result_effect": line.result_effect.value,
                    "installation_id": budget_row["installation_id"],
                    "residence_id": budget_row["residence_id"],
                    "currency": budget_row["currency"],
                    "planned_amount": line.planned.amount,
                    "created_at": func.transaction_timestamp(),
                }
                for line in lines
            ]
        )
    )


def _lines_from_drafts(
    lines: tuple[FinancialBudgetLineDraft, ...],
) -> tuple[FinancialBudgetLineRecord, ...]:
    return tuple(
        FinancialBudgetLineRecord(
            category_id=line.category_id,
            result_effect=line.result_effect,
            planned=line.planned,
        )
        for line in sorted(
            lines, key=lambda line: (line.result_effect.value, str(line.category_id))
        )
    )


def _load_records(
    connection: Connection, rows: Sequence[RowMapping]
) -> tuple[FinancialBudgetRecord, ...]:
    if not rows:
        return ()
    budgets = financial_budgets
    lines = financial_budget_lines
    ids = [row["id"] for row in rows]
    line_rows = (
        connection.execute(
            select(lines)
            .select_from(
                lines.join(
                    budgets,
                    (lines.c.budget_id == budgets.c.id)
                    & (lines.c.revision == budgets.c.version),
                )
            )
            .where(lines.c.budget_id.in_(ids))
            .order_by(lines.c.budget_id, lines.c.result_effect, lines.c.category_id)
        )
        .mappings()
        .all()
    )
    grouped: dict[UUID, list[FinancialBudgetLineRecord]] = defaultdict(list)
    try:
        for line_row in line_rows:
            grouped[line_row["budget_id"]].append(
                FinancialBudgetLineRecord(
                    category_id=line_row["category_id"],
                    result_effect=FinancialResultEffect(line_row["result_effect"]),
                    planned=Money(line_row["planned_amount"], line_row["currency"]),
                )
            )
    except (KeyError, TypeError, ValueError):
        raise FinancialBudgetPersistenceError("budget state is invalid") from None
    return tuple(_record(row, tuple(grouped[row["id"]])) for row in rows)


def _record(
    row: RowMapping, lines: tuple[FinancialBudgetLineRecord, ...]
) -> FinancialBudgetRecord:
    try:
        return FinancialBudgetRecord(
            id=row["id"],
            residence_id=row["residence_id"],
            owner_operator_id=row["owner_operator_id"],
            visibility_scope=FinancialVisibilityScope(row["visibility_scope"]),
            name=row["name"],
            currency=row["currency"],
            period_kind=FinancialBudgetPeriodKind(row["period_kind"]),
            period_start=row["period_start"],
            date_basis=FinancialBudgetDateBasis(row["date_basis"]),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            lines=lines,
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialBudgetPersistenceError("budget state is invalid") from None


__all__ = [
    "FinancialBudgetAccessError",
    "FinancialBudgetCategoryNotFoundError",
    "FinancialBudgetConflictError",
    "FinancialBudgetInvalidShapeError",
    "FinancialBudgetNotEditableError",
    "FinancialBudgetNotFoundError",
    "FinancialBudgetPersistenceError",
    "FinancialBudgetStore",
    "FinancialBudgetVersionConflictError",
]
