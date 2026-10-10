from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "apps/app/lib/features/finance"
API = (FINANCE / "financial_cash_flow_api.dart").read_text(encoding="utf-8")
CONTROLLER = (FINANCE / "financial_cash_flow_controller.dart").read_text(
    encoding="utf-8"
)
SCREEN = (FINANCE / "financial_cash_flow_screen.dart").read_text(encoding="utf-8")
CORE_API = (FINANCE / "financial_core_api.dart").read_text(encoding="utf-8")
ACCOUNTS = (FINANCE / "financial_accounts_screen.dart").read_text(encoding="utf-8")
ROUTES = (ROOT / "apps/app/lib/routing/app_routes.dart").read_text(encoding="utf-8")
ROUTER = (ROOT / "apps/app/lib/routing/app_router.dart").read_text(encoding="utf-8")
ALL = {"api": API, "controller": CONTROLLER, "screen": SCREEN}


def _code(source: str) -> str:
    return re.sub(r"(?m)^\s*//.*$", "", source)


def test_money_never_uses_floating_point_in_the_cash_flow_client() -> None:
    for name, source in ALL.items():
        code = _code(source)
        for forbidden in ("toDouble", "parseDouble", "double.parse", "BigInt"):
            assert forbidden not in code, (name, forbidden)
        assert not re.search(r"\bdouble\b", code), name
        assert not re.search(r"\bnum\b", code), name


def test_the_client_never_derives_balances_totals_or_risk() -> None:
    for name, source in ALL.items():
        code = _code(source)
        for forbidden in (
            "balance +",
            "balance -",
            ".amount +",
            ".amount -",
            "amount) +",
            "closing -",
            "opening +",
            "reduce(",
        ):
            assert forbidden not in code, (name, forbidden)
    for field in (
        "balanceAfter",
        "accountBalanceAfter",
        "closingBalance",
        "balanceAtReference",
        "firstNegativeDate",
        "projectionStatus",
        "negative",
    ):
        assert f"values['{field}']" in API, field


def test_the_cash_flow_client_only_reads() -> None:
    api = _code(API)
    assert "client.get(" in api
    for forbidden in ("client.post(", "client.put(", "client.delete(", "client.patch("):
        assert forbidden not in api, forbidden
    for name in ("controller", "screen"):
        lowered = _code(ALL[name]).lower()
        for forbidden in (
            "createmovement",
            "realizeoccurrence",
            "generateoccurrences",
            "skipoccurrence",
            "createtransfer",
            "reversemovement",
            "client.post",
            "idempotencykey",
        ):
            assert forbidden not in lowered, (name, forbidden)


def test_the_wire_contract_is_strict() -> None:
    assert "part 'financial_cash_flow_api.dart';" in CORE_API
    assert API.count("_strictMap(") >= 7
    assert "_strictJsonObject(" in API
    assert "financialCashFlowEventsMax = 2000" in API
    assert "financialCashFlowWindowMaxDays = 92" in API
    assert "projectionStatus contradicts its issues" in API


def test_route_and_entry_point_are_registered() -> None:
    assert "financeCashFlowPath = '/app/financas/fluxo-de-caixa'" in ROUTES
    assert "path: AppRoutes.financeCashFlowPath" in ROUTER
    assert "FinancialCashFlowScreen()" in ROUTER
    assert "context.go(AppRoutes.financeCashFlowPath)" in ACCOUNTS


def test_every_state_is_explicit_on_screen() -> None:
    for key in (
        "loadingKey",
        "emptyKey",
        "errorKey",
        "rejectedKey",
        "staleKey",
        "statusKey",
        "riskKey",
        "noticeKey",
    ):
        assert f"FinancialCashFlowScreen.{key}" in SCREEN, key
    assert "Nada foi omitido em silêncio" in SCREEN
    assert "nada nesta tela cria lançamentos" in SCREEN
