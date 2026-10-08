from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
API = ROOT / "apps/api/app"
DOMAIN = (FINANCE / "goals.py").read_text(encoding="utf-8")
SCHEMA = (PERSISTENCE / "financial_goal_schema.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "financial_goal_store.py").read_text(encoding="utf-8")
MIGRATION = (PERSISTENCE / "migrations/versions/0028_financial_goals.py").read_text(
    encoding="utf-8"
)
MOVEMENT_SCHEMA = (PERSISTENCE / "financial_movement_schema.py").read_text(
    encoding="utf-8"
)
BALANCE_QUERY = (PERSISTENCE / "financial_balance_transaction.py").read_text(
    encoding="utf-8"
)
ROUTE = (API / "api/routes/finance_goals.py").read_text(encoding="utf-8")
SERVICE = (API / "services/financial_goals.py").read_text(encoding="utf-8")
ADR = (ROOT / "docs/adr/0029-financial-goals-with-virtual-allocation.md").read_text(
    encoding="utf-8"
)
DOC = (ROOT / "docs/architecture/FINANCIAL_GOALS.md").read_text(encoding="utf-8")


def _code(source: str) -> str:
    """Source without docstrings and comments, so prose never trips a contract."""
    without_docstrings = re.sub(r'"""[\s\S]*?"""', "", source)
    return re.sub(r"(?m)^\s*#.*$", "", without_docstrings)


def test_goal_domain_is_provider_and_persistence_neutral() -> None:
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


def test_the_ledger_never_learns_about_goals() -> None:
    lowered = MOVEMENT_SCHEMA.lower()
    for forbidden in ("goal", "allocated", "project"):
        assert forbidden not in lowered, forbidden
    assert "ALTER TABLE finance.movements" not in MIGRATION
    assert "finance.budgets" not in MIGRATION
    assert "INSERT INTO finance.movements" not in MIGRATION


def test_goal_tables_hold_planning_and_events_never_money_authority() -> None:
    columns = set(re.findall(r'Column\(\s*"(\w+)"', SCHEMA))
    for forbidden in (
        "balance",
        "allocated",
        "remaining",
        "saved",
        "progress",
        "movement_id",
        "transfer_id",
        "budget_id",
        "project_id",
    ):
        assert forbidden not in columns, forbidden
    assert {"target_amount", "amount", "kind"} <= columns


def test_the_goal_store_never_writes_the_ledger_or_classification() -> None:
    code = _code(STORE)
    for forbidden in (
        "financial_movements",
        "financial_movement_allocation",
        "financial_budget",
        "financial_transfer",
        "financial_audit",
        "create_standard_movement_in_transaction",
        ".delete(",
        "delete(",
    ):
        assert forbidden not in code, forbidden
    assert "retry" not in code.lower()
    assert "SERIALIZABLE" not in code.upper()


def test_money_is_decimal_never_float_in_schema_and_store() -> None:
    for source in (SCHEMA, STORE):
        lowered = _code(source).lower()
        assert "float(" not in lowered
        assert "double" not in lowered
    assert SCHEMA.count("Numeric(24, 8)") == 2
    assert MIGRATION.count("numeric(24, 8)") >= 2


def test_migration_is_forced_rls_append_only_and_never_grants_delete() -> None:
    assert 'down_revision: str | None = "0027_recurrence_suggestions"' in MIGRATION
    for table in ("goals", "goal_allocation_events"):
        assert f"ALTER TABLE finance.{table} ENABLE ROW LEVEL SECURITY" in MIGRATION
        assert f"ALTER TABLE finance.{table} FORCE ROW LEVEL SECURITY" in MIGRATION
    grants = re.findall(r"GRANT [^\n\"]*", MIGRATION)
    assert grants
    for grant in grants:
        assert "DELETE" not in grant.upper(), grant
        assert "TRUNCATE" not in grant.upper(), grant
    # Events: append-only (no UPDATE grant at all, an UPDATE trigger on top).
    assert "GRANT SELECT, INSERT ON finance.goal_allocation_events" in MIGRATION
    assert "trg_finance_reject_goal_allocation_event_update" in MIGRATION
    assert "BEFORE UPDATE ON finance.goal_allocation_events" in MIGRATION
    # Goals: only the planning columns move.
    assert (
        "GRANT UPDATE (title, description, target_amount, target_date, version, "
        in MIGRATION
    )
    assert "SECURITY DEFINER" not in MIGRATION
    assert "BYPASSRLS" not in MIGRATION.upper()


def test_the_account_lock_is_shared_by_the_store_and_the_event_trigger() -> None:
    assert "meufinanceiro:goal-account:" in MIGRATION
    assert "meufinanceiro:goal-account:" in STORE
    assert "pg_advisory_xact_lock" in STORE
    assert "pg_advisory_xact_lock" in MIGRATION
    # The lock is taken before the canonical balance is read.
    allocate = STORE[STORE.index("    def allocate(") :]
    assert allocate.index("_lock_account(") < allocate.index("_require_availability(")
    # Nothing in the ledger path takes it: goals can never block Movements.
    movement_store = (PERSISTENCE / "financial_movement_store.py").read_text(
        encoding="utf-8"
    )
    assert "goal-account" not in movement_store
    assert "pg_advisory" not in movement_store


def test_availability_reuses_the_canonical_balance_and_does_not_aggregate_movements() -> (
    None
):
    code = _code(STORE)
    assert "read_account_balance_in_transaction(" in code
    assert "require_allocation_within_availability(" in code
    for forbidden in ("financial_movements", "movements.c.amount", "opening_balance"):
        assert forbidden not in code, forbidden
    balance = _code(BALANCE_QUERY)
    assert "derive_financial_account_balance_and_statement(" in balance
    assert "get_opening_balance_in_transaction(" in balance
    assert "list_account_movements_in_transaction(" in balance
    # The trigger is structural only: it must not re-implement the balance in SQL.
    assert "finance.movements" not in MIGRATION
    assert "account_opening_balances" not in MIGRATION


def test_the_store_has_cas_idempotency_and_bounded_reads() -> None:
    code = _code(STORE)
    assert "goals.c.version == replacement.expected_version" in code
    assert code.count("on_conflict_do_nothing") == 2
    assert 'isolation_level="REPEATABLE READ"' in code
    assert "postgresql_readonly=True" in code
    assert "GOAL_LIST_MAX" in code and "GOAL_EVENTS_MAX" in code
    assert ".limit(GOAL_LIST_MAX + 1)" in code and ".limit(GOAL_EVENTS_MAX + 1)" in code


def test_the_route_has_exactly_the_goal_endpoints_and_no_delete_or_patch() -> None:
    routes = re.findall(r'^@router\.(\w+)\(\s*"([^"]+)"', ROUTE, re.M)
    assert sorted(routes) == sorted(
        [
            ("get", "/goals"),
            ("post", "/goals"),
            ("get", "/goals/{goal_id}"),
            ("put", "/goals/{goal_id}"),
            ("get", "/goals/{goal_id}/summary"),
            ("post", "/goals/{goal_id}/allocations"),
        ]
    )
    assert "@router.delete" not in ROUTE and "@router.patch" not in ROUTE


def test_request_models_are_strict_and_money_travels_as_text() -> None:
    models = ROUTE.split("class GoalCreateRequest")[1].split("class GoalResponse")[0]
    assert models.count('extra="forbid"') == 3
    assert "float" not in _code(ROUTE)
    assert "target_amount: str" in models and "amount: str" in models
    assert "owner_operator_id" not in models  # the payload never picks the owner
    assert "residence" not in models.lower()  # nor the residence


def test_service_and_route_do_not_own_financial_arithmetic() -> None:
    for source in (SERVICE, ROUTE):
        code = _code(source)
        for forbidden in (
            "float(",
            "financial_movements",
            "quantize(",
            "get_balance",
            "balance_query",
        ):
            assert forbidden not in code, forbidden
    assert "summarize_goal(" in _code(SERVICE)
    assert "can_edit_goal(" in _code(SERVICE)


def test_errors_are_mapped_to_sanitized_statuses() -> None:
    for status in ("401", "403", "404", "409", "422", "503"):
        assert (
            f"HTTP_{status}" in ROUTE
            or status in {"401", "422"}  # 401 is the auth dependency, 422 is shape
        )
    assert "HTTP_403_FORBIDDEN" in ROUTE and "HTTP_503_SERVICE_UNAVAILABLE" in ROUTE
    assert "str(error)" not in ROUTE and "repr(error)" not in ROUTE


def test_adr_and_architecture_document_the_decision() -> None:
    for term in (
        "destinação virtual",
        "append-only",
        "pg_advisory_xact_lock",
        "derive_financial_account_balance_and_statement",
        "INSUFFICIENT",
        "expectedVersion",
        "SHARED",
        "RLS",
        "FORCE",
        "dinheiro bloqueado",
    ):
        assert term in ADR or term in DOC, term
    assert "ADR-0029" in DOC
    assert "FINANCIAL_GOALS.md" in ADR
    adr_index = (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")
    assert "0029-financial-goals-with-virtual-allocation.md" in adr_index
    roadmap = (ROOT / "docs/ROADMAP.md").read_text(encoding="utf-8")
    assert "#260" in roadmap
    # The stale status of #256 stays fixed: PR #257 is merged.
    suggestions = (
        ROOT / "docs/architecture/FINANCIAL_RECURRENCE_SUGGESTIONS.md"
    ).read_text(encoding="utf-8")
    assert "ainda não ocorreram" not in suggestions
    assert "PR #257" in suggestions
    sequence = (ROOT / "docs/architecture/IMPLEMENTATION_SEQUENCE.md").read_text(
        encoding="utf-8"
    )
    assert "ainda sem PR; sugestões derivadas" not in sequence
