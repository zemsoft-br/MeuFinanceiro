"""Read-only, keyset-paginated read model of unclassified Movements.

A pending Movement is *derived* at read time (STANDARD, INCOME/EXPENSE, visible
to the operator, no allocation set). Nothing is persisted, locked or written: the
store never touches ``finance.movements`` or ``movement_allocation_sets`` beyond
SELECT, and visibility, residence scoping and audience stay with forced RLS.

Each call is one bounded statement for the page itself (plus the fixed context
and membership statements, plus one existence check when an account filter is
given), so the cost per page does not depend on the number of Movements, accounts,
allocations, rules or categories.
"""

from __future__ import annotations

from uuid import UUID

from meufinanceiro_finance import (
    PENDING_PAGE_LIMIT_MAX,
    FinancialAccountStatus,
    FinancialPendingMovementCandidate,
    FinancialPendingMovementCandidatePage,
    FinancialPendingMovementKey,
    FinancialResultEffect,
    FinancialVisibilityScope,
    validate_financial_resource_id,
)
from meufinanceiro_finance.movements import FinancialMovementRole
from sqlalchemy import Date, Engine, literal, select, tuple_
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    FinancialMovementPersistenceError,
    _record as _movement_record,
    _require_active_membership,
    _set_context,
)

_CATEGORIZABLE_EFFECTS = (
    FinancialResultEffect.INCOME.value,
    FinancialResultEffect.EXPENSE.value,
)


class FinancialPendingMovementPersistenceError(RuntimeError):
    """Sanitized persistence failure for the pending-Movement read model."""


class FinancialPendingMovementAccessError(FinancialPendingMovementPersistenceError):
    """Actor has no active membership in the requested residence."""


class FinancialPendingMovementAccountNotFoundError(
    FinancialPendingMovementPersistenceError
):
    """Filter account is missing or invisible to the operator."""


class FinancialPendingMovementStore:
    """Page through the derived pending-classification inbox."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

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
    ) -> FinancialPendingMovementCandidatePage:
        """Return up to ``limit`` unclassified visible Movements after ``after``.

        Order is ``effective_date DESC, id DESC`` and the position is a keyset,
        so a page never repeats or skips a Movement because of concurrent
        appends or classifications. ``limit + 1`` rows are read to know whether
        another page exists. Read-only: no lock, no write.
        """
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if not 1 <= limit <= PENDING_PAGE_LIMIT_MAX:
            raise ValueError(f"limit must be between 1 and {PENDING_PAGE_LIMIT_MAX}")
        if after is not None and not isinstance(after, FinancialPendingMovementKey):
            raise TypeError("after must be FinancialPendingMovementKey")
        if account_id is not None:
            validate_financial_resource_id(account_id)
        if result_effect is not None:
            if not isinstance(result_effect, FinancialResultEffect):
                raise TypeError("result_effect must be FinancialResultEffect")
            if result_effect.value not in _CATEGORIZABLE_EFFECTS:
                raise ValueError("result_effect must be INCOME or EXPENSE")

        movements = financial_movements
        accounts = financial_accounts
        sets = financial_movement_allocation_sets
        # The ordered, limited scan runs on Movements alone so it can walk the
        # partial keyset index and stop after ``limit + 1`` rows; accounts are
        # joined afterwards to those few rows only. Joining first lets the planner
        # drive from accounts and sort the whole residence (measured: seconds).
        scan = (
            select(movements)
            .where(
                movements.c.installation_id == installation_id,
                movements.c.residence_id == residence_id,
                movements.c.role == FinancialMovementRole.STANDARD.value,
                movements.c.result_effect.in_(_CATEGORIZABLE_EFFECTS),
                ~select(sets.c.id)
                .where(
                    sets.c.installation_id == movements.c.installation_id,
                    sets.c.residence_id == movements.c.residence_id,
                    sets.c.movement_id == movements.c.id,
                )
                .exists(),
            )
            .order_by(movements.c.effective_date.desc(), movements.c.id.desc())
            .limit(limit + 1)
        )
        if account_id is not None:
            scan = scan.where(movements.c.account_id == account_id)
        if result_effect is not None:
            scan = scan.where(movements.c.result_effect == result_effect.value)
        if after is not None:
            scan = scan.where(
                tuple_(movements.c.effective_date, movements.c.id)
                < tuple_(
                    literal(after.effective_date, Date()),
                    literal(after.movement_id, PG_UUID(as_uuid=True)),
                )
            )
        page = scan.subquery("pending_page")
        statement = (
            select(
                *page.c,
                accounts.c.visibility_scope.label("account_visibility_scope"),
                accounts.c.owner_operator_id.label("account_owner_operator_id"),
                accounts.c.status.label("account_status"),
            )
            .select_from(
                page.join(
                    accounts,
                    (accounts.c.id == page.c.account_id)
                    & (accounts.c.installation_id == page.c.installation_id)
                    & (accounts.c.residence_id == page.c.residence_id),
                )
            )
            .order_by(page.c.effective_date.desc(), page.c.id.desc())
        )

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
                if account_id is not None:
                    visible_account = connection.scalar(
                        select(accounts.c.id).where(
                            accounts.c.id == account_id,
                            accounts.c.installation_id == installation_id,
                            accounts.c.residence_id == residence_id,
                        )
                    )
                    if visible_account is None:
                        raise FinancialPendingMovementAccountNotFoundError(
                            "financial account was not found"
                        )
                rows = connection.execute(statement).mappings().all()
        except FinancialMovementAccessError:
            raise FinancialPendingMovementAccessError(
                "pending Movement access denied"
            ) from None
        except FinancialPendingMovementPersistenceError:
            raise
        except (DBAPIError, FinancialMovementPersistenceError):
            raise FinancialPendingMovementPersistenceError(
                "pending Movements could not be read"
            ) from None

        try:
            candidates = tuple(
                FinancialPendingMovementCandidate(
                    movement=_movement_record(row),
                    account_visibility_scope=FinancialVisibilityScope(
                        row["account_visibility_scope"]
                    ),
                    account_owner_operator_id=row["account_owner_operator_id"],
                    account_status=FinancialAccountStatus(row["account_status"]),
                )
                for row in rows[:limit]
            )
        except (KeyError, TypeError, ValueError, FinancialMovementPersistenceError):
            raise FinancialPendingMovementPersistenceError(
                "pending Movement state is invalid"
            ) from None
        return FinancialPendingMovementCandidatePage(
            candidates=candidates, has_more=len(rows) > limit
        )


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialPendingMovementAccessError",
    "FinancialPendingMovementAccountNotFoundError",
    "FinancialPendingMovementPersistenceError",
    "FinancialPendingMovementStore",
]
