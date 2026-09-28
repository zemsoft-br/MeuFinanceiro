"""Residence/operator-aware persistence for canonical financial categories."""

from __future__ import annotations

from uuid import UUID

from meufinanceiro_finance import (
    FinancialCategoryDraft,
    FinancialCategoryRecord,
    FinancialCategoryStatus,
    FinancialVisibilityScope,
    new_financial_resource_id,
    validate_financial_resource_id,
)
from sqlalchemy import Connection, Engine, func, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.household_schema import household_memberships


class FinancialCategoryPersistenceError(RuntimeError):
    """Sanitized persistence failure for financial-category operations."""


class FinancialCategoryAccessError(FinancialCategoryPersistenceError):
    """Actor has no active membership in the requested residence."""


class FinancialCategoryNotFoundError(FinancialCategoryPersistenceError):
    """Category is missing or outside the actor's effective audience."""


class FinancialCategoryParentNotFoundError(FinancialCategoryPersistenceError):
    """Requested parent is missing, inactive, or outside the creation scope."""


class FinancialCategoryStore:
    """Create and read canonical category trees through PostgreSQL RLS."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def create_category(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        draft: FinancialCategoryDraft,
    ) -> FinancialCategoryRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        if not isinstance(draft, FinancialCategoryDraft):
            raise TypeError("draft must be FinancialCategoryDraft")

        category_id = new_financial_resource_id()
        try:
            with self._engine.begin() as connection:
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
                if draft.parent_id is not None:
                    _require_active_parent(
                        connection,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        operator_id=operator_id,
                        parent_id=draft.parent_id,
                        visibility_scope=draft.visibility_scope,
                    )
                row = (
                    connection.execute(
                        insert(financial_categories)
                        .values(
                            id=category_id,
                            installation_id=installation_id,
                            residence_id=residence_id,
                            owner_operator_id=operator_id,
                            visibility_scope=draft.visibility_scope.value,
                            parent_id=draft.parent_id,
                            name=draft.name,
                            status=FinancialCategoryStatus.ACTIVE.value,
                            created_at=func.transaction_timestamp(),
                            updated_at=func.transaction_timestamp(),
                            disabled_at=None,
                        )
                        .returning(*financial_categories.c)
                    )
                    .mappings()
                    .one()
                )
        except (
            FinancialCategoryAccessError,
            FinancialCategoryParentNotFoundError,
            FinancialCategoryPersistenceError,
        ):
            raise
        except IntegrityError:
            raise FinancialCategoryPersistenceError(
                "financial category could not be persisted"
            ) from None
        except DBAPIError:
            raise FinancialCategoryPersistenceError(
                "financial category could not be persisted"
            ) from None

        return _record(row)

    def list_categories(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialCategoryRecord, ...]:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")

        try:
            with self._engine.begin() as connection:
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
                rows = (
                    connection.execute(
                        select(financial_categories)
                        .where(
                            financial_categories.c.installation_id == installation_id,
                            financial_categories.c.residence_id == residence_id,
                        )
                        .order_by(
                            financial_categories.c.name,
                            financial_categories.c.id,
                        )
                    )
                    .mappings()
                    .all()
                )
        except (FinancialCategoryAccessError, FinancialCategoryPersistenceError):
            raise
        except DBAPIError:
            raise FinancialCategoryPersistenceError(
                "financial categories could not be read"
            ) from None

        return tuple(_record(row) for row in rows)

    def get_category(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        category_id: UUID,
    ) -> FinancialCategoryRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_resource_id(category_id)

        try:
            with self._engine.begin() as connection:
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
                row = (
                    connection.execute(
                        select(financial_categories).where(
                            financial_categories.c.id == category_id,
                            financial_categories.c.installation_id == installation_id,
                            financial_categories.c.residence_id == residence_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except (FinancialCategoryAccessError, FinancialCategoryPersistenceError):
            raise
        except DBAPIError:
            raise FinancialCategoryPersistenceError(
                "financial category could not be read"
            ) from None

        if row is None:
            raise FinancialCategoryNotFoundError("financial category was not found")
        return _record(row)


def _set_context(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> None:
    connection.execute(
        select(
            func.set_config(
                "app.current_installation_id",
                str(installation_id),
                True,
            ),
            func.set_config(
                "app.current_residence_id",
                str(residence_id),
                True,
            ),
            func.set_config(
                "app.current_operator_id",
                str(operator_id),
                True,
            ),
        )
    )


def _require_active_membership(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> None:
    membership_id = connection.scalar(
        select(household_memberships.c.id).where(
            household_memberships.c.installation_id == installation_id,
            household_memberships.c.residence_id == residence_id,
            household_memberships.c.operator_id == operator_id,
            household_memberships.c.status == "active",
        )
    )
    if membership_id is None:
        raise FinancialCategoryAccessError("financial category access denied")


def _require_active_parent(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    parent_id: UUID,
    visibility_scope: FinancialVisibilityScope,
) -> None:
    parent = connection.scalar(
        select(financial_categories.c.id).where(
            financial_categories.c.id == parent_id,
            financial_categories.c.installation_id == installation_id,
            financial_categories.c.residence_id == residence_id,
            financial_categories.c.owner_operator_id == operator_id,
            financial_categories.c.visibility_scope == visibility_scope.value,
            financial_categories.c.status == FinancialCategoryStatus.ACTIVE.value,
        )
    )
    if parent is None:
        raise FinancialCategoryParentNotFoundError(
            "financial category parent was not found"
        )


def _record(row: RowMapping) -> FinancialCategoryRecord:
    try:
        return FinancialCategoryRecord(
            id=row["id"],
            residence_id=row["residence_id"],
            owner_operator_id=row["owner_operator_id"],
            visibility_scope=FinancialVisibilityScope(row["visibility_scope"]),
            parent_id=row["parent_id"],
            name=row["name"],
            status=FinancialCategoryStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            disabled_at=row["disabled_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialCategoryPersistenceError(
            "financial category state is invalid"
        ) from None


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialCategoryAccessError",
    "FinancialCategoryNotFoundError",
    "FinancialCategoryParentNotFoundError",
    "FinancialCategoryPersistenceError",
    "FinancialCategoryStore",
]
