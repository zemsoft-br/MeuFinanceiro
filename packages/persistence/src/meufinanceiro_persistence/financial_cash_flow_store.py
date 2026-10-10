"""Read-only loading of everything one cash flow projection needs (ADR-0031).

Nothing here is written, persisted, cached or locked. The whole read is one
REPEATABLE READ, read-only transaction, so the accounts, the ledger aggregates,
the window Movements and the recurrence model all come from the same snapshot:
a Movement or occurrence committed between two statements can never appear in
one and be missing from another. The pure domain function ``project_cash_flow``
then derives the projection; this module holds no financial rule.

Authorization is the database's: the session context is set, an active
membership is required, and forced RLS on accounts, Movements, transfer legs,
recurrence rules and occurrences decides the audience *before* any sum. Explicit
account filters only narrow what RLS already allows; an account that is not
visible is indistinguishable from one that does not exist.

Cost shape: a fixed number of statements, independent of the number of accounts,
Movements, rules or occurrences (context, membership, accounts, opening balances,
ledger aggregates, window Movements, transfer legs, realized occurrences plus
their two derivation reads, pending occurrences, live occurrence months, rules).
Every list is bounded and an overflow fails instead of being cut short.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from meufinanceiro_finance import (
    CASH_FLOW_ACCOUNTS_MAX,
    CASH_FLOW_EVENTS_MAX,
    RECURRENCE_LIST_MAX,
    RECURRENCE_OCCURRENCE_LIST_MAX,
    FinancialAccountRecord,
    FinancialCashFlowAccountInput,
    FinancialCashFlowLimitError,
    FinancialCashFlowSource,
    FinancialCashFlowWindow,
    FinancialMovementRecord,
    FinancialOccurrenceStatus,
    FinancialOpeningBalanceRecord,
    FinancialRecurrenceOccurrenceRecord,
    FinancialRecurrenceRecord,
    Money,
    cash_flow_rule_months,
    validate_currency_code,
    validate_financial_resource_id,
)
from sqlalchemy import Connection, Engine, case, func, select
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_account_store import (
    FinancialAccountPersistenceError,
)
from meufinanceiro_persistence.financial_account_store import (
    _record as _account_record,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    FinancialMovementPersistenceError,
    _require_active_membership,
    _set_context,
)
from meufinanceiro_persistence.financial_movement_store import (
    _record as _movement_record,
)
from meufinanceiro_persistence.financial_opening_balance_schema import (
    financial_opening_balances,
)
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalancePersistenceError,
)
from meufinanceiro_persistence.financial_opening_balance_store import (
    _record as _opening_record,
)
from meufinanceiro_persistence.financial_recurrence_schema import (
    financial_recurrence_occurrences,
    financial_recurrences,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrencePersistenceError,
    _load_occurrences,
    _occurrence_record,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    _record as _rule_record,
)
from meufinanceiro_persistence.financial_transfer_schema import (
    financial_transfer_legs,
)


class FinancialCashFlowPersistenceError(RuntimeError):
    """The cash flow could not be read (sanitized)."""


class FinancialCashFlowAccessError(FinancialCashFlowPersistenceError):
    """No active membership in the residence."""


class FinancialCashFlowAccountNotFoundError(FinancialCashFlowPersistenceError):
    """A requested account does not exist or is not visible (indistinguishable)."""


class FinancialCashFlowLimitExceededError(FinancialCashFlowPersistenceError):
    """The selection holds more accounts or events than one read may return."""


_OCCURRENCE_LIVE_MONTHS_MAX = RECURRENCE_OCCURRENCE_LIST_MAX


class FinancialCashFlowStore:
    """Load one consistent :class:`FinancialCashFlowSource` for a window."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def read_source(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        window: FinancialCashFlowWindow,
        account_ids: tuple[UUID, ...] | None = None,
        currency: str | None = None,
    ) -> FinancialCashFlowSource:
        """Everything the projection reads, from one REPEATABLE READ snapshot.

        ``account_ids`` ``None`` selects every visible ACTIVE account; an explicit
        selection must be visible (any status) or the read fails with
        :class:`FinancialCashFlowAccountNotFoundError`. ``currency`` narrows the
        selection to one currency.
        """
        _require_scope(installation_id, residence_id, operator_id)
        if not isinstance(window, FinancialCashFlowWindow):
            raise TypeError("window must be FinancialCashFlowWindow")
        selection = _selection(account_ids)
        if currency is not None:
            currency = validate_currency_code(currency)
        try:
            with self._engine.connect().execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            ) as connection:
                with connection.begin():
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
                    return _read(
                        connection,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        window=window,
                        selection=selection,
                        currency=currency,
                    )
        except FinancialMovementAccessError:
            raise FinancialCashFlowAccessError("cash flow access denied") from None
        except FinancialCashFlowPersistenceError:
            raise
        except FinancialCashFlowLimitError:
            raise FinancialCashFlowLimitExceededError(
                "cash flow selection is too large"
            ) from None
        except (
            FinancialMovementPersistenceError,
            FinancialAccountPersistenceError,
            FinancialOpeningBalancePersistenceError,
            FinancialRecurrencePersistenceError,
            DBAPIError,
            ArithmeticError,
            TypeError,
            ValueError,
        ):
            raise FinancialCashFlowPersistenceError(
                "cash flow could not be read"
            ) from None


def _read(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    window: FinancialCashFlowWindow,
    selection: tuple[UUID, ...] | None,
    currency: str | None,
) -> FinancialCashFlowSource:
    accounts = _accounts(connection, installation_id, residence_id, selection, currency)
    ids = [account.id for account in accounts]
    scope = (installation_id, residence_id)
    openings = _openings(connection, scope, ids)
    before, through_reference = _aggregates(connection, scope, ids, window)
    entries = tuple(
        FinancialCashFlowAccountInput(
            account=account,
            opening_balance=openings.get(account.id),
            net_before_window=Money(
                before.get(account.id, Decimal(0)), account.currency
            ),
            net_through_reference=Money(
                through_reference.get(account.id, Decimal(0)), account.currency
            ),
        )
        for account in accounts
    )
    movements = _window_movements(connection, scope, ids, window)
    movement_ids = [movement.id for movement in movements]
    transfer_ids = _transfer_ids(connection, movement_ids)
    realized = _realized_occurrences(connection, scope, movement_ids)
    months = cash_flow_rule_months(window)
    pending: tuple[FinancialRecurrenceOccurrenceRecord, ...] = ()
    live: frozenset[tuple[UUID, date]] = frozenset()
    if months is not None:
        pending = _pending_occurrences(connection, scope, ids, window)
        live = _live_months(
            connection, scope, ids, months.from_period, months.through_period
        )
    rules = _rules(connection, scope, ids)
    return FinancialCashFlowSource(
        accounts=entries,
        movements=movements,
        transfer_ids=transfer_ids,
        realized_occurrences=realized,
        pending_occurrences=pending,
        live_occurrence_months=live,
        rules=rules,
    )


def _accounts(
    connection: Connection,
    installation_id: UUID,
    residence_id: UUID,
    selection: tuple[UUID, ...] | None,
    currency: str | None,
) -> tuple[FinancialAccountRecord, ...]:
    accounts = financial_accounts
    statement = select(accounts).where(
        accounts.c.installation_id == installation_id,
        accounts.c.residence_id == residence_id,
    )
    if selection is None:
        statement = statement.where(accounts.c.status == "ACTIVE")
        if currency is not None:
            statement = statement.where(accounts.c.currency == currency)
    else:
        statement = statement.where(accounts.c.id.in_(selection))
    rows = (
        connection.execute(
            statement.order_by(accounts.c.created_at, accounts.c.id).limit(
                CASH_FLOW_ACCOUNTS_MAX + 1
            )
        )
        .mappings()
        .all()
    )
    if selection is not None and len(rows) != len(selection):
        # Unknown, invisible (forced RLS) and other-residence ids look the same.
        raise FinancialCashFlowAccountNotFoundError("financial account was not found")
    if len(rows) > CASH_FLOW_ACCOUNTS_MAX:
        raise FinancialCashFlowLimitExceededError("cash flow selection is too large")
    records = tuple(_account_record(row) for row in rows)
    if currency is not None:
        # An explicit selection is proven visible first, then narrowed.
        records = tuple(record for record in records if record.currency == currency)
    return records


def _openings(
    connection: Connection, scope: tuple[UUID, UUID], ids: list[UUID]
) -> dict[UUID, FinancialOpeningBalanceRecord]:
    if not ids:
        return {}
    table = financial_opening_balances
    rows = (
        connection.execute(
            select(table).where(
                table.c.installation_id == scope[0],
                table.c.residence_id == scope[1],
                table.c.account_id.in_(ids),
            )
        )
        .mappings()
        .all()
    )
    openings: dict[UUID, FinancialOpeningBalanceRecord] = {}
    for row in rows:
        record = _opening_record(row)
        if record.account_id in openings:
            raise FinancialCashFlowPersistenceError("cash flow state is invalid")
        openings[record.account_id] = record
    return openings


def _aggregates(
    connection: Connection,
    scope: tuple[UUID, UUID],
    ids: list[UUID],
    window: FinancialCashFlowWindow,
) -> tuple[dict[UUID, Decimal], dict[UUID, Decimal]]:
    """Exact NUMERIC sums: before the window and up to the reference date.

    ``from <= reference`` always holds, so one scan of ``effective_date <=
    reference`` (index ``ix_finance_movements_account_effective``) feeds both.
    """
    if not ids:
        return {}, {}
    movements = financial_movements
    before = func.coalesce(
        func.sum(
            case(
                (movements.c.effective_date < window.from_date, movements.c.amount),
                else_=0,
            )
        ),
        0,
    )
    rows = connection.execute(
        select(
            movements.c.account_id,
            before.label("before_window"),
            func.sum(movements.c.amount).label("through_reference"),
        )
        .where(
            movements.c.installation_id == scope[0],
            movements.c.residence_id == scope[1],
            movements.c.account_id.in_(ids),
            movements.c.effective_date <= window.reference_date,
        )
        .group_by(movements.c.account_id)
    ).all()
    return (
        {row.account_id: Decimal(row.before_window) for row in rows},
        {row.account_id: Decimal(row.through_reference) for row in rows},
    )


def _window_movements(
    connection: Connection,
    scope: tuple[UUID, UUID],
    ids: list[UUID],
    window: FinancialCashFlowWindow,
) -> tuple[FinancialMovementRecord, ...]:
    if not ids:
        return ()
    movements = financial_movements
    rows = (
        connection.execute(
            select(movements)
            .where(
                movements.c.installation_id == scope[0],
                movements.c.residence_id == scope[1],
                movements.c.account_id.in_(ids),
                movements.c.effective_date >= window.from_date,
                movements.c.effective_date <= window.through_date,
            )
            .order_by(
                movements.c.effective_date, movements.c.created_at, movements.c.id
            )
            .limit(CASH_FLOW_EVENTS_MAX + 1)
        )
        .mappings()
        .all()
    )
    if len(rows) > CASH_FLOW_EVENTS_MAX:
        raise FinancialCashFlowLimitExceededError("cash flow selection is too large")
    return tuple(_movement_record(row) for row in rows)


def _transfer_ids(connection: Connection, movement_ids: list[UUID]) -> dict[UUID, UUID]:
    if not movement_ids:
        return {}
    legs = financial_transfer_legs
    rows = connection.execute(
        select(legs.c.movement_id, legs.c.transfer_id).where(
            legs.c.movement_id.in_(movement_ids)
        )
    ).all()
    return {row.movement_id: row.transfer_id for row in rows}


def _realized_occurrences(
    connection: Connection, scope: tuple[UUID, UUID], movement_ids: list[UUID]
) -> dict[UUID, FinancialRecurrenceOccurrenceRecord]:
    """REALIZED occurrences linked to window Movements (``movement_id`` is unique)."""
    if not movement_ids:
        return {}
    occurrences = financial_recurrence_occurrences
    rows = (
        connection.execute(
            select(occurrences).where(
                occurrences.c.installation_id == scope[0],
                occurrences.c.residence_id == scope[1],
                occurrences.c.status == FinancialOccurrenceStatus.REALIZED.value,
                occurrences.c.movement_id.in_(movement_ids),
            )
        )
        .mappings()
        .all()
    )
    realized: dict[UUID, FinancialRecurrenceOccurrenceRecord] = {}
    for record in _load_occurrences(connection, rows):
        if record.realization is None or record.realization.movement_id in realized:
            raise FinancialCashFlowPersistenceError("cash flow state is invalid")
        realized[record.realization.movement_id] = record
    return realized


def _pending_occurrences(
    connection: Connection,
    scope: tuple[UUID, UUID],
    ids: list[UUID],
    window: FinancialCashFlowWindow,
) -> tuple[FinancialRecurrenceOccurrenceRecord, ...]:
    """Every PENDING occurrence due by the end of the window, overdue included."""
    if not ids:
        return ()
    occurrences = financial_recurrence_occurrences
    rows = (
        connection.execute(
            select(occurrences)
            .where(
                occurrences.c.installation_id == scope[0],
                occurrences.c.residence_id == scope[1],
                occurrences.c.account_id.in_(ids),
                occurrences.c.status == FinancialOccurrenceStatus.PENDING.value,
                occurrences.c.scheduled_date <= window.through_date,
            )
            .order_by(
                occurrences.c.scheduled_date,
                occurrences.c.recurrence_id,
                occurrences.c.id,
            )
            .limit(CASH_FLOW_EVENTS_MAX + 1)
        )
        .mappings()
        .all()
    )
    if len(rows) > CASH_FLOW_EVENTS_MAX:
        raise FinancialCashFlowLimitExceededError("cash flow selection is too large")
    return tuple(_occurrence_record(row) for row in rows)


def _live_months(
    connection: Connection,
    scope: tuple[UUID, UUID],
    ids: list[UUID],
    first: date,
    last: date,
) -> frozenset[tuple[UUID, date]]:
    """Months already decided by a live (non-SUPERSEDED) occurrence."""
    if not ids:
        return frozenset()
    occurrences = financial_recurrence_occurrences
    rows = connection.execute(
        select(occurrences.c.recurrence_id, occurrences.c.period_start)
        .where(
            occurrences.c.installation_id == scope[0],
            occurrences.c.residence_id == scope[1],
            occurrences.c.account_id.in_(ids),
            occurrences.c.status != FinancialOccurrenceStatus.SUPERSEDED.value,
            occurrences.c.period_start >= first,
            occurrences.c.period_start <= last,
        )
        .limit(_OCCURRENCE_LIVE_MONTHS_MAX + 1)
    ).all()
    if len(rows) > _OCCURRENCE_LIVE_MONTHS_MAX:
        raise FinancialCashFlowLimitExceededError("cash flow selection is too large")
    return frozenset((row.recurrence_id, row.period_start) for row in rows)


def _rules(
    connection: Connection, scope: tuple[UUID, UUID], ids: list[UUID]
) -> tuple[FinancialRecurrenceRecord, ...]:
    if not ids:
        return ()
    rules = financial_recurrences
    rows = (
        connection.execute(
            select(rules)
            .where(
                rules.c.installation_id == scope[0],
                rules.c.residence_id == scope[1],
                rules.c.account_id.in_(ids),
            )
            .order_by(rules.c.created_at, rules.c.id)
            .limit(RECURRENCE_LIST_MAX + 1)
        )
        .mappings()
        .all()
    )
    if len(rows) > RECURRENCE_LIST_MAX:
        raise FinancialCashFlowLimitExceededError("cash flow selection is too large")
    return tuple(_rule_record(row) for row in rows)


def _selection(account_ids: tuple[UUID, ...] | None) -> tuple[UUID, ...] | None:
    if account_ids is None:
        return None
    if not isinstance(account_ids, tuple) or not account_ids:
        raise ValueError("account_ids must be a non-empty tuple or None")
    if len(account_ids) > CASH_FLOW_ACCOUNTS_MAX:
        raise FinancialCashFlowLimitExceededError("cash flow selection is too large")
    for account_id in account_ids:
        validate_financial_resource_id(account_id)
    if len(set(account_ids)) != len(account_ids):
        raise ValueError("account_ids must be unique")
    return account_ids


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


__all__ = [
    "FinancialCashFlowAccessError",
    "FinancialCashFlowAccountNotFoundError",
    "FinancialCashFlowLimitExceededError",
    "FinancialCashFlowPersistenceError",
    "FinancialCashFlowStore",
]
