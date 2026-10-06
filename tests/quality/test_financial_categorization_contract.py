from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
DOMAIN = (FINANCE / "categorization_rules.py").read_text(encoding="utf-8")
SCHEMA = (PERSISTENCE / "financial_categorization_rule_schema.py").read_text(
    encoding="utf-8"
)
STORE = (PERSISTENCE / "financial_categorization_rule_store.py").read_text(
    encoding="utf-8"
)
MIGRATION = (
    PERSISTENCE / "migrations/versions/0021_categorization_rules.py"
).read_text(encoding="utf-8")
MOVEMENT_SCHEMA = (PERSISTENCE / "financial_movement_schema.py").read_text(
    encoding="utf-8"
)
AUDIT_EVENTS = (FINANCE / "audit_events.py").read_text(encoding="utf-8")


def test_rule_domain_is_provider_and_persistence_neutral() -> None:
    lowered = DOMAIN.lower()
    for forbidden in (
        "sqlalchemy",
        "meufinanceiro_persistence",
        "pluggy",
        "fastapi",
        "provider_",
        "external_resource_id",
        "regex",
        "re.compile",
        "float(",
    ):
        assert forbidden not in lowered, forbidden


def test_rule_persistence_never_uses_float_or_provider_semantics() -> None:
    for source in (SCHEMA, STORE, MIGRATION):
        lowered = source.lower()
        assert "float" not in lowered
        assert "pluggy" not in lowered
        assert "provider" not in lowered


def test_v1_matching_is_exact_or_contains_on_the_description_only() -> None:
    assert re.findall(r"^    (EXACT|CONTAINS) = ", DOMAIN, re.M) == [
        "EXACT",
        "CONTAINS",
    ]
    assert "casefold()" in DOMAIN
    assert "unicodedata.normalize" in DOMAIN
    # Tie-breaking by creation time, id or order is forbidden by contract.
    assert "AMBIGUOUS" in DOMAIN
    assert "created_at" not in DOMAIN.split("def evaluate_movement_categorization")[1]


def test_ledger_and_audit_contracts_gain_nothing_for_rules() -> None:
    lowered = MOVEMENT_SCHEMA.lower()
    assert "rule" not in lowered and "category_id" not in lowered
    assert "RULE" not in AUDIT_EVENTS
    assert "CATEGORIZATION" not in AUDIT_EVENTS


def test_rule_origin_is_provenance_only_without_financial_payload() -> None:
    assert "financial_movement_allocation_rule_origins" in SCHEMA
    columns = re.findall(
        r'Column\("(\w+)"',
        SCHEMA.split("financial_movement_allocation_rule_origins = Table(")[1].split(
            "Index("
        )[0],
    )
    assert columns == [
        "allocation_set_id",
        "installation_id",
        "residence_id",
        "movement_id",
        "rule_id",
        "created_at",
    ]


def test_rules_are_semantically_immutable_and_provenance_is_append_only() -> None:
    upgrade = MIGRATION.split("def downgrade")[0]
    assert "GRANT UPDATE (status, disabled_at, disabled_by_operator_id)" in upgrade
    assert "GRANT SELECT, INSERT ON finance.categorization_rules" in upgrade
    assert "GRANT SELECT, INSERT ON finance.movement_allocation_rule_origins" in upgrade
    assert "GRANT DELETE" not in upgrade and "GRANT UPDATE ON" not in upgrade
    assert upgrade.count("FORCE ROW LEVEL SECURITY") == 2
    assert "enforce_categorization_rule_immutability" in upgrade
    assert "FOR SHARE" in upgrade


def test_apply_reevaluates_canonical_state_under_the_movement_lock() -> None:
    start = STORE.index("def apply_rule_to_movement(")
    body = STORE[start:]
    assert body.index("_lock_eligible_movement(") < body.index("_current_set_row(")
    assert body.index("_current_set_row(") < body.index("_append_allocation_set(")
    assert "evaluate_movement_categorization(" in body
    assert "categorization_apply_idempotency_key(" in body
    assert "supersedes_id=None" in body and "revision=1" in body
    assert "revise_allocation_set" not in body


def test_rule_set_lock_is_one_contract_taken_in_a_fixed_order() -> None:
    assert "pg_advisory_xact_lock" in STORE
    assert "_RULE_SET_LOCK_NAMESPACE" in STORE
    for method, end in (
        ("def create_rule(", "def list_rules("),
        ("def disable_rule(", "def list_current_rule_origins("),
        ("def apply_rule_to_movement(", "def _create_digest("),
    ):
        body = STORE.split(method)[1].split(end)[0]
        assert body.count("_acquire_rule_set_lock(") == 1, method
    apply = STORE.split("def apply_rule_to_movement(")[1]
    assert apply.index("_acquire_rule_set_lock(") < apply.index("_active_rules(")
    assert apply.index("_acquire_rule_set_lock(") < apply.index(
        "_lock_eligible_movement("
    )
    # reads and preview never block on the rule-set lock
    for reader in ("def list_rules(", "def list_current_rule_origins("):
        body = STORE.split(reader)[1].split("    def ")[0]
        assert "_acquire_rule_set_lock(" not in body, reader
