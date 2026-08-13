"""Operational CLI for the isolated demonstration fixture."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from meufinanceiro_persistence.database import Database
from meufinanceiro_persistence.demo import (
    DemoFixtureStore,
    DemoModeDisabledError,
)


class DemoCliSettings(BaseSettings):
    database_url: SecretStr
    admin_database_url: SecretStr | None = None
    demo_operator_password: SecretStr | None = None
    app_demo_mode: bool = False

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")


def _serialize(value: object) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the isolated demo fixture")
    parser.add_argument("command", choices=("load", "status", "reset"))
    args = parser.parse_args()

    settings = DemoCliSettings()  # type: ignore[call-arg]
    database = Database(settings.database_url.get_secret_value())
    reset_database = (
        Database(settings.admin_database_url.get_secret_value())
        if settings.admin_database_url is not None
        else None
    )
    operator_password = (
        settings.demo_operator_password.get_secret_value()
        if settings.demo_operator_password is not None
        else None
    )
    store = DemoFixtureStore(
        database.engine,
        enabled=settings.app_demo_mode,
        operator_password=operator_password,
        reset_engine=(reset_database.engine if reset_database is not None else None),
    )
    try:
        if args.command == "load":
            print(_serialize(asdict(store.load())))
            return
        if args.command == "status":
            if not settings.app_demo_mode:
                raise DemoModeDisabledError("demo mode is not enabled")
            print(_serialize(asdict(store.status())))
            return
        removed = store.reset()
        print(_serialize({"fixture_id": store.status().fixture_id, "removed": removed}))
    except DemoModeDisabledError as exc:
        parser.error(str(exc))
    finally:
        database.dispose()
        if reset_database is not None:
            reset_database.dispose()


if __name__ == "__main__":
    main()
