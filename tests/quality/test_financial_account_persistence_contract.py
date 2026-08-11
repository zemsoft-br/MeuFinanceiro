from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
ACCOUNTS = (FINANCE / "accounts.py").read_text(encoding="utf-8")
SCHEMA = (PERSISTENCE / "financial_account_schema.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "financial_account_store.py").read_text(encoding="utf-8")
MIGRATION = (PERSISTENCE / "migrations/versions/0011_financial_accounts.py").read_text(
    encoding="utf-8"
)
PERSISTENCE_PROJECT = (ROOT / "packages/persistence/pyproject.toml").read_text(
    encoding="utf-8"
)
API_DOCKERFILE = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
WORKER_DOCKERFILE = (ROOT / "apps/worker/Dockerfile").read_text(encoding="utf-8")


def test_account_domain_is_provider_neutral_and_contains_no_balance_authority() -> None:
    for source in (ACCOUNTS, SCHEMA, STORE, MIGRATION):
        lowered = source.lower()
        for forbidden in (
            "external_resource_id",
            "pluggy",
            "fitid",
            "available_balance",
            "initial_balance",
            "current_balance",
        ):
            assert forbidden not in lowered
    assert 'Column("balance"' not in SCHEMA
    assert " balance " not in MIGRATION.lower()


def test_account_types_visibility_and_archive_shape_are_closed() -> None:
    for value in (
        "CHECKING",
        "SAVINGS",
        "CASH",
        "DIGITAL_WALLET",
        "INVESTMENT",
        "BENEFIT",
        "CUSTOM",
        "PERSONAL",
        "SHARED",
        "HOUSEHOLD",
        "ACTIVE",
        "ARCHIVED",
    ):
        assert value in MIGRATION
    assert "custom_type_name IS NOT NULL" in MIGRATION
    assert "account_type <> 'CUSTOM' AND custom_type_name IS NULL" in MIGRATION
    assert "currency ~ '^[A-Z]{3}$'" in MIGRATION
    assert "ck_finance_accounts_id_uuid4" in MIGRATION
    assert "ck_finance_accounts_id_uuid4" in SCHEMA
    assert "-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-" in MIGRATION


def test_shared_grants_are_structurally_bound_to_shared_accounts() -> None:
    assert "visibility_scope varchar(16) NOT NULL" in MIGRATION
    assert "ck_finance_account_grants_shared" in MIGRATION
    assert "visibility_scope = 'SHARED'" in MIGRATION
    assert "owner_operator_id, visibility_scope" in MIGRATION
    assert "owner_operator_id, visibility_scope" in MIGRATION
    assert "ck_finance_account_grants_shared" in SCHEMA
    assert '"visibility_scope",' in SCHEMA


def test_account_rls_is_operator_aware_and_non_recursive() -> None:
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "app.current_residence_id" in MIGRATION
    assert "app.current_operator_id" in MIGRATION
    assert "m.status = 'active'" in MIGRATION
    assert "accounts.owner_operator_id" in MIGRATION
    assert "accounts.visibility_scope = 'HOUSEHOLD'" in MIGRATION
    assert "accounts.visibility_scope = 'SHARED'" in MIGRATION
    assert "FROM finance.account_grants g" in MIGRATION
    assert "g.account_id = accounts.id" in MIGRATION
    assert "g.visibility_scope = accounts.visibility_scope" in MIGRATION

    grants_policy = MIGRATION.split(
        "CREATE POLICY finance_account_grants_select",
        maxsplit=1,
    )[1].split("ALTER TABLE finance.accounts", maxsplit=1)[0]
    assert "FROM finance.accounts" not in grants_policy


def test_account_insert_policy_is_owner_bound_and_active_only() -> None:
    insert_policy = MIGRATION.split(
        "CREATE POLICY finance_accounts_insert",
        maxsplit=1,
    )[1].split("GRANT USAGE ON SCHEMA finance", maxsplit=1)[0]
    assert "accounts.residence_id" in insert_policy
    assert "accounts.owner_operator_id" in insert_policy
    assert "accounts.status = 'ACTIVE'" in insert_policy
    assert "accounts.archived_at IS NULL" in insert_policy
    assert "m.status = 'active'" in insert_policy


def test_runtime_privileges_are_read_create_only_for_accounts() -> None:
    assert "GRANT SELECT, INSERT ON finance.accounts" in MIGRATION
    assert "GRANT SELECT ON finance.account_grants" in MIGRATION
    for forbidden in (
        "GRANT UPDATE ON finance.accounts",
        "GRANT DELETE ON finance.accounts",
        "GRANT SELECT, INSERT, UPDATE",
        "GRANT INSERT ON finance.account_grants",
        "GRANT UPDATE ON finance.account_grants",
        "GRANT DELETE ON finance.account_grants",
    ):
        assert forbidden not in MIGRATION


def test_store_derives_owner_from_actor_and_exposes_no_mutating_account_method() -> (
    None
):
    create_method = STORE.split("def create_account(", maxsplit=1)[1].split(
        "def list_accounts(", maxsplit=1
    )[0]
    assert "owner_operator_id=operator_id" in create_method
    assert "new_financial_resource_id()" in create_method
    assert "app.current_operator_id" in STORE
    assert "financial account was not found" in STORE
    for forbidden in (
        "def update_account(",
        "def archive_account(",
        "def delete_account(",
        "external_account_id",
        "provider",
    ):
        assert forbidden not in STORE


def test_persistence_dependency_is_packaged_in_api_and_worker_images() -> None:
    assert '"meufinanceiro-finance==0.1.0"' in PERSISTENCE_PROJECT
    for dockerfile in (API_DOCKERFILE, WORKER_DOCKERFILE):
        assert "COPY packages/finance/pyproject.toml" in dockerfile
        assert "COPY packages/finance/src" in dockerfile
        assert "./packages/finance" in dockerfile
