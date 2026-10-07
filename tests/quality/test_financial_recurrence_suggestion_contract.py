from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
DOMAIN = (FINANCE / "recurrence_suggestions.py").read_text(encoding="utf-8")
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
MIGRATION = (
    PERSISTENCE / "migrations/versions/0027_recurrence_suggestions.py"
).read_text(encoding="utf-8")
SCHEMA = (PERSISTENCE / "financial_recurrence_suggestion_schema.py").read_text(
    encoding="utf-8"
)
STORE = (PERSISTENCE / "financial_recurrence_suggestion_store.py").read_text(
    encoding="utf-8"
)
RECURRENCE_STORE = (PERSISTENCE / "financial_recurrence_store.py").read_text(
    encoding="utf-8"
)
MOVEMENT_SCHEMA = (PERSISTENCE / "financial_movement_schema.py").read_text(
    encoding="utf-8"
)
API = ROOT / "apps/api/app"
ROUTE = (API / "api/routes/finance_recurrence_suggestions.py").read_text(
    encoding="utf-8"
)
SERVICE = (API / "services/financial_recurrence_suggestions.py").read_text(
    encoding="utf-8"
)
MAIN = (API / "main.py").read_text(encoding="utf-8")
ADR = (ROOT / "docs/adr/0028-assisted-recurrence-suggestions.md").read_text(
    encoding="utf-8"
)
DOC = (ROOT / "docs/architecture/FINANCIAL_RECURRENCE_SUGGESTIONS.md").read_text(
    encoding="utf-8"
)


def _code(source: str) -> str:
    """Source without docstrings and comments, so prose never trips a contract."""
    without_docstrings = re.sub(r'"""[\s\S]*?"""', "", source)
    return re.sub(r"(?m)^\s*#.*$", "", without_docstrings)


def test_the_detector_is_pure_deterministic_and_provider_neutral() -> None:
    code = _code(DOMAIN)
    lowered = code.lower()
    for forbidden in (
        "float(",
        "random",
        "datetime.now",
        "date.today",
        "time.time",
        "uuid4",
        "sqlalchemy",
        "fastapi",
        "pluggy",
        "merchant",
        "difflib",
        "levenshtein",
        "fuzz",
        "sklearn",
        "openai",
        "anthropic",
        "confidence",
        "score",
    ):
        assert forbidden not in lowered, forbidden
    assert "normalize_categorization_text" in code  # the one normalization contract
    assert "SUGGESTION_SCAN_MAX" in code and "SUGGESTION_LIST_MAX" in code


def test_the_fingerprint_is_versioned_and_blind_to_evidence() -> None:
    match = re.search(r"return _digest\(([\s\S]*?)\n    \)\n", _code(DOMAIN))
    assert match is not None
    hashed = match.group(1)
    assert "_FINGERPRINT_NAMESPACE" in hashed
    for forbidden in ("movement", "date", "amount", "evidence", "version"):
        assert forbidden not in hashed.lower().replace("_description", ""), forbidden
    assert "meufinanceiro:recurrence-suggestion:v1" in DOMAIN


def test_reason_codes_are_a_closed_enumeration_without_a_numeric_score() -> None:
    reasons = re.findall(r'^    ([A-Z_]+) = "\1"$', DOMAIN, flags=re.MULTILINE)
    for expected in (
        "EXACT_DESCRIPTION",
        "CONSECUTIVE_MONTHS",
        "ONE_PER_MONTH",
        "DAY_WINDOW",
        "AMOUNT_FIXED",
        "AMOUNT_VARIABLE",
        "FIXED",
        "VARIABLE",
        "ACCEPTED",
        "DISMISSED",
    ):
        assert expected in reasons, expected


def test_adr_and_architecture_document_the_decision() -> None:
    for term in (
        "derivada",
        "fingerprint",
        "FIXED",
        "VARIABLE",
        "append-only",
        "RLS",
        "ACTIVE",
        "nunca é aceita",
        "uma única transação",
        "zero",
    ):
        assert term in ADR or term in DOC, term
    assert "ADR-0028" in DOC
    assert "FINANCIAL_RECURRENCE_SUGGESTIONS.md" in ADR
    adr_index = (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")
    assert "0028-assisted-recurrence-suggestions.md" in adr_index


def test_docs_state_that_254_is_closed_and_pr_255_merged() -> None:
    sequence = (ROOT / "docs/architecture/IMPLEMENTATION_SEQUENCE.md").read_text(
        encoding="utf-8"
    )
    roadmap = (ROOT / "docs/ROADMAP.md").read_text(encoding="utf-8")
    recurrences = (ROOT / "docs/architecture/FINANCIAL_RECURRENCES.md").read_text(
        encoding="utf-8"
    )
    for source in (sequence, roadmap, recurrences):
        assert "#254" in source or "PR #255" in source
        assert "aguardando revisão de PR" not in source
        assert "sem PR ainda):** recorrências" not in source
    assert "PR #255" in sequence and "PR #255" in roadmap and "PR #255" in recurrences


def test_decisions_are_append_only_forced_rls_and_never_granted_more() -> None:
    assert 'down_revision: str | None = "0026_recurrence_revisions"' in MIGRATION
    for statement in (
        "ALTER TABLE finance.recurrence_suggestion_decisions ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE finance.recurrence_suggestion_decisions FORCE ROW LEVEL SECURITY",
    ):
        assert statement in MIGRATION, statement
    grants = re.findall(r"GRANT [^\n\"]*", MIGRATION)
    assert grants == [
        "GRANT SELECT, INSERT ON finance.recurrence_suggestion_decisions TO {role}"
    ]
    assert "SECURITY DEFINER" not in MIGRATION
    for name in (
        "uq_finance_recurrence_decisions_operator_fingerprint",
        "uq_finance_recurrence_decisions_recurrence",
        "ck_finance_recurrence_decisions_shape",
        "ck_finance_recurrence_decisions_link",
        "ck_finance_recurrence_decisions_immutable",
    ):
        assert name in MIGRATION, name
    assert "ALTER TABLE finance.movements" not in MIGRATION


def test_the_ledger_and_the_schema_never_hold_a_suggestion_or_a_balance() -> None:
    assert "suggestion" not in MOVEMENT_SCHEMA.lower()
    columns = set(re.findall(r'Column\(\s*"(\w+)"', SCHEMA))
    for forbidden in ("balance", "amount", "expected_amount", "movement_id", "score"):
        assert forbidden not in columns, forbidden
    assert {"fingerprint", "decision", "recurrence_id", "evidence_digest"} <= columns


def test_the_suggestion_store_never_writes_the_ledger_or_an_occurrence() -> None:
    code = _code(STORE)
    for table in ("financial_movements", "financial_recurrence_occurrences"):
        assert not re.search(rf"(insert|update|delete)\(\s*{table}", code), table
        assert f"pg_insert({table}" not in code
    assert "delete(" not in code and ".delete(" not in code
    assert "float(" not in code.lower() and "retry" not in code.lower()
    assert "date.today" not in code and "datetime.now" not in code
    # Acceptance reuses the one canonical writer, on its own transaction.
    assert "create_recurrence_in_transaction(" in code
    assert "def create_recurrence_in_transaction" in _code(RECURRENCE_STORE)
    # Reading goes through the detector; commands re-run it for the caller.
    assert code.count("self._candidate(") >= 2
    assert "detect_recurrence_suggestions(" in code


def test_the_route_has_exactly_the_three_suggestion_endpoints() -> None:
    routes = re.findall(r'^@router\.(\w+)\(\s*"([^"]+)"', ROUTE, re.M)
    assert sorted(routes) == sorted(
        [
            ("get", "/recurrence-suggestions"),
            ("post", "/recurrence-suggestions/{fingerprint}/dismiss"),
            ("post", "/recurrence-suggestions/{fingerprint}/accept"),
        ]
    )
    for verb in ("put", "patch", "delete"):
        assert f"@router.{verb}" not in ROUTE
    assert "finance_recurrence_suggestions_router" in MAIN
    assert "FinancialRecurrenceSuggestionService(" in MAIN


def test_a_read_never_reaches_a_write_and_nothing_is_automatic() -> None:
    full_service = _code(SERVICE)
    service = full_service[
        full_service.index("class FinancialRecurrenceSuggestionService") :
    ]
    route = _code(ROUTE)
    listing = service[
        service.index("def list_suggestions") : service.index("def dismiss")
    ]
    assert "self._store.list_suggestions(" in listing
    for forbidden in ("_store.dismiss(", "_store.accept(", "create_"):
        assert forbidden not in listing, forbidden
    get = route[
        route.index("def list_recurrence_suggestions") : route.index(
            "def dismiss_recurrence_suggestion"
        )
    ]
    for forbidden in (".dismiss(", ".accept("):
        assert forbidden not in get, forbidden
    for source in (service, route):
        for forbidden in (
            "float(",
            "financial_movements",
            "monthrange",
            "timedelta",
            "datetime.now",
            "date.today",
            "background",
            "scheduler",
            "Thread(",
        ):
            assert forbidden not in source, forbidden
    # The only clock is injected; the default lives in the composition root.
    assert "clock: Callable[[], date]" in service


def test_the_client_cannot_widen_the_accepted_recurrence() -> None:
    body = ROUTE[
        ROUTE.index("class SuggestionAcceptRequest") : ROUTE.index(
            "class SuggestionEvidenceResponse"
        )
    ]
    assert 'extra="forbid"' in body
    fields = set(re.findall(r"^    (\w+): ", body, re.M))
    assert fields == {
        "idempotency_key",
        "description",
        "expected_amount",
        "start_date",
        "day_of_month",
        "end_date",
    }
    for forbidden in ("account", "currency", "effect", "owner", "frequency"):
        assert forbidden not in "".join(sorted(fields)), forbidden
