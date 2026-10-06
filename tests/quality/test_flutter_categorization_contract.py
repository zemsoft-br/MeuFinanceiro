from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "apps/app/lib/features/finance"
API = (FINANCE / "financial_categorization_rules_api.dart").read_text(encoding="utf-8")
CONTROLLER = (FINANCE / "financial_categorization_controller.dart").read_text(
    encoding="utf-8"
)
DIALOG = (FINANCE / "financial_categorization_apply_dialog.dart").read_text(
    encoding="utf-8"
)
SCREEN = (FINANCE / "financial_categorization_rules_screen.dart").read_text(
    encoding="utf-8"
)
DETAIL = (FINANCE / "financial_account_detail_screen.dart").read_text(encoding="utf-8")
CORE_CONTROLLER = (FINANCE / "financial_core_controller.dart").read_text(
    encoding="utf-8"
)
ALL = {
    "api": API,
    "controller": CONTROLLER,
    "dialog": DIALOG,
    "screen": SCREEN,
}


def test_no_floating_point_or_provider_semantics_in_the_rule_client() -> None:
    for name, source in ALL.items():
        assert not re.search(r"\b(double|num)\b", source), name
        assert "toDouble" not in source and "parseDouble" not in source, name
        lowered = source.lower()
        for forbidden in ("pluggy", "provideritem", "provider_item"):
            assert forbidden not in lowered, (name, forbidden)


def test_the_client_never_matches_ranks_or_decides() -> None:
    # Matching, normalization, priority and eligibility are server authority.
    for name, source in ALL.items():
        for forbidden in (
            "casefold",
            "toLowerCase().contains",
            ".priority >",
            "sort((",
        ):
            if name == "screen" and forbidden == "sort((":
                continue  # alphabetical ordering of dropdown labels only
            assert forbidden not in source, (name, forbidden)
    assert "applicableItems" in API
    assert "status == FinancialCategorizationPreviewStatus.matched" in API


def test_writes_are_sent_once_and_never_retried_automatically() -> None:
    for name, source in ALL.items():
        assert "Timer(" not in source and "Timer.periodic" not in source, name
        assert not re.search(r"\bwhile\s*\(", source), name
        assert "Future.delayed" not in source, name
    apply = CONTROLLER.split("Future<void> apply()")[1].split("void reset()")[0]
    assert apply.count("applyCategorizationRules(") == 1
    assert "unknownOutcome" in apply
    assert "if (!state.canApply) return;" in apply


def test_ui_has_no_edit_undo_or_optimistic_success_for_rules() -> None:
    for token in ("Editar regra", "Desfazer", "undo"):
        assert token not in SCREEN and token not in DIALOG
    assert "disableCategorizationRule" in CONTROLLER
    for verb in ("client.put(", "client.patch(", "client.delete("):
        assert verb not in API
    # Only the backend response ever becomes visible state.
    create = CONTROLLER.split("Future<FinancialMutationOutcome> createRule(")[1].split(
        "Future<FinancialMutationOutcome> disableRule("
    )[0]
    assert create.index("createCategorizationRule(") < create.index("_withRule(")


def test_provenance_is_evidence_only_and_read_in_bulk() -> None:
    assert "listRuleOrigins(accountId)" in CORE_CONTROLLER
    assert CORE_CONTROLLER.count("listRuleOrigins(") == 1
    assert "ruleOriginsBySetId.containsKey(" in DETAIL
    assert "allocation.allocationSetId" in DETAIL
    # a rule label never replaces or mutates the authoritative classification
    assert "classifyMovement" not in DIALOG and "reviseMovement" not in DIALOG


def test_apply_confirmation_and_summary_are_backend_driven() -> None:
    assert "Confirmar e aplicar" in DIALOG
    assert "Resultado parcial" in DIALOG and "Concluído" in DIALOG
    assert "isFullSuccess" in DIALOG
    assert "ref.listen<FinancialCategorizationApplyState>" in DIALOG
    assert "barrierDismissible: false" in DETAIL
