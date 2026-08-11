from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
IDS = (FINANCE / "ids.py").read_text(encoding="utf-8")
ADR = (
    ROOT / "docs/adr/0017-canonical-financial-resource-identifiers.md"
).read_text(encoding="utf-8")
INVARIANTS = (ROOT / "docs/architecture/FINANCIAL_INVARIANTS.md").read_text(
    encoding="utf-8"
)
SEQUENCE = (ROOT / "docs/architecture/IMPLEMENTATION_SEQUENCE.md").read_text(
    encoding="utf-8"
)


def test_financial_id_contract_is_standard_library_only() -> None:
    lowered = IDS.lower()
    assert "from uuid import" in IDS
    for forbidden in (
        "fastapi",
        "sqlalchemy",
        "httpx",
        "pluggy",
        "meufinanceiro_persistence",
        "requests",
        "flutter",
    ):
        assert forbidden not in lowered


def test_financial_id_generation_and_validation_are_strict_uuid4() -> None:
    assert "uuid4()" in IDS
    assert "value.int == 0" in IDS
    assert "value.variant != RFC_4122" in IDS
    assert "value.version != 4" in IDS
    assert 'raise TypeError("financial resource id must be UUID")' in IDS
    assert "UUID(str" not in IDS
    assert "UUID(value" not in IDS


def test_adr_keeps_local_id_opaque_and_external_identity_separate() -> None:
    assert "UUID v4 RFC 4122" in ADR
    assert "não codifica" in ADR
    for required in (
        "residência",
        "operador",
        "timestamp",
        "valor monetário",
        "provider",
        "identificador externo",
        "external_resource_id",
        "FITID",
        "fingerprint",
    ):
        assert required in ADR
    assert "não substituem o UUID local" in ADR


def test_adr_separates_resource_id_from_operation_ids_and_authorization() -> None:
    for required in (
        "idempotency key",
        "correlation ID",
        "reconciliation/link ID",
        "transfer ID",
        "Autorização nunca é inferida do ID",
        "client-generated UUID",
    ):
        assert required in ADR


def test_architecture_marks_financial_id_decision_as_resolved() -> None:
    assert "ADR-0017 / #131" in INVARIANTS
    assert "ADR-0017 / #131" in SEQUENCE
    assert "convenções de IDs financeiros" not in INVARIANTS.split(
        "Ainda pendentes:", maxsplit=1
    )[1]
