from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "apps/app/lib/features/finance"
API = (FINANCE / "financial_pending_api.dart").read_text(encoding="utf-8")
CONTROLLER = (FINANCE / "financial_pending_controller.dart").read_text(encoding="utf-8")
SCREEN = (FINANCE / "financial_pending_screen.dart").read_text(encoding="utf-8")
ROUTES = (ROOT / "apps/app/lib/routing/app_routes.dart").read_text(encoding="utf-8")
ROUTER = (ROOT / "apps/app/lib/routing/app_router.dart").read_text(encoding="utf-8")
ALL = {"api": API, "controller": CONTROLLER, "screen": SCREEN}


def test_no_floating_point_or_provider_semantics_in_the_inbox_client() -> None:
    for name, source in ALL.items():
        assert not re.search(r"\b(double|num)\b", source), name
        assert "toDouble" not in source and "parseDouble" not in source, name
        lowered = source.lower()
        for forbidden in ("pluggy", "provideritem", "provider_item"):
            assert forbidden not in lowered, (name, forbidden)


def test_the_client_never_derives_pendency_matches_or_ranks() -> None:
    # What is pending, which rule wins and what the suggestion is stay with the
    # backend; the client only displays and pages.
    for name, source in ALL.items():
        for forbidden in ("casefold", "toLowerCase", ".priority", "sort(", ".sort"):
            assert forbidden not in source, (name, forbidden)
    assert "matchedRuleId" in API and "suggestedCategoryId" in API
    # A suggestion only exists for MATCHED: the shape is validated, never guessed.
    assert "pending suggestion shape is invalid" in API


def test_the_inbox_read_is_get_only_and_keyset_paged() -> None:
    assert API.count("client.get(") == 1
    for verb in ("client.post(", "client.put(", "client.patch(", "client.delete("):
        assert verb not in API
    assert "finance/pending-movements?" in API
    for param in ("limit=", "cursor=", "accountId=", "resultEffect=", "ruleStatus="):
        assert param in API
    for forbidden in ("offset", "page=", "search"):
        assert forbidden not in API.lower()
    assert "financialPendingPageLimitMax = 100" in API


def test_no_request_per_row_and_no_hidden_polling() -> None:
    for name, source in ALL.items():
        assert "Timer(" not in source and "Timer.periodic" not in source, name
        assert "Future.delayed" not in source, name
        assert not re.search(r"\bwhile\s*\(", source), name
    # Loading is a fixed set of reads; nothing iterates items to fetch more.
    load = CONTROLLER.split("Future<void> _loadFirst(")[1]
    assert load.count("listPendingMovements(") == 1
    assert load.count("listCategories()") == 1
    assert load.count("listAccounts()") == 1
    for fetch in ("getAccount(", "getMovementAllocation", "listCategorizationRules"):
        assert fetch not in CONTROLLER


def test_writes_reuse_the_canonical_endpoints_once_and_never_retry() -> None:
    assert CONTROLLER.count(".applyCategorizationRules(") == 1
    assert CONTROLLER.count(".createMovementAllocation(") == 1
    assert "reviseMovementAllocation" not in CONTROLLER
    # Every write answer ends in the one canonical re-read.
    apply = CONTROLLER.split("Future<FinancialPendingActionResult> applySuggestion(")[
        1
    ].split("Future<FinancialPendingActionResult> classify(")[0]
    assert apply.count("_reconcile(") >= 2
    assert apply.index("applyCategorizationRules(") < apply.index("_reconcile(")
    classify = CONTROLLER.split("Future<FinancialPendingActionResult> classify(")[
        1
    ].split("bool _canWrite(")[0]
    assert classify.index("createMovementAllocation(") < classify.index("_reconcile(")


def test_nothing_leaves_the_list_before_a_canonical_read() -> None:
    for token in ("removeWhere", "items.where(", "items.remove", ".removeAt("):
        assert token not in CONTROLLER, token
    # The list is only ever replaced by a server page (or appended with one).
    assert CONTROLLER.count("items: page.items") >= 2
    assert "if (!known.contains(item.movementId)) item" in CONTROLLER


def test_a_rule_is_applied_only_after_an_explicit_confirmation() -> None:
    apply = SCREEN.split("Future<void> _apply(")[1].split("Future<void> _classify(")[0]
    assert apply.index("showDialog<bool>") < apply.index("applySuggestion(")
    assert "if (confirmed != true || !mounted) return;" in apply
    # Ambiguous items never carry a rule, so no apply action exists for them.
    assert "if (item.hasSuggestion)" in SCREEN
    assert (
        "bool get hasSuggestion => ruleStatus == FinancialPendingRuleStatus.matched"
        in API
    )
    assert "item.matchedRuleId == null" in CONTROLLER


def test_the_screen_never_talks_to_the_network_and_is_routed() -> None:
    assert "authenticatedApiClientProvider" not in SCREEN
    assert "client." not in SCREEN
    assert "financePendingPath = '/app/financas/pendencias'" in ROUTES
    assert "FinancialPendingScreen()" in ROUTER
