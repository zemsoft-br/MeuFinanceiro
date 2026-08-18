from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERSISTENCE = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/banking_disconnect_store.py"
)
SYNC_STORE = (
    ROOT / "packages/persistence/src/meufinanceiro_persistence/banking_sync_store.py"
)
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


def test_disconnect_observes_provider_before_transaction_commit() -> None:
    orchestration = ORCHESTRATION.read_text(encoding="utf-8")

    observe = orchestration.index("self._provider.get_connection(")
    mutate = orchestration.index("self._provider.disconnect(")
    assert observe < mutate
    assert "remote.status is ConnectionStatus.DISCONNECTED" in orchestration
    assert "LOCAL_FINALIZATION_PENDING" in orchestration
    assert "recovered_from_provider_state = True" in orchestration


def test_disconnect_and_sync_start_serialize_on_connection_row() -> None:
    persistence = PERSISTENCE.read_text(encoding="utf-8")
    sync_store = SYNC_STORE.read_text(encoding="utf-8")

    assert "connection_disconnection_transaction" in persistence
    assert "for_update=True" in persistence
    assert "yield local" in persistence
    assert "_finalize_on_connection(" in persistence
    assert "connection_status = _require_connection(" in sync_store
    sync_begin = sync_store.split("def begin_manual_sync(", 1)[1].split(
        "def mark_sync_running(", 1
    )[0]
    assert "for_update=True" in sync_begin
    assert "pg_advisory" not in persistence


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
    result_block = orchestration.split("class BankingDisconnectResult", 1)[1].split(
        "class ConnectionDisconnectionStore", 1
    )[0]
    assert "external_connection_id" not in result_block
