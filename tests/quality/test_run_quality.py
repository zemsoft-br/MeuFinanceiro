from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra" / "scripts" / "run-quality.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_quality", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_313_is_supported() -> None:
    module = load_module()

    module.validate_python_version((3, 13))


@pytest.mark.parametrize("version", [(3, 12), (3, 14), (4, 0)])
def test_unsupported_python_versions_are_rejected(version: tuple[int, int]) -> None:
    module = load_module()

    with pytest.raises(RuntimeError, match="Python 3.13.x is required"):
        module.validate_python_version(version)
