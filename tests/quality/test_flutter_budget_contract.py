from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "apps/app/lib/features/finance"
API = (FINANCE / "financial_budget_api.dart").read_text(encoding="utf-8")
CONTROLLER = (FINANCE / "financial_budget_controller.dart").read_text(encoding="utf-8")
POLICY = (FINANCE / "financial_budget_policy.dart").read_text(encoding="utf-8")
SCREEN = (FINANCE / "financial_budget_screen.dart").read_text(encoding="utf-8")
EDITOR = (FINANCE / "financial_budget_editor_dialog.dart").read_text(encoding="utf-8")
CORE_API = (FINANCE / "financial_core_api.dart").read_text(encoding="utf-8")
ROUTES = (ROOT / "apps/app/lib/routing/app_routes.dart").read_text(encoding="utf-8")
ROUTER = (ROOT / "apps/app/lib/routing/app_router.dart").read_text(encoding="utf-8")
CLIENT = (ROOT / "apps/app/lib/core/auth/authenticated_api_client.dart").read_text(
    encoding="utf-8"
)
ALL = {
    "api": API,
    "controller": CONTROLLER,
    "policy": POLICY,
    "screen": SCREEN,
    "editor": EDITOR,
}


def _code(source: str) -> str:
    return re.sub(r"(?m)^\s*//.*$", "", source)


def test_money_never_uses_floating_point_in_the_budget_client() -> None:
    for name, source in ALL.items():
        code = _code(source)
        assert "toDouble" not in code and "parseDouble" not in code, name
        assert "double.parse" not in code and "double.tryParse" not in code, name
        assert not re.search(r"\bnum\b", code), name
    for name in ("api", "controller", "screen", "editor"):
        assert not re.search(r"\bdouble\b", _code(ALL[name])), name
    # The only double is the visual bar fraction, parsed from the server text with
    # integers; it never carries an amount.
    assert len(re.findall(r"\bdouble\b", _code(POLICY))) == 1
    assert "double financialBudgetProgressFraction(" in POLICY
    assert "int.tryParse(" in POLICY


def test_the_client_never_derives_realized_remaining_status_or_percent() -> None:
    for name, source in ALL.items():
        code = _code(source)
        for forbidden in (
            "realized -",
            "- realized",
            "realized +",
            "planned -",
            "- planned",
            "BigInt",
            "fold(",
            "reduce(",
        ):
            assert forbidden not in code, (name, forbidden)
    # Realized/remaining/status/percent are parsed from the server, never built.
    for field in ("realized", "remaining", "status", "progressPercent"):
        assert f"values['{field}']" in API


def test_no_provider_semantics_ledger_writes_or_balance_in_the_budget_client() -> None:
    for name, source in ALL.items():
        lowered = _code(source).lower()
        for forbidden in (
            "pluggy",
            "provideritem",
            "createmovement",
            "createtransfer",
            "reversemovement",
            "createmovementallocation",
            "openingbalance",
            "balancesnapshot",
        ):
            assert forbidden not in lowered, (name, forbidden)


def test_requests_are_the_budget_endpoints_and_there_is_no_delete() -> None:
    code = _code(API)
    assert code.count("client.get(") == 3
    assert code.count("client.post(") == 1
    assert code.count("client.put(") == 1
    for verb in ("client.patch(", "client.delete("):
        assert verb not in code
    for path in (
        "finance/budgets?period=",
        "finance/budgets/$id/summary",
        "finance/budgets',",
    ):
        assert path in code
    assert "expectedVersion" in code
    assert "enum AuthHttpMethod { get, post, put, delete }" in (
        ROOT / "apps/app/lib/core/auth/auth_http.dart"
    ).read_text(encoding="utf-8")
    assert "AuthHttpMethod.put" in CLIENT
    assert "part 'financial_budget_api.dart';" in CORE_API


def test_a_write_is_sent_once_and_every_answer_ends_in_one_canonical_reread() -> None:
    code = _code(CONTROLLER)
    assert code.count(".createBudget(") == 1
    assert code.count(".replaceBudget(") == 1
    for token in ("Timer(", "Timer.periodic", "Future.delayed", "retry", "Retry"):
        assert token not in code, token
    assert not re.search(r"\bwhile\s*\(", code)
    assert not re.search(r"\bfor\s*\(.*(createBudget|replaceBudget)", code)
    create = code.split("Future<FinancialBudgetActionResult> createBudget(")[1].split(
        "Future<FinancialBudgetActionResult> replaceBudget("
    )[0]
    assert create.index(".createBudget(") < create.index("_reconcile(")
    replace = code.split("Future<FinancialBudgetActionResult> replaceBudget(")[1].split(
        "bool _canWrite("
    )[0]
    assert replace.index(".replaceBudget(") < replace.index("_reconcile(")
    # A 409 never re-bases or resends: it reconciles and raises the notice.
    assert "FinancialBudgetActionOutcome.conflict, conflict: true" in code


def test_nothing_changes_before_a_canonical_read() -> None:
    code = _code(CONTROLLER)
    assert not re.search(r"budgets\.(add|remove|insert)", code)
    for token in ("removeWhere", ".removeAt(", "..add(", "[...state.budgets"):
        assert token not in code, token
    # The plan is only ever replaced by a server read.
    assert code.count("api.listBudgets(") == 1
    assert code.count(".getBudgetSummary(") == 1
    assert code.count("api.listCategories()") == 1


def test_the_cost_is_fixed_and_there_is_no_request_per_line() -> None:
    code = _code(CONTROLLER)
    for fetch in (
        "getBudget(",
        "getAccount(",
        "listAccounts(",
        "getMovementAllocation",
        "listCategorizationRules",
        "listPendingMovements",
    ):
        assert fetch not in code, fetch
    assert "ref.read(financialCoreApiProvider)" in code


def test_the_screen_goes_through_the_controller_and_is_routed() -> None:
    assert "authenticatedApiClientProvider" not in _code(SCREEN)
    assert "client." not in _code(SCREEN) and "client." not in _code(EDITOR)
    assert "financeBudgetsPath = '/app/financas/orcamentos'" in ROUTES
    assert "FinancialBudgetScreen()" in ROUTER
    assert "AppRoutes.financePendingPath" in SCREEN  # coverage bridge to #249


def test_the_editor_only_builds_requests_and_never_sends_them() -> None:
    assert "Navigator.of(context).pop(result)" in EDITOR
    for token in ("ref.read", "createBudget(", "replaceBudget(", "ConsumerState"):
        assert token not in _code(EDITOR), token
    # Scope, currency, month and basis are immutable after creation.
    assert "não mudam depois de criados" in EDITOR


def test_the_client_validates_and_shows_the_declared_scope_without_deriving_it() -> (
    None
):
    assert "'realizationAccountScope'" in API
    assert "values['realizationAccountScope']" in API
    assert "realizationAccountScope is invalid" in API
    # Shown in plain text on the loaded budget and in the editor, not a tooltip.
    assert "financialBudgetRealizationScopeNotice(" in SCREEN
    assert "financialBudgetRealizationScopeNotice(" in EDITOR
    assert "scopeNoticeKey" in SCREEN and "scopeNoticeKey" in EDITOR
    for source in (SCREEN, EDITOR):
        assert "Tooltip(" not in _code(source).replace("tooltip:", "")
    assert "Contas pessoais e" in POLICY and "compartilhadas não entram" in POLICY
