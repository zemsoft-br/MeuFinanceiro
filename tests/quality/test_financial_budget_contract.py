from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
DOMAIN = (FINANCE / "budgets.py").read_text(encoding="utf-8")
SCHEMA = (PERSISTENCE / "financial_budget_schema.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "financial_budget_store.py").read_text(encoding="utf-8")
MIGRATION = (PERSISTENCE / "migrations/versions/0023_monthly_budgets.py").read_text(
    encoding="utf-8"
)
MOVEMENT_SCHEMA = (PERSISTENCE / "financial_movement_schema.py").read_text(
    encoding="utf-8"
)


def _code(source: str) -> str:
    """Source without docstrings and comments, so prose never trips a contract."""
    without_docstrings = re.sub(r'"""[\s\S]*?"""', "", source)
    return re.sub(r"(?m)^\s*#.*$", "", without_docstrings)


def test_budget_domain_is_provider_and_persistence_neutral() -> None:
    lowered = _code(DOMAIN).lower()
    for forbidden in (
        "sqlalchemy",
        "meufinanceiro_persistence",
        "pluggy",
        "fastapi",
        "provider_",
        "float(",
        ": float",
    ):
        assert forbidden not in lowered, forbidden


def test_the_ledger_never_learns_about_budgets() -> None:
    lowered = MOVEMENT_SCHEMA.lower()
    for forbidden in ("budget", "planned", "category_id"):
        assert forbidden not in lowered, forbidden
    assert "ALTER TABLE finance.movements" not in MIGRATION


def test_budget_tables_hold_planning_only() -> None:
    columns = set(re.findall(r'Column\(\s*"(\w+)"', SCHEMA))
    for forbidden in (
        "balance",
        "realized",
        "remaining",
        "movement_id",
        "account_id",
        "spent",
        "progress",
    ):
        assert forbidden not in columns, forbidden
    assert "planned_amount" in columns


def test_the_budget_store_never_touches_the_ledger_or_classification() -> None:
    code = _code(STORE)
    for forbidden in (
        "financial_movements",
        "financial_movement_allocation",
        "movement_allocation",
        "financial_audit",
    ):
        assert forbidden not in code, forbidden


def test_money_is_decimal_never_float_in_schema_and_store() -> None:
    for source in (SCHEMA, STORE):
        lowered = _code(source).lower()
        assert "float(" not in lowered
        assert "double" not in lowered
    assert "Numeric(24, 8)" in SCHEMA
    assert "numeric(24, 8)" in MIGRATION


def test_migration_is_forced_rls_cas_and_never_grants_delete() -> None:
    assert 'down_revision: str | None = "0022_pending_movement_indexes"' in MIGRATION
    for table in ("budgets", "budget_lines"):
        assert f"ALTER TABLE finance.{table} ENABLE ROW LEVEL SECURITY" in MIGRATION
        assert f"ALTER TABLE finance.{table} FORCE ROW LEVEL SECURITY" in MIGRATION
    grants = re.findall(r"GRANT [^\n\"]*", MIGRATION)
    assert grants
    for grant in grants:
        assert "DELETE" not in grant.upper(), grant
        assert "TRUNCATE" not in grant.upper(), grant
    assert (
        "GRANT UPDATE (name, version, updated_at, updated_by_operator_id)" in MIGRATION
    )
    assert "CONSTRAINT TRIGGER trg_finance_validate_budget_closure" in MIGRATION
    assert "SECURITY DEFINER" not in MIGRATION


def test_the_store_has_cas_and_idempotent_create_and_no_delete() -> None:
    code = _code(STORE)
    assert "def create_budget" in code and "def replace_budget" in code
    assert "budgets.c.version == replacement.expected_version" in code
    assert "on_conflict_do_nothing" in code
    assert "delete(" not in code and ".delete(" not in code
    assert "retry" not in code.lower()
