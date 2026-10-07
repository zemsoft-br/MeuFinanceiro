from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "apps/app/lib/features/finance"
API = (FINANCE / "financial_recurrence_api.dart").read_text(encoding="utf-8")
CONTROLLER = (FINANCE / "financial_recurrence_controller.dart").read_text(
    encoding="utf-8"
)
POLICY = (FINANCE / "financial_recurrence_policy.dart").read_text(encoding="utf-8")
SCREEN = (FINANCE / "financial_recurrence_screen.dart").read_text(encoding="utf-8")
EDITOR = (FINANCE / "financial_recurrence_editor_dialog.dart").read_text(
    encoding="utf-8"
)
REALIZE = (FINANCE / "financial_recurrence_realize_dialog.dart").read_text(
    encoding="utf-8"
)
CORE_API = (FINANCE / "financial_core_api.dart").read_text(encoding="utf-8")
ACCOUNTS = (FINANCE / "financial_accounts_screen.dart").read_text(encoding="utf-8")
ROUTES = (ROOT / "apps/app/lib/routing/app_routes.dart").read_text(encoding="utf-8")
ROUTER = (ROOT / "apps/app/lib/routing/app_router.dart").read_text(encoding="utf-8")
ALL = {
    "api": API,
    "controller": CONTROLLER,
    "policy": POLICY,
    "screen": SCREEN,
    "editor": EDITOR,
    "realize": REALIZE,
}


def _code(source: str) -> str:
    return re.sub(r"(?m)^\s*//.*$", "", source)


def test_money_never_uses_floating_point_in_the_recurrence_client() -> None:
    for name, source in ALL.items():
        code = _code(source)
        assert "toDouble" not in code and "parseDouble" not in code, name
        assert "double.parse" not in code and "double.tryParse" not in code, name
        assert not re.search(r"\bdouble\b", code), name
        assert not re.search(r"\bnum\b", code), name


def test_the_client_owns_no_calendar_balance_or_realized_arithmetic() -> None:
    for name, source in ALL.items():
        code = _code(source)
        for forbidden in (
            "BigInt",
            "fold(",
            "reduce(",
            "daysInMonth",
            "lastDay",
            "Duration(days",
            ".add(Duration",
            "expected -",
            "- expected",
            "actual -",
            "- actual",
            "balance",
        ):
            assert forbidden not in code, (name, forbidden)
    # The only clock is the injectable provider in the controller (a default).
    assert _code(CONTROLLER).count("DateTime.now") == 1
    assert "(ref) => DateTime.now" in CONTROLLER
    for name in ("api", "policy", "screen", "editor", "realize"):
        assert "DateTime.now" not in _code(ALL[name]), name
    # Status, link and amounts are parsed from the server, never built.
    for field in ("status", "realization", "scheduledDate", "periodStart"):
        assert f"values['{field}']" in API


def test_no_provider_semantics_and_no_direct_ledger_writes_in_the_client() -> None:
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


def test_requests_are_the_recurrence_endpoints_and_there_is_no_delete() -> None:
    code = _code(API)
    assert code.count("client.get(") == 2
    assert code.count("client.post(") == 5
    assert code.count("client.put(") == 1
    for verb in ("client.patch(", "client.delete("):
        assert verb not in code
    for path in (
        "'finance/recurrences'",
        "'finance/recurrences/$id/$action'",
        "'finance/recurrences/$id/occurrences/generate'",
        "finance/recurrence-occurrences?fromPeriod=$from&throughPeriod=$through",
        "'finance/recurrence-occurrences/$id/skip'",
        "'finance/recurrence-occurrences/$id/realize'",
    ):
        assert path in code, path
    assert "expectedVersion" in code and "idempotencyKey" in code
    assert "part 'financial_recurrence_api.dart';" in CORE_API


def test_a_write_is_sent_once_and_every_answer_ends_in_one_canonical_reread() -> None:
    code = _code(CONTROLLER)
    for call in (
        ".createRecurrence(",
        ".replaceRecurrence(",
        ".pauseRecurrence(",
        ".resumeRecurrence(",
        ".generateOccurrences(",
        ".skipOccurrence(",
        ".realizeOccurrence(",
    ):
        assert code.count(call) == 1, call
    for token in ("Timer(", "Timer.periodic", "Future.delayed", "retry(", "Retry("):
        assert token not in code, token
    assert not re.search(r"\bwhile\s*\(", code)
    # Every write goes through one helper that always reconciles with a read.
    assert code.count("_write(") >= 7
    write = code.split("Future<FinancialRecurrenceActionResult> _write(")[1].split(
        "Future<FinancialRecurrenceActionResult> _afterFailedWrite("
    )[0]
    assert "_reconcile(" in write and "await send()" in write
    # A 409 never re-bases or resends: it reconciles and raises the notice.
    assert "FinancialRecurrenceActionOutcome.conflict," in code
    assert "conflict: true" in code


def test_nothing_changes_before_a_canonical_read() -> None:
    code = _code(CONTROLLER)
    for token in (
        "recurrences.add",
        "occurrences.add",
        "removeWhere",
        ".removeAt(",
        "..add(",
        "[...state.recurrences",
        "[...state.occurrences",
        "optimistic",
    ):
        assert token not in code, token
    # The lists are only ever replaced by a server read.
    assert code.count("api.listRecurrences()") == 1
    assert code.count("api.listOccurrences(") == 1
    assert code.count("api.listAccounts()") == 1


def test_the_cost_is_fixed_and_there_is_no_request_per_rule_or_occurrence() -> None:
    code = _code(CONTROLLER)
    for fetch in (
        "getRecurrence(",
        "getAccount(",
        "getBalance(",
        "getStatement(",
        "listMovements(",
        "listBudgets(",
        "listPendingMovements",
    ):
        assert fetch not in code, fetch
    assert "ref.read(financialCoreApiProvider)" in code


def test_an_ambiguous_attempt_keeps_its_key_only_for_an_identical_retry() -> None:
    code = _code(CONTROLLER)
    assert "_createKeys" in code and "_realizeKeys" in code
    assert "_realizeKeys[attempt] ?? input.idempotencyKey" in code
    # A definite answer forgets the key; an unknown one keeps it.
    assert "onDefiniteFailure" in code
    assert "_realizeKeys.remove(attempt)" in code


def test_the_screen_goes_through_the_controller_and_is_routed() -> None:
    assert "authenticatedApiClientProvider" not in _code(SCREEN)
    for source in (SCREEN, EDITOR, REALIZE):
        assert "client." not in _code(source)
    assert "financeRecurrencesPath = '/app/financas/recorrencias'" in ROUTES
    assert "FinancialRecurrenceScreen()" in ROUTER
    assert "AppRoutes.financeRecurrencesPath" in ACCOUNTS


def test_the_dialogs_only_build_requests_and_never_send_them() -> None:
    for source in (EDITOR, REALIZE):
        code = _code(source)
        for token in (
            "ref.read",
            "ConsumerState",
            "createRecurrence(",
            "replaceRecurrence(",
            "realizeOccurrence(",
        ):
            assert token not in code, token
        assert "Navigator.of(context).pop(" in code
    # Account, effect, currency and start are immutable after creation.
    assert "não mudam depois de criar" in EDITOR


def test_forecast_never_looks_like_a_fact() -> None:
    assert "Previsto não altera o saldo nem o extrato" in POLICY
    assert "Somente Registrar cria um" in POLICY
    assert "financialRecurrenceForecastNotice" in SCREEN
    assert "financialRecurrenceForecastNotice" in EDITOR
    assert "financialRecurrenceRealizeNotice" in REALIZE
    # Status is stated in text, never by colour alone.
    assert "financialOccurrenceStatusLabel(" in SCREEN
    assert "financialOccurrenceStatusHint(" in SCREEN
    # Registering is explicit and confirmed; skipping asks first.
    assert "Registrar" in SCREEN and "Pular esta previsão?" in SCREEN
    assert "showDialog<FinancialRecurrenceRealizeInput>" in SCREEN


def test_the_server_decides_what_the_client_may_do() -> None:
    assert "canEdit" in API
    assert "values['canEdit']" in API
    assert "rule.canEdit" in SCREEN and "occurrence.canEdit" in SCREEN
    assert "Somente leitura" in SCREEN
