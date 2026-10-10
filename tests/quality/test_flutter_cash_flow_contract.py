from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTE = (ROOT / "apps/api/app/api/routes/finance_cash_flow.py").read_text(
    encoding="utf-8"
)
DOMAIN = (ROOT / "packages/finance/src/meufinanceiro_finance/cash_flow.py").read_text(
    encoding="utf-8"
)
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


def _wire_fields(class_name: str) -> set[str]:
    """JSON names of one Pydantic response model of the cash flow route."""
    for node in ast.parse(ROUTE).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            names: set[str] = set()
            for item in node.body:
                if not isinstance(item, ast.AnnAssign):
                    continue
                assert isinstance(item.target, ast.Name)
                name = item.target.id
                if isinstance(item.value, ast.Call):
                    for keyword in item.value.keywords:
                        if keyword.arg == "serialization_alias":
                            assert isinstance(keyword.value, ast.Constant)
                            name = str(keyword.value.value)
                names.add(name)
            return names
    raise AssertionError(class_name)


def _dart_keys(const_name: str) -> set[str]:
    match = re.search(rf"const {const_name} = <String>\{{([^}}]*)\}};", API)
    assert match, const_name
    return set(re.findall(r"'([A-Za-z]+)'", match.group(1)))


def _python_enum(class_name: str) -> set[str]:
    match = re.search(
        rf"class {class_name}\(StrEnum\):\n((?:    .*\n|\n)*?)\n\n", DOMAIN
    )
    assert match, class_name
    return set(re.findall(r'^    [A-Z_]+ = "([A-Z_]+)"$', match.group(1), re.M))


def _dart_enum(enum_name: str) -> set[str]:
    match = re.search(rf"enum {enum_name} \{{([\s\S]*?)\n\}}", API)
    assert match, enum_name
    return set(re.findall(r"\('([A-Z_]+)'\)", match.group(1)))


def test_the_dart_parser_accepts_exactly_the_python_response_fields() -> None:
    # The strict parser rejects unknown keys and requires every known one: a
    # field added on one side only would break every read.
    for model, keys in (
        ("CashFlowResponse", "_cashFlowKeys"),
        ("CashFlowGroupResponse", "_cashFlowGroupKeys"),
        ("CashFlowIssueResponse", "_cashFlowIssueKeys"),
        ("CashFlowRiskResponse", "_cashFlowRiskKeys"),
        ("CashFlowTotalsResponse", "_cashFlowTotalsKeys"),
        ("CashFlowAccountResponse", "_cashFlowAccountKeys"),
        ("CashFlowDayResponse", "_cashFlowDayKeys"),
        ("CashFlowEventResponse", "_cashFlowEventKeys"),
    ):
        assert _wire_fields(model) == _dart_keys(keys), model
    for field in ("historicalRisk", "evaluatedDays", "anchored"):
        assert f"values['{field}']" in API, field


def test_the_dart_enums_match_the_domain_wire_values() -> None:
    for python, dart in (
        ("FinancialCashFlowIssueCode", "FinancialCashFlowIssueCode"),
        ("FinancialCashFlowProjectionStatus", "FinancialCashFlowProjectionStatus"),
    ):
        values = _python_enum(python)
        assert values, python
        assert values == _dart_enum(dart), python
    # Wire enums are bounded text; the bound must fit the longest value.
    bound = re.search(r"_enumByWire<T>\([\s\S]*?maxLength: (\d+)\)", CORE_API)
    assert bound
    longest = max(len(value) for value in _python_enum("FinancialCashFlowIssueCode"))
    assert longest <= int(bound.group(1))


def test_relative_presets_never_send_a_client_date() -> None:
    controller = _code(CONTROLLER)
    assert "days: state.period.relativeDays" in controller
    assert "financialCashFlowAddDays(" not in controller
    api = _code(API)
    assert "'days=$days'" in api
    assert "use through or days, not both" in api
