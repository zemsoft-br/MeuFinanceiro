from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
DOMAIN = (FINANCE / "audit_events.py").read_text(encoding="utf-8")
RECORD = (FINANCE / "audit_event_records.py").read_text(encoding="utf-8")
PUBLIC = (FINANCE / "__init__.py").read_text(encoding="utf-8")
ADR = (
    ROOT / "docs/adr/0023-financial-transactional-audit-trail.md"
).read_text(encoding="utf-8")


def test_audit_contract_remains_provider_and_persistence_neutral() -> None:
    for source in (DOMAIN, RECORD):
        lowered = source.lower()
        for forbidden in (
            "sqlalchemy",
            "meufinanceiro_persistence",
            "pluggy",
            "fastapi",
            "provider_item_id",
            "external_resource_id",
        ):
            assert forbidden not in lowered


def test_audit_contract_has_no_financial_payload_fields() -> None:
    combined = DOMAIN + RECORD
    for forbidden_field in (
        "    amount:",
        "    currency:",
        "    description:",
        "    reason:",
        "    payload:",
        "    request_body:",
        "    request_digest:",
        "    access_token:",
        "    refresh_token:",
        "    before_snapshot:",
        "    after_snapshot:",
    ):
        assert forbidden_field not in combined


def test_audit_event_and_subject_matrix_is_closed_and_versioned() -> None:
    assert "class FinancialAuditEventType(StrEnum)" in DOMAIN
    assert "class FinancialAuditSubjectType(StrEnum)" in DOMAIN
    assert "_SUBJECT_BY_EVENT" in DOMAIN
    assert "_RELATED_SUBJECT_BY_EVENT" in DOMAIN
    assert "FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION = 1" in DOMAIN
    assert "event_schema_version" in DOMAIN
    assert "event_schema_version" in RECORD
    assert "unsupported financial audit event schema version" in RECORD


def test_related_subject_shape_is_derived_from_event_type() -> None:
    assert "audit event must not have related subject" in DOMAIN
    assert "audit event requires related subject" in DOMAIN
    assert "audit related subject must differ from subject" in DOMAIN
    assert "subject_type" in DOMAIN
    assert "related_subject_type" in DOMAIN
    assert "audit subject type does not match event type" in RECORD
    assert "audit related subject type does not match event type" in RECORD


def test_public_contract_exports_audit_types_without_arbitrary_writer() -> None:
    for exported in (
        "FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION",
        "FinancialAuditEventDraft",
        "FinancialAuditEventRecord",
        "FinancialAuditEventType",
        "FinancialAuditSubjectType",
        "financial_audit_related_subject_type_for_event",
        "financial_audit_subject_type_for_event",
    ):
        assert exported in PUBLIC
    assert "create_audit_event" not in PUBLIC
    assert "append_audit_event" not in PUBLIC


def test_adr_requires_transactional_actor_only_append_only_audit() -> None:
    assert "mesma transação PostgreSQL" in ADR
    assert "retry replay" in ADR
    assert "actor_operator_id = current operator" in ADR
    assert "UPDATE proibido" in ADR
    assert "DELETE proibido" in ADR
    assert "Hash chain" in ADR
    assert "não fornecer proteção real" in ADR
    assert "transaction_timestamp()" in ADR
