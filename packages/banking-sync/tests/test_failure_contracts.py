from __future__ import annotations

from meufinanceiro_banking_sync.service import _safe_provider_reason_code


def test_provider_reason_code_matches_persistence_diagnostic_contract() -> None:
    assert _safe_provider_reason_code("SAFE_RATE_LIMIT") == "SAFE_RATE_LIMIT"
    assert _safe_provider_reason_code("provider.reason-1:temporary") == (
        "provider.reason-1:temporary"
    )

    for unsafe in (
        "contains spaces",
        "contains/slash",
        "line\nbreak",
        "x" * 129,
        "",
    ):
        assert _safe_provider_reason_code(unsafe) is None

    assert _safe_provider_reason_code(None) is None
