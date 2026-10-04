from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTE = (ROOT / "apps/api/app/api/routes/finance.py").read_text(encoding="utf-8")
STORE = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence"
    / "financial_movement_allocation_store.py"
).read_text(encoding="utf-8")


def test_allocation_surface_has_no_in_place_or_destructive_verbs() -> None:
    verbs = re.findall(r"@router\.(patch|put|delete)\(", ROUTE)
    assert verbs == []


def test_routes_use_the_service_boundary_and_never_the_stores() -> None:
    assert "FinancialCategoryStore(" not in ROUTE
    assert "FinancialMovementAllocationStore(" not in ROUTE
    assert "app.state.financial_core" not in ROUTE
    for method in (
        "list_categories",
        "create_category",
        "get_current_allocation",
        "list_current_allocations",
        "create_allocation",
        "revise_allocation",
    ):
        assert f"_service(request).{method}(" in ROUTE


def test_bulk_current_read_is_one_joined_statement_not_a_per_movement_loop() -> None:
    start = STORE.index("def list_current_allocation_sets(")
    end = STORE.index("def list_allocation_history(")
    body = STORE[start:end]
    assert body.count("connection.execute(") == 1
    assert "_set_record(" not in body
    assert ".exists()" in body
    assert "_grouped_set_records(rows)" in body
