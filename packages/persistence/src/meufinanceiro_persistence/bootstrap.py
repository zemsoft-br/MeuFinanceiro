"""Create or reconcile the unprivileged PostgreSQL runtime role."""

from __future__ import annotations

import logging

import psycopg
from meufinanceiro_security.redaction import install_log_redaction
from psycopg import sql

from meufinanceiro_persistence.settings import BootstrapSettings

logger = logging.getLogger("meufinanceiro.persistence.bootstrap")


def normalize_psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def bootstrap_runtime_role(settings: BootstrapSettings) -> None:
    database_url = normalize_psycopg_url(settings.admin_database_url.get_secret_value())
    role_name = settings.app_database_user
    password = settings.app_database_password.get_secret_value()

    with psycopg.connect(database_url, autocommit=True) as connection:
        database_name = connection.info.dbname
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            administrative_row = cursor.fetchone()
            if administrative_row is None:
                raise RuntimeError("database did not return the administrative role")
            administrative_role = administrative_row[0]
            if role_name == administrative_role:
                raise ValueError(
                    "APP_DATABASE_USER must differ from the administrative database role"
                )

            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,))
            exists = cursor.fetchone() is not None
            if not exists:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(
                        sql.Identifier(role_name),
                        sql.Literal(password),
                    )
                )
            else:
                cursor.execute(
                    sql.SQL(
                        "ALTER ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(
                        sql.Identifier(role_name),
                        sql.Literal(password),
                    )
                )

            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name),
                    sql.Identifier(role_name),
                )
            )
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")

    logger.info("runtime database role reconciled role=%s", role_name)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    install_log_redaction()
    bootstrap_runtime_role(BootstrapSettings())  # type: ignore[call-arg]


if __name__ == "__main__":
    main()
