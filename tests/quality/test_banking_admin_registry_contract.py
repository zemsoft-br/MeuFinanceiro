from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_SOURCE = (
    REPOSITORY_ROOT / "packages/banking/src/meufinanceiro_banking/registry.py"
).read_text(encoding="utf-8")
ADMIN_SOURCE = (REPOSITORY_ROOT / "apps/api/app/services/banking_admin.py").read_text(
    encoding="utf-8"
)
MAIN_SOURCE = (REPOSITORY_ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")
CONFIG_SOURCE = (REPOSITORY_ROOT / "apps/api/app/core/config.py").read_text(
    encoding="utf-8"
)


def test_registry_remains_provider_neutral() -> None:
    lowered = REGISTRY_SOURCE.lower()

    for forbidden in (
        "pluggy",
        "httpx",
        "requests",
        "fastapi",
        "sqlalchemy",
        "meufinanceiro_persistence",
        "api_key",
        "connect_token",
    ):
        assert forbidden not in lowered


def test_administration_service_does_not_define_http_routes() -> None:
    lowered = ADMIN_SOURCE.lower()

    for forbidden in (
        "apirouter",
        "@router",
        "connect_token",
        "api_key",
        "password",
        "mfa",
        "httpx",
        "requests",
        "pluggy",
    ):
        assert forbidden not in lowered


def test_default_runtime_registry_is_empty_and_frozen() -> None:
    assert "BankingProviderRegistry().freeze()" in MAIN_SOURCE
    assert ".register(" not in MAIN_SOURCE


def test_banking_feature_flag_is_disabled_by_default() -> None:
    assert "app_banking_enabled: bool = False" in CONFIG_SOURCE
