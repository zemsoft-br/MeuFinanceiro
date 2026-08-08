from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/app"
LIB = APP / "lib"
WEB = APP / "web"
PLUGGY_ROOT = LIB / "features/banking/pluggy/connect"
REAUTH_ROOT = LIB / "features/banking/pluggy/reauthentication"
ADAPTER = LIB / "platform/pluggy/pluggy_connect_launcher_web.dart"
CONTROLLER = PLUGGY_ROOT / "pluggy_connect_controller.dart"
REAUTH_CONTROLLER = REAUTH_ROOT / "pluggy_reauthentication_controller.dart"
API = PLUGGY_ROOT / "pluggy_connect_api.dart"
PUBSPEC = APP / "pubspec.yaml"
PUBSPEC_LOCK = APP / "pubspec.lock"


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
    assert "Duration(seconds: 15)" in source
    assert "Timer(_scriptLoadTimeout" in source
    assert "'language': 'pt'" in source
    assert "'countries': ['BR']" in source
    assert "'includeSandbox': false" in source
    assert "if (normalizedUpdateItem != null) 'updateItem': normalizedUpdateItem" in source
    assert "_validateItemId(updateItem)" in source

    for forbidden in (
        "clientUserId",
        "forceAskForCredentials",
        "webhookUrl",
        "oauthRedirectUri",
        "selectedConnectorId",
        "connectorIds",
        "products",
    ):
        assert forbidden not in source


def test_create_flow_never_supplies_update_item() -> None:
    controller = _read(CONTROLLER)
    reauthentication = _read(REAUTH_CONTROLLER)

    assert "updateItem:" not in controller
    assert "updateItem: launchMaterial.updateItem" in reauthentication
    assert "issueReauthenticationMaterial(connectionId)" in reauthentication


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
    assert "flutter_pluggy_connect" not in _read(PUBSPEC)
    assert "flutter_pluggy_connect" not in _read(PUBSPEC_LOCK)


def test_callback_is_reduced_to_transient_item_id_before_backend() -> None:
    api = _read(API)
    adapter = _read(ADAPTER)
    controller = _read(CONTROLLER)
    reauthentication = _read(REAUTH_CONTROLLER)

    assert "payload['item']" in adapter
    assert "data['item']" in adapter
    assert "item['id']" in adapter
    on_error = adapter.split("'onError':", 1)[1].split("}),", 1)[0]
    assert "PluggyConnectCallback.itemAvailable(extraction.itemId)" in on_error
    assert "jsonBody: {'itemId': normalizedItemId}" in api
    assert "banking/pluggy/connections" in api
    assert "itemId != expectedItem" in reauthentication

    for source in (controller, reauthentication):
        for forbidden in (
            "clientUserId",
            "executionStatus",
            "connector",
            "account",
            "institution",
        ):
            assert forbidden not in source

    state_source = controller.split("class PluggyConnectState", 1)[1].split(
        "final pluggyConnectLauncherProvider", 1
    )[0]
    reauth_state = reauthentication.split(
        "class PluggyReauthenticationState", 1
    )[1].split("final pluggyReauthenticationLauncherProvider", 1)[0]
    assert "connectToken" not in state_source
    assert "itemId" not in state_source
    assert "connectToken" not in reauth_state
    assert "itemId" not in reauth_state


def test_connect_token_and_item_id_are_not_persisted_or_logged() -> None:
    production_sources = "\n".join(
        [
            *(_read(path) for path in sorted(PLUGGY_ROOT.glob("*.dart"))),
            *(_read(path) for path in sorted(REAUTH_ROOT.glob("*.dart"))),
            _read(ADAPTER),
        ]
    )

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
    assert "EphemeralPluggyUpdateMaterial(<redacted>)" in production_sources
    assert "PluggyUpdateLaunchMaterial(<redacted>)" in production_sources
    assert "PluggyConnectCallback(${type.name}, <redacted>)" in _read(
        LIB / "core/banking/pluggy/pluggy_connect_launcher_contract.dart"
    )


def test_client_never_supplies_residence_or_provider_ownership_scope() -> None:
    production = "\n".join(
        _read(path)
        for path in sorted(
            [
                *PLUGGY_ROOT.glob("*.dart"),
                *REAUTH_ROOT.glob("*.dart"),
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

    reauthentication = _read(REAUTH_CONTROLLER)
    reauth_demo = reauthentication.index("demoStatus.enabled")
    reauth_token = reauthentication.index("issueReauthenticationMaterial(connectionId)")
    reauth_launcher = reauthentication.index(".launch(")

    assert demo_check < token_issue < launcher
    assert reauth_demo < reauth_token < reauth_launcher
    assert "PluggyConnectPhase.demoUnavailable" in controller
    assert "PluggyReauthenticationPhase.demoUnavailable" in reauthentication


def test_service_worker_never_caches_api_or_cross_origin_provider_resources() -> None:
    worker = _read(WEB / "sw.js")
    assert "url.origin !== self.location.origin" in worker
    assert "url.pathname === '/api'" in worker
    assert "url.pathname.startsWith('/api/')" in worker
    assert "cdn.pluggy.ai" not in worker
