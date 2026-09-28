from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOVEMENTS = (
    ROOT / "packages/finance/src/meufinanceiro_finance/movements.py"
).read_text(encoding="utf-8")
ADR = (ROOT / "docs/adr/0019-canonical-movement-append-only-ledger.md").read_text(
    encoding="utf-8"
)


def test_movement_has_one_signed_money_effect_and_no_pending_state() -> None:
    assert "amount: Money" in MOVEMENTS
    assert "FinancialResultEffect" in MOVEMENTS
    assert 'INCOME = "INCOME"' in MOVEMENTS
    assert 'EXPENSE = "EXPENSE"' in MOVEMENTS
    assert 'NEUTRAL = "NEUTRAL"' in MOVEMENTS
    assert "Movement amount must not be zero" in MOVEMENTS
    for forbidden in (
        "credit_debit",
        "debit_credit",
        "pending",
        "balance",
    ):
        assert forbidden not in MOVEMENTS.lower()


def test_income_expense_and_neutral_sign_rules_are_explicit() -> None:
    assert "INCOME Movement amount must be positive" in MOVEMENTS
    assert "EXPENSE Movement amount must be negative" in MOVEMENTS
    assert "result_effect is FinancialResultEffect.INCOME" in MOVEMENTS
    assert "result_effect is FinancialResultEffect.EXPENSE" in MOVEMENTS
    assert "NEUTRAL" in ADR


def test_cash_and_competence_dates_are_separate_and_explicit() -> None:
    assert "effective_date: date" in MOVEMENTS
    assert "competence_date: date" in MOVEMENTS
    assert '_require_plain_date(self.effective_date, "effective_date")' in MOVEMENTS
    assert '_require_plain_date(self.competence_date, "competence_date")' in MOVEMENTS
    assert "não define default silencioso" in ADR


def test_movement_has_no_independent_acl_or_category_link() -> None:
    draft = MOVEMENTS.split("class FinancialMovementDraft", maxsplit=1)[1].split(
        "class FinancialMovementReversalDraft", maxsplit=1
    )[0]
    for forbidden in (
        "owner_operator_id",
        "visibility_scope",
        "grant",
        "category_id",
    ):
        assert forbidden not in draft
    assert "Audiência herdada da conta" in ADR
    assert "Sua audiência é a audiência da conta financeira" in ADR


def test_reversal_command_cannot_supply_original_financial_effect() -> None:
    reversal = MOVEMENTS.split(
        "class FinancialMovementReversalDraft",
        maxsplit=1,
    )[1].split("def _validate_standard_amount", maxsplit=1)[0]
    assert "movement_id: UUID" in reversal
    assert "effective_date: date" in reversal
    assert "competence_date: date" in reversal
    assert "reason: str" in reversal
    for forbidden in (
        "amount:",
        "account_id:",
        "currency:",
        "result_effect:",
    ):
        assert forbidden not in reversal
    assert "amount exatamente oposto" in ADR


def test_contract_is_provider_and_persistence_neutral() -> None:
    lowered = MOVEMENTS.lower()
    for forbidden in (
        "sqlalchemy",
        "fastapi",
        "httpx",
        "pluggy",
        "external_resource_id",
        "fitid",
        "provider",
    ):
        assert forbidden not in lowered


def test_transfer_is_documented_as_two_neutral_movements_not_implemented_here() -> None:
    assert "dois Movements `NEUTRAL`" in ADR
    assert "transfer_id" in ADR
    assert "transfer_id" not in MOVEMENTS
