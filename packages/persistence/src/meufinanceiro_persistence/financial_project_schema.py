"""SQLAlchemy metadata for project plans and append-only expense links (#262).

The original Movement is never modified and no realized amount is persisted.
Each chain is keyed by original movement_id, not project_id (ADR-0030).
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import metadata

_UUID4 = "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"

financial_projects = Table(
    "projects",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("owner_operator_id", UUID(as_uuid=True), nullable=False),
    Column("visibility_scope", String(16), nullable=False),
    Column("title", String(96), nullable=False),
    Column("description", String(280)),
    Column("currency", String(3), nullable=False),
    Column("planned_amount", Numeric(24, 8), nullable=False),
    Column("target_date", Date()),
    Column("version", Integer(), nullable=False),
    Column("idempotency_key", UUID(as_uuid=True), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("updated_by_operator_id", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(f"id::text ~ {_UUID4}", name="ck_finance_projects_id_uuid4"),
    CheckConstraint(
        f"idempotency_key::text ~ {_UUID4}",
        name="ck_finance_projects_idempotency_uuid4",
    ),
    CheckConstraint(
        "visibility_scope IN ('PERSONAL', 'HOUSEHOLD')",
        name="ck_finance_projects_scope",
    ),
    CheckConstraint(
        "length(btrim(title)) BETWEEN 1 AND 96",
        name="ck_finance_projects_title",
    ),
    CheckConstraint(
        "description IS NULL OR length(btrim(description)) BETWEEN 1 AND 280",
        name="ck_finance_projects_description",
    ),
    CheckConstraint(
        "currency ~ '^[A-Z]{3}$'",
        name="ck_finance_projects_currency",
    ),
    CheckConstraint(
        "planned_amount > 0 AND planned_amount::text NOT IN "
        "('NaN', 'Infinity', '-Infinity')",
        name="ck_finance_projects_positive",
    ),
    CheckConstraint("version >= 1", name="ck_finance_projects_version"),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'",
        name="ck_finance_projects_request_digest",
    ),
    CheckConstraint(
        "updated_at >= created_at", name="ck_finance_projects_timestamps"
    ),
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_finance_projects_residence",
    ),
    ForeignKeyConstraint(
        ["residence_id", "owner_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_projects_owner",
    ),
    ForeignKeyConstraint(
        ["residence_id", "updated_by_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_projects_updater",
    ),
    UniqueConstraint(
        "id", "installation_id", "residence_id", "currency",
        "owner_operator_id", "visibility_scope",
        name="uq_finance_projects_full_scope",
    ),
    UniqueConstraint(
        "installation_id", "idempotency_key",
        name="uq_finance_projects_idempotency",
    ),
    schema="finance",
)

financial_project_link_revisions = Table(
    "project_movement_link_revisions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("movement_id", UUID(as_uuid=True), nullable=False),
    Column("account_id", UUID(as_uuid=True), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("result_effect", String(16), nullable=False),
    Column("role", String(16), nullable=False),
    Column("owner_operator_id", UUID(as_uuid=True), nullable=False),
    Column("visibility_scope", String(16), nullable=False),
    Column("project_id", UUID(as_uuid=True)),
    Column("supersedes_id", UUID(as_uuid=True)),
    Column("revision", Integer(), nullable=False),
    Column("actor_operator_id", UUID(as_uuid=True), nullable=False),
    Column("idempotency_key", UUID(as_uuid=True), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        f"id::text ~ {_UUID4}", name="ck_finance_project_links_id_uuid4"
    ),
    CheckConstraint(
        f"idempotency_key::text ~ {_UUID4}",
        name="ck_finance_project_links_idempotency_uuid4",
    ),
    CheckConstraint(
        "result_effect = 'EXPENSE' AND role = 'STANDARD'",
        name="ck_finance_project_links_expense",
    ),
    CheckConstraint(
        "visibility_scope IN ('PERSONAL', 'HOUSEHOLD')",
        name="ck_finance_project_links_scope",
    ),
    CheckConstraint(
        "(revision = 1 AND supersedes_id IS NULL AND project_id IS NOT NULL) "
        "OR (revision > 1 AND supersedes_id IS NOT NULL)",
        name="ck_finance_project_links_chain",
    ),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'",
        name="ck_finance_project_links_digest",
    ),
    ForeignKeyConstraint(
        [
            "movement_id", "installation_id", "residence_id",
            "account_id", "currency", "result_effect", "role",
        ],
        [
            "finance.movements.id", "finance.movements.installation_id",
            "finance.movements.residence_id", "finance.movements.account_id",
            "finance.movements.currency", "finance.movements.result_effect",
            "finance.movements.role",
        ],
        ondelete="RESTRICT", name="fk_finance_project_links_expense",
    ),
    ForeignKeyConstraint(
        [
            "project_id", "installation_id", "residence_id", "currency",
            "owner_operator_id", "visibility_scope",
        ],
        [
            "finance.projects.id", "finance.projects.installation_id",
            "finance.projects.residence_id", "finance.projects.currency",
            "finance.projects.owner_operator_id", "finance.projects.visibility_scope",
        ],
        ondelete="RESTRICT", name="fk_finance_project_links_project",
    ),
    ForeignKeyConstraint(
        ["supersedes_id"], ["finance.project_movement_link_revisions.id"],
        ondelete="RESTRICT", name="fk_finance_project_links_predecessor",
    ),
    ForeignKeyConstraint(
        ["residence_id", "actor_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT", name="fk_finance_project_links_actor",
    ),
    UniqueConstraint(
        "movement_id", "revision", name="uq_finance_project_links_revision"
    ),
    UniqueConstraint(
        "supersedes_id", name="uq_finance_project_links_successor"
    ),
    UniqueConstraint(
        "installation_id", "idempotency_key",
        name="uq_finance_project_links_idempotency",
    ),
    schema="finance",
)

Index(
    "ix_finance_projects_owner",
    financial_projects.c.residence_id,
    financial_projects.c.owner_operator_id,
    financial_projects.c.created_at,
    financial_projects.c.id,
)
Index(
    "ix_finance_project_links_movement",
    financial_project_link_revisions.c.movement_id,
    financial_project_link_revisions.c.revision.desc(),
)
Index(
    "ix_finance_project_links_project",
    financial_project_link_revisions.c.project_id,
    financial_project_link_revisions.c.movement_id,
)

__all__ = ["financial_projects", "financial_project_link_revisions"]
