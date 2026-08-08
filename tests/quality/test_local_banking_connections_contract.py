from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUERY_SOURCE = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/banking_queries.py"
).read_text(encoding="utf-8")
SERVICE_SOURCE = (
    ROOT / "apps/api/app/services/banking_connections.py"
).read_text(encoding="utf-8")
ROUTE_SOURCE = (
    ROOT / "apps/api/app/api/routes/banking_local_connections.py"
).read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")


def test_persistence_query_selects_only_allowlisted_local_metadata() -> None:
    safe_columns = QUERY_SOURCE.split("_SAFE_CONNECTION_COLUMNS = (", 1)[1].split(
        ")\n\n\nclass BankingConnectionQueryStore", 1
    )[0]
    assert "connections.c.id" in safe_columns
    assert "connections.c.provider" in safe_columns
    assert "connections.c.status" in safe_columns
    assert "external_connection_id" not in safe_columns
    assert "provider_reason_code" not in safe_columns
    assert "provider_configuration_id" not in safe_columns
    assert '"app.current_installation_id"' in QUERY_SOURCE
    assert '"app.current_residence_id"' in QUERY_SOURCE
    assert "connections.c.installation_id == installation_id" in QUERY_SOURCE
    assert "connections.c.residence_id == residence_id" in QUERY_SOURCE


def test_public_response_never_contains_provider_item_or_diagnostic_ids() -> None:
    for forbidden in (
        "external_connection_id",
        "externalConnectionId",
        "item_id",
        "itemId",
        "clientUserId",
        "provider_reason_code",
        "providerReasonCode",
        "configuration_id",
        "credential",
        "apiKey",
        "accessToken",
    ):
        assert forbidden not in ROUTE_SOURCE
        assert forbidden not in SERVICE_SOURCE


def test_endpoint_accepts_no_scope_filters_or_body() -> None:
    assert 'APIRouter(prefix="/banking"' in ROUTE_SOURCE
    assert '@router.get("/connections"' in ROUTE_SOURCE
    assert "request.query_params" in ROUTE_SOURCE
    assert "request.stream()" in ROUTE_SOURCE
    assert "primary_residence_id" in ROUTE_SOURCE
    for forbidden in (
        'alias="residenceId"',
        'alias="installationId"',
        'alias="provider"',
    ):
        assert forbidden not in ROUTE_SOURCE


def test_local_query_is_composed_independently_of_external_provider_flags() -> None:
    query_creation = MAIN_SOURCE.index(
        "banking_connection_query_store = BankingConnectionQueryStore(database.engine)"
    )
    provider_flag_block = MAIN_SOURCE.index(
        "resolved_settings.app_banking_enabled\n"
        "            and resolved_settings.app_banking_pluggy_enabled"
    )
    service_creation = MAIN_SOURCE.index(
        "app.state.banking_connections = BankingConnectionsService("
    )

    assert query_creation < provider_flag_block < service_creation
    assert "use_enabled_credentials" not in QUERY_SOURCE
    assert "Pluggy" not in QUERY_SOURCE
    assert "httpx" not in QUERY_SOURCE
    assert "transport" not in QUERY_SOURCE.lower()
