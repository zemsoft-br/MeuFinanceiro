from __future__ import annotations

import re
from pathlib import Path

from meufinanceiro_persistence.demo_contract import (
    DEMO_CONTRACT_CHECKSUM,
    DEMO_CURRENCY,
    DEMO_FIXTURE_ID,
    DEMO_FIXTURE_VERSION,
    DEMO_REFERENCE_DATE,
    DEMO_SCOPE,
    DEMO_TIMEZONE,
)

ROOT = Path(__file__).resolve().parents[2]
DART = (ROOT / "apps/app/lib/core/demo/demo_status.dart").read_text(encoding="utf-8")


def _dart_string(name: str) -> str:
    match = re.search(
        rf"static const {re.escape(name)}\s*=\s*'([^']+)';",
        DART,
    )
    assert match is not None, f"missing Dart demo constant: {name}"
    return match.group(1)


def _dart_int(name: str) -> int:
    match = re.search(
        rf"static const {re.escape(name)}\s*=\s*([0-9]+);",
        DART,
    )
    assert match is not None, f"missing Dart demo constant: {name}"
    return int(match.group(1))


def test_flutter_demo_status_contract_matches_persistence_contract() -> None:
    assert _dart_string("canonicalFixtureId") == DEMO_FIXTURE_ID
    assert _dart_int("canonicalFixtureVersion") == DEMO_FIXTURE_VERSION
    assert _dart_string("canonicalReferenceDate") == DEMO_REFERENCE_DATE.isoformat()
    assert _dart_string("canonicalTimezone") == DEMO_TIMEZONE
    assert _dart_string("canonicalCurrency") == DEMO_CURRENCY
    assert _dart_string("canonicalScope") == DEMO_SCOPE
    assert _dart_string("canonicalContractChecksum") == DEMO_CONTRACT_CHECKSUM
