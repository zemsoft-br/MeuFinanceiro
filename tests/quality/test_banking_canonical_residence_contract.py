from __future__ import annotations

from pathlib import Path

from meufinanceiro_persistence.schema import connections

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "packages"
    / "persistence"
    / "src"
    / "meufinanceiro_persistence"
    / "migrations"
    / "versions"
    / "0006_banking_residence_fk.py"
)
_CONSTRAINT_NAME = "fk_connections_household_residence_scope"


def test_connection_metadata_requires_canonical_household_residence() -> None:
    constraints = {
        constraint.name: constraint
        for constraint in connections.foreign_key_constraints
    }
    constraint = constraints[_CONSTRAINT_NAME]

    assert tuple(constraint.column_keys) == ("residence_id", "installation_id")
    assert tuple(element.target_fullname for element in constraint.elements) == (
        "household.residences.id",
        "household.residences.installation_id",
    )
    assert constraint.referred_table.fullname == "household.residences"
    assert constraint.ondelete == "RESTRICT"


def test_migration_fails_closed_without_synthesizing_residences() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert "context.is_offline_mode()" in content
    assert "requires online validation" in content
    assert "LOCK TABLE household.residences, integrations.connections" in content
    assert "IN SHARE ROW EXCLUSIVE MODE" in content
    assert "SELECT EXISTS" in content
    assert "LEFT JOIN household.residences" in content
    assert "residence.id = banking_connection.residence_id" in content
    assert "residence.installation_id = banking_connection.installation_id" in content
    assert "non-canonical residence references" in content
    assert 'ondelete="RESTRICT"' in content
    assert 'ondelete="CASCADE"' not in content
    assert "INSERT INTO household.residences" not in content
    assert "UPDATE integrations.connections" not in content
    assert "primary_residence" not in content
