from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
MANUAL_ENTRIES = (FINANCE / "manual_entries.py").read_text(encoding="utf-8")
FINANCE_PUBLIC = (FINANCE / "__init__.py").read_text(encoding="utf-8")
ARCHITECTURE = (ROOT / "docs/architecture/FINANCIAL_MOVEMENTS.md").read_text(
    encoding="utf-8"
)


def test_manual_entries_map_positive_magnitude_to_existing_signed_ledger() -> None:
    assert "class FinancialManualEntryType(StrEnum)" in MANUAL_ENTRIES
    assert 'INCOME = "INCOME"' in MANUAL_ENTRIES
    assert 'EXPENSE = "EXPENSE"' in MANUAL_ENTRIES
    assert "if self.magnitude.amount <= 0:" in MANUAL_ENTRIES
    assert "manual entry magnitude must be positive" in MANUAL_ENTRIES
    assert "amount = self.magnitude" in MANUAL_ENTRIES
    assert "amount = -self.magnitude" in MANUAL_ENTRIES
    assert "FinancialResultEffect.INCOME" in MANUAL_ENTRIES
    assert "FinancialResultEffect.EXPENSE" in MANUAL_ENTRIES
    assert "FinancialMovementDraft(" in MANUAL_ENTRIES


def test_manual_entry_service_uses_only_the_append_only_movement_boundary() -> None:
    assert "class FinancialManualEntryMovementStore(Protocol)" in MANUAL_ENTRIES
    assert "def create_movement(" in MANUAL_ENTRIES
    assert "self._store.create_movement(" in MANUAL_ENTRIES
    assert "validate_financial_idempotency_key(idempotency_key)" in MANUAL_ENTRIES

    lowered = MANUAL_ENTRIES.lower()
    assert '"finance.movements"' not in MANUAL_ENTRIES
    assert "'finance.movements'" not in MANUAL_ENTRIES

    for forbidden in (
        "sqlalchemy",
        "meufinanceiro_persistence",
        "update_movement",
        "delete_movement",
        "upsert_movement",
        "category_id",
        "transfer_id",
        "pluggy",
        "fastapi",
    ):
        assert forbidden not in lowered


def test_manual_entry_contract_is_public_and_redacts_financial_material() -> None:
    for exported in (
        "FinancialManualEntryDraft",
        "FinancialManualEntryMovementStore",
        "FinancialManualEntryService",
        "FinancialManualEntryType",
    ):
        assert exported in FINANCE_PUBLIC

    assert "<magnitude-account-dates-description-redacted>" in MANUAL_ENTRIES


def test_manual_entries_are_documented_as_a_use_case_not_a_second_ledger() -> None:
    assert "Entrada manual de receita e despesa" in ARCHITECTURE
    assert "magnitude positiva" in ARCHITECTURE
    assert "exatamente um `Movement` `STANDARD`" in ARCHITECTURE
    assert "não cria outra tabela" in ARCHITECTURE
