"""Residence-scoped projects, immutable expense-link revisions and derived facts.

The ledger and category allocation authorities are never written here. Link
concurrency is serialized by the exact advisory lock used by migration 0029.
RLS always executes as the non-privileged runtime role (ADR-0030, #262).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from uuid import UUID

from meufinanceiro_finance import (
    FinancialMovementRole,
    FinancialProjectDraft,
    FinancialProjectExpenseFact,
    FinancialProjectLinkRevisionDraft,
    FinancialProjectLinkRevisionRecord,
    FinancialProjectRecord,
    FinancialProjectReplacement,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    new_financial_resource_id,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    _record as movement_record,
    _require_active_membership,
    _set_context,
)
from meufinanceiro_persistence.financial_project_schema import (
    financial_project_link_revisions,
    financial_projects,
)

PROJECT_LIST_MAX = 1000
PROJECT_LINKS_MAX = 1000
PROJECT_REVISIONS_MAX = 100
_CREATE_DIGEST_NS = "meufinanceiro:project-create:v1"
_LINK_DIGEST_NS = "meufinanceiro:project-link:v1"


class FinancialProjectPersistenceError(RuntimeError):
    """Sanitized failure in project persistence."""


class FinancialProjectAccessError(FinancialProjectPersistenceError):
    """No active membership in the requested residence."""


class FinancialProjectNotFoundError(FinancialProjectPersistenceError):
    """Project or linked Movement does not exist or is invisible."""


class FinancialProjectNotEditableError(FinancialProjectPersistenceError):
    """Visible project, but only its owner can edit it."""


class FinancialProjectConflictError(FinancialProjectPersistenceError):
    """Stale predecessor/CAS, ineligible target or mismatched idempotency."""


class FinancialProjectLimitError(FinancialProjectPersistenceError):
    """Bounded read or write limit is exceeded (no silent truncation)."""


class FinancialProjectStore:
    """Persist project planning and one versioned link chain per expense."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def create_project(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialProjectDraft,
    ) -> FinancialProjectRecord:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialProjectDraft):
            raise TypeError("draft must be FinancialProjectDraft")
        digest = _digest(_CREATE_DIGEST_NS, operator_id, draft.canonical_material())
        p = financial_projects
        try:
            with self._engine.begin() as conn:
                _prepare(conn, installation_id, residence_id, operator_id)
                existing = _project_by_key(conn, installation_id, idempotency_key)
                if existing is not None:
                    return _replay_project(existing, digest)
                inserted = conn.execute(
                    pg_insert(p).values(
                        id=new_financial_resource_id(),
                        installation_id=installation_id,
                        residence_id=residence_id,
                        owner_operator_id=operator_id,
                        visibility_scope=draft.visibility_scope.value,
                        title=draft.title,
                        description=draft.description,
                        currency=draft.planned.currency,
                        planned_amount=draft.planned.amount,
                        target_date=draft.target_date,
                        version=1,
                        idempotency_key=idempotency_key,
                        request_digest=digest,
                        updated_by_operator_id=operator_id,
                        created_at=func.transaction_timestamp(),
                        updated_at=func.transaction_timestamp(),
                    ).on_conflict_do_nothing(
                        index_elements=[p.c.installation_id, p.c.idempotency_key]
                    ).returning(*p.c)
                ).mappings().one_or_none()
                if inserted is not None:
                    return _project_record(inserted)
                raced = _project_by_key(conn, installation_id, idempotency_key)
                if raced is not None:
                    return _replay_project(raced, digest)
                raise FinancialProjectConflictError("project conflict")
        except FinancialMovementAccessError:
            raise FinancialProjectAccessError("project access denied") from None
        except FinancialProjectPersistenceError:
            raise
        except IntegrityError as error:
            raise _integrity_error(error) from None
        except DBAPIError:
            raise FinancialProjectPersistenceError(
                "project could not be persisted"
            ) from None

    def get_project(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        project_id: UUID,
    ) -> FinancialProjectRecord:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(project_id)
        try:
            with self._engine.begin() as conn:
                _prepare(conn, installation_id, residence_id, operator_id)
                row = _visible_project(conn, installation_id, residence_id, project_id)
                if row is None:
                    raise FinancialProjectNotFoundError("project was not found")
                return _project_record(row)
        except FinancialMovementAccessError:
            raise FinancialProjectAccessError("project access denied") from None
        except FinancialProjectPersistenceError:
            raise
        except DBAPIError:
            raise FinancialProjectPersistenceError(
                "project could not be read"
            ) from None

    def list_projects(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialProjectRecord, ...]:
        _require_scope(installation_id, residence_id, operator_id)
        p = financial_projects
        try:
            with self._engine.begin() as conn:
                _prepare(conn, installation_id, residence_id, operator_id)
                rows = conn.execute(
                    select(p).where(
                        p.c.installation_id == installation_id,
                        p.c.residence_id == residence_id,
                    ).order_by(p.c.created_at, p.c.id).limit(PROJECT_LIST_MAX + 1)
                ).mappings().all()
                if len(rows) > PROJECT_LIST_MAX:
                    raise FinancialProjectLimitError("project list exceeds bound")
                return tuple(_project_record(row) for row in rows)
        except FinancialMovementAccessError:
            raise FinancialProjectAccessError("project access denied") from None
        except FinancialProjectPersistenceError:
            raise
        except DBAPIError:
            raise FinancialProjectPersistenceError(
                "projects could not be read"
            ) from None

    def replace_project(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        project_id: UUID,
        replacement: FinancialProjectReplacement,
    ) -> FinancialProjectRecord:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(project_id)
        if not isinstance(replacement, FinancialProjectReplacement):
            raise TypeError("replacement must be FinancialProjectReplacement")
        p = financial_projects
        try:
            with self._engine.begin() as conn:
                _prepare(conn, installation_id, residence_id, operator_id)
                row = _visible_project(conn, installation_id, residence_id, project_id)
                if row is None:
                    raise FinancialProjectNotFoundError("project was not found")
                if row["owner_operator_id"] != operator_id:
                    raise FinancialProjectNotEditableError("project is read-only")
                if replacement.planned.currency != row["currency"]:
                    raise FinancialProjectConflictError("project currency is immutable")
                updated = conn.execute(
                    update(p).where(
                        p.c.id == project_id,
                        p.c.installation_id == installation_id,
                        p.c.residence_id == residence_id,
                        p.c.owner_operator_id == operator_id,
                        p.c.version == replacement.expected_version,
                    ).values(
                        title=replacement.title,
                        description=replacement.description,
                        planned_amount=replacement.planned.amount,
                        target_date=replacement.target_date,
                        version=replacement.expected_version + 1,
                        updated_at=func.transaction_timestamp(),
                        updated_by_operator_id=operator_id,
                    ).returning(*p.c)
                ).mappings().one_or_none()
                if updated is None:
                    raise FinancialProjectConflictError("project version is stale")
                return _project_record(updated)
        except FinancialMovementAccessError:
            raise FinancialProjectAccessError("project access denied") from None
        except FinancialProjectPersistenceError:
            raise
        except IntegrityError as error:
            raise _integrity_error(error) from None
        except DBAPIError:
            raise FinancialProjectPersistenceError(
                "project could not be updated"
            ) from None

    def revise_link(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialProjectLinkRevisionDraft,
    ) -> FinancialProjectLinkRevisionRecord:
        """Append one link/unlink/reassign under the movement-scoped SQL lock.

        A first-key lookup is an optimization only. The lock + second lookup
        settle concurrent replay, and the insert trigger enforces the chain.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialProjectLinkRevisionDraft):
            raise TypeError("draft must be FinancialProjectLinkRevisionDraft")
        digest = _digest(_LINK_DIGEST_NS, operator_id, draft.canonical_material())
        h = financial_project_link_revisions
        m = financial_movements
        a = financial_accounts
        try:
            with self._engine.begin() as conn:
                _prepare(conn, installation_id, residence_id, operator_id)
                existing = _link_by_key(conn, installation_id, idempotency_key)
                if existing is not None:
                    return _replay_link(existing, digest)
                _lock_movement(conn, draft.movement_id)
                raced = _link_by_key(conn, installation_id, idempotency_key)
                if raced is not None:
                    return _replay_link(raced, digest)

                target = conn.execute(
                    select(
                        m.c.id, m.c.account_id, m.c.currency,
                        m.c.role, m.c.result_effect,
                        a.c.owner_operator_id, a.c.visibility_scope,
                        a.c.status,
                    ).join(a, m.c.account_id == a.c.id).where(
                        m.c.id == draft.movement_id,
                        m.c.installation_id == installation_id,
                        m.c.residence_id == residence_id,
                        m.c.role == FinancialMovementRole.STANDARD.value,
                        m.c.result_effect == FinancialResultEffect.EXPENSE.value,
                    )
                ).mappings().one_or_none()
                if target is None:
                    raise FinancialProjectNotFoundError("expense was not found")
                if (
                    target["owner_operator_id"] != operator_id
                    or target["visibility_scope"] not in ("PERSONAL", "HOUSEHOLD")
                ):
                    raise FinancialProjectConflictError("expense is not eligible")
                if draft.project_id is not None:
                    project = _visible_project(
                        conn, installation_id, residence_id, draft.project_id
                    )
                    if project is None:
                        raise FinancialProjectNotFoundError("project was not found")
                    if (
                        project["owner_operator_id"] != operator_id
                        or project["visibility_scope"] != target["visibility_scope"]
                        or project["currency"] != target["currency"]
                        or target["status"] != "ACTIVE"
                    ):
                        raise FinancialProjectConflictError("project link is invalid")

                latest = conn.execute(
                    select(h).where(
                        h.c.installation_id == installation_id,
                        h.c.residence_id == residence_id,
                        h.c.movement_id == draft.movement_id,
                    ).order_by(h.c.revision.desc()).limit(1)
                ).mappings().one_or_none()
                if (
                    (latest is None and draft.expected_predecessor_id is not None)
                    or (
                        latest is not None
                        and latest["id"] != draft.expected_predecessor_id
                    )
                ):
                    raise FinancialProjectConflictError("link predecessor is stale")
                if latest is None and draft.project_id is None:
                    raise FinancialProjectConflictError("nothing to unlink")
                if latest is not None and latest["project_id"] == draft.project_id:
                    raise FinancialProjectConflictError("link state is unchanged")
                revision = 1 if latest is None else latest["revision"] + 1
                if revision > PROJECT_REVISIONS_MAX:
                    raise FinancialProjectLimitError("link revision limit reached")
                inserted = conn.execute(
                    pg_insert(h).values(
                        id=new_financial_resource_id(),
                        installation_id=installation_id,
                        residence_id=residence_id,
                        movement_id=draft.movement_id,
                        account_id=target["account_id"],
                        currency=target["currency"],
                        result_effect=target["result_effect"],
                        role=target["role"],
                        owner_operator_id=operator_id,
                        visibility_scope=target["visibility_scope"],
                        project_id=draft.project_id,
                        supersedes_id=latest["id"] if latest is not None else None,
                        revision=revision,
                        actor_operator_id=operator_id,
                        idempotency_key=idempotency_key,
                        request_digest=digest,
                        created_at=func.transaction_timestamp(),
                    ).on_conflict_do_nothing(
                        index_elements=[h.c.installation_id, h.c.idempotency_key]
                    ).returning(*h.c)
                ).mappings().one_or_none()
                if inserted is not None:
                    return _link_record(inserted)
                # A concurrent key on a different Movement can win independently;
                # still return only if its digest and RLS visibility match.
                raced = _link_by_key(conn, installation_id, idempotency_key)
                if raced is not None:
                    return _replay_link(raced, digest)
                raise FinancialProjectConflictError("project link conflict")
        except FinancialMovementAccessError:
            raise FinancialProjectAccessError("project access denied") from None
        except FinancialProjectPersistenceError:
            raise
        except IntegrityError as error:
            raise _integrity_error(error) from None
        except DBAPIError:
            raise FinancialProjectPersistenceError(
                "project link could not be persisted"
            ) from None

    def get_link(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> FinancialProjectLinkRevisionRecord | None:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(movement_id)
        h = financial_project_link_revisions
        try:
            with self._engine.begin() as conn:
                _prepare(conn, installation_id, residence_id, operator_id)
                _require_visible_original_expense(
                    conn, installation_id, residence_id, movement_id
                )
                row = conn.execute(
                    select(h).where(
                        h.c.installation_id == installation_id,
                        h.c.residence_id == residence_id,
                        h.c.movement_id == movement_id,
                    ).order_by(h.c.revision.desc()).limit(1)
                ).mappings().one_or_none()
                return None if row is None else _link_record(row)
        except FinancialMovementAccessError:
            raise FinancialProjectAccessError("project access denied") from None
        except DBAPIError:
            raise FinancialProjectPersistenceError(
                "project link could not be read"
            ) from None

    def read_link_history(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> tuple[FinancialProjectLinkRevisionRecord, ...]:
        """Read a bounded complete chain for one visible Movement.

        An unlinked Movement returns an empty history. Every revision must be
        visible under the same audience or the result fails closed.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(movement_id)
        h = financial_project_link_revisions
        try:
            with self._engine.begin() as conn:
                _prepare(conn, installation_id, residence_id, operator_id)
                _require_visible_original_expense(
                    conn, installation_id, residence_id, movement_id
                )
                rows = conn.execute(
                    select(h).where(
                        h.c.installation_id == installation_id,
                        h.c.residence_id == residence_id,
                        h.c.movement_id == movement_id,
                    ).order_by(h.c.revision).limit(PROJECT_REVISIONS_MAX + 1)
                ).mappings().all()
                if len(rows) > PROJECT_REVISIONS_MAX:
                    raise FinancialProjectLimitError(
                        "project link history exceeds bound"
                    )
                return tuple(_link_record(row) for row in rows)
        except FinancialMovementAccessError:
            raise FinancialProjectAccessError("project access denied") from None
        except FinancialProjectPersistenceError:
            raise
        except DBAPIError:
            raise FinancialProjectPersistenceError(
                "project link history could not be read"
            ) from None

    def read_project_facts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        project_id: UUID,
    ) -> tuple[FinancialProjectRecord, tuple[FinancialProjectExpenseFact, ...]]:
        """Consistent read; no per-Movement query and no realized cache.

        Constant statement count: context, membership, project, current links,
        originals, reversals. A bounded result is mandatory; never truncate.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(project_id)
        h = financial_project_link_revisions
        m = financial_movements
        try:
            with self._engine.connect().execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            ) as conn:
                with conn.begin():
                    _prepare(conn, installation_id, residence_id, operator_id)
                    visible = _visible_project(
                        conn, installation_id, residence_id, project_id
                    )
                    if visible is None:
                        raise FinancialProjectNotFoundError("project was not found")
                    project = _project_record(visible)
                    # One chain per movement: the highest revision must target
                    # this project. A previous link is not current.
                    ranked = select(
                        h.c.movement_id,
                        h.c.project_id,
                        func.row_number().over(
                            partition_by=h.c.movement_id,
                            order_by=h.c.revision.desc(),
                        ).label("ranking"),
                    ).where(
                        h.c.installation_id == installation_id,
                        h.c.residence_id == residence_id,
                    ).subquery()
                    linked = conn.execute(
                        select(ranked.c.movement_id).where(
                            ranked.c.ranking == 1,
                            ranked.c.project_id == project_id,
                        ).limit(PROJECT_LINKS_MAX + 1)
                    ).scalars().all()
                    if len(linked) > PROJECT_LINKS_MAX:
                        raise FinancialProjectLimitError(
                            "project expense list exceeds bound"
                        )
                    if not linked:
                        return project, ()
                    originals = conn.execute(
                        select(m).where(
                            m.c.id.in_(linked),
                            m.c.installation_id == installation_id,
                            m.c.residence_id == residence_id,
                            m.c.role == FinancialMovementRole.STANDARD.value,
                            m.c.result_effect == FinancialResultEffect.EXPENSE.value,
                        )
                    ).mappings().all()
                    if len(originals) != len(linked):
                        raise FinancialProjectPersistenceError(
                            "project expenses are unavailable"
                        )
                    reversals = conn.execute(
                        select(m).where(
                            m.c.reversal_of_id.in_(linked),
                            m.c.installation_id == installation_id,
                            m.c.residence_id == residence_id,
                            m.c.role == FinancialMovementRole.REVERSAL.value,
                        )
                    ).mappings().all()
                    by_original = {
                        row["reversal_of_id"]: movement_record(row)
                        for row in reversals
                    }
                    try:
                        facts = tuple(
                            FinancialProjectExpenseFact(
                                project_id=project_id,
                                original=movement_record(row),
                                reversal=by_original.get(row["id"]),
                            )
                            for row in originals
                        )
                    except (TypeError, ValueError):
                        raise FinancialProjectPersistenceError(
                            "project realization is invalid"
                        ) from None
                    return project, facts
        except FinancialMovementAccessError:
            raise FinancialProjectAccessError("project access denied") from None
        except FinancialProjectPersistenceError:
            raise
        except DBAPIError:
            raise FinancialProjectPersistenceError(
                "project realization could not be read"
            ) from None


def _require_visible_original_expense(
    conn: Connection, installation_id: UUID,
    residence_id: UUID, movement_id: UUID,
) -> None:
    """The absence of a link is not evidence that an expense exists.

    Use the canonical Movement RLS policy. A wrong residence, invisible account,
    forged ID or ineligible Movement must not be reported as an unlinked expense.
    """
    movements = financial_movements
    present = conn.scalar(
        select(movements.c.id).where(
            movements.c.id == movement_id,
            movements.c.installation_id == installation_id,
            movements.c.residence_id == residence_id,
            movements.c.role == FinancialMovementRole.STANDARD.value,
            movements.c.result_effect == FinancialResultEffect.EXPENSE.value,
        )
    )
    if present is None:
        raise FinancialProjectNotFoundError("expense was not found")


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
    conn: Connection, installation_id: UUID, residence_id: UUID, operator_id: UUID
) -> None:
    _set_context(
        conn, installation_id=installation_id,
        residence_id=residence_id, operator_id=operator_id,
    )
    _require_active_membership(
        conn, installation_id=installation_id,
        residence_id=residence_id, operator_id=operator_id,
    )


def _lock_movement(conn: Connection, movement_id: UUID) -> None:
    conn.execute(
        select(func.pg_advisory_xact_lock(
            func.hashtextextended(
                "meufinanceiro:project-movement:" + str(movement_id), 0
            )
        ))
    )


def _digest(namespace: str, operator_id: UUID, material: Sequence[object]) -> str:
    serialized = json.dumps(
        [namespace, str(operator_id), material],
        ensure_ascii=True, separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _visible_project(
    conn: Connection, installation_id: UUID, residence_id: UUID, project_id: UUID
) -> RowMapping | None:
    p = financial_projects
    return conn.execute(
        select(p).where(
            p.c.id == project_id,
            p.c.installation_id == installation_id,
            p.c.residence_id == residence_id,
        )
    ).mappings().one_or_none()


def _project_by_key(
    conn: Connection, installation_id: UUID, key: UUID
) -> RowMapping | None:
    p = financial_projects
    return conn.execute(
        select(p).where(
            p.c.installation_id == installation_id,
            p.c.idempotency_key == key,
        )
    ).mappings().one_or_none()


def _link_by_key(
    conn: Connection, installation_id: UUID, key: UUID
) -> RowMapping | None:
    h = financial_project_link_revisions
    return conn.execute(
        select(h).where(
            h.c.installation_id == installation_id,
            h.c.idempotency_key == key,
        )
    ).mappings().one_or_none()


def _replay_project(row: RowMapping, digest: str) -> FinancialProjectRecord:
    if row["request_digest"] != digest:
        raise FinancialProjectConflictError("project idempotency conflict")
    return _project_record(row)


def _replay_link(row: RowMapping, digest: str) -> FinancialProjectLinkRevisionRecord:
    if row["request_digest"] != digest:
        raise FinancialProjectConflictError("project link idempotency conflict")
    return _link_record(row)


def _project_record(row: RowMapping) -> FinancialProjectRecord:
    try:
        return FinancialProjectRecord(
            id=row["id"],
            residence_id=row["residence_id"],
            owner_operator_id=row["owner_operator_id"],
            visibility_scope=FinancialVisibilityScope(row["visibility_scope"]),
            title=row["title"],
            description=row["description"],
            planned=Money(row["planned_amount"], row["currency"]),
            target_date=row["target_date"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialProjectPersistenceError("project state is invalid") from None


def _link_record(row: RowMapping) -> FinancialProjectLinkRevisionRecord:
    try:
        return FinancialProjectLinkRevisionRecord(
            id=row["id"],
            movement_id=row["movement_id"],
            project_id=row["project_id"],
            supersedes_id=row["supersedes_id"],
            revision=row["revision"],
            actor_operator_id=row["actor_operator_id"],
            created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialProjectPersistenceError(
            "project link state is invalid"
        ) from None


def _integrity_error(error: IntegrityError) -> FinancialProjectPersistenceError:
    diag = getattr(error.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    if name in {"ck_finance_projects_owner_limit", "ck_finance_project_links_bound"}:
        return FinancialProjectLimitError("project limit reached")
    return FinancialProjectConflictError("project conflict")


__all__ = [
    "PROJECT_LIST_MAX",
    "PROJECT_LINKS_MAX",
    "PROJECT_REVISIONS_MAX",
    "FinancialProjectAccessError",
    "FinancialProjectConflictError",
    "FinancialProjectLimitError",
    "FinancialProjectNotEditableError",
    "FinancialProjectNotFoundError",
    "FinancialProjectPersistenceError",
    "FinancialProjectStore",
]
