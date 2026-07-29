from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MeuFinanceiro API"
    app_env: str = "local"
    app_log_level: str = "INFO"
    app_demo_mode: bool = False
    app_banking_enabled: bool = False
    database_url: SecretStr
    app_keyring_file: Path = Path("/run/secrets/app_keyring")
    database_pool_size: int = 5
    database_max_overflow: int = 5

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
