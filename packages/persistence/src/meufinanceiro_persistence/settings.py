"""Environment contracts for migration and database bootstrap commands."""

from __future__ import annotations

import re

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def validate_role_name(value: str) -> str:
    if not ROLE_PATTERN.fullmatch(value):
        raise ValueError(
            "APP_DATABASE_USER must be an ASCII SQL identifier with at most 63 characters"
        )
    return value


class MigrationSettings(BaseSettings):
    database_url: SecretStr
    app_database_user: str = "meufinanceiro_app"

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    @field_validator("app_database_user")
    @classmethod
    def _validate_role_name(cls, value: str) -> str:
        return validate_role_name(value)


class BootstrapSettings(BaseSettings):
    admin_database_url: SecretStr
    app_database_user: str = "meufinanceiro_app"
    app_database_password: SecretStr

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    @field_validator("app_database_user")
    @classmethod
    def _validate_role_name(cls, value: str) -> str:
        return validate_role_name(value)
