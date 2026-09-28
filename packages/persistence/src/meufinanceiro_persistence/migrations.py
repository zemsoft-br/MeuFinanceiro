"""Programmatic Alembic runner and revision inspection."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine

PACKAGE_DIR = Path(__file__).resolve().parent
ALEMBIC_INI = PACKAGE_DIR / "alembic.ini"
MIGRATIONS_DIR = PACKAGE_DIR / "migrations"


def build_alembic_config(database_url: str, *, app_database_user: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.set_main_option("app_database_user", app_database_user)
    return config


def upgrade(database_url: str, *, app_database_user: str) -> None:
    config = build_alembic_config(
        database_url,
        app_database_user=app_database_user,
    )
    command.upgrade(config, "head")


def downgrade_to_base(database_url: str, *, app_database_user: str) -> None:
    config = build_alembic_config(
        database_url,
        app_database_user=app_database_user,
    )
    command.downgrade(config, "base")


def expected_revision() -> str:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    revision = ScriptDirectory.from_config(config).get_current_head()
    if revision is None:
        raise RuntimeError("Alembic has no head revision")
    return revision


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def create_migration_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)
