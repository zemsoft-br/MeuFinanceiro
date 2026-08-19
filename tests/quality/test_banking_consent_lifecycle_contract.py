from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = (
    ROOT / "packages/banking-sync/src/meufinanceiro_banking_sync/consent_lifecycle.py"
)
PROVIDER = ROOT / "packages/banking/src/meufinanceiro_banking/provider.py"


def test_consent_lifecycle_is_provider_neutral_and_local_only() -> None:
    source = LIFECYCLE.read_text(encoding="utf-8")
    lowered = source.lower()

    assert "pluggy" not in lowered
    assert "bankingprovider" not in lowered
    assert "external_connection_id" not in source
    assert "provider_reason_code" not in source
    assert "http" not in lowered
    assert "requests" not in lowered
    assert "urllib" not in lowered


def test_consent_lifecycle_never_infers_revoked() -> None:
    source = LIFECYCLE.read_text(encoding="utf-8")
    state_block = source.split("class ConsentLifecycleState", 1)[1].split(
        "@dataclass", 1
    )[0]

    assert "REVOKED" not in state_block
    for state in ("UNKNOWN", "NON_EXPIRING", "VALID", "EXPIRING", "EXPIRED"):
        assert f'{state} = "{state}"' in state_block


def test_consent_lifecycle_uses_injected_clock_and_explicit_policy() -> None:
    source = LIFECYCLE.read_text(encoding="utf-8")

    assert "warning_window: timedelta" in source
    assert "clock: ConsentClock" in source
    assert "self._clock()" in source
    assert "datetime.now" not in source
    assert "datetime.utcnow" not in source


def test_banking_provider_contract_is_not_expanded_with_consent_mutation() -> None:
    provider = PROVIDER.read_text(encoding="utf-8").lower()

    assert "renew_consent" not in provider
    assert "renewal_consent" not in provider
    assert "consent_renewal(" not in provider
