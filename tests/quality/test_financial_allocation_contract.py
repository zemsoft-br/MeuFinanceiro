from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
DOMAIN = (FINANCE / "allocations.py").read_text(encoding="utf-8")
RECORDS = (FINANCE / "allocation_records.py").read_text(encoding="utf-8")
FINANCE_PUBLIC = (FINANCE / "__init__.py").read_text(encoding="utf-8")
MOVEMENT_SCHEMA = (PERSISTENCE / "financial_movement_schema.py").read_text(
    encoding="utf-8"
)
ADR = (ROOT / "docs/adr/0022-movement-classification-and-allocation.md").read_text(
    encoding="utf-8"
)


def test_allocation_domain_remains_provider_and_persistence_neutral() -> None:
    for source in (DOMAIN, RECORDS):
        lowered = source.lower()
        for forbidden in (
            "sqlalchemy",
            "meufinanceiro_persistence",
            "pluggy",
            "fastapi",
            "provider_item_id",
            "external_resource_id",
        ):
            assert forbidden not in lowered


def test_movement_ledger_does_not_gain_category_or_allocation_authority() -> None:
    lowered = MOVEMENT_SCHEMA.lower()
    assert "category_id" not in lowered
    assert "allocation_id" not in lowered
    assert "allocation_set_id" not in lowered
    assert "current_allocation" not in lowered
    assert "não recebe `category_id`" in ADR


def test_allocation_contract_uses_money_and_order_independent_material() -> None:
    assert "amount: Money" in DOMAIN
    assert "canonical_amount" in DOMAIN
    assert "category_id.hex" in DOMAIN
    assert "canonical_material" in DOMAIN
    assert "allocation amounts must share the same sign" in DOMAIN
    assert "allocation currencies must match" in DOMAIN
    assert "allocation categories must be unique" in DOMAIN
    assert "float(" not in DOMAIN
    assert "float" not in RECORDS.lower()


def test_audience_compatibility_is_explicit_and_fail_closed() -> None:
    assert "is_category_audience_compatible_for_movement" in DOMAIN
    assert "FinancialVisibilityScope.HOUSEHOLD" in DOMAIN
    assert "FinancialVisibilityScope.PERSONAL" in DOMAIN
    assert "SHARED and HOUSEHOLD Movements" in DOMAIN
    assert "return False" in DOMAIN
    assert "audiência igual ou mais ampla" in ADR


def test_revision_contract_is_append_only_and_public() -> None:
    assert "FinancialMovementAllocationRevisionDraft" in DOMAIN
    assert "supersedes_id" in DOMAIN
    assert "FinancialMovementAllocationSetRecord" in RECORDS
    assert "FinancialMovementAllocationDraft" in FINANCE_PUBLIC
    assert "FinancialMovementAllocationRevisionDraft" in FINANCE_PUBLIC
    assert "FinancialMovementAllocationSetDraft" in FINANCE_PUBLIC
    assert "FinancialMovementAllocationSetRecord" in FINANCE_PUBLIC
    assert "não executa UPDATE/DELETE" in ADR
