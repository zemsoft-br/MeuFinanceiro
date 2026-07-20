from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "infra"
    / "scripts"
    / "check-flutter-toolchain.py"
)
PINNED_REVISION = "ee80f08bbf97172ec030b8751ceab557177a34a6"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_flutter_toolchain", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_expected_version_accepts_semver(tmp_path: Path) -> None:
    module = load_module()
    version_file = tmp_path / ".flutter-version"
    version_file.write_text("3.44.6\n", encoding="utf-8")

    assert module.load_expected_version(version_file) == "3.44.6"


def test_load_expected_version_rejects_invalid_value(tmp_path: Path) -> None:
    module = load_module()
    version_file = tmp_path / ".flutter-version"
    version_file.write_text("stable\n", encoding="utf-8")

    with pytest.raises(module.FlutterToolchainError, match="expected X.Y.Z"):
        module.load_expected_version(version_file)


def test_load_expected_revision_accepts_full_sha(tmp_path: Path) -> None:
    module = load_module()
    revision_file = tmp_path / ".flutter-revision"
    revision_file.write_text(f"{PINNED_REVISION}\n", encoding="utf-8")

    assert module.load_expected_revision(revision_file) == PINNED_REVISION


def test_load_expected_revision_rejects_short_sha(tmp_path: Path) -> None:
    module = load_module()
    revision_file = tmp_path / ".flutter-revision"
    revision_file.write_text("ee80f08\n", encoding="utf-8")

    with pytest.raises(module.FlutterToolchainError, match="40 lowercase hex"):
        module.load_expected_revision(revision_file)


def test_parse_machine_identity_reads_version_and_revision() -> None:
    module = load_module()
    payload = json.dumps(
        {
            "frameworkVersion": "3.44.6",
            "frameworkRevision": PINNED_REVISION,
            "channel": "stable",
        }
    )

    assert module.parse_machine_identity(payload) == ("3.44.6", PINNED_REVISION)


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        '{"channel":"stable"}',
        '{"frameworkVersion":"3.44.6","frameworkRevision":"short"}',
    ],
)
def test_parse_machine_identity_rejects_invalid_payload(payload: str) -> None:
    module = load_module()

    with pytest.raises(module.FlutterToolchainError):
        module.parse_machine_identity(payload)


def test_find_flutter_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    monkeypatch.setattr(module.shutil, "which", lambda _: None)

    with pytest.raises(module.FlutterToolchainError, match="not available on PATH"):
        module.find_flutter()


def test_read_installed_identity_reports_command_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()

    def fake_run(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stderr="broken SDK", stdout="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(module.FlutterToolchainError, match="broken SDK"):
        module.read_installed_identity("flutter")


def test_validate_toolchain_rejects_version_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    monkeypatch.setattr(module, "load_expected_version", lambda: "3.44.6")
    monkeypatch.setattr(module, "load_expected_revision", lambda: PINNED_REVISION)
    monkeypatch.setattr(module, "find_flutter", lambda: "/opt/flutter/bin/flutter")
    monkeypatch.setattr(
        module,
        "read_installed_identity",
        lambda _: ("3.44.5", PINNED_REVISION),
    )

    with pytest.raises(module.FlutterToolchainError, match="version mismatch"):
        module.validate_toolchain()


def test_validate_toolchain_rejects_revision_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    monkeypatch.setattr(module, "load_expected_version", lambda: "3.44.6")
    monkeypatch.setattr(module, "load_expected_revision", lambda: PINNED_REVISION)
    monkeypatch.setattr(module, "find_flutter", lambda: "/opt/flutter/bin/flutter")
    monkeypatch.setattr(
        module,
        "read_installed_identity",
        lambda _: ("3.44.6", "a" * 40),
    )

    with pytest.raises(module.FlutterToolchainError, match="revision mismatch"):
        module.validate_toolchain()


def test_main_succeeds_with_matching_toolchain(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_module()
    monkeypatch.setattr(
        module,
        "validate_toolchain",
        lambda: ("3.44.6", PINNED_REVISION, "/opt/flutter/bin/flutter"),
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "validation passed: 3.44.6" in output
    assert PINNED_REVISION in output
