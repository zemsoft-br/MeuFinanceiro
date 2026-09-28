"""SQLAlchemy metadata for explicit reconciled-transaction ledger decisions."""

from __future__ import annotations

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import metadata


reconciled_transaction_ledger_links = Table(
    "reconciled_transaction_ledger_links",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("connection_id", UUID(as_uuid=True), nullable=False),
    Column("reconciled_transaction_id", UUID(as_uuid=True), nullable=False),
    Column("source_observation_id", UUID(as_uuid=True), nullable=False),
    Column("source_observation_updated_at", DateTime(timezone=True), nullable=False),
    Column("decision", String(32), nullable=False),
    Column("financial_account_id", UUID(as_uuid=True), nullable=True),
    Column("movement_id", UUID(as_uuid=True), nullable=True),
    Column("currency", String(3), nullable=False),
    Column("movement_result_effect", String(16), nullable=True),
    Column("movement_role", String(16), nullable=True),
    Column("decided_by_operator_id", UUID(as_uuid=True), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    Column("idempotency_key", UUID(as_uuid=True), nullable=False),
    Column("request_digest", CHAR(64), nullable=False),
    CheckConstraint(
        "id::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_banking_ledger_links_id_uuid4",
    ),
    CheckConstraint(
        "idempotency_key::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_banking_ledger_links_idempotency_uuid4",
    ),
    CheckConstraint(
        "decision IN ('IMPORT_AS_INCOME', 'IMPORT_AS_EXPENSE', "
        "'LINK_EXISTING_MOVEMENT', 'IGNORE')",
        name="ck_banking_ledger_links_decision",
    ),
    CheckConstraint(
        "currency ~ '^[A-Z]{3}$'",
        name="ck_banking_ledger_links_currency",
    ),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'",
        name="ck_banking_ledger_links_request_digest",
    ),
    CheckConstraint(
        "(decision = 'IGNORE' AND financial_account_id IS NULL "
        "AND movement_id IS NULL AND movement_result_effect IS NULL "
        "AND movement_role IS NULL) OR "
        "(decision = 'IMPORT_AS_INCOME' AND financial_account_id IS NOT NULL "
        "AND movement_id IS NOT NULL AND movement_result_effect = 'INCOME' "
        "AND movement_role = 'STANDARD') OR "
        "(decision = 'IMPORT_AS_EXPENSE' AND financial_account_id IS NOT NULL "
        "AND movement_id IS NOT NULL AND movement_result_effect = 'EXPENSE' "
        "AND movement_role = 'STANDARD') OR "
        "(decision = 'LINK_EXISTING_MOVEMENT' AND financial_account_id IS NOT NULL "
        "AND movement_id IS NOT NULL "
        "AND movement_result_effect IN ('INCOME', 'EXPENSE', 'NEUTRAL') "
        "AND movement_role = 'STANDARD')",
        name="ck_banking_ledger_links_shape",
    ),
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_banking_ledger_links_residence_scope",
    ),
    ForeignKeyConstraint(
        ["connection_id", "residence_id"],
        ["integrations.connections.id", "integrations.connections.residence_id"],
        ondelete="RESTRICT",
        name="fk_banking_ledger_links_connection_scope",
    ),
    ForeignKeyConstraint(
        ["reconciled_transaction_id", "connection_id", "residence_id"],
        [
            "integrations.reconciled_transactions.id",
            "integrations.reconciled_transactions.connection_id",
            "integrations.reconciled_transactions.residence_id",
        ],
        ondelete="RESTRICT",
        name="fk_banking_ledger_links_reconciled_scope",
    ),
    ForeignKeyConstraint(
        ["source_observation_id", "connection_id", "residence_id"],
        [
            "integrations.external_observations.id",
            "integrations.external_observations.connection_id",
            "integrations.external_observations.residence_id",
        ],
        ondelete="RESTRICT",
        name="fk_banking_ledger_links_source_scope",
    ),
    ForeignKeyConstraint(
        ["financial_account_id", "installation_id", "residence_id", "currency"],
        [
            "finance.accounts.id",
            "finance.accounts.installation_id",
            "finance.accounts.residence_id",
            "finance.accounts.currency",
        ],
        ondelete="RESTRICT",
        name="fk_banking_ledger_links_account_scope",
    ),
    ForeignKeyConstraint(
        [
            "movement_id",
            "installation_id",
            "residence_id",
            "financial_account_id",
            "currency",
            "movement_result_effect",
            "movement_role",
        ],
        [
            "finance.movements.id",
            "finance.movements.installation_id",
            "finance.movements.residence_id",
            "finance.movements.account_id",
            "finance.movements.currency",
            "finance.movements.result_effect",
            "finance.movements.role",
        ],
        ondelete="RESTRICT",
        name="fk_banking_ledger_links_movement_scope",
    ),
    ForeignKeyConstraint(
        ["residence_id", "decided_by_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_banking_ledger_links_operator_membership",
    ),
    UniqueConstraint(
        "reconciled_transaction_id",
        "connection_id",
        "residence_id",
        name="uq_banking_ledger_links_reconciled_decision",
    ),
    UniqueConstraint(
        "installation_id",
        "idempotency_key",
        name="uq_banking_ledger_links_idempotency",
    ),
    schema="integrations",
)

Index(
    "ix_banking_ledger_links_residence_decided",
    reconciled_transaction_ledger_links.c.residence_id,
    reconciled_transaction_ledger_links.c.decided_at,
    reconciled_transaction_ledger_links.c.id,
)
Index(
    "ix_banking_ledger_links_movement",
    reconciled_transaction_ledger_links.c.residence_id,
    reconciled_transaction_ledger_links.c.movement_id,
)


__all__ = ["reconciled_transaction_ledger_links"]
