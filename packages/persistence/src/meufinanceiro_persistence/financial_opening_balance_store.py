"""Persistence boundary for immutable account opening-balance anchors."""

from __future__ import annotations

from uuid import UUID

from meufinanceiro_finance import (
    FinancialAuditEventDraft,
    FinancialAuditEventType,
    FinancialOpeningBalanceDraft,
    FinancialOpeningBalanceRecord,
    Money,
    new_financial_resource_id,
    validate_financial_resource_id,
)
from sqlalchemy import Connection, Engine, func, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_audit_store import _append_financial_audit_event
from meufinanceiro_persistence.financial_opening_balance_schema import (
    financial_opening_balances,
)
from meufinanceiro_persistence.household_schema import household_memberships


class FinancialOpeningBalancePersistenceError(RuntimeError):
    """Sanitized persistence failure for opening-balance operations."""


class FinancialOpeningBalanceAccessError(FinancialOpeningBalancePersistenceError):
    """Actor has no active membership in the requested residence."""


class FinancialOpeningBalanceAccountNotFoundError(
    FinancialOpeningBalancePersistenceError
):
    """Target account is missing, inactive, invisible, or not owned by creator."""


class FinancialOpeningBalanceCurrencyMismatchError(
    FinancialOpeningBalancePersistenceError
):
    """Opening-balance currency differs from the canonical account currency."""


class FinancialOpeningBalanceAlreadyExistsError(
    FinancialOpeningBalancePersistenceError
):
    """The account already has its immutable opening anchor."""


class FinancialOpeningBalanceStore:
    """Create once and read opening balances through account-derived RLS."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def create_opening_balance(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
        draft: FinancialOpeningBalanceDraft,
    ) -> FinancialOpeningBalanceRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_resource_id(account_id)
        if not isinstance(draft, FinancialOpeningBalanceDraft):
            raise TypeError("draft must be FinancialOpeningBalanceDraft")

        opening_balance_id = new_financial_resource_id()
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
                account_currency = connection.scalar(
                    select(financial_accounts.c.currency).where(
                        financial_accounts.c.id == account_id,
                        financial_accounts.c.installation_id == installation_id,
                        financial_accounts.c.residence_id == residence_id,
                        financial_accounts.c.owner_operator_id == operator_id,
                        financial_accounts.c.status == "ACTIVE",
                    )
                )
                if account_currency is None:
                    raise FinancialOpeningBalanceAccountNotFoundError(
                        "financial account was not found"
                    )
                if account_currency != draft.amount.currency:
                    raise FinancialOpeningBalanceCurrencyMismatchError(
                        "opening balance currency must match account currency"
                    )

                row = (
                    connection.execute(
                        insert(financial_opening_balances)
                        .values(
                            id=opening_balance_id,
                            installation_id=installation_id,
                            residence_id=residence_id,
                            account_id=account_id,
                            currency=draft.amount.currency,
                            amount=draft.amount.amount,
                            effective_date=draft.effective_date,
                            created_by_operator_id=operator_id,
                            created_at=func.transaction_timestamp(),
                        )
                        .returning(*financial_opening_balances.c)
                    )
                    .mappings()
                    .one()
                )
                _append_financial_audit_event(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    actor_operator_id=operator_id,
                    draft=FinancialAuditEventDraft(
                        event_type=FinancialAuditEventType.OPENING_BALANCE_CREATED,
                        subject_id=opening_balance_id,
                    ),
                )
        except (
            FinancialOpeningBalanceAccessError,
            FinancialOpeningBalanceAccountNotFoundError,
            FinancialOpeningBalanceCurrencyMismatchError,
            FinancialOpeningBalancePersistenceError,
        ):
            raise
        except IntegrityError as error:
            if _constraint_name(error) == "uq_finance_opening_balance_account":
                raise FinancialOpeningBalanceAlreadyExistsError(
                    "financial account already has an opening balance"
                ) from None
            raise FinancialOpeningBalancePersistenceError(
                "opening balance could not be persisted"
            ) from None
        except DBAPIError:
            raise FinancialOpeningBalancePersistenceError(
                "opening balance could not be persisted"
            ) from None

        return _record(row)

    def get_opening_balance(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialOpeningBalanceRecord | None:
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
                        select(financial_opening_balances).where(
                            financial_opening_balances.c.account_id == account_id,
                            financial_opening_balances.c.installation_id
                            == installation_id,
                            financial_opening_balances.c.residence_id == residence_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except (
            FinancialOpeningBalanceAccessError,
            FinancialOpeningBalancePersistenceError,
        ):
            raise
        except DBAPIError:
            raise FinancialOpeningBalancePersistenceError(
                "opening balance could not be read"
            ) from None

        return None if row is None else _record(row)


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
        raise FinancialOpeningBalanceAccessError("opening balance access denied")


def _record(row: RowMapping) -> FinancialOpeningBalanceRecord:
    try:
        return FinancialOpeningBalanceRecord(
            id=row["id"],
            residence_id=row["residence_id"],
            account_id=row["account_id"],
            amount=Money(row["amount"], row["currency"]),
            effective_date=row["effective_date"],
            created_by_operator_id=row["created_by_operator_id"],
            created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialOpeningBalancePersistenceError(
            "opening balance state is invalid"
        ) from None


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialOpeningBalanceAccessError",
    "FinancialOpeningBalanceAccountNotFoundError",
    "FinancialOpeningBalanceAlreadyExistsError",
    "FinancialOpeningBalanceCurrencyMismatchError",
    "FinancialOpeningBalancePersistenceError",
    "FinancialOpeningBalanceStore",
]
