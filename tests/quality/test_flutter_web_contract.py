from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra" / "scripts" / "check-flutter-web-contract.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_flutter_web_contract", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flutter_web_source_contract() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--source-only"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_generated_loader_accepts_inactive_remote_fallback_with_local_engine(
    tmp_path: Path,
) -> None:
    module = load_module()
    bootstrap = tmp_path / "flutter_bootstrap.js"
    bootstrap.write_text(
        'const fallback = "https://www.gstatic.com/flutter-canvaskit";'
        '_flutter.buildConfig={"useLocalCanvasKit":true};',
        encoding="utf-8",
    )
    for relative in module.REQUIRED_LOCAL_ENGINE_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    module.validate_local_flutter_engine(tmp_path)


def test_generated_loader_rejects_remote_engine_configuration(tmp_path: Path) -> None:
    module = load_module()
    bootstrap = tmp_path / "flutter_bootstrap.js"
    bootstrap.write_text(
        '_flutter.buildConfig={"useLocalCanvasKit":false};',
        encoding="utf-8",
    )

    with pytest.raises(module.FlutterWebContractError, match="local CanvasKit"):
        module.validate_local_flutter_engine(tmp_path)


def test_project_owned_bootstrap_rejects_remote_runtime_origin(tmp_path: Path) -> None:
    module = load_module()
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "app_bootstrap.js").write_text(
        "fetch('https://www.gstatic.com/runtime.js')",
        encoding="utf-8",
    )

    with pytest.raises(module.FlutterWebContractError, match="remote runtime origins"):
        module.validate_project_owned_files_have_no_remote_origins(tmp_path)
