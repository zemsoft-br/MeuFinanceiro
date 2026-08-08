from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/app"
LIB = APP / "lib"
WEB = APP / "web"
PLUGGY_ROOT = LIB / "features/banking/pluggy/connect"
ADAPTER = LIB / "platform/pluggy/pluggy_connect_launcher_web.dart"
CONTROLLER = PLUGGY_ROOT / "pluggy_connect_controller.dart"
API = PLUGGY_ROOT / "pluggy_connect_api.dart"
PUBSPEC = APP / "pubspec.yaml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_web_adapter_uses_exact_lazy_allowlisted_pluggy_asset() -> None:
    source = _read(ADAPTER)

    assert (
        "https://cdn.pluggy.ai/pluggy-connect/v2.8.2/pluggy-connect.js"
        in source
    )
    assert "latest" not in source.lower()
    assert "ScriptElement()" in source
    assert "head.append(script)" in source
    assert "widget.callMethod('init')" in source
    assert "'language': 'pt'" in source
    assert "'countries': ['BR']" in source
    assert "'includeSandbox': false" in source

    for forbidden in (
        "clientUserId",
        "updateItem",
        "webhookUrl",
        "oauthRedirectUri",
        "selectedConnectorId",
        "connectorIds",
        "products",
    ):
        assert forbidden not in source


def test_pluggy_script_is_not_a_static_bootstrap_dependency() -> None:
    for path in (
        WEB / "index.html",
        WEB / "app_bootstrap.js",
        WEB / "sw.js",
        LIB / "main.dart",
        LIB / "app/app.dart",
    ):
        source = _read(path)
        assert "cdn.pluggy.ai" not in source
        assert "pluggy-connect.js" not in source
        assert "pluggy_connect_launcher_web" not in source


def test_web_target_does_not_depend_on_flutter_pluggy_connect_package() -> None:
    pubspec = _read(PUBSPEC)
    assert "flutter_pluggy_connect" not in pubspec


def test_callback_is_reduced_to_transient_item_id_before_backend() -> None:
    api = _read(API)
    adapter = _read(ADAPTER)
    controller = _read(CONTROLLER)

    assert "payload['item']" in adapter
    assert "data['item']" in adapter
    assert "item['id']" in adapter
    assert "jsonBody: {'itemId': normalizedItemId}" in api
    assert "banking/pluggy/connections" in api

    for forbidden in (
        "clientUserId",
        "executionStatus",
        "connector",
        "account",
        "institution",
    ):
        assert forbidden not in controller

    state_source = controller.split("class PluggyConnectState", 1)[1].split(
        "final pluggyConnectLauncherProvider", 1
    )[0]
    assert "connectToken" not in state_source
    assert "itemId" not in state_source


def test_connect_token_and_item_id_are_not_persisted_or_logged() -> None:
    production_sources = "\n".join(
        _read(path) for path in sorted(PLUGGY_ROOT.glob("*.dart"))
    ) + "\n" + _read(ADAPTER)

    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "IndexedDB",
        "SharedPreferences",
        "sqflite",
        "sqlite",
        "debugPrint(",
        "print(",
    ):
        assert forbidden not in production_sources

    assert "EphemeralConnectToken(<redacted>)" in production_sources
    assert "PluggyConnectCallback(${type.name}, <redacted>)" in _read(
        LIB / "core/banking/pluggy/pluggy_connect_launcher_contract.dart"
    )


def test_client_never_supplies_residence_or_provider_ownership_scope() -> None:
    production = "\n".join(
        _read(path)
        for path in sorted(
            [
                *PLUGGY_ROOT.glob("*.dart"),
                LIB / "platform/pluggy/pluggy_connect_launcher_web.dart",
                LIB / "core/banking/pluggy/pluggy_connect_launcher_contract.dart",
            ]
        )
    )
    for forbidden in (
        "clientUserId",
        "installationId",
        "residenceId",
        "primaryResidenceId':",
        "primary_residence_id",
    ):
        assert forbidden not in production


def test_demo_is_checked_before_token_issue_or_launcher_call() -> None:
    controller = _read(CONTROLLER)
    demo_check = controller.index("demoStatus.enabled")
    token_issue = controller.index("issueToken()")
    launcher = controller.index(".launch(")

    assert demo_check < token_issue < launcher
    assert "PluggyConnectPhase.demoUnavailable" in controller


def test_service_worker_never_caches_api_or_cross_origin_provider_resources() -> None:
    worker = _read(WEB / "sw.js")
    assert "url.origin !== self.location.origin" in worker
    assert "url.pathname === '/api'" in worker
    assert "url.pathname.startsWith('/api/')" in worker
    assert "cdn.pluggy.ai" not in worker
