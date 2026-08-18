from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERSISTENCE = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/banking_disconnect_store.py"
)
LOCK = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/banking_connection_lock.py"
)
PUBLIC_STORE = ROOT / "packages/persistence/src/meufinanceiro_persistence/banking.py"
ORCHESTRATION = (
    ROOT / "packages/banking-sync/src/meufinanceiro_banking_sync/disconnect.py"
)
REAUTH = (
    ROOT
    / "packages/banking-pluggy-execution/src/"
    "meufinanceiro_banking_pluggy_execution/reauthentication.py"
)


def test_disconnect_is_provider_neutral_and_history_preserving() -> None:
    persistence = PERSISTENCE.read_text(encoding="utf-8")
    orchestration = ORCHESTRATION.read_text(encoding="utf-8")
    combined = (persistence + orchestration).lower()

    assert "pluggy" not in combined
    assert "delete(" not in persistence
    assert "update(external_accounts)" in persistence
    assert "update(connections)" in persistence
    assert "StoredExternalAccountStatus.DISCONNECTED" in persistence
    assert "StoredConnectionStatus.DISCONNECTED" in persistence
    assert "provider_reason_code=None" in persistence
    assert "next_refresh_allowed_at=None" in persistence


def test_disconnect_observes_provider_before_destructive_mutation() -> None:
    orchestration = ORCHESTRATION.read_text(encoding="utf-8")

    observe = orchestration.index("self._provider.get_connection(")
    mutate = orchestration.index("self._provider.disconnect(")
    finalize = orchestration.index("self._finalize_local(", mutate)
    assert observe < mutate < finalize
    assert "remote.status is ConnectionStatus.DISCONNECTED" in orchestration
    assert "LOCAL_FINALIZATION_PENDING" in orchestration
    assert "recovered_from_provider_state=True" in orchestration


def test_disconnect_and_sync_start_share_one_advisory_lock_contract() -> None:
    persistence = PERSISTENCE.read_text(encoding="utf-8")
    lock = LOCK.read_text(encoding="utf-8")
    public_store = PUBLIC_STORE.read_text(encoding="utf-8")

    assert "connection_operation_lock_key(connection_id)" in persistence
    assert "pg_advisory_lock" in persistence
    assert "pg_advisory_unlock" in persistence
    assert "hold_connection_disconnection_lock" in persistence
    assert "hold_connection_sync_start_lock" in persistence
    assert "hold_connection_sync_start_lock" in public_store
    assert "return super().begin_manual_sync(" in public_store
    assert "blake2b(" in lock
    assert "digest_size=8" in lock


def test_disconnect_requires_active_membership_and_reauth_stays_fail_closed() -> None:
    persistence = PERSISTENCE.read_text(encoding="utf-8")
    reauth = REAUTH.read_text(encoding="utf-8")

    assert "household_memberships.c.status == \"active\"" in persistence
    assert "connection.status is StoredConnectionStatus.DISCONNECTED" in reauth
    assert "PluggyReauthenticationErrorCode.CONNECTION_NOT_AVAILABLE" in reauth


def test_disconnect_public_result_and_errors_do_not_expose_external_ids() -> None:
    orchestration = ORCHESTRATION.read_text(encoding="utf-8")

    assert "<connection-id-redacted>" in orchestration
    assert "provider_reason_code" not in orchestration
    assert "external_connection_id" not in orchestration.split(
        "def __repr__(self) -> str:", 1
    )[1].split("class ConnectionDisconnectionStore", 1)[0]
