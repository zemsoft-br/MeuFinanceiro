from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError
from urllib.request import Request

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/pluggy-spike/pluggy_auth_lifecycle.py"
RUNBOOK = ROOT / "docs/spikes/PLUGGY_AUTH_LIFECYCLE_LAB.md"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pluggy_auth_lifecycle", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def http_error(
    request: Request, status_code: int, headers: dict[str, str] | None = None
) -> HTTPError:
    return HTTPError(request.full_url, status_code, "Error", headers, None)


def test_auth_lifecycle_is_documented_read_only_and_quality_checked() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert RUNBOOK.is_file()
    assert '"/items"' not in source
    assert '"PATCH"' not in source
    assert '"DELETE"' not in source
    assert "import requests" not in source
    assert "from requests" not in source
    assert "dotenv" not in source


def test_initial_authentication_and_read_only_probe_are_sanitized() -> None:
    module = load_module()
    calls: list[tuple[str, str, str | None]] = []

    def transport(request: Request, timeout: float) -> bytes:
        assert timeout == 15.0
        calls.append(
            (request.method, request.full_url, request.get_header("X-api-key"))
        )
        if request.full_url.endswith("/auth"):
            return json.dumps({"apiKey": "api-key-secret"}).encode()
        if "/connectors?" in request.full_url:
            return json.dumps(
                {"results": [{"id": 1, "name": "Pluggy Bank", "sandbox": True}]}
            ).encode()
        raise AssertionError(request.full_url)

    trace = module.RequestTrace()
    client = module.AuthLifecycleClient(
        module.Credentials("client-id-secret", "client-secret-secret"),
        transport=transport,
        sleeper=lambda _: None,
        jitter=lambda _: 0.0,
    )
    api_key = client.authenticate(trace)
    connectors, active_key = client.list_connectors_with_refresh(api_key, trace)
    report = module.lifecycle_report(
        connectors,
        trace,
        expiration_probe_requested=False,
        expiration_observed=False,
        expiration_wait_seconds=None,
    )
    rendered = module.validate_report(
        report,
        forbidden_values=(
            "client-id-secret",
            "client-secret-secret",
            *client.issued_api_keys,
        ),
    )

    assert active_key == "api-key-secret"
    assert trace.attempts == 2
    assert trace.auth_refreshes == 0
    assert report["connectors"]["record_count"] == 1
    assert "api-key-secret" not in rendered
    assert "client-secret-secret" not in rendered
    assert calls[0][0] == "POST"
    assert calls[1][0] == "GET"


def test_401_refreshes_api_key_exactly_once() -> None:
    module = load_module()
    auth_count = 0
    connector_count = 0
    connector_keys: list[str | None] = []

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal auth_count, connector_count
        del timeout
        if request.full_url.endswith("/auth"):
            auth_count += 1
            return json.dumps({"apiKey": f"api-key-{auth_count}"}).encode()
        if "/connectors?" in request.full_url:
            connector_count += 1
            connector_keys.append(request.get_header("X-api-key"))
            if connector_count == 1:
                raise http_error(request, 401)
            return json.dumps({"results": []}).encode()
        raise AssertionError(request.full_url)

    trace = module.RequestTrace()
    client = module.AuthLifecycleClient(
        module.Credentials("client", "secret"),
        transport=transport,
        sleeper=lambda _: None,
        jitter=lambda _: 0.0,
    )
    first_key = client.authenticate(trace)
    _, active_key = client.list_connectors_with_refresh(first_key, trace)

    assert first_key == "api-key-1"
    assert active_key == "api-key-2"
    assert auth_count == 2
    assert connector_count == 2
    assert connector_keys == ["api-key-1", "api-key-2"]
    assert trace.auth_refreshes == 1
    assert trace.status_counts == {"401": 1}


def test_second_401_stops_without_refresh_loop() -> None:
    module = load_module()
    auth_count = 0
    connector_count = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal auth_count, connector_count
        del timeout
        if request.full_url.endswith("/auth"):
            auth_count += 1
            return json.dumps({"apiKey": f"api-key-{auth_count}"}).encode()
        connector_count += 1
        raise http_error(request, 401)

    trace = module.RequestTrace()
    client = module.AuthLifecycleClient(
        module.Credentials("client", "secret"),
        transport=transport,
        sleeper=lambda _: None,
        jitter=lambda _: 0.0,
    )
    key = client.authenticate(trace)

    with pytest.raises(module.SpikeError, match="uma única renovação"):
        client.list_connectors_with_refresh(key, trace)

    assert auth_count == 2
    assert connector_count == 2
    assert trace.auth_refreshes == 1
    assert trace.status_counts == {"401": 2}


def test_429_prefers_rate_limit_reset_and_retries_once() -> None:
    module = load_module()
    calls = 0
    sleeps: list[float] = []

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        del timeout
        calls += 1
        if calls == 1:
            raise http_error(
                request,
                429,
                {"RateLimit-Reset": "2", "Retry-After": "60"},
            )
        return json.dumps({"results": []}).encode()

    trace = module.RequestTrace()
    client = module.AuthLifecycleClient(
        module.Credentials("client", "secret"),
        transport=transport,
        sleeper=sleeps.append,
        jitter=lambda _: 0.0,
    )
    payload, _ = client.list_connectors_with_refresh("api-key", trace)

    assert payload == {"results": []}
    assert calls == 2
    assert sleeps == [2.0]
    assert trace.retry_after_observed
    assert trace.rate_limit_reset_observed
    assert trace.wait_buckets == {"ONE_TO_FIVE_SECONDS": 1}


def test_429_uses_retry_after_when_reset_is_absent() -> None:
    module = load_module()
    calls = 0
    sleeps: list[float] = []

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        del timeout
        calls += 1
        if calls == 1:
            raise http_error(request, 429, {"Retry-After": "60"})
        return json.dumps({"results": []}).encode()

    trace = module.RequestTrace()
    client = module.AuthLifecycleClient(
        module.Credentials("client", "secret"),
        transport=transport,
        sleeper=sleeps.append,
        jitter=lambda _: 0.0,
    )
    client.list_connectors_with_refresh("api-key", trace)

    assert calls == 2
    assert sleeps == [60.0]
    assert trace.wait_buckets == {"THIRTY_ONE_TO_SIXTY_SECONDS": 1}


def test_429_without_usable_window_does_not_retry() -> None:
    module = load_module()
    calls = 0
    sleeps: list[float] = []

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        del timeout
        calls += 1
        raise http_error(request, 429, {"Retry-After": "invalid"})

    trace = module.RequestTrace()
    client = module.AuthLifecycleClient(
        module.Credentials("client", "secret"),
        transport=transport,
        sleeper=sleeps.append,
        jitter=lambda _: 0.0,
    )

    with pytest.raises(module.SpikeError, match="sem janela segura"):
        client.list_connectors_with_refresh("api-key", trace)

    assert calls == 1
    assert sleeps == []


def test_5xx_and_network_failures_use_bounded_exponential_backoff() -> None:
    module = load_module()
    server_calls = 0
    server_sleeps: list[float] = []

    def server_transport(request: Request, timeout: float) -> bytes:
        nonlocal server_calls
        del timeout
        server_calls += 1
        if server_calls < 3:
            raise http_error(request, 500)
        return json.dumps({"results": []}).encode()

    trace = module.RequestTrace()
    client = module.AuthLifecycleClient(
        module.Credentials("client", "secret"),
        transport=server_transport,
        sleeper=server_sleeps.append,
        jitter=lambda _: 0.0,
    )
    client.list_connectors_with_refresh("api-key", trace)

    assert server_calls == 3
    assert server_sleeps == [0.5, 1.0]
    assert trace.transient_failures == 2

    network_calls = 0
    network_sleeps: list[float] = []

    def network_transport(request: Request, timeout: float) -> bytes:
        nonlocal network_calls
        del request, timeout
        network_calls += 1
        raise TimeoutError

    network_trace = module.RequestTrace()
    network_client = module.AuthLifecycleClient(
        module.Credentials("client", "secret"),
        transport=network_transport,
        sleeper=network_sleeps.append,
        jitter=lambda _: 0.0,
    )
    with pytest.raises(module.SpikeError, match="rede ou timeout"):
        network_client.list_connectors_with_refresh("api-key", network_trace)

    assert network_calls == 3
    assert network_sleeps == [0.5, 1.0]
    assert network_trace.transient_failures == 3


@pytest.mark.parametrize("status_code", [400, 404])
def test_functional_http_errors_are_not_retried(status_code: int) -> None:
    module = load_module()
    calls = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        del timeout
        calls += 1
        raise http_error(request, status_code)

    trace = module.RequestTrace()
    client = module.AuthLifecycleClient(
        module.Credentials("client", "secret"),
        transport=transport,
        sleeper=lambda _: None,
        jitter=lambda _: 0.0,
    )
    with pytest.raises(module.SpikeError, match=f"HTTP {status_code}"):
        client.list_connectors_with_refresh("api-key", trace)
    assert calls == 1


def test_report_uses_only_coarse_expiration_and_wait_metadata() -> None:
    module = load_module()
    trace = module.RequestTrace(
        attempts=4,
        authentication_requests=2,
        resource_requests=2,
        auth_refreshes=1,
        status_counts={"401": 1},
        wait_buckets={"ONE_TO_FIVE_SECONDS": 1},
    )
    report = module.lifecycle_report(
        {"results": []},
        trace,
        expiration_probe_requested=True,
        expiration_observed=True,
        expiration_wait_seconds=7260.0,
    )
    rendered = module.validate_report(report)

    assert report["authentication"]["expiration_wait_bucket"] == (
        "TWO_HOURS_OR_MORE"
    )
    assert "7260" not in rendered
    assert "X-API-KEY" not in rendered
    assert report["privacy"]["api_key_persisted"] is False


def test_script_type_checks_strictly() -> None:
    if importlib.util.find_spec("mypy") is None:
        pytest.skip("mypy is installed by the mandatory quality environment")
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
