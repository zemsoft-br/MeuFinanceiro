from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTE_SOURCE = (ROOT / "apps/api/app/api/routes/banking_admin.py").read_text(
    encoding="utf-8"
)
AUTH_SOURCE = (ROOT / "apps/api/app/api/auth.py").read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")


def test_banking_administration_routes_require_installation_admin() -> None:
    assert ROUTE_SOURCE.count("Depends(require_installation_admin)") == 4
    assert "require_operator_session" in AUTH_SOURCE
    assert "OperatorRole.INSTALLATION_ADMIN" in AUTH_SOURCE


def test_installation_context_is_only_derived_from_authenticated_principal() -> None:
    assert (
        ROUTE_SOURCE.count("installation_id=authenticated.principal.installation_id")
        == 4
    )
    assert "installation_id:" not in ROUTE_SOURCE
    assert 'Field(alias="installation_id")' not in ROUTE_SOURCE


def test_routes_do_not_execute_provider_or_expose_external_identifiers() -> None:
    lowered = ROUTE_SOURCE.casefold()
    for forbidden in (
        "banking_pluggy_execution",
        "pluggyreadonlyexecutionservice",
        "httpx",
        "requests",
        "external_connection_id",
        "item_id",
        "account_id",
        "list_accounts",
        "list_transactions",
    ):
        assert forbidden not in lowered


def test_credentials_are_request_only_and_responses_are_metadata_only() -> None:
    assert "SecretStr" in ROUTE_SOURCE
    response_section = ROUTE_SOURCE.split("class ProviderConfigurationResponse", 1)[1]
    response_section = response_section.split("def _response", 1)[0]
    assert "client_id" not in response_section
    assert "client_secret" not in response_section
    assert "installation_id" not in response_section


def test_admin_routes_are_no_store_and_registered_once() -> None:
    assert '"/api/v1/admin/banking/"' in AUTH_SOURCE
    assert (
        MAIN_SOURCE.count('include_router(banking_admin_router, prefix="/api/v1")') == 1
    )
