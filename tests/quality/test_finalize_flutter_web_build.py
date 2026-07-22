from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra" / "scripts" / "finalize-flutter-web-build.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("finalize_flutter_web_build", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_absent_legacy_worker_requires_no_change(tmp_path: Path) -> None:
    module = load_module()

    assert module.remove_empty_legacy_worker(tmp_path) is False


def test_empty_legacy_worker_is_removed(tmp_path: Path) -> None:
    module = load_module()
    worker = tmp_path / module.LEGACY_WORKER_NAME
    worker.touch()

    assert module.remove_empty_legacy_worker(tmp_path) is True
    assert not worker.exists()


def test_non_empty_legacy_worker_is_rejected(tmp_path: Path) -> None:
    module = load_module()
    worker = tmp_path / module.LEGACY_WORKER_NAME
    worker.write_text("self.addEventListener('fetch', () => {})", encoding="utf-8")

    with pytest.raises(module.FlutterWebFinalizationError, match="contains"):
        module.remove_empty_legacy_worker(tmp_path)

    assert worker.exists()


def test_copied_script_accepts_explicit_build_directory(tmp_path: Path) -> None:
    copied_script = tmp_path / "finalize-flutter-web-build.py"
    copied_script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    build_dir = tmp_path / "build" / "web"
    build_dir.mkdir(parents=True)

    result = subprocess.run(
        [
            sys.executable,
            str(copied_script),
            "--build-dir",
            str(build_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "no legacy worker present" in result.stdout
