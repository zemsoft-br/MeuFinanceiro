"""Residence/operator-aware persistence for canonical financial accounts."""

from __future__ import annotations

from uuid import UUID

from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountRecord,
    FinancialAccountStatus,
    FinancialAccountType,
    FinancialVisibilityScope,
    new_financial_resource_id,
    validate_financial_resource_id,
)
from sqlalchemy import Connection, Engine, func, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.household_schema import household_memberships


class FinancialAccountPersistenceError(RuntimeError):
    """Sanitized persistence failure for financial-account operations."""


class FinancialAccountAccessError(FinancialAccountPersistenceError):
    """Actor has no active membership in the requested residence."""


class FinancialAccountNotFoundError(FinancialAccountPersistenceError):
    """Account is missing or outside the actor's effective audience."""


class FinancialAccountStore:
    """Create and read canonical accounts through PostgreSQL RLS."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def create_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        draft: FinancialAccountDraft,
    ) -> FinancialAccountRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        if not isinstance(draft, FinancialAccountDraft):
            raise TypeError("draft must be FinancialAccountDraft")

        account_id = new_financial_resource_id()
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
                        insert(financial_accounts)
                        .values(
                            id=account_id,
                            installation_id=installation_id,
                            residence_id=residence_id,
                            owner_operator_id=operator_id,
                            visibility_scope=draft.visibility_scope.value,
                            account_type=draft.account_type.value,
                            custom_type_name=draft.custom_type_name,
                            name=draft.name,
                            currency=draft.currency,
                            status=FinancialAccountStatus.ACTIVE.value,
                            created_at=func.transaction_timestamp(),
                            updated_at=func.transaction_timestamp(),
                            archived_at=None,
                        )
                        .returning(*financial_accounts.c)
                    )
                    .mappings()
                    .one()
                )
        except (FinancialAccountAccessError, FinancialAccountPersistenceError):
            raise
        except IntegrityError:
            raise FinancialAccountPersistenceError(
                "financial account could not be persisted"
            ) from None
        except DBAPIError:
            raise FinancialAccountPersistenceError(
                "financial account could not be persisted"
            ) from None

        return _record(row)

    def list_accounts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialAccountRecord, ...]:
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
                        select(financial_accounts)
                        .where(
                            financial_accounts.c.installation_id == installation_id,
                            financial_accounts.c.residence_id == residence_id,
                        )
                        .order_by(
                            financial_accounts.c.created_at,
                            financial_accounts.c.id,
                        )
                    )
                    .mappings()
                    .all()
                )
        except (FinancialAccountAccessError, FinancialAccountPersistenceError):
            raise
        except DBAPIError:
            raise FinancialAccountPersistenceError(
                "financial accounts could not be read"
            ) from None

        return tuple(_record(row) for row in rows)

    def get_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_resource_id(account_id)

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
                        select(financial_accounts).where(
                            financial_accounts.c.id == account_id,
                            financial_accounts.c.installation_id == installation_id,
                            financial_accounts.c.residence_id == residence_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except (FinancialAccountAccessError, FinancialAccountPersistenceError):
            raise
        except DBAPIError:
            raise FinancialAccountPersistenceError(
                "financial account could not be read"
            ) from None

        if row is None:
            raise FinancialAccountNotFoundError("financial account was not found")
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
        raise FinancialAccountAccessError("financial account access denied")


def _record(row: RowMapping) -> FinancialAccountRecord:
    try:
        return FinancialAccountRecord(
            id=row["id"],
            residence_id=row["residence_id"],
            owner_operator_id=row["owner_operator_id"],
            visibility_scope=FinancialVisibilityScope(row["visibility_scope"]),
            account_type=FinancialAccountType(row["account_type"]),
            custom_type_name=row["custom_type_name"],
            name=row["name"],
            currency=row["currency"],
            status=FinancialAccountStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            archived_at=row["archived_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialAccountPersistenceError(
            "financial account state is invalid"
        ) from None


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialAccountAccessError",
    "FinancialAccountNotFoundError",
    "FinancialAccountPersistenceError",
    "FinancialAccountStore",
]
