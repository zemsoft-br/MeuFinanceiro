from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLUTTER = ROOT / "apps/app/lib"
API = (FLUTTER / "features/finance/financial_core_api.dart").read_text(encoding="utf-8")
CONTROLLER = (FLUTTER / "features/finance/financial_core_controller.dart").read_text(
    encoding="utf-8"
)
LIST_SCREEN = (FLUTTER / "features/finance/financial_accounts_screen.dart").read_text(
    encoding="utf-8"
)
CREATE_SCREEN = (
    FLUTTER / "features/finance/financial_account_create_screen.dart"
).read_text(encoding="utf-8")
DETAIL_SCREEN = (
    FLUTTER / "features/finance/financial_account_detail_screen.dart"
).read_text(encoding="utf-8")
ROUTES = (FLUTTER / "routing/app_routes.dart").read_text(encoding="utf-8")
ROUTER = (FLUTTER / "routing/app_router.dart").read_text(encoding="utf-8")


def test_financial_flutter_money_contract_never_uses_double() -> None:
    combined = API + CONTROLLER + LIST_SCREEN + CREATE_SCREEN + DETAIL_SCREEN
    assert "double.parse" not in combined
    assert "double.tryParse" not in combined
    assert "double " not in API
    assert "final String amount;" in API
    assert "money must use string fields" in API
    assert "_moneyPattern" in API
    assert "_zeroMoneyPattern" in API


def test_financial_flutter_parser_is_fail_closed_and_provider_neutral() -> None:
    assert "_strictMap" in API
    assert "values.length != allowedKeys.length" in API
    assert "_financialResourceIdPattern" in API
    assert "_currencyPattern" in API
    assert "_timezoneSuffixPattern" in API
    assert "financial account identity mismatch" in API
    assert "opening balance account mismatch" in API
    assert "movement account mismatch" in API
    assert "financial movement identity mismatch" in API
    for forbidden in (
        "pluggy",
        "provideritem",
        "provider_item",
        "externalresource",
        "external_resource",
        "clientuserid",
        "client_user",
    ):
        assert forbidden not in API.lower()


def test_financial_flutter_uses_current_riverpod_notifier_family_shape() -> None:
    assert (
        re.search(
            r"NotifierProvider\s*\.\s*autoDispose\s*\.\s*family",
            CONTROLLER,
        )
        is not None
    )
    assert "extends Notifier<FinancialAccountDetailState>" in CONTROLLER
    assert "FinancialAccountDetailController(this.accountId)" in CONTROLLER
    assert "FamilyNotifier" not in CONTROLLER
    assert "AutoDisposeNotifier" not in CONTROLLER
    assert (
        re.search(
            r"NotifierProvider\s*\.\s*autoDispose\s*<\s*"
            r"FinancialAccountsController\s*,\s*FinancialAccountsState\s*>",
            CONTROLLER,
        )
        is not None
    )


def test_detail_controller_revalidates_currency_across_resources() -> None:
    assert "openingBalance.money.currency != account.currency" in CONTROLLER
    assert "balance.currency != account.currency" in CONTROLLER
    assert "statement.currency != account.currency" in CONTROLLER
    assert "entry.movement.money.currency != account.currency" in CONTROLLER
    assert "opening balance currency mismatch" in CONTROLLER
    assert "balance account mismatch" in CONTROLLER
    assert "statement account mismatch" in CONTROLLER


def test_financial_flutter_exposes_semantic_commands_without_generic_writer() -> None:
    assert "createManualEntry" in API
    assert "reverseMovement" in API
    assert "createTransfer" in API
    assert "createManualEntry" in CONTROLLER
    assert "reverseMovement" in CONTROLLER
    assert "createTransfer" in CONTROLLER
    for required in (
        "Nova receita",
        "Nova despesa",
        "Transferir",
        "Reverter lançamento",
    ):
        assert required in DETAIL_SCREEN
    assert "finance/movements/$id/reversal" in API
    assert "finance/transfers" in API
    assert "POST /finance/movements" not in API




def test_financial_flutter_does_not_require_opening_balance_for_commands() -> None:
    assert "state.openingBalance != null" not in DETAIL_SCREEN
    assert "Informe o saldo inicial para liberar novas operações" not in DETAIL_SCREEN
def test_financial_flutter_uses_backend_derived_balance_and_statement() -> None:
    assert "getBalance" in API
    assert "getStatement" in API
    assert "currentBalance" in API
    assert "balanceAfter" in API
    assert "await api.getBalance(accountId)" in CONTROLLER
    assert "await api.getStatement(accountId)" in CONTROLLER
    assert "_moneyLabel(balance.currentBalance)" in DETAIL_SCREEN
    assert "_moneyLabel(entry.balanceAfter)" in DETAIL_SCREEN
    assert "Saldo inicial não informado" in DETAIL_SCREEN
    assert "não significa saldo zero" in DETAIL_SCREEN


def test_financial_flutter_preserves_transfer_atomicity_in_reversal_ui() -> None:
    assert "movement.resultEffect != FinancialResultEffect.neutral" in DETAIL_SCREEN
    assert "reverseTransfer" not in DETAIL_SCREEN
    assert "reverseTransfer" not in CONTROLLER
    assert "perna" not in DETAIL_SCREEN.lower()


def test_financial_flutter_generates_uuid_v4_idempotency_keys() -> None:
    assert "_newUuidV4" in API
    assert "(bytes[6] & 0x0f) | 0x40" in API
    assert "(bytes[8] & 0x3f) | 0x80" in API
    assert "_idempotencyKey(idempotencyKey ?? _newUuidV4())" in API


def test_financial_routes_are_under_app_namespace_and_select_finance_destination() -> (
    None
):
    assert "static const financePath = '/app/financas'" in ROUTES
    assert (
        "static const financeAccountCreatePath = '/app/financas/contas/nova'" in ROUTES
    )
    assert (
        "static const financeAccountDetailPath = '/app/financas/contas/:accountId'"
        in ROUTES
    )
    assert "destination.id == AppRouteId.finance" in ROUTES
    assert "FinancialAccountsScreen" in ROUTER
    assert "FinancialAccountCreateScreen" in ROUTER
    assert "FinancialAccountDetailScreen" in ROUTER


def test_account_creation_sends_only_declared_wire_fields() -> None:
    create_input = API.split("class FinancialAccountCreateInput", 1)[1].split(
        "class FinancialOpeningBalanceCreateInput", 1
    )[0]
    for required in (
        "'name'",
        "'accountType'",
        "'customTypeName'",
        "'currency'",
        "'visibilityScope'",
    ):
        assert required in create_input
    for forbidden in (
        "ownerOperatorId",
        "residenceId",
        "installationId",
        "operatorId",
        "balance",
        "status",
    ):
        assert forbidden not in create_input


def test_financial_ui_uses_only_existing_design_tokens() -> None:
    combined = LIST_SCREEN + CREATE_SCREEN + DETAIL_SCREEN
    assert "AppTokens.space6" not in combined
    assert "AppTokens.space20" in combined
    assert "AppTokens.radiusMedium" in combined
