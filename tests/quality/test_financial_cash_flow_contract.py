from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
API = ROOT / "apps/api/app"
DOMAIN = (FINANCE / "cash_flow.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "financial_cash_flow_store.py").read_text(encoding="utf-8")
ROUTE = (API / "api/routes/finance_cash_flow.py").read_text(encoding="utf-8")
SERVICE = (API / "services/financial_cash_flow.py").read_text(encoding="utf-8")
MAIN = (API / "main.py").read_text(encoding="utf-8")
MIGRATIONS = PERSISTENCE / "migrations/versions"
ADR = (ROOT / "docs/adr/0031-read-only-cash-flow-projection.md").read_text(
    encoding="utf-8"
)


def _code(source: str) -> str:
    """Source without docstrings and comments, so prose never trips a contract."""
    without_docstrings = re.sub(r'"""[\s\S]*?"""', "", source)
    return re.sub(r"(?m)^\s*#.*$", "", without_docstrings)


def test_cash_flow_domain_is_pure_and_float_free() -> None:
    lowered = _code(DOMAIN).lower()
    for forbidden in (
        "sqlalchemy",
        "meufinanceiro_persistence",
        "pluggy",
        "fastapi",
        "float(",
        ": float",
        "date.today",
        "datetime.now",
        "time.time",
    ):
        assert forbidden not in lowered, forbidden


def test_no_projection_is_ever_persisted() -> None:
    for path in MIGRATIONS.glob("*.py"):
        lowered = path.read_text(encoding="utf-8").lower()
        for forbidden in ("cash_flow", "cashflow", "projected_balance", "projection"):
            assert forbidden not in lowered, (path.name, forbidden)


def test_store_only_reads_in_one_read_only_snapshot() -> None:
    code = _code(STORE)
    for forbidden in (
        "insert(",
        "update(",
        "delete(",
        ".begin_nested",
        "create_standard_movement_in_transaction",
        "generate_occurrences",
        "pg_advisory",
        "FOR UPDATE",
        "with_for_update",
    ):
        assert forbidden not in code, forbidden
    assert 'isolation_level="REPEATABLE READ"' in code
    assert "postgresql_readonly=True" in code
    assert code.count("self._engine.connect()") == 1
    assert "self._engine.begin()" not in code


def test_every_list_is_bounded_and_fails_instead_of_truncating() -> None:
    code = _code(STORE)
    limits = re.findall(r"\.limit\(\s*([A-Z_]+) \+ 1\s*\)", code)
    assert sorted(set(limits)) == [
        "CASH_FLOW_ACCOUNTS_MAX",
        "CASH_FLOW_EVENTS_MAX",
        "RECURRENCE_LIST_MAX",
        "_OCCURRENCE_LIVE_MONTHS_MAX",
    ]
    assert code.count("FinancialCashFlowLimitExceededError(") >= len(limits)


def test_route_is_get_only_and_never_reaches_a_writer() -> None:
    code = _code(ROUTE)
    assert re.findall(r"@router\.(\w+)\(", code) == ["get"]
    assert '"/cash-flow"' in code
    for forbidden in ("Store(", "engine", "insert", "commit", "float"):
        assert forbidden not in code, forbidden
    assert "canonical_amount" in code


def test_service_composes_store_and_pure_projection_only() -> None:
    code = _code(SERVICE)
    assert "project_cash_flow(" in code
    assert "read_source(" in code
    for forbidden in ("generate", "realize", "create_", "float", "date.today"):
        assert forbidden not in code, forbidden
    assert "FinancialCashFlowService(" in MAIN
    assert "financial_cash_flow_store,\n            clock=date.today" in MAIN


def test_expectations_never_precede_the_reference_date() -> None:
    code = _code(DOMAIN)
    assert "d.scheduled_date >= window.reference_date" in code
    assert "window.reference_date if overdue else occurrence.scheduled_date" in code


def test_adr_records_the_projection_decision() -> None:
    for required in (
        "Status: Proposed",
        "REPEATABLE READ",
        "EXPECTED_RULE",
        "UNGENERATED_PAST_OCCURRENCES",
        "nenhuma migration",
        "92 dias",
        "2000 eventos",
        "`historicalRisk`",
        "`anchored`",
        "`evaluatedDays`",
        "`days` (1–92)",
    ):
        assert required in ADR, required


def test_risk_only_evaluates_anchored_days_on_each_side_of_the_reference() -> None:
    code = _code(DOMAIN)
    assert "d.anchored and d.projected" in code
    assert "d.anchored and not d.projected" in code
    assert (
        "FinancialCashFlowIssueCode.OPENING_BALANCE_AFTER_WINDOW_START: (\n"
        "        FinancialCashFlowIssueSeverity.INCOMPLETE"
    ) in code
