from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from urllib.request import Request

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/pluggy-spike/pluggy_spike.py"
GITIGNORE = ROOT / ".gitignore"
LAB_DOC = ROOT / "docs/spikes/PLUGGY_SANDBOX_LAB.md"
CONTRACT_DOC = ROOT / "docs/architecture/BANKING_PROVIDER_CONTRACT.md"
QUALITY_RUNNER = ROOT / "infra/scripts/run-quality.py"
QUALITY_WORKFLOW = ROOT / ".github/workflows/quality.yml"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pluggy_spike", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_spike_is_isolated_and_ignored() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "from dotenv" not in source
    assert "requests" not in source
    assert '"/items"' not in source
    assert 'LOOPBACK_HOST = "127.0.0.1"' in source
    assert ".pluggy-spike/" in GITIGNORE.read_text(encoding="utf-8")
    assert LAB_DOC.is_file()
    assert CONTRACT_DOC.is_file()


def test_client_uses_widget_flow_without_direct_item_creation() -> None:
    module = load_module()
    calls: list[tuple[str, str, dict[str, str]]] = []

    def transport(request: Request, timeout: float) -> bytes:
        assert timeout == 15.0
        calls.append((request.method, request.full_url, dict(request.headers)))
        if request.full_url.endswith("/auth"):
            return json.dumps({"accessToken": "api-key-secret"}).encode()
        if "/connectors?" in request.full_url:
            return json.dumps(
                {"results": [{"id": 1, "name": "Pluggy Bank", "sandbox": True}]}
            ).encode()
        if request.full_url.endswith("/connect_token"):
            return json.dumps({"accessToken": "connect-token-secret"}).encode()
        raise AssertionError(request.full_url)

    credentials = module.Credentials("client-id-secret", "client-secret-secret")
    client = module.PluggyClient(
        credentials, transport=transport, sleeper=lambda _: None
    )
    api_key = client.authenticate()
    connectors = client.list_sandbox_connectors(api_key)
    connect_token = client.create_connect_token(api_key, "sandbox-test")

    assert api_key == "api-key-secret"
    assert connect_token == "connect-token-secret"
    assert module.metadata_inventory(connectors)["record_count"] == 1
    assert not any(
        method == "POST" and url.endswith("/items")
        for method, url, _ in calls
    )


def test_reports_drop_values_and_reject_tokens(tmp_path: Path) -> None:
    module = load_module()
    item = {
        "id": "item-sensitive",
        "status": "UPDATED",
        "executionStatus": "SUCCESS",
        "owner": "Pessoa Sensível",
    }
    products = {
        "accounts": {
            "results": [
                {
                    "id": "account-sensitive",
                    "number": "12345-6",
                    "balance": 999.99,
                    "owner": "Pessoa Sensível",
                }
            ]
        }
    }
    report = module.collection_report(
        item_id="item-sensitive",
        item=item,
        products=products,
        salt=b"fixed-test-salt",
    )
    output = tmp_path / "report.json"
    module.write_report(
        report,
        output,
        forbidden_values=(
            "item-sensitive",
            "account-sensitive",
            "12345-6",
            "Pessoa Sensível",
            "999.99",
        ),
    )
    rendered = output.read_text(encoding="utf-8")
    assert "item-sensitive" not in rendered
    assert "account-sensitive" not in rendered
    assert "Pessoa Sensível" not in rendered
    assert "999.99" not in rendered
    assert '"record_count": 1' in rendered
    assert "balance" in rendered
    assert "owner" in rendered


def test_report_scanner_rejects_sensitive_keys_and_jwt() -> None:
    module = load_module()
    try:
        module.validate_report({"accessToken": "not-even-needed"})
    except module.SpikeError:
        pass
    else:
        raise AssertionError("Sensitive key was accepted")

    jwt = "eyJaaaaaaaaaa.bbbbbbbbbb.cccccccccc"
    try:
        module.validate_report({"value": jwt})
    except module.SpikeError:
        pass
    else:
        raise AssertionError("JWT-like value was accepted")


def test_api_base_override_is_test_only() -> None:
    module = load_module()
    assert module.resolve_api_base(None, {}) == module.API_BASE
    try:
        module.resolve_api_base("http://127.0.0.1:9999", {})
    except module.SpikeError:
        pass
    else:
        raise AssertionError("Unsafe API base override was accepted")
    assert (
        module.resolve_api_base(
            "http://127.0.0.1:9999",
            {"PLUGGY_SPIKE_ALLOW_TEST_API_BASE": "1"},
        )
        == "http://127.0.0.1:9999"
    )


def test_widget_contains_only_sandbox_configuration() -> None:
    module = load_module()
    page = module._widget_html("connect-token-secret").decode("utf-8")
    assert "includeSandbox: true" in page
    assert "127.0.0.1" not in page
    assert "user-ok" in page
    assert "password-ok" in page
    assert "123456" in page
    assert "console.log" not in page


def test_transient_failures_use_bounded_retry() -> None:
    module = load_module()
    attempts = 0
    sleeps: list[float] = []

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal attempts
        del request, timeout
        attempts += 1
        if attempts < 3:
            raise TimeoutError
        return json.dumps({"accessToken": "api-key-secret"}).encode()

    client = module.PluggyClient(
        module.Credentials("client", "secret"),
        transport=transport,
        sleeper=sleeps.append,
    )
    assert client.authenticate() == "api-key-secret"
    assert attempts == 3
    assert sleeps == [0.25, 0.5]


def test_callback_store_allows_only_bounded_metadata(tmp_path: Path) -> None:
    module = load_module()
    session = tmp_path / "session.json"
    store = module.CallbackStore(session)
    store.save(
        {
            "outcome": "secret-value",
            "itemId": "not-a-uuid-secret",
            "executionStatus": "STATUS_WITH_SECRET=abc",
        }
    )
    payload = json.loads(session.read_text(encoding="utf-8"))
    assert payload["outcome"] == "unknown"
    assert payload["item_id"] is None
    assert payload["execution_status"] is None

    valid_item = "12345678-1234-5678-1234-567812345678"
    store.save(
        {
            "outcome": "success",
            "itemId": valid_item,
            "executionStatus": "SUCCESS",
        }
    )
    payload = json.loads(session.read_text(encoding="utf-8"))
    assert payload["outcome"] == "success"
    assert payload["item_id"] == valid_item
    assert payload["execution_status"] == "SUCCESS"


def test_outputs_are_restricted_to_ignored_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    monkeypatch.chdir(tmp_path)
    expected = (tmp_path / ".pluggy-spike" / "report.json").resolve()
    assert module.local_output_path(Path(".pluggy-spike/report.json")) == expected
    try:
        module.local_output_path(Path("outside.json"))
    except module.SpikeError:
        pass
    else:
        raise AssertionError("Output outside .pluggy-spike was accepted")


def test_main_quality_gates_check_spike_source() -> None:
    quality = QUALITY_RUNNER.read_text(encoding="utf-8")
    workflow = QUALITY_WORKFLOW.read_text(encoding="utf-8")
    for content in (quality, workflow):
        assert "tools/pluggy-spike" in content
        assert "tools/pluggy-spike/pluggy_spike.py" in content
