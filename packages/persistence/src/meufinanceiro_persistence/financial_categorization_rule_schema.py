"""SQLAlchemy metadata for deterministic categorization rules and provenance."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import metadata

_UUID4 = "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"

financial_categorization_rules = Table(
    "categorization_rules",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("created_by_operator_id", UUID(as_uuid=True), nullable=False),
    Column("account_id", UUID(as_uuid=True), nullable=True),
    Column("result_effect", String(16), nullable=True),
    Column("description_matcher", String(16), nullable=False),
    Column("description_pattern", String(256), nullable=False),
    Column("target_category_id", UUID(as_uuid=True), nullable=False),
    Column("priority", Integer(), nullable=False),
    Column("status", String(16), nullable=False),
    Column("idempotency_key", UUID(as_uuid=True), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("disabled_at", DateTime(timezone=True), nullable=True),
    Column("disabled_by_operator_id", UUID(as_uuid=True), nullable=True),
    CheckConstraint(f"id::text ~ {_UUID4}", name="ck_finance_cat_rules_id_uuid4"),
    CheckConstraint(
        f"idempotency_key::text ~ {_UUID4}",
        name="ck_finance_cat_rules_idempotency_uuid4",
    ),
    CheckConstraint(
        "result_effect IS NULL OR result_effect IN ('INCOME', 'EXPENSE')",
        name="ck_finance_cat_rules_result_effect",
    ),
    CheckConstraint(
        "description_matcher IN ('EXACT', 'CONTAINS')",
        name="ck_finance_cat_rules_matcher",
    ),
    CheckConstraint(
        "length(btrim(description_pattern)) BETWEEN 1 AND 256",
        name="ck_finance_cat_rules_pattern_length",
    ),
    CheckConstraint(
        "priority BETWEEN 1 AND 1000",
        name="ck_finance_cat_rules_priority",
    ),
    CheckConstraint(
        "status IN ('ACTIVE', 'DISABLED')",
        name="ck_finance_cat_rules_status",
    ),
    CheckConstraint(
        "(status = 'ACTIVE' AND disabled_at IS NULL "
        "AND disabled_by_operator_id IS NULL) OR "
        "(status = 'DISABLED' AND disabled_at IS NOT NULL "
        "AND disabled_by_operator_id IS NOT NULL)",
        name="ck_finance_cat_rules_disable_state",
    ),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'",
        name="ck_finance_cat_rules_request_digest",
    ),
    CheckConstraint(
        "disabled_at IS NULL OR disabled_at >= created_at",
        name="ck_finance_cat_rules_timestamps",
    ),
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_finance_cat_rules_residence",
    ),
    ForeignKeyConstraint(
        ["residence_id", "created_by_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_cat_rules_creator_membership",
    ),
    ForeignKeyConstraint(
        ["residence_id", "disabled_by_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_cat_rules_disabler_membership",
    ),
    ForeignKeyConstraint(
        ["account_id"],
        ["finance.accounts.id"],
        ondelete="RESTRICT",
        name="fk_finance_cat_rules_account",
    ),
    ForeignKeyConstraint(
        ["target_category_id"],
        ["finance.categories.id"],
        ondelete="RESTRICT",
        name="fk_finance_cat_rules_category",
    ),
    UniqueConstraint(
        "id",
        "installation_id",
        "residence_id",
        name="uq_finance_cat_rules_scope",
    ),
    UniqueConstraint(
        "installation_id",
        "idempotency_key",
        name="uq_finance_cat_rules_idempotency",
    ),
    schema="finance",
)

financial_movement_allocation_rule_origins = Table(
    "movement_allocation_rule_origins",
    metadata,
    Column("allocation_set_id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("movement_id", UUID(as_uuid=True), nullable=False),
    Column("rule_id", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["allocation_set_id", "installation_id", "residence_id", "movement_id"],
        [
            "finance.movement_allocation_sets.id",
            "finance.movement_allocation_sets.installation_id",
            "finance.movement_allocation_sets.residence_id",
            "finance.movement_allocation_sets.movement_id",
        ],
        ondelete="RESTRICT",
        name="fk_finance_rule_origins_set",
    ),
    ForeignKeyConstraint(
        ["rule_id", "installation_id", "residence_id"],
        [
            "finance.categorization_rules.id",
            "finance.categorization_rules.installation_id",
            "finance.categorization_rules.residence_id",
        ],
        ondelete="RESTRICT",
        name="fk_finance_rule_origins_rule",
    ),
    ForeignKeyConstraint(
        ["movement_id"],
        ["finance.movements.id"],
        ondelete="RESTRICT",
        name="fk_finance_rule_origins_movement",
    ),
    schema="finance",
)

Index(
    "ix_finance_cat_rules_scope",
    financial_categorization_rules.c.residence_id,
    financial_categorization_rules.c.status,
    financial_categorization_rules.c.priority.desc(),
    financial_categorization_rules.c.created_at,
    financial_categorization_rules.c.id,
)
Index(
    "ix_finance_cat_rules_category",
    financial_categorization_rules.c.residence_id,
    financial_categorization_rules.c.target_category_id,
)
Index(
    "ix_finance_rule_origins_rule",
    financial_movement_allocation_rule_origins.c.residence_id,
    financial_movement_allocation_rule_origins.c.rule_id,
)
Index(
    "ix_finance_rule_origins_movement",
    financial_movement_allocation_rule_origins.c.residence_id,
    financial_movement_allocation_rule_origins.c.movement_id,
)

__all__ = [
    "financial_categorization_rules",
    "financial_movement_allocation_rule_origins",
]
