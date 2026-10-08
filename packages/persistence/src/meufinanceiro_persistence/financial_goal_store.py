"""Residence/operator-aware persistence for financial goals and virtual allocations.

Goals are planning and an allocation is a virtual, append-only event: this store
never writes the ledger. A new allocation reads the *canonical* account balance in the
very transaction that appends the event, under a per-account advisory lock (ADR-0029),
so two concurrent allocations to one account cannot consume the same availability.
Movements are never blocked: they do not take that lock. Authorization is
double-checked: the store verifies what it can explain, forced RLS and database
triggers decide the rest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from meufinanceiro_finance import (
    GOAL_ACCOUNTS_MAX,
    GOAL_EVENTS_MAX,
    FinancialAccountRecord,
    FinancialGoalAccountInput,
    FinancialGoalAllocationDraft,
    FinancialGoalDraft,
    FinancialGoalEventKind,
    FinancialGoalEventRecord,
    FinancialGoalInsufficientAllocationError,
    FinancialGoalInsufficientAvailabilityError,
    FinancialGoalRecord,
    FinancialGoalReplacement,
    FinancialVisibilityScope,
    Money,
    is_goal_account_eligible,
    new_financial_resource_id,
    require_allocation_within_availability,
    require_release_within_allocated,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from sqlalchemy import Connection, Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_account_store import (
    get_account_in_transaction,
)
from meufinanceiro_persistence.financial_balance_transaction import (
    read_account_balance_in_transaction,
)
from meufinanceiro_persistence.financial_goal_schema import (
    financial_goal_allocation_events,
    financial_goals,
)
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    _require_active_membership,
    _set_context,
)

_CREATE_DIGEST_NAMESPACE = "meufinanceiro:goal-create:v1"
_EVENT_DIGEST_NAMESPACE = "meufinanceiro:goal-allocation:v1"
GOAL_LIST_MAX = 1000


class FinancialGoalPersistenceError(RuntimeError):
    """Sanitized persistence failure for goal operations."""


class FinancialGoalAccessError(FinancialGoalPersistenceError):
    """Actor has no active membership in the requested residence."""


class FinancialGoalNotFoundError(FinancialGoalPersistenceError):
    """Goal is missing or invisible to the actor (indistinguishable)."""


class FinancialGoalNotEditableError(FinancialGoalPersistenceError):
    """Goal is visible but the actor is not its owner."""


class FinancialGoalAccountNotFoundError(FinancialGoalPersistenceError):
    """Account is missing, invisible or not eligible for the goal (same error)."""


class FinancialGoalInvalidShapeError(FinancialGoalPersistenceError):
    """The request is well-typed but contradicts the stored goal identity."""


class FinancialGoalConflictError(FinancialGoalPersistenceError):
    """Idempotency key reused with other material, or the state forbids the write."""


class FinancialGoalVersionConflictError(FinancialGoalPersistenceError):
    """``expectedVersion`` is stale: the goal changed since the caller read it."""


class FinancialGoalLimitError(FinancialGoalPersistenceError):
    """An explicit bound (goals per owner, accounts or events per goal) was reached."""


class FinancialGoalAvailabilityError(FinancialGoalPersistenceError):
    """The allocation exceeds the balance not yet allocated to goals."""


class FinancialGoalReleaseError(FinancialGoalPersistenceError):
    """The release exceeds what the goal holds on that account."""


class FinancialGoalStore:
    """Create, read, list, CAS-edit and allocate to financial goals."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    # -- goals ----------------------------------------------------------------

    def create_goal(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialGoalDraft,
    ) -> FinancialGoalRecord:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialGoalDraft):
            raise TypeError("draft must be FinancialGoalDraft")

        request_digest = _create_digest(operator_id, draft)
        goals = financial_goals
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                existing = _goal_by_idempotency(
                    connection, installation_id, idempotency_key
                )
                if existing is not None:
                    return _replay_goal(existing, request_digest)

                inserted = (
                    connection.execute(
                        pg_insert(goals)
                        .values(
                            id=new_financial_resource_id(),
                            installation_id=installation_id,
                            residence_id=residence_id,
                            owner_operator_id=operator_id,
                            visibility_scope=draft.visibility_scope.value,
                            title=draft.title,
                            description=draft.description,
                            currency=draft.currency,
                            target_amount=draft.target.amount,
                            target_date=draft.target_date,
                            version=1,
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                            updated_by_operator_id=operator_id,
                            created_at=func.transaction_timestamp(),
                            updated_at=func.transaction_timestamp(),
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                goals.c.installation_id,
                                goals.c.idempotency_key,
                            ]
                        )
                        .returning(*goals.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if inserted is None:
                    raced = _goal_by_idempotency(
                        connection, installation_id, idempotency_key
                    )
                    if raced is not None:
                        return _replay_goal(raced, request_digest)
                    raise FinancialGoalConflictError("goal conflict")
                return _goal_record(inserted)
        except FinancialMovementAccessError:
            raise FinancialGoalAccessError("goal access denied") from None
        except FinancialGoalPersistenceError:
            raise
        except IntegrityError as error:
            raise _integrity_error(error) from None
        except DBAPIError:
            raise FinancialGoalPersistenceError("goal could not be persisted") from None

    def get_goal(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
    ) -> FinancialGoalRecord:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(goal_id)
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                row = _visible_goal(connection, installation_id, residence_id, goal_id)
                if row is None:
                    raise FinancialGoalNotFoundError("goal was not found")
                return _goal_record(row)
        except FinancialMovementAccessError:
            raise FinancialGoalAccessError("goal access denied") from None
        except FinancialGoalPersistenceError:
            raise
        except DBAPIError:
            raise FinancialGoalPersistenceError("goal could not be read") from None

    def list_goals(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[tuple[FinancialGoalRecord, Money], ...]:
        """Visible goals with what each one holds: two statements, no N+1.

        Fails (never truncates) when more than ``GOAL_LIST_MAX`` goals are visible.
        """
        _require_scope(installation_id, residence_id, operator_id)
        goals = financial_goals
        events = financial_goal_allocation_events
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                rows = (
                    connection.execute(
                        select(goals)
                        .where(
                            goals.c.installation_id == installation_id,
                            goals.c.residence_id == residence_id,
                        )
                        .order_by(goals.c.created_at, goals.c.id)
                        .limit(GOAL_LIST_MAX + 1)
                    )
                    .mappings()
                    .all()
                )
                if len(rows) > GOAL_LIST_MAX:
                    raise FinancialGoalLimitError("goal list exceeds its bound")
                totals: dict[UUID, Decimal] = {}
                if rows:
                    totals = {
                        total.goal_id: total.allocated
                        for total in connection.execute(
                            select(
                                events.c.goal_id,
                                func.sum(events.c.amount).label("allocated"),
                            )
                            .where(events.c.goal_id.in_([row["id"] for row in rows]))
                            .group_by(events.c.goal_id)
                        )
                    }
                records = [_goal_record(row) for row in rows]
                return tuple(
                    (record, Money(totals.get(record.id, Decimal(0)), record.currency))
                    for record in records
                )
        except FinancialMovementAccessError:
            raise FinancialGoalAccessError("goal access denied") from None
        except FinancialGoalPersistenceError:
            raise
        except DBAPIError:
            raise FinancialGoalPersistenceError("goals could not be read") from None

    def replace_goal(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
        replacement: FinancialGoalReplacement,
    ) -> FinancialGoalRecord:
        """Replace the planning data iff ``expected_version`` is still current (CAS).

        A stale version raises ``FinancialGoalVersionConflictError`` and writes
        nothing. Allocation events are never touched.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(goal_id)
        if not isinstance(replacement, FinancialGoalReplacement):
            raise TypeError("replacement must be FinancialGoalReplacement")
        goals = financial_goals
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                current = _visible_goal(
                    connection, installation_id, residence_id, goal_id
                )
                if current is None:
                    raise FinancialGoalNotFoundError("goal was not found")
                if current["owner_operator_id"] != operator_id:
                    raise FinancialGoalNotEditableError("goal is read-only")
                if current["version"] != replacement.expected_version:
                    raise FinancialGoalVersionConflictError("goal version is stale")
                if replacement.target.currency != current["currency"]:
                    raise FinancialGoalInvalidShapeError(
                        "target currency must match the goal currency"
                    )
                updated = (
                    connection.execute(
                        update(goals)
                        .where(
                            goals.c.id == goal_id,
                            goals.c.installation_id == installation_id,
                            goals.c.residence_id == residence_id,
                            goals.c.owner_operator_id == operator_id,
                            goals.c.version == replacement.expected_version,
                        )
                        .values(
                            title=replacement.title,
                            description=replacement.description,
                            target_amount=replacement.target.amount,
                            target_date=replacement.target_date,
                            version=replacement.expected_version + 1,
                            updated_at=func.transaction_timestamp(),
                            updated_by_operator_id=operator_id,
                        )
                        .returning(*goals.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if updated is None:
                    # Lost the race between the read above and the CAS.
                    raise FinancialGoalVersionConflictError("goal version is stale")
                return _goal_record(updated)
        except FinancialMovementAccessError:
            raise FinancialGoalAccessError("goal access denied") from None
        except FinancialGoalPersistenceError:
            raise
        except IntegrityError as error:
            raise _integrity_error(error) from None
        except DBAPIError:
            raise FinancialGoalPersistenceError("goal could not be persisted") from None

    # -- allocations ----------------------------------------------------------

    def allocate(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
        idempotency_key: UUID,
        draft: FinancialGoalAllocationDraft,
    ) -> FinancialGoalEventRecord:
        """Append one virtual ``ALLOCATE`` / ``RELEASE`` event, atomically.

        Order inside the one transaction: context, membership, idempotency replay,
        goal, account eligibility, **account advisory lock**, replay again (a racer
        with the same key may have won while we waited), availability or release
        check against the canonical balance and the event sums, then the insert.
        Nothing in ``finance.movements`` is read for write or touched.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(goal_id)
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialGoalAllocationDraft):
            raise TypeError("draft must be FinancialGoalAllocationDraft")

        request_digest = _event_digest(operator_id, goal_id, draft)
        events = financial_goal_allocation_events
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                replay = _event_by_idempotency(
                    connection, installation_id, idempotency_key
                )
                if replay is not None:
                    return _replay_event(replay, request_digest)

                goal = _visible_goal(connection, installation_id, residence_id, goal_id)
                if goal is None:
                    raise FinancialGoalNotFoundError("goal was not found")
                if goal["owner_operator_id"] != operator_id:
                    raise FinancialGoalNotEditableError("goal is read-only")
                if draft.amount.currency != goal["currency"]:
                    raise FinancialGoalInvalidShapeError(
                        "amount currency must match the goal currency"
                    )
                account = get_account_in_transaction(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    account_id=draft.account_id,
                )
                if account is None or not is_goal_account_eligible(
                    goal_visibility_scope=FinancialVisibilityScope(
                        goal["visibility_scope"]
                    ),
                    goal_owner_operator_id=goal["owner_operator_id"],
                    goal_currency=goal["currency"],
                    account=account,
                    for_new_allocation=draft.kind is FinancialGoalEventKind.ALLOCATE,
                ):
                    raise FinancialGoalAccountNotFoundError(
                        "financial account was not found"
                    )

                _lock_account(connection, account.id)
                replay = _event_by_idempotency(
                    connection, installation_id, idempotency_key
                )
                if replay is not None:
                    return _replay_event(replay, request_digest)

                if draft.kind is FinancialGoalEventKind.ALLOCATE:
                    self._require_availability(
                        connection,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        account=account,
                        draft=draft,
                    )
                else:
                    held = _sum(
                        connection,
                        events.c.goal_id == goal_id,
                        events.c.account_id == account.id,
                    )
                    try:
                        require_release_within_allocated(
                            allocated=Money(held, account.currency),
                            amount=draft.amount,
                        )
                    except FinancialGoalInsufficientAllocationError:
                        raise FinancialGoalReleaseError(
                            "release exceeds the allocated amount"
                        ) from None

                inserted = (
                    connection.execute(
                        pg_insert(events)
                        .values(
                            id=new_financial_resource_id(),
                            installation_id=installation_id,
                            residence_id=residence_id,
                            goal_id=goal_id,
                            account_id=account.id,
                            currency=account.currency,
                            kind=draft.kind.value,
                            amount=draft.signed_amount,
                            actor_operator_id=operator_id,
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                            created_at=func.transaction_timestamp(),
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                events.c.installation_id,
                                events.c.idempotency_key,
                            ]
                        )
                        .returning(*events.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if inserted is None:
                    raced = _event_by_idempotency(
                        connection, installation_id, idempotency_key
                    )
                    if raced is not None:
                        return _replay_event(raced, request_digest)
                    raise FinancialGoalConflictError("goal allocation conflict")
                return _event_record(inserted)
        except FinancialMovementAccessError:
            raise FinancialGoalAccessError("goal access denied") from None
        except FinancialGoalPersistenceError:
            raise
        except IntegrityError as error:
            raise _integrity_error(error) from None
        except DBAPIError:
            raise FinancialGoalPersistenceError(
                "goal allocation could not be persisted"
            ) from None

    @staticmethod
    def _require_availability(
        connection: Connection,
        *,
        installation_id: UUID,
        residence_id: UUID,
        account: FinancialAccountRecord,
        draft: FinancialGoalAllocationDraft,
    ) -> None:
        events = financial_goal_allocation_events
        snapshot = read_account_balance_in_transaction(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
            account=account,
            calculated_at=datetime.now(UTC),
        )
        allocated_total = _sum(connection, events.c.account_id == account.id)
        try:
            require_allocation_within_availability(
                balance=snapshot.current_balance,
                allocated_total=Money(allocated_total, account.currency),
                amount=draft.amount,
            )
        except FinancialGoalInsufficientAvailabilityError:
            raise FinancialGoalAvailabilityError(
                "allocation exceeds the available balance"
            ) from None

    # -- summary facts --------------------------------------------------------

    def read_goal_facts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        goal_id: UUID,
    ) -> tuple[
        FinancialGoalRecord,
        tuple[FinancialGoalEventRecord, ...],
        tuple[FinancialGoalAccountInput, ...],
    ]:
        """The goal, its full event history and the canonical account facts.

        One REPEATABLE READ, read-only transaction (a consistent snapshot) with a
        bounded number of statements: context, membership, goal, events, the
        per-account allocation totals and, per account the goal uses (at most
        ``GOAL_ACCOUNTS_MAX``), the account and its canonical balance reads. It
        never writes and never truncates: a history beyond its bound fails.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(goal_id)
        events = financial_goal_allocation_events
        try:
            with self._engine.connect().execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            ) as connection:
                with connection.begin():
                    _prepare(connection, installation_id, residence_id, operator_id)
                    row = _visible_goal(
                        connection, installation_id, residence_id, goal_id
                    )
                    if row is None:
                        raise FinancialGoalNotFoundError("goal was not found")
                    goal = _goal_record(row)
                    event_rows = (
                        connection.execute(
                            select(events)
                            .where(events.c.goal_id == goal_id)
                            .order_by(events.c.created_at, events.c.id)
                            .limit(GOAL_EVENTS_MAX + 1)
                        )
                        .mappings()
                        .all()
                    )
                    if len(event_rows) > GOAL_EVENTS_MAX:
                        raise FinancialGoalLimitError("goal history exceeds its bound")
                    history = tuple(_event_record(item) for item in event_rows)
                    account_ids = sorted({item.account_id for item in history}, key=str)
                    if len(account_ids) > GOAL_ACCOUNTS_MAX:
                        raise FinancialGoalLimitError(
                            "goal accounts exceed their bound"
                        )
                    inputs = self._account_inputs(
                        connection,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        currency=goal.currency,
                        account_ids=account_ids,
                    )
                    return goal, history, inputs
        except FinancialMovementAccessError:
            raise FinancialGoalAccessError("goal access denied") from None
        except FinancialGoalPersistenceError:
            raise
        except DBAPIError:
            raise FinancialGoalPersistenceError("goal could not be read") from None

    @staticmethod
    def _account_inputs(
        connection: Connection,
        *,
        installation_id: UUID,
        residence_id: UUID,
        currency: str,
        account_ids: Sequence[UUID],
    ) -> tuple[FinancialGoalAccountInput, ...]:
        if not account_ids:
            return ()
        events = financial_goal_allocation_events
        totals = {
            total.account_id: total.allocated
            for total in connection.execute(
                select(
                    events.c.account_id,
                    func.sum(events.c.amount).label("allocated"),
                )
                .where(events.c.account_id.in_(list(account_ids)))
                .group_by(events.c.account_id)
            )
        }
        calculated_at = datetime.now(UTC)
        inputs: list[FinancialGoalAccountInput] = []
        for account_id in account_ids:
            account = get_account_in_transaction(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                account_id=account_id,
            )
            if account is None:
                raise FinancialGoalPersistenceError("goal account state is invalid")
            snapshot = read_account_balance_in_transaction(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                account=account,
                calculated_at=calculated_at,
            )
            try:
                inputs.append(
                    FinancialGoalAccountInput(
                        account_id=account_id,
                        account_status=account.status,
                        balance=snapshot.current_balance,
                        allocated_total=Money(
                            totals.get(account_id, Decimal(0)), currency
                        ),
                    )
                )
            except (TypeError, ValueError):
                raise FinancialGoalPersistenceError(
                    "goal account state is invalid"
                ) from None
        return tuple(inputs)


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


def _lock_account(connection: Connection, account_id: UUID) -> None:
    """Serialize every allocation to one account for the rest of the transaction.

    Same key as the event trigger (which re-takes it; the lock is re-entrant). It is
    never taken by Movement writers, so a goal can never block the ledger.
    """
    connection.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(
                    "meufinanceiro:goal-account:" + str(account_id), 0
                )
            )
        )
    )


def _sum(connection: Connection, *conditions: ColumnElement[bool]) -> Decimal:
    events = financial_goal_allocation_events
    value = connection.scalar(
        select(func.coalesce(func.sum(events.c.amount), 0)).where(*conditions)
    )
    return Decimal(0) if value is None else Decimal(value)


def _create_digest(operator_id: UUID, draft: FinancialGoalDraft) -> str:
    material = json.dumps(
        [_CREATE_DIGEST_NAMESPACE, str(operator_id), draft.canonical_material()],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _event_digest(
    operator_id: UUID, goal_id: UUID, draft: FinancialGoalAllocationDraft
) -> str:
    material = json.dumps(
        [
            _EVENT_DIGEST_NAMESPACE,
            str(operator_id),
            str(goal_id),
            draft.canonical_material(),
        ],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _goal_by_idempotency(
    connection: Connection, installation_id: UUID, idempotency_key: UUID
) -> RowMapping | None:
    goals = financial_goals
    return (
        connection.execute(
            select(goals).where(
                goals.c.installation_id == installation_id,
                goals.c.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )


def _event_by_idempotency(
    connection: Connection, installation_id: UUID, idempotency_key: UUID
) -> RowMapping | None:
    events = financial_goal_allocation_events
    return (
        connection.execute(
            select(events).where(
                events.c.installation_id == installation_id,
                events.c.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )


def _visible_goal(
    connection: Connection,
    installation_id: UUID,
    residence_id: UUID,
    goal_id: UUID,
) -> RowMapping | None:
    goals = financial_goals
    return (
        connection.execute(
            select(goals).where(
                goals.c.id == goal_id,
                goals.c.installation_id == installation_id,
                goals.c.residence_id == residence_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _replay_goal(row: RowMapping, request_digest: str) -> FinancialGoalRecord:
    if row["request_digest"] != request_digest:
        raise FinancialGoalConflictError("goal idempotency conflict")
    return _goal_record(row)


def _replay_event(row: RowMapping, request_digest: str) -> FinancialGoalEventRecord:
    if row["request_digest"] != request_digest:
        raise FinancialGoalConflictError("goal allocation idempotency conflict")
    return _event_record(row)


def _goal_record(row: RowMapping) -> FinancialGoalRecord:
    try:
        return FinancialGoalRecord(
            id=row["id"],
            residence_id=row["residence_id"],
            owner_operator_id=row["owner_operator_id"],
            visibility_scope=FinancialVisibilityScope(row["visibility_scope"]),
            title=row["title"],
            description=row["description"],
            target=Money(row["target_amount"], row["currency"]),
            target_date=row["target_date"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialGoalPersistenceError("goal state is invalid") from None


def _event_record(row: RowMapping) -> FinancialGoalEventRecord:
    try:
        return FinancialGoalEventRecord(
            id=row["id"],
            goal_id=row["goal_id"],
            account_id=row["account_id"],
            kind=FinancialGoalEventKind(row["kind"]),
            amount=Money(abs(row["amount"]), row["currency"]),
            actor_operator_id=row["actor_operator_id"],
            created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialGoalPersistenceError("goal event state is invalid") from None


_LIMIT_CONSTRAINTS = frozenset(
    (
        "ck_finance_goals_owner_limit",
        "ck_finance_goal_events_event_limit",
        "ck_finance_goal_events_account_limit",
    )
)


def _integrity_error(error: IntegrityError) -> FinancialGoalPersistenceError:
    diagnostic = getattr(error.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    if name in _LIMIT_CONSTRAINTS:
        return FinancialGoalLimitError("goal limit reached")
    if name == "ck_finance_goal_events_negative":
        return FinancialGoalReleaseError("release exceeds the allocated amount")
    if name == "ck_finance_goal_events_account":
        return FinancialGoalAccountNotFoundError("financial account was not found")
    return FinancialGoalConflictError("goal conflict")


__all__ = [
    "GOAL_LIST_MAX",
    "FinancialGoalAccessError",
    "FinancialGoalAccountNotFoundError",
    "FinancialGoalAvailabilityError",
    "FinancialGoalConflictError",
    "FinancialGoalInvalidShapeError",
    "FinancialGoalLimitError",
    "FinancialGoalNotEditableError",
    "FinancialGoalNotFoundError",
    "FinancialGoalPersistenceError",
    "FinancialGoalReleaseError",
    "FinancialGoalStore",
    "FinancialGoalVersionConflictError",
]
