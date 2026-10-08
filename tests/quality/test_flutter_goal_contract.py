from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "apps/app/lib/features/finance"
API = (FINANCE / "financial_goal_api.dart").read_text(encoding="utf-8")
CONTROLLER = (FINANCE / "financial_goal_controller.dart").read_text(encoding="utf-8")
POLICY = (FINANCE / "financial_goal_policy.dart").read_text(encoding="utf-8")
SCREEN = (FINANCE / "financial_goal_screen.dart").read_text(encoding="utf-8")
EDITOR = (FINANCE / "financial_goal_editor_dialog.dart").read_text(encoding="utf-8")
ALLOCATION = (FINANCE / "financial_goal_allocation_dialog.dart").read_text(
    encoding="utf-8"
)
CORE_API = (FINANCE / "financial_core_api.dart").read_text(encoding="utf-8")
ROUTES = (ROOT / "apps/app/lib/routing/app_routes.dart").read_text(encoding="utf-8")
ROUTER = (ROOT / "apps/app/lib/routing/app_router.dart").read_text(encoding="utf-8")
HUB = (FINANCE / "financial_accounts_screen.dart").read_text(encoding="utf-8")
ALL = {
    "api": API,
    "controller": CONTROLLER,
    "policy": POLICY,
    "screen": SCREEN,
    "editor": EDITOR,
    "allocation": ALLOCATION,
}


def _code(source: str) -> str:
    return re.sub(r"(?m)^\s*//.*$", "", source)


def test_money_never_uses_floating_point_in_the_goal_client() -> None:
    for name, source in ALL.items():
        code = _code(source)
        assert "toDouble" not in code and "parseDouble" not in code, name
        assert "double.parse" not in code and "double.tryParse" not in code, name
        assert not re.search(r"\bnum\b", code), name
    for name in ("api", "controller", "screen", "editor", "allocation"):
        assert not re.search(r"\bdouble\b", _code(ALL[name])), name
    # The only double is the visual bar fraction, parsed from the server text with
    # integers; it never carries an amount.
    assert len(re.findall(r"\bdouble\b", _code(POLICY))) == 1
    assert "double financialGoalProgressFraction(" in POLICY
    assert "int.tryParse(" in POLICY


def test_the_client_never_derives_allocated_remaining_progress_or_backing() -> None:
    for name, source in ALL.items():
        code = _code(source)
        for forbidden in (
            "allocated -",
            "- allocated",
            "allocated +",
            "target -",
            "- target",
            "BigInt",
            "fold(",
            "reduce(",
            ".compareTo(",
        ):
            assert forbidden not in code, (name, forbidden)
    # Everything shown is parsed from the server, never built.
    for field in (
        "allocated",
        "remainingTarget",
        "surplus",
        "progressPercent",
        "progressStatus",
        "backingStatus",
        "shortfall",
        "hasInsufficientBacking",
        "accountBalance",
        "accountAllocatedTotal",
    ):
        assert f"values['{field}']" in API, field


def test_no_provider_semantics_ledger_writes_or_balance_reads_in_the_goal_client() -> (
    None
):
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
            "getbalance",
            "liststatement",
        ):
            assert forbidden not in lowered, (name, forbidden)


def test_requests_are_the_goal_endpoints_and_there_is_no_delete() -> None:
    code = _code(API)
    assert code.count("client.get(") == 2
    assert code.count("client.post(") == 2
    assert code.count("client.put(") == 1
    for verb in ("client.patch(", "client.delete("):
        assert verb not in code
    for path in (
        "finance/goals'",
        "finance/goals/$id/summary",
        "finance/goals/$id/allocations",
        "finance/goals/$id'",
    ):
        assert path in code, path
    assert "expectedVersion" in code
    assert "part 'financial_goal_api.dart';" in CORE_API


def test_a_write_is_sent_once_and_every_answer_ends_in_one_canonical_reread() -> None:
    code = _code(CONTROLLER)
    assert code.count(".createGoal(") == 1
    assert code.count(".replaceGoal(") == 1
    assert code.count(".allocateGoal(") == 1
    for token in ("Timer(", "Timer.periodic", "Future.delayed", "retry", "Retry"):
        assert token not in code, token
    assert not re.search(r"\bwhile\s*\(", code)
    assert not re.search(r"\bfor\s*\(.*(createGoal|replaceGoal|allocateGoal)", code)
    for method, call, stop in (
        (
            "createGoal",
            ".createGoal(",
            "Future<FinancialGoalActionResult> replaceGoal(",
        ),
        ("replaceGoal", ".replaceGoal(", "Future<FinancialGoalActionResult> allocate("),
        ("allocate", ".allocateGoal(", "bool _canWrite("),
    ):
        body = code.split(f"Future<FinancialGoalActionResult> {method}(")[1].split(
            stop
        )[0]
        assert body.index(call) < body.index("_reconcile("), method
    # A 409 never re-bases or resends: it reconciles and raises the notice.
    assert "FinancialGoalActionOutcome.conflict, conflict: true" in code


def test_nothing_changes_before_a_canonical_read() -> None:
    code = _code(CONTROLLER)
    assert not re.search(r"goals\.(add|remove|insert)", code)
    for token in ("removeWhere", ".removeAt(", "..add(", "[...state.goals"):
        assert token not in code, token
    # The goals are only ever replaced by a server read.
    assert code.count("api.listGoals()") == 1
    assert code.count(".getGoalSummary(") == 1
    assert code.count("api.listAccounts()") == 1


def test_the_cost_is_fixed_and_there_is_no_request_per_item() -> None:
    code = _code(CONTROLLER)
    for fetch in (
        "getGoal(",
        "getAccount(",
        "listMovements(",
        "listStatement",
        "getMovementAllocation",
        "listBudgets(",
        "listPendingMovements",
    ):
        assert fetch not in code, fetch
    assert "ref.read(financialCoreApiProvider)" in code


def test_the_screen_goes_through_the_controller_and_is_routed() -> None:
    for name in ("screen", "editor", "allocation"):
        code = _code(ALL[name])
        assert "authenticatedApiClientProvider" not in code, name
        assert "client." not in code, name
    assert "financialGoalsControllerProvider" in SCREEN
    assert "static const financeGoalsPath = '/app/financas/metas';" in ROUTES
    assert "FinancialGoalScreen()" in ROUTER
    assert "AppRoutes.financeGoalsPath" in HUB


def test_the_virtual_allocation_text_is_permanent_and_never_a_guarantee() -> None:
    assert "Destinação virtual; não transfere nem bloqueia dinheiro." in POLICY
    # Shown on the screen itself and in the allocation dialog, never only a tooltip.
    assert "financialGoalVirtualNotice" in SCREEN
    assert "financialGoalVirtualNotice" in ALLOCATION
    assert "financialGoalVirtualNotice" in EDITOR
    assert "garantia bancária" in POLICY
    for forbidden in ("tooltip: financialGoalVirtualNotice", "Tooltip("):
        assert forbidden not in _code(SCREEN), forbidden


def test_read_only_members_get_no_write_controls() -> None:
    code = _code(SCREEN)
    # The three writes live behind the server-decided canEdit.
    assert "if (goal.canEdit) ..." in code
    for key in ("allocateKey", "releaseKey", "editKey"):
        assert f"FinancialGoalScreen.{key}" in code
    assert "!goal.canEdit" in code  # the read-only explanation
    assert "SHARED" not in code and "shared" not in code.lower().replace(
        "compartilhada", ""
    )
