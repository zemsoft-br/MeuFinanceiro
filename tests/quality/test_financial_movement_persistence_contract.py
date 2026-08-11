from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
DOMAIN = (FINANCE / "movements.py").read_text(encoding="utf-8")
RECORD = (FINANCE / "movement_records.py").read_text(encoding="utf-8")
OPERATION_IDS = (FINANCE / "operation_ids.py").read_text(encoding="utf-8")
FINANCE_PUBLIC = (FINANCE / "__init__.py").read_text(encoding="utf-8")
ACCOUNT_SCHEMA = (PERSISTENCE / "financial_account_schema.py").read_text(
    encoding="utf-8"
)
SCHEMA = (PERSISTENCE / "financial_movement_schema.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "financial_movement_store.py").read_text(encoding="utf-8")
PUBLIC_STORE = (PERSISTENCE / "financial_movement.py").read_text(encoding="utf-8")
MIGRATION = (
    PERSISTENCE / "migrations/versions/0014_financial_movements.py"
).read_text(encoding="utf-8")
ADR = (
    ROOT
    / "docs/adr/0020-financial-movement-persistence-idempotency-and-reversal-integrity.md"
).read_text(encoding="utf-8")
ARCHITECTURE = (ROOT / "docs/architecture/FINANCIAL_MOVEMENTS.md").read_text(
    encoding="utf-8"
)


def test_movement_persistence_uses_signed_money_without_balance_authority() -> None:
    assert "amount numeric(24,8) NOT NULL" in MIGRATION
    assert "currency varchar(3) NOT NULL" in MIGRATION
    assert "result_effect IN ('INCOME', 'EXPENSE', 'NEUTRAL')" in MIGRATION
    assert "amount <> 0" in MIGRATION
    assert "uq_finance_accounts_opening_scope" in ACCOUNT_SCHEMA

    for source in (SCHEMA, STORE, MIGRATION):
        lowered = source.lower()
        for forbidden in (
            "current_balance",
            "available_balance",
            "cached_balance",
            "balance numeric",
        ):
            assert forbidden not in lowered


def test_idempotency_is_independent_versioned_and_fail_closed() -> None:
    assert "new_financial_idempotency_key" in OPERATION_IDS
    assert "validate_financial_idempotency_key" in OPERATION_IDS
    assert "value.version != 4" in OPERATION_IDS
    assert "installation_id, idempotency_key" in MIGRATION
    assert "uq_finance_movements_idempotency" in MIGRATION
    assert "request_digest varchar(64) NOT NULL" in MIGRATION
    assert "meufinanceiro:financial-movement-operation:v1" in STORE
    assert "hashlib.sha256" in STORE
    assert ".on_conflict_do_nothing(" in STORE
    assert "FinancialMovementIdempotencyConflictError" in STORE
    assert "movement_id" not in OPERATION_IDS
    assert "mesma key + mesmo digest" in ADR


def test_reversal_is_derived_unique_serialized_and_database_guarded() -> None:
    assert "_lock_standard_movement_for_reversal(" in STORE
    assert "func.finance.lock_standard_movement_for_reversal(" in STORE
    assert ".with_for_update()" not in STORE
    assert "reversal_amount = -original_amount" in STORE
    assert "FinancialMovementRole.REVERSAL.value" in STORE
    assert "reversal_target_role=FinancialMovementRole.STANDARD.value" in STORE
    assert "uq_finance_movements_one_reversal UNIQUE (reversal_of_id)" in MIGRATION
    assert "fk_finance_movements_reversal_target" in MIGRATION
    assert "reversal_target_role" in MIGRATION
    assert "validate_movement_reversal_amount" in MIGRATION
    assert "NEW.amount <> -original_amount" in MIGRATION
    assert "ck_finance_movement_reversal_amount" in MIGRATION
    assert "finance_movements_lock_update" in MIGRATION
    assert "FOR UPDATE USING (" in MIGRATION
    assert "movements.role = 'STANDARD'" in MIGRATION
    assert "FOR UPDATE OF m" in MIGRATION
    assert "SECURITY DEFINER" in MIGRATION
    assert "SET search_path = pg_catalog, pg_temp" in MIGRATION
    assert "REVOKE ALL ON FUNCTION" in MIGRATION
    assert "GRANT EXECUTE ON FUNCTION" in MIGRATION
    assert "amount" not in FinancialReversalDraftShape.caller_supplied_fields(DOMAIN)


class FinancialReversalDraftShape:
    @staticmethod
    def caller_supplied_fields(source: str) -> set[str]:
        start = source.index("class FinancialMovementReversalDraft")
        end = source.index("def _validate_standard_amount", start)
        block = source[start:end]
        return {
            field
            for field in ("amount", "account_id", "currency", "result_effect")
            if f"    {field}:" in block
        }


def test_rls_inherits_account_visibility_and_limits_writes_to_active_owner() -> None:
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "finance_movements_select" in MIGRATION
    assert "finance_movements_insert" in MIGRATION
    assert "EXISTS (SELECT 1 FROM finance.accounts a" in MIGRATION
    assert "a.owner_operator_id" in MIGRATION
    assert "a.status = 'ACTIVE'" in MIGRATION
    assert "m.status = 'active'" in MIGRATION
    assert "movements.created_by_operator_id" in MIGRATION
    assert "FinancialMovementAccountNotFoundError" in STORE
    assert "PERSONAL" in ARCHITECTURE
    assert "HOUSEHOLD" in ARCHITECTURE
    assert "SHARED" in ARCHITECTURE


def test_opening_anchor_is_enforced_on_effective_date_not_competence_date() -> None:
    assert "financial_opening_balances.c.effective_date" in STORE
    assert "effective_date < opening_date" in STORE
    assert "movements.effective_date < ob.effective_date" in MIGRATION
    assert "competence_date" in STORE
    assert "competence_date" not in MIGRATION.split("after_opening_anchor =", 1)[1].split(
        "op.execute(\"ALTER TABLE finance.movements", 1
    )[0]


def test_runtime_and_store_are_append_only() -> None:
    assert "GRANT SELECT, INSERT ON finance.movements" in MIGRATION
    for forbidden in (
        "GRANT UPDATE ON finance.movements",
        "GRANT DELETE ON finance.movements",
        "GRANT UPDATE (",
        "def update_movement(",
        "def delete_movement(",
        "def upsert_movement(",
    ):
        assert forbidden not in MIGRATION + STORE + PUBLIC_STORE
    assert "def create_movement(" in STORE
    assert "def reverse_movement(" in STORE
    assert "def get_movement(" in STORE
    assert "def list_movements(" in STORE


def test_persisted_record_and_public_api_redact_and_export_contracts() -> None:
    assert "@dataclass(frozen=True, slots=True, repr=False)" in RECORD
    assert "<amount-account-dates-description-identities-redacted>" in RECORD
    assert "FinancialMovementRecord" in FINANCE_PUBLIC
    assert "new_financial_idempotency_key" in FINANCE_PUBLIC
    assert "FinancialOpeningBalanceDraft" in FINANCE_PUBLIC
    assert "FinancialMovementStore" in PUBLIC_STORE


def test_movement_persistence_has_no_provider_api_category_or_transfer_coupling() -> None:
    for source in (RECORD, OPERATION_IDS, SCHEMA, STORE, MIGRATION):
        lowered = source.lower()
        for forbidden in (
            "pluggy",
            "fastapi",
            "category_id",
            "transfer_id",
            "external_resource_id",
            "provider_item_id",
        ):
            assert forbidden not in lowered
