from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "packages/banking-sync"
SERVICE = (PACKAGE / "src/meufinanceiro_banking_sync/service.py").read_text(
    encoding="utf-8"
)
MODELS = (PACKAGE / "src/meufinanceiro_banking_sync/models.py").read_text(
    encoding="utf-8"
)
PYPROJECT = (PACKAGE / "pyproject.toml").read_text(encoding="utf-8")
OBSERVATION_STORE = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/banking_observation_store.py"
).read_text(encoding="utf-8")
QUALITY = (ROOT / "infra/scripts/run-quality.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
LICENSES = (ROOT / "infra/scripts/check-python-licenses.py").read_text(encoding="utf-8")


def test_manual_sync_package_is_provider_neutral() -> None:
    combined = f"{SERVICE}\n{MODELS}\n{PYPROJECT}"
    for forbidden in (
        "meufinanceiro_banking_pluggy",
        "Pluggy",
        "httpx",
        "FastAPI",
        "APIRouter",
        "apps.worker",
        "meufinanceiro_worker",
    ):
        assert forbidden not in combined

    assert '"meufinanceiro-banking==0.1.0"' in PYPROJECT
    assert '"meufinanceiro-persistence==0.1.0"' in PYPROJECT
    dependency_block = PYPROJECT.split("dependencies = [", maxsplit=1)[1].split(
        "]", maxsplit=1
    )[0]
    assert dependency_block.count('"') == 4


def test_manual_sync_uses_only_contextual_local_identifiers() -> None:
    assert "installation_id: UUID" in SERVICE
    assert "residence_id: UUID" in SERVICE
    assert "connection_id: UUID" in SERVICE
    for forbidden in (
        "item_id",
        "client_user_id",
        "clientUserId",
        "client_secret",
        "accessToken",
        "connectToken",
    ):
        assert forbidden not in SERVICE


def test_bounded_full_scan_and_cursor_priority_are_explicit() -> None:
    assert "max_accounts_per_run: int = 20" in MODELS
    assert "max_pages_per_run: int = 20" in MODELS
    assert "max_records_per_run: int = 5_000" in MODELS
    assert "changed_since=None" in SERVICE
    assert "_prioritize_accounts_with_cursors" in SERVICE
    assert "pending if cursor is not None else fresh" in SERVICE
    assert "page.next_cursor" in SERVICE
    assert "next_cursor in seen_cursors" in SERVICE
    assert "ManualSyncStopReason.ACCOUNT_LIMIT" in SERVICE
    assert "ManualSyncStopReason.PAGE_LIMIT" in SERVICE
    assert "ManualSyncStopReason.RECORD_LIMIT" in SERVICE


def test_transaction_status_and_provider_error_maps_are_explicit() -> None:
    for status in ("CONFIRMED", "PENDING", "INFERRED", "DELETED"):
        assert f"TransactionStatus.{status}" in SERVICE
        assert f"StoredTransactionObservationStatus.{status}" in SERVICE
    for category in (
        "AUTHENTICATION",
        "AUTHORIZATION",
        "NOT_FOUND",
        "INVALID_REQUEST",
        "REQUIRES_USER_ACTION",
        "RATE_LIMITED",
        "TEMPORARILY_UNAVAILABLE",
        "CONFLICT",
        "UNSUPPORTED",
        "INTERNAL",
    ):
        assert f"ProviderErrorCategory.{category}" in SERVICE
        assert f"StoredSyncErrorCategory.{category}" in SERVICE


def test_terminal_page_clears_recovery_checkpoint_atomically() -> None:
    signature = OBSERVATION_STORE.split(
        "def apply_transaction_page",
        maxsplit=1,
    )[1].split("def _set_context", maxsplit=1)[0]
    assert "cursor: str | None" in signature
    assert "_commit_cursor(" in signature
    assert "cursor=normalized_cursor" in signature

    commit_cursor = OBSERVATION_STORE.split("def _commit_cursor", maxsplit=1)[1].split(
        "def _locked_cursor", maxsplit=1
    )[0]
    assert "if cursor is None:" in commit_cursor
    assert "delete(sync_cursors)" in commit_cursor
    assert "previous_committed_at >= committed_at" in commit_cursor


def test_result_representation_redacts_operational_and_financial_material() -> None:
    result_class = MODELS.split("class ManualSyncResult", maxsplit=1)[1].split(
        "class ManualSyncExecutionError", maxsplit=1
    )[0]
    representation = result_class.split("def __repr__", maxsplit=1)[1]
    assert "self.sync_run_id" not in representation
    assert "<sync-run-id-redacted>" in representation
    for forbidden in (
        "cursor",
        "external_account",
        "external_transaction",
        "fingerprint",
        "amount",
        "description",
    ):
        assert forbidden not in result_class.lower()


def test_quality_and_license_inventory_include_manual_sync_package() -> None:
    for source in (QUALITY, WORKFLOW):
        assert "packages/banking-sync" in source
        assert "packages/banking-sync/src" in source
        assert "packages/banking-sync/tests" in source
    assert "meufinanceiro-banking-sync" in LICENSES
