from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTE = (ROOT / "apps/api/app/api/routes/finance_categorization.py").read_text(
    encoding="utf-8"
)
SERVICE = (ROOT / "apps/api/app/services/financial_categorization.py").read_text(
    encoding="utf-8"
)
MAIN = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")


def test_rule_surface_has_no_in_place_or_destructive_verbs() -> None:
    assert re.findall(r"@router\.(patch|put|delete)\(", ROUTE) == []
    posts = re.findall(r'@router\.post\(\s*"([^"]+)"', ROUTE)
    assert posts == [
        "/categorization-rules",
        "/categorization-rules/{rule_id}/disable",
        "/accounts/{account_id}/categorization-rules/preview",
        "/accounts/{account_id}/categorization-rules/apply",
    ]
    gets = re.findall(r'@router\.get\(\s*"([^"]+)"', ROUTE)
    assert gets == [
        "/categorization-rules",
        "/accounts/{account_id}/categorization-rules/origins",
    ]


def test_routes_use_the_service_boundary_and_never_the_stores() -> None:
    assert "FinancialCategorizationRuleStore(" not in ROUTE
    assert "app.state.financial_categorization" not in ROUTE
    for method in (
        "list_rules",
        "create_rule",
        "disable_rule",
        "preview",
        "apply",
        "list_rule_origins",
    ):
        assert f"_service(request).{method}(" in ROUTE
    assert "financial_categorization" in MAIN
    assert "finance_categorization_router" in MAIN


def test_request_models_are_closed_and_v1_only() -> None:
    assert ROUTE.count('extra="forbid"') >= 3
    for forbidden in (
        "regex",
        "fuzzy",
        "amount_min",
        "amount_max",
        "merchant",
        "pluggy",
    ):
        assert forbidden not in ROUTE.lower()


def test_preview_is_read_only_and_apply_is_never_retried() -> None:
    preview = SERVICE.split("def preview(")[1].split("def apply(")[0]
    for write in (
        "apply_rule_to_movement",
        "create_rule",
        "disable_rule",
        "create_allocation_set",
        "revise_allocation_set",
    ):
        assert write not in preview
    apply = SERVICE.split("def apply(")[1].split("def _owned_active_account")[0]
    assert apply.count("apply_rule_to_movement(") == 1
    assert "while " not in apply and "retry" not in apply.lower()
    assert "FAILED" in apply


def test_service_never_contains_a_financial_decision_the_store_owns() -> None:
    # Matching, priority and eligibility live in the finance domain package.
    for token in ("casefold", "normalize", ".priority", "max("):
        assert token not in SERVICE.replace("evaluate_movement_categorization", "")
    assert "evaluate_movement_categorization(" in SERVICE
    assert "usable_categorization_rules(" in SERVICE
    assert "float(" not in SERVICE and "float(" not in ROUTE
