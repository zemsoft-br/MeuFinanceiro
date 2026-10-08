# mypy: ignore-errors
"""Planning-only financial projects and append-only Movement link revisions.

Revision ID: 0029_financial_projects
Revises: 0028_financial_goals
Create Date: 2026-10-08
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0029_financial_projects"
down_revision: str | None = "0028_financial_goals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
_UUID4 = "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def upgrade() -> None:
    role = _quoted_role()

    op.execute(
        f"""
        CREATE TABLE finance.projects (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            owner_operator_id uuid NOT NULL,
            visibility_scope varchar(16) NOT NULL,
            title varchar(96) NOT NULL,
            description varchar(280),
            currency varchar(3) NOT NULL,
            planned_amount numeric(24,8) NOT NULL,
            target_date date,
            version integer NOT NULL,
            idempotency_key uuid NOT NULL,
            request_digest varchar(64) NOT NULL,
            updated_by_operator_id uuid NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_projects_id_uuid4
                CHECK (id::text ~ '{_UUID4}'),
            CONSTRAINT ck_finance_projects_idempotency_uuid4
                CHECK (idempotency_key::text ~ '{_UUID4}'),
            CONSTRAINT ck_finance_projects_scope
                CHECK (visibility_scope IN ('PERSONAL', 'HOUSEHOLD')),
            CONSTRAINT ck_finance_projects_title
                CHECK (length(btrim(title)) BETWEEN 1 AND 96),
            CONSTRAINT ck_finance_projects_description
                CHECK (description IS NULL OR
                       length(btrim(description)) BETWEEN 1 AND 280),
            CONSTRAINT ck_finance_projects_currency
                CHECK (currency ~ '^[A-Z]{{3}}$'),
            CONSTRAINT ck_finance_projects_positive
                CHECK (planned_amount > 0 AND planned_amount::text
                       NOT IN ('NaN', 'Infinity', '-Infinity')),
            CONSTRAINT ck_finance_projects_version CHECK (version >= 1),
            CONSTRAINT ck_finance_projects_request_digest
                CHECK (request_digest ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT ck_finance_projects_timestamps
                CHECK (updated_at >= created_at),
            CONSTRAINT fk_finance_projects_residence
                FOREIGN KEY (residence_id, installation_id)
                REFERENCES household.residences (id, installation_id)
                ON DELETE RESTRICT,
            CONSTRAINT fk_finance_projects_owner
                FOREIGN KEY (residence_id, owner_operator_id)
                REFERENCES household.memberships (residence_id, operator_id)
                ON DELETE RESTRICT,
            CONSTRAINT fk_finance_projects_updater
                FOREIGN KEY (residence_id, updated_by_operator_id)
                REFERENCES household.memberships (residence_id, operator_id)
                ON DELETE RESTRICT,
            CONSTRAINT uq_finance_projects_full_scope
                UNIQUE (id, installation_id, residence_id, currency,
                        owner_operator_id, visibility_scope),
            CONSTRAINT uq_finance_projects_idempotency
                UNIQUE (installation_id, idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_projects_owner ON finance.projects "
        "(residence_id, owner_operator_id, created_at, id)"
    )

    op.execute(
        f"""
        CREATE TABLE finance.project_movement_link_revisions (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            movement_id uuid NOT NULL,
            account_id uuid NOT NULL,
            currency varchar(3) NOT NULL,
            result_effect varchar(16) NOT NULL,
            role varchar(16) NOT NULL,
            owner_operator_id uuid NOT NULL,
            visibility_scope varchar(16) NOT NULL,
            project_id uuid,
            supersedes_id uuid,
            revision integer NOT NULL,
            actor_operator_id uuid NOT NULL,
            idempotency_key uuid NOT NULL,
            request_digest varchar(64) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_project_links_id_uuid4
                CHECK (id::text ~ '{_UUID4}'),
            CONSTRAINT ck_finance_project_links_idempotency_uuid4
                CHECK (idempotency_key::text ~ '{_UUID4}'),
            CONSTRAINT ck_finance_project_links_expense
                CHECK (result_effect = 'EXPENSE' AND role = 'STANDARD'),
            CONSTRAINT ck_finance_project_links_scope
                CHECK (visibility_scope IN ('PERSONAL', 'HOUSEHOLD')),
            CONSTRAINT ck_finance_project_links_chain CHECK (
                (revision = 1 AND supersedes_id IS NULL AND project_id IS NOT NULL)
                OR (revision > 1 AND supersedes_id IS NOT NULL)
            ),
            CONSTRAINT ck_finance_project_links_digest
                CHECK (request_digest ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT fk_finance_project_links_expense
                FOREIGN KEY (
                    movement_id, installation_id, residence_id, account_id,
                    currency, result_effect, role
                )
                REFERENCES finance.movements (
                    id, installation_id, residence_id, account_id,
                    currency, result_effect, role
                ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_project_links_project
                FOREIGN KEY (
                    project_id, installation_id, residence_id,
                    currency, owner_operator_id, visibility_scope
                )
                REFERENCES finance.projects (
                    id, installation_id, residence_id,
                    currency, owner_operator_id, visibility_scope
                ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_project_links_predecessor
                FOREIGN KEY (supersedes_id)
                REFERENCES finance.project_movement_link_revisions (id)
                ON DELETE RESTRICT,
            CONSTRAINT fk_finance_project_links_actor
                FOREIGN KEY (residence_id, actor_operator_id)
                REFERENCES household.memberships (residence_id, operator_id)
                ON DELETE RESTRICT,
            CONSTRAINT uq_finance_project_links_revision
                UNIQUE (movement_id, revision),
            CONSTRAINT uq_finance_project_links_successor
                UNIQUE (supersedes_id),
            CONSTRAINT uq_finance_project_links_idempotency
                UNIQUE (installation_id, idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_project_links_movement "
        "ON finance.project_movement_link_revisions (movement_id, revision DESC)"
    )
    op.execute(
        "CREATE INDEX ix_finance_project_links_project "
        "ON finance.project_movement_link_revisions (project_id, movement_id)"
    )

    op.execute(
        """
        CREATE FUNCTION finance.enforce_project_row()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE owned_count integer;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.version IS DISTINCT FROM 1
                    OR NEW.updated_by_operator_id IS DISTINCT FROM NEW.owner_operator_id
                    OR NEW.updated_at IS DISTINCT FROM NEW.created_at THEN
                    RAISE EXCEPTION 'invalid initial project'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_projects_initial';
                END IF;
                PERFORM pg_advisory_xact_lock(hashtextextended(
                    'meufinanceiro:project-owner:' || NEW.owner_operator_id::text, 0
                ));
                SELECT count(*) INTO owned_count FROM finance.projects p
                    WHERE p.installation_id = NEW.installation_id
                      AND p.residence_id = NEW.residence_id
                      AND p.owner_operator_id = NEW.owner_operator_id;
                IF owned_count >= 200 THEN
                    RAISE EXCEPTION 'project owner limit reached'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_projects_owner_limit';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.version IS DISTINCT FROM OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
                OR NEW.updated_by_operator_id IS DISTINCT FROM OLD.owner_operator_id
                OR (to_jsonb(NEW) - 'title' - 'description' - 'planned_amount'
                        - 'target_date' - 'version' - 'updated_at'
                        - 'updated_by_operator_id')
                   IS DISTINCT FROM
                   (to_jsonb(OLD) - 'title' - 'description' - 'planned_amount'
                        - 'target_date' - 'version' - 'updated_at'
                        - 'updated_by_operator_id')
            THEN
                RAISE EXCEPTION 'project identity is immutable'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_projects_immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_enforce_project_row "
        "BEFORE INSERT OR UPDATE ON finance.projects "
        "FOR EACH ROW EXECUTE FUNCTION finance.enforce_project_row()"
    )

    op.execute(
        """
        CREATE FUNCTION finance.enforce_project_link_revision()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            movement_row finance.movements%ROWTYPE;
            account_row finance.accounts%ROWTYPE;
            project_row finance.projects%ROWTYPE;
            predecessor finance.project_movement_link_revisions%ROWTYPE;
        BEGIN
            -- Per-Movement lock across all projects, not per project. Prevent forks.
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'meufinanceiro:project-movement:' || NEW.movement_id::text, 0
            ));
            IF NEW.created_at IS DISTINCT FROM transaction_timestamp()
                OR NEW.revision > 100 THEN
                RAISE EXCEPTION 'project link revision limit or timestamp'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_project_links_bound';
            END IF;

            SELECT m.* INTO movement_row
                FROM finance.movements m
                WHERE m.id = NEW.movement_id;
            IF NOT FOUND
                OR movement_row.installation_id IS DISTINCT FROM NEW.installation_id
                OR movement_row.residence_id IS DISTINCT FROM NEW.residence_id
                OR movement_row.account_id IS DISTINCT FROM NEW.account_id
                OR movement_row.currency IS DISTINCT FROM NEW.currency
                OR movement_row.role IS DISTINCT FROM 'STANDARD'
                OR movement_row.result_effect IS DISTINCT FROM 'EXPENSE'
            THEN
                RAISE EXCEPTION 'target must be an original expense'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_project_links_movement';
            END IF;

            SELECT a.* INTO account_row FROM finance.accounts a
                WHERE a.id = NEW.account_id;
            IF NOT FOUND
                OR account_row.installation_id IS DISTINCT FROM NEW.installation_id
                OR account_row.residence_id IS DISTINCT FROM NEW.residence_id
                OR account_row.currency IS DISTINCT FROM NEW.currency
                OR account_row.owner_operator_id IS DISTINCT FROM NEW.owner_operator_id
                OR account_row.visibility_scope IS DISTINCT FROM NEW.visibility_scope
                OR account_row.visibility_scope NOT IN ('PERSONAL', 'HOUSEHOLD')
                OR NEW.actor_operator_id IS DISTINCT FROM account_row.owner_operator_id
                OR (NEW.project_id IS NOT NULL
                    AND account_row.status IS DISTINCT FROM 'ACTIVE')
            THEN
                RAISE EXCEPTION 'expense account is not eligible'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_project_links_account';
            END IF;

            IF NEW.project_id IS NOT NULL THEN
                SELECT p.* INTO project_row FROM finance.projects p
                    WHERE p.id = NEW.project_id;
                IF NOT FOUND
                    OR project_row.installation_id IS DISTINCT FROM NEW.installation_id
                    OR project_row.residence_id IS DISTINCT FROM NEW.residence_id
                    OR project_row.currency IS DISTINCT FROM NEW.currency
                    OR project_row.owner_operator_id IS DISTINCT FROM NEW.owner_operator_id
                    OR project_row.visibility_scope IS DISTINCT FROM NEW.visibility_scope
                THEN
                    RAISE EXCEPTION 'project is not eligible'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_project_links_project';
                END IF;
            END IF;

            IF NEW.supersedes_id IS NULL THEN
                -- A first link cannot be added after prior links to the movement.
                IF NEW.revision IS DISTINCT FROM 1
                    OR NEW.project_id IS NULL
                    OR EXISTS (
                        SELECT 1 FROM finance.project_movement_link_revisions h
                        WHERE h.movement_id = NEW.movement_id
                    ) THEN
                    RAISE EXCEPTION 'first project link already exists'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_project_links_predecessor';
                END IF;
            ELSE
                SELECT h.* INTO predecessor
                    FROM finance.project_movement_link_revisions h
                    WHERE h.id = NEW.supersedes_id;
                IF NOT FOUND
                    OR predecessor.movement_id IS DISTINCT FROM NEW.movement_id
                    OR predecessor.installation_id IS DISTINCT FROM NEW.installation_id
                    OR predecessor.residence_id IS DISTINCT FROM NEW.residence_id
                    OR predecessor.account_id IS DISTINCT FROM NEW.account_id
                    OR predecessor.owner_operator_id IS DISTINCT FROM NEW.owner_operator_id
                    OR predecessor.visibility_scope IS DISTINCT FROM NEW.visibility_scope
                    OR predecessor.currency IS DISTINCT FROM NEW.currency
                    OR predecessor.revision + 1 IS DISTINCT FROM NEW.revision
                    OR predecessor.project_id IS NOT DISTINCT FROM NEW.project_id
                    OR EXISTS (
                        SELECT 1 FROM finance.project_movement_link_revisions h
                        WHERE h.supersedes_id = NEW.supersedes_id
                    ) THEN
                    RAISE EXCEPTION 'stale or invalid project link predecessor'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_project_links_predecessor';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_enforce_project_link_revision "
        "BEFORE INSERT ON finance.project_movement_link_revisions "
        "FOR EACH ROW EXECUTE FUNCTION finance.enforce_project_link_revision()"
    )
    op.execute(
        """
        CREATE FUNCTION finance.reject_project_link_history_mutation()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            RAISE EXCEPTION 'project links are append-only'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_finance_project_links_append_only';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_reject_project_link_mutation "
        "BEFORE UPDATE OR DELETE ON finance.project_movement_link_revisions "
        "FOR EACH ROW EXECUTE FUNCTION finance.reject_project_link_history_mutation()"
    )

    installation = (
        "NULLIF(current_setting('app.current_installation_id', true), '')::uuid"
    )
    residence = "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    actor = "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"

    def membership(alias: str) -> str:
        return (
            "EXISTS (SELECT 1 FROM household.memberships hm "
            f"WHERE hm.installation_id = {alias}.installation_id "
            f"AND hm.residence_id = {alias}.residence_id "
            f"AND hm.operator_id = {actor} AND hm.status = 'active')"
        )

    project_scope = (
        f"projects.installation_id = {installation} "
        f"AND projects.residence_id = {residence} "
        f"AND {membership('projects')}"
    )
    project_owned = f"projects.owner_operator_id = {actor}"
    op.execute("ALTER TABLE finance.projects ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.projects FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_projects_select ON finance.projects "
        f"FOR SELECT USING ({project_scope} AND "
        f"(projects.visibility_scope = 'HOUSEHOLD' OR {project_owned}))"
    )
    op.execute(
        "CREATE POLICY finance_projects_insert ON finance.projects "
        f"FOR INSERT WITH CHECK ({project_scope} AND {project_owned} "
        f"AND projects.updated_by_operator_id = {actor} AND projects.version = 1)"
    )
    op.execute(
        "CREATE POLICY finance_projects_update ON finance.projects "
        f"FOR UPDATE USING ({project_scope} AND {project_owned}) "
        f"WITH CHECK ({project_scope} AND {project_owned} "
        f"AND projects.updated_by_operator_id = {actor})"
    )

    link_scope = (
        f"project_movement_link_revisions.installation_id = {installation} "
        f"AND project_movement_link_revisions.residence_id = {residence} "
        f"AND {membership('project_movement_link_revisions')}"
    )
    link_owned = f"project_movement_link_revisions.owner_operator_id = {actor}"
    op.execute(
        "ALTER TABLE finance.project_movement_link_revisions ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE finance.project_movement_link_revisions FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY finance_project_links_select "
        "ON finance.project_movement_link_revisions "
        f"FOR SELECT USING ({link_scope} AND "
        f"(project_movement_link_revisions.visibility_scope = 'HOUSEHOLD' "
        f"OR {link_owned}))"
    )
    op.execute(
        "CREATE POLICY finance_project_links_insert "
        "ON finance.project_movement_link_revisions "
        f"FOR INSERT WITH CHECK ({link_scope} AND {link_owned} "
        f"AND project_movement_link_revisions.actor_operator_id = {actor})"
    )
    op.execute(f"GRANT SELECT, INSERT ON finance.projects TO {role}")
    op.execute(
        "GRANT UPDATE (title, description, planned_amount, target_date, "
        f"version, updated_at, updated_by_operator_id) ON finance.projects TO {role}"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON finance.project_movement_link_revisions TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE SELECT, INSERT ON finance.project_movement_link_revisions FROM {role}"
    )
    op.execute(
        "REVOKE UPDATE (title, description, planned_amount, target_date, "
        f"version, updated_at, updated_by_operator_id) ON finance.projects FROM {role}"
    )
    op.execute(f"REVOKE SELECT, INSERT ON finance.projects FROM {role}")

    op.execute(
        "DROP TRIGGER trg_finance_reject_project_link_mutation "
        "ON finance.project_movement_link_revisions"
    )
    op.execute("DROP FUNCTION finance.reject_project_link_history_mutation()")
    op.execute(
        "DROP TRIGGER trg_finance_enforce_project_link_revision "
        "ON finance.project_movement_link_revisions"
    )
    op.execute("DROP FUNCTION finance.enforce_project_link_revision()")
    op.execute("DROP TABLE finance.project_movement_link_revisions")
    op.execute("DROP TRIGGER trg_finance_enforce_project_row ON finance.projects")
    op.execute("DROP FUNCTION finance.enforce_project_row()")
    op.execute("DROP TABLE finance.projects")
