from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
CATEGORY_DOMAIN = (FINANCE / "categories.py").read_text(encoding="utf-8")
CATEGORY_STORE = (PERSISTENCE / "financial_category_store.py").read_text(
    encoding="utf-8"
)
CATEGORY_SCHEMA = (PERSISTENCE / "financial_category_schema.py").read_text(
    encoding="utf-8"
)
MIGRATION = (
    PERSISTENCE / "migrations/versions/0012_financial_categories.py"
).read_text(encoding="utf-8")


def test_category_contract_is_provider_neutral_and_not_a_movement_model() -> None:
    for source in (CATEGORY_DOMAIN, CATEGORY_STORE, CATEGORY_SCHEMA, MIGRATION):
        lowered = source.lower()
        for forbidden in (
            "pluggy",
            "external_resource_id",
            "fitid",
            "transaction_id",
            "movement_id",
            "amount",
            "balance",
            "income_type",
            "expense_type",
        ):
            assert forbidden not in lowered


def test_shared_visibility_is_explicitly_deferred() -> None:
    assert "SHARED category visibility is not supported yet" in CATEGORY_DOMAIN
    assert "visibility_scope IN ('PERSONAL', 'HOUSEHOLD')" in MIGRATION
    assert "visibility_scope IN ('PERSONAL', 'HOUSEHOLD')" in CATEGORY_SCHEMA
    assert "account_grants" not in MIGRATION
    assert "category_grants" not in MIGRATION


def test_category_tree_scope_is_closed_by_composite_fk() -> None:
    assert "ck_finance_categories_not_self_parent" in MIGRATION
    assert "fk_finance_categories_parent_scope" in MIGRATION
    for field in (
        "parent_id",
        "installation_id",
        "residence_id",
        "owner_operator_id",
        "visibility_scope",
    ):
        assert field in MIGRATION
    assert "ON DELETE RESTRICT" in MIGRATION
    assert "fk_finance_categories_parent_scope" in CATEGORY_SCHEMA


def test_category_rls_is_operator_aware_and_has_no_admin_bypass() -> None:
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "app.current_residence_id" in MIGRATION
    assert "app.current_operator_id" in MIGRATION
    assert "m.status = 'active'" in MIGRATION
    assert "categories.owner_operator_id" in MIGRATION
    assert "categories.visibility_scope = 'HOUSEHOLD'" in MIGRATION
    policy = MIGRATION.split("CREATE POLICY finance_categories_select", maxsplit=1)[1]
    for forbidden in ("administrator", "membership_role", "is_admin", "bypass"):
        assert forbidden not in policy.lower()


def test_category_runtime_permissions_are_create_read_only() -> None:
    assert "GRANT SELECT, INSERT ON finance.categories" in MIGRATION
    for forbidden in (
        "GRANT UPDATE ON finance.categories",
        "GRANT DELETE ON finance.categories",
        "GRANT SELECT, INSERT, UPDATE",
    ):
        assert forbidden not in MIGRATION


def test_category_store_exposes_only_create_list_get() -> None:
    assert "def create_category(" in CATEGORY_STORE
    assert "def list_categories(" in CATEGORY_STORE
    assert "def get_category(" in CATEGORY_STORE
    for forbidden in (
        "def update_category(",
        "def move_category(",
        "def disable_category(",
        "def delete_category(",
    ):
        assert forbidden not in CATEGORY_STORE
    assert "owner_operator_id=operator_id" in CATEGORY_STORE
    assert "financial category was not found" in CATEGORY_STORE
    assert "financial category parent was not found" in CATEGORY_STORE
