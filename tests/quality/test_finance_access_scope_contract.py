from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "packages/finance/src/meufinanceiro_finance"
ACCESS = (FINANCE / "access.py").read_text(encoding="utf-8")
ADR = (
    ROOT / "docs/adr/0016-financial-resource-visibility-and-authorization.md"
).read_text(encoding="utf-8")
INVARIANTS = (ROOT / "docs/architecture/FINANCIAL_INVARIANTS.md").read_text(
    encoding="utf-8"
)


def test_financial_audience_contract_is_provider_and_persistence_neutral() -> None:
    lowered = ACCESS.lower()
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


def test_visibility_scopes_are_explicit_and_closed() -> None:
    assert 'PERSONAL = "PERSONAL"' in ACCESS
    assert 'SHARED = "SHARED"' in ACCESS
    assert 'HOUSEHOLD = "HOUSEHOLD"' in ACCESS
    assert "shared_operator_ids" in ACCESS
    assert "explicit grants are valid only for SHARED resources" in ACCESS
    assert "resource owner must not have a redundant shared grant" in ACCESS


def test_audience_authorization_fails_closed_on_membership_and_residence() -> None:
    function = ACCESS.split("def can_access_financial_resource(", maxsplit=1)[1].split(
        "def require_financial_resource_access", maxsplit=1
    )[0]
    assert "if not actor.membership_active" in function
    assert "actor.residence_id != audience.residence_id" in function
    assert "actor.operator_id == audience.owner_operator_id" in function
    assert "actor.operator_id in audience.shared_operator_ids" in function
    assert "FinancialVisibilityScope.HOUSEHOLD" in function


def test_audience_function_has_no_administrative_role_bypass() -> None:
    function = ACCESS.split("def can_access_financial_resource(", maxsplit=1)[1].split(
        "def require_financial_resource_access", maxsplit=1
    )[0]
    for forbidden in (
        "administrator",
        "membership_role",
        "is_admin",
        "superuser",
        "bypass",
    ):
        assert forbidden not in function.lower()


def test_access_error_and_repr_do_not_emit_scope_identifiers() -> None:
    assert (
        'raise FinancialAccessDeniedError("financial resource access denied")' in ACCESS
    )
    assert "<scope-redacted>" in ACCESS
    for forbidden in (
        "str(self.residence_id)",
        "str(self.operator_id)",
        "str(self.owner_operator_id)",
        "self.shared_operator_ids!r",
    ):
        assert forbidden not in ACCESS


def test_adr_requires_operator_aware_rls_and_no_admin_bypass() -> None:
    assert "app.current_residence_id" in ADR
    assert "app.current_operator_id" in ADR
    assert "USING" in ADR
    assert "WITH CHECK" in ADR
    assert "não" in ADR.lower()
    assert "bypass" in ADR.lower()
    assert "PERSONAL" in ADR
    assert "SHARED" in ADR
    assert "HOUSEHOLD" in ADR


def test_financial_invariants_reference_accepted_audience_contract() -> None:
    assert "ADR-0016" in INVARIANTS
    assert "owner_operator_id" in INVARIANTS
    assert "visibility_scope" in INVARIANTS
    assert "app.current_operator_id" in INVARIANTS
    assert "papel administrativo não concede bypass" in INVARIANTS
