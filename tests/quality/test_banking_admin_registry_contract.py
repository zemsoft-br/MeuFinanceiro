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
COMPOSE_SOURCE = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")


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


def test_administration_service_does_not_define_http_routes_or_provider_details() -> (
    None
):
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


def test_banking_flags_are_disabled_by_default_and_forwarded() -> None:
    assert "app_banking_enabled: bool = False" in CONFIG_SOURCE
    assert "app_banking_pluggy_enabled: bool = False" in CONFIG_SOURCE
    assert "APP_BANKING_ENABLED: ${APP_BANKING_ENABLED:-false}" in COMPOSE_SOURCE
    assert (
        "APP_BANKING_PLUGGY_ENABLED: ${APP_BANKING_PLUGGY_ENABLED:-false}"
        in COMPOSE_SOURCE
    )


def test_runtime_composes_executor_only_when_both_flags_are_enabled() -> None:
    assert "PluggyReadOnlyExecutionService" in MAIN_SOURCE
    assert (
        "app.state.banking_pluggy_execution = banking_pluggy_execution" in MAIN_SOURCE
    )
    assert (
        "resolved_settings.app_banking_enabled\n"
        "            and resolved_settings.app_banking_pluggy_enabled" in MAIN_SOURCE
    )
    assert (
        '("pluggy",) if resolved_settings.app_banking_pluggy_enabled else ()'
        in MAIN_SOURCE
    )


def test_startup_does_not_perform_provider_io() -> None:
    for forbidden in (
        "use_enabled_credentials(",
        ".get_connection_state(",
        ".get_capabilities(",
        ".list_accounts(",
        ".list_transactions(",
    ):
        assert forbidden not in MAIN_SOURCE
