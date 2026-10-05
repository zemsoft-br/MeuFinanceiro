from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
API = ROOT / "apps/api/app"
DOMAIN = (FINANCE / "pending_movements.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "financial_pending_movement_store.py").read_text(
    encoding="utf-8"
)
MIGRATION = (
    PERSISTENCE / "migrations/versions/0022_pending_movement_indexes.py"
).read_text(encoding="utf-8")
MOVEMENT_SCHEMA = (PERSISTENCE / "financial_movement_schema.py").read_text(
    encoding="utf-8"
)
SERVICE = (API / "services/financial_pending_movements.py").read_text(encoding="utf-8")
ROUTE = (API / "api/routes/finance_pending.py").read_text(encoding="utf-8")
ADR = (ROOT / "docs/adr/0025-derived-pending-classification-inbox.md").read_text(
    encoding="utf-8"
)
DOC = (ROOT / "docs/architecture/FINANCIAL_PENDING_INBOX.md").read_text(
    encoding="utf-8"
)


def _code(source: str) -> str:
    """Source without docstrings and comments, so prose never trips a contract."""
    without_docstrings = re.sub(r'"""[\s\S]*?"""', "", source)
    return re.sub(r"(?m)^\s*#.*$", "", without_docstrings)


def test_pending_domain_is_provider_and_persistence_neutral() -> None:
    lowered = DOMAIN.lower()
    for forbidden in (
        "sqlalchemy",
        "meufinanceiro_persistence",
        "pluggy",
        "fastapi",
        "provider_",
        "float(",
        "regex",
    ):
        assert forbidden not in lowered, forbidden


def test_the_inbox_reuses_the_rule_evaluation_and_never_matches_text() -> None:
    # One evaluation pipeline for preview, apply and the inbox.
    assert "evaluate_movement_categorization(" in DOMAIN
    assert "usable_categorization_rules(" in DOMAIN
    for source in (DOMAIN, SERVICE, ROUTE, STORE):
        for forbidden in (
            "casefold",
            "normalize_categorization_text",
            ".priority",
            "description_pattern",
            "normalized_pattern",
        ):
            assert forbidden not in source, forbidden
    # Rule filtering is once per account, never per Movement.
    assert "usable_by_account" in DOMAIN


def test_the_inbox_store_is_select_only_with_a_keyset_and_no_offset() -> None:
    lowered = _code(STORE).lower()
    for verb in (".insert(", "pg_insert", ".update(", ".delete(", "for update", "lock"):
        assert verb not in lowered, verb
    for token in ("offset", ".offset(", "float"):
        assert token not in lowered, token
    assert "tuple_(movements.c.effective_date, movements.c.id)" in STORE
    assert "effective_date.desc(), movements.c.id.desc()" in STORE
    assert ".limit(limit + 1)" in STORE
    assert "PENDING_PAGE_LIMIT_MAX" in STORE
    # The ordered, limited scan must run before the accounts join.
    assert STORE.index("scan = (") < STORE.index("page = scan.subquery(")
    assert STORE.index("page = scan.subquery(") < STORE.index("page.join(")


def test_nothing_pending_is_persisted_and_movement_stays_the_only_ledger() -> None:
    lowered_schema = MOVEMENT_SCHEMA.lower()
    for forbidden in ("pending", "inbox", "reviewed", "category_id", "dismiss"):
        # The two keyset indexes are named *pending_scan* but add no column.
        cleaned = re.sub(r"ix_finance_movements_pending\w*", "", lowered_schema)
        assert forbidden not in cleaned, forbidden
    # The migration only creates and drops indexes.
    statements = re.findall(r'op\.execute\(\s*(?:f?"([^"]*)")', MIGRATION)
    assert statements
    for statement in statements:
        assert statement.startswith(("CREATE INDEX", "DROP INDEX")), statement
    for forbidden in ("CREATE TABLE", "ALTER TABLE", "GRANT", "POLICY", "TRIGGER"):
        assert forbidden not in MIGRATION, forbidden
    assert 'down_revision: str | None = "0021_categorization_rules"' in MIGRATION


def test_the_route_is_get_only_with_a_closed_query_contract() -> None:
    assert len(re.findall(r"^@router\.", ROUTE, re.M)) == 1
    assert '@router.get("/pending-movements"' in ROUTE
    for verb in ("@router.post", "@router.put", "@router.patch", "@router.delete"):
        assert verb not in ROUTE, verb
    assert "_ALLOWED_QUERY" in ROUTE
    for param in ("limit", "cursor", "accountId", "resultEffect", "ruleStatus"):
        assert f'"{param}"' in ROUTE, param
    for forbidden in ("offset", "search"):
        assert forbidden not in ROUTE.split("_ALLOWED_QUERY = ")[1].split(")")[0]
    assert "PENDING_PAGE_LIMIT_MAX" in ROUTE


def test_the_service_cost_is_fixed_and_the_scan_budget_is_explicit() -> None:
    assert "MAX_SCAN_BATCHES = 5" in SERVICE
    assert "SCAN_BATCH_SIZE = PENDING_PAGE_LIMIT_MAX" in SERVICE
    # One rule read and one category read per request.
    assert SERVICE.count(".list_rules(") == 1
    assert SERVICE.count(".list_categories(") == 1
    # The only loop over the store is the bounded scan.
    assert "for _ in range(MAX_SCAN_BATCHES):" in SERVICE
    assert not re.search(r"\bwhile\b", _code(SERVICE))
    for write in ("create_rule", "disable_rule", "apply_rule", "create_allocation"):
        assert write not in SERVICE, write


def test_adr_and_doc_state_the_derived_no_second_authority_decision() -> None:
    for text in (ADR, DOC):
        assert "derivad" in text.lower()
        assert "movement_allocation_sets" in text
        assert "keyset" in text.lower()
        assert "0022" in text
    assert "Status: Accepted" in ADR
    assert "ADR-0025" in DOC
    assert (
        "Pull Request, merge e integração ao `develop` **ainda não ocorreram**" in DOC
    )
