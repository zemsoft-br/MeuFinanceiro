"""One-shot migration command used by Docker Compose."""

from __future__ import annotations

import argparse
import logging

from meufinanceiro_security.redaction import install_log_redaction

from meufinanceiro_persistence.migrations import downgrade_to_base, upgrade
from meufinanceiro_persistence.settings import MigrationSettings

logger = logging.getLogger("meufinanceiro.persistence.migrate")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("upgrade", "downgrade-base"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    install_log_redaction()
    settings = MigrationSettings()  # type: ignore[call-arg]
    database_url = settings.database_url.get_secret_value()

    if args.action == "upgrade":
        upgrade(database_url, app_database_user=settings.app_database_user)
        logger.info("database migrations applied")
    else:
        downgrade_to_base(database_url, app_database_user=settings.app_database_user)
        logger.info("database migrations downgraded to base")


if __name__ == "__main__":
    main()
