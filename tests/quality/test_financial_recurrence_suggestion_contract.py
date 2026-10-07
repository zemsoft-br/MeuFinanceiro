from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
DOMAIN = (FINANCE / "recurrence_suggestions.py").read_text(encoding="utf-8")
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
