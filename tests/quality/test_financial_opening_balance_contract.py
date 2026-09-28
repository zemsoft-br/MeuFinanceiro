from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
DOMAIN = (FINANCE / "opening_balances.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "financial_opening_balance_store.py").read_text(encoding="utf-8")
SCHEMA = (PERSISTENCE / "financial_opening_balance_schema.py").read_text(
    encoding="utf-8"
)
MIGRATION = (
    PERSISTENCE / "migrations/versions/0013_account_opening_balances.py"
).read_text(encoding="utf-8")
ACCOUNT_MIGRATION = (
    PERSISTENCE / "migrations/versions/0011_financial_accounts.py"
).read_text(encoding="utf-8")
ADR = (ROOT / "docs/adr/0018-immutable-account-opening-balance.md").read_text(
    encoding="utf-8"
)


def test_opening_balance_is_separate_from_account_balance_authority() -> None:
    for forbidden in (
        " initial_balance ",
        " available_balance ",
        " current_balance ",
        " balance numeric",
    ):
        assert forbidden not in ACCOUNT_MIGRATION.lower()
    assert "CREATE TABLE finance.account_opening_balances" in MIGRATION
    assert "uq_finance_opening_balance_account UNIQUE (account_id)" in MIGRATION
    assert "append-once" in ADR
    assert "Ausência" in ADR


def test_opening_balance_uses_money_shape_and_account_currency_fk() -> None:
    assert "amount: Money" in DOMAIN
    assert "effective_date: date" in DOMAIN
    assert "amount numeric(24,8) NOT NULL" in MIGRATION
    assert "currency varchar(3) NOT NULL" in MIGRATION
    assert "uq_finance_accounts_opening_scope" in MIGRATION
    assert "fk_finance_opening_balance_account_scope" in MIGRATION
    assert "account_id, installation_id, residence_id, currency" in MIGRATION
    assert 'Money(row["amount"], row["currency"])' in STORE


def test_opening_balance_rls_inherits_account_visibility_and_owner_only_insert() -> (
    None
):
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "app.current_residence_id" in MIGRATION
    assert "app.current_operator_id" in MIGRATION
    assert "EXISTS (SELECT 1 FROM finance.accounts a" in MIGRATION
    assert "a.owner_operator_id" in MIGRATION
    assert "a.status = 'ACTIVE'" in MIGRATION
    assert "created_by_operator_id" in MIGRATION
    assert "m.status = 'active'" in MIGRATION


def test_runtime_permissions_and_store_are_immutable() -> None:
    assert "GRANT SELECT, INSERT ON finance.account_opening_balances" in MIGRATION
    for forbidden in (
        "GRANT UPDATE ON finance.account_opening_balances",
        "GRANT DELETE ON finance.account_opening_balances",
        "def update_opening_balance(",
        "def delete_opening_balance(",
        "def upsert_opening_balance(",
    ):
        assert forbidden not in MIGRATION + STORE
    assert "def create_opening_balance(" in STORE
    assert "def get_opening_balance(" in STORE
    assert "financial account already has an opening balance" in STORE


def test_opening_balance_has_no_provider_or_movement_dependency() -> None:
    for source in (DOMAIN, STORE, SCHEMA, MIGRATION):
        lowered = source.lower()
        for forbidden in (
            "pluggy",
            "external_resource_id",
            "fitid",
            "movement_id",
            "transaction_id",
            "provider_balance",
        ):
            assert forbidden not in lowered
