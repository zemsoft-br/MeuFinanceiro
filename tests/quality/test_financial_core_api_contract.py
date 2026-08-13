from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTE = (ROOT / "apps/api/app/api/routes/finance.py").read_text(encoding="utf-8")
SERVICE = (ROOT / "apps/api/app/services/financial_core.py").read_text(encoding="utf-8")
AUTH = (ROOT / "apps/api/app/api/auth.py").read_text(encoding="utf-8")
MAIN = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")


def test_financial_api_does_not_expose_generic_movement_creation() -> None:
    assert '@router.post("/movements"' not in ROUTE
    assert "FinancialMovementDraft" not in ROUTE
    assert "FinancialMovementDraft" not in SERVICE
    assert "manual-entries" not in ROUTE
    assert "transfers" not in ROUTE


def test_financial_api_derives_scope_from_authenticated_primary_residence() -> None:
    assert "Depends(require_primary_residence)" in ROUTE
    assert "authenticated.principal.installation_id" in ROUTE
    assert "authenticated.principal.primary_residence_id" in ROUTE
    assert "authenticated.principal.operator_id" in ROUTE
    for client_scope in (
        "residence_id: UUID =",
        "installation_id: UUID =",
        "operator_id: UUID =",
    ):
        assert client_scope not in ROUTE


def test_financial_money_wire_never_uses_float() -> None:
    assert "amount: str" in ROUTE
    assert "Decimal(payload.amount)" in ROUTE
    assert "money.canonical_amount" in ROUTE
    assert "float(" not in ROUTE
    assert "double" not in ROUTE.lower()


def test_financial_routes_are_no_store_and_validation_is_sanitized() -> None:
    assert '"/api/v1/finance/"' in AUTH
    assert '_FINANCE_VALIDATION_PREFIX = "/api/v1/finance/"' in MAIN
    assert '"invalid financial request"' in MAIN


def test_financial_service_is_store_protocol_orchestration_only() -> None:
    assert "class FinancialAccountStoreBoundary(Protocol)" in SERVICE
    assert "class FinancialOpeningBalanceStoreBoundary(Protocol)" in SERVICE
    assert "class FinancialMovementStoreBoundary(Protocol)" in SERVICE
    assert "sqlalchemy" not in SERVICE.lower()
    assert "pluggy" not in SERVICE.lower()
    assert "fastapi" not in SERVICE.lower()


def test_financial_route_is_provider_neutral() -> None:
    lowered = ROUTE.lower()
    for forbidden in (
        "pluggy",
        "provider_item_id",
        "external_resource_id",
        "external_account_id",
        "clientuser",
    ):
        assert forbidden not in lowered
