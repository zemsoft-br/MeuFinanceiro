from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
DOMAIN = (FINANCE / "transfers.py").read_text(encoding="utf-8")
RECORD = (FINANCE / "transfer_records.py").read_text(encoding="utf-8")
SCHEMA = (PERSISTENCE / "financial_transfer_schema.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "financial_transfer_store.py").read_text(encoding="utf-8")
PUBLIC = (PERSISTENCE / "financial_transfer.py").read_text(encoding="utf-8")
MIGRATION = (
    PERSISTENCE / "migrations/versions/0015_financial_transfers.py"
).read_text(encoding="utf-8")
ADR = (ROOT / "docs/adr/0021-atomic-internal-transfers.md").read_text(
    encoding="utf-8"
)


def test_transfer_domain_is_two_opposite_neutral_movements() -> None:
    assert "FinancialTransferDraft" in DOMAIN
    assert "amount=-self.magnitude" in DOMAIN
    assert "amount=self.magnitude" in DOMAIN
    assert DOMAIN.count("result_effect=FinancialResultEffect.NEUTRAL") == 2
    assert "transfer accounts must be distinct" in DOMAIN
    assert "transfer magnitude must be positive" in DOMAIN


def test_transfer_table_is_relation_not_second_money_ledger() -> None:
    start = MIGRATION.index("CREATE TABLE finance.transfers")
    end = MIGRATION.index("CREATE TABLE finance.transfer_legs", start)
    transfer_table = MIGRATION[start:end].lower()

    assert "source_account_id uuid not null" in transfer_table
    assert "destination_account_id uuid not null" in transfer_table
    assert "amount numeric" not in transfer_table
    assert 'Column("amount"' not in SCHEMA
    assert "current_balance" not in (SCHEMA + STORE).lower()
    assert "cached_balance" not in (SCHEMA + STORE).lower()


def test_transfer_leg_relation_prevents_cross_direction_movement_reuse() -> None:
    assert "CREATE TABLE finance.transfer_legs" in MIGRATION
    assert "direction IN ('SOURCE', 'DESTINATION')" in MIGRATION
    assert "uq_finance_transfer_legs_movement UNIQUE" in MIGRATION
    assert 'UniqueConstraint(\n        "movement_id"' in SCHEMA
    assert "DEFERRABLE INITIALLY DEFERRED" in MIGRATION
    assert "fk_finance_transfer_legs_movement" in MIGRATION


def test_transfer_claim_precedes_links_and_both_movement_legs() -> None:
    assert "uq_finance_transfers_idempotency" in MIGRATION
    assert ".on_conflict_do_nothing(" in STORE
    assert "_transfer_by_idempotency(" in STORE
    assert "meufinanceiro:financial-transfer-operation:v1" in STORE
    assert "hashlib.sha256" in STORE

    claim = STORE.index("pg_insert(financial_transfers)")
    links = STORE.index("_insert_leg_links(", claim)
    first_leg = STORE.index("_insert_standard_leg(", links)
    second_leg = STORE.index("_insert_standard_leg(", first_leg + 1)
    assert claim < links < first_leg < second_leg
    assert "FinancialMovementStore(" not in STORE


def test_transfer_integrity_is_deferred_and_guards_both_legs() -> None:
    assert "validate_transfer_integrity" in MIGRATION
    assert "CREATE CONSTRAINT TRIGGER trg_finance_validate_transfer_integrity" in MIGRATION
    assert "DEFERRABLE INITIALLY DEFERRED" in MIGRATION
    assert "source_row.result_effect IS DISTINCT FROM 'NEUTRAL'" in MIGRATION
    assert "destination_row.result_effect IS DISTINCT FROM 'NEUTRAL'" in MIGRATION
    assert "source_row.amount IS DISTINCT FROM -destination_row.amount" in MIGRATION
    assert "source_row.effective_date IS DISTINCT FROM destination_row.effective_date" in MIGRATION
    assert "source_row.competence_date IS DISTINCT FROM destination_row.competence_date" in MIGRATION
    assert "source_row.description IS DISTINCT FROM destination_row.description" in MIGRATION
    assert "ck_finance_transfer_integrity" in MIGRATION


def test_transfer_reversal_is_atomic_and_individual_leg_reversal_is_guarded() -> None:
    assert "FinancialTransferReversalDraft" in DOMAIN
    assert "reverse_transfer(" in STORE
    assert "role=FinancialTransferRole.REVERSAL.value" in STORE
    assert "reversal_of_id=draft.transfer_id" in STORE
    assert 'movement_id=original["destination_movement_id"]' in STORE
    assert 'movement_id=original["source_movement_id"]' in STORE
    assert "uq_finance_transfers_one_reversal" in MIGRATION
    assert "ck_finance_movement_transfer_reversal_required" in MIGRATION
    assert "transfer Movement requires atomic transfer reversal" in MIGRATION
    assert "reversal_of_id" in RECORD


def test_transfer_rls_uses_intersection_and_runtime_is_append_only() -> None:
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "finance_transfers_select" in MIGRATION
    assert "visible_source" in MIGRATION
    assert "visible_destination" in MIGRATION
    assert "owned_source" in MIGRATION
    assert "owned_destination" in MIGRATION
    assert "finance_transfer_legs_select" in MIGRATION
    assert "finance_transfer_legs_insert" in MIGRATION
    assert "GRANT SELECT, INSERT ON finance.transfers" in MIGRATION
    assert "GRANT SELECT, INSERT ON finance.transfer_legs" in MIGRATION
    for forbidden in (
        "GRANT UPDATE ON finance.transfers",
        "GRANT DELETE ON finance.transfers",
        "GRANT UPDATE ON finance.transfer_legs",
        "GRANT DELETE ON finance.transfer_legs",
        "def update_transfer(",
        "def delete_transfer(",
    ):
        assert forbidden not in MIGRATION + STORE + PUBLIC


def test_transfer_contract_has_no_provider_api_category_or_cross_currency_coupling() -> None:
    combined = (DOMAIN + RECORD + SCHEMA + STORE).lower()
    for forbidden in (
        "pluggy",
        "fastapi",
        "category_id",
        "exchange_rate",
        "provider_item_id",
        "external_resource_id",
    ):
        assert forbidden not in combined
    assert "cross-currency" in ADR
    assert "mesma moeda" in ADR
