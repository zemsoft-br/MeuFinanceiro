from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra" / "scripts" / "check-flutter-licenses.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_flutter_licenses", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pub_cache_override_has_priority(tmp_path: Path) -> None:
    module = load_module()
    configured = tmp_path / "custom-cache"

    result = module.pub_cache_root(
        {
            "PUB_CACHE": str(configured),
            "LOCALAPPDATA": str(tmp_path / "Local"),
        },
        platform="nt",
        home=tmp_path / "home",
    )

    assert result == configured.resolve()


def test_windows_pub_cache_uses_local_app_data(tmp_path: Path) -> None:
    module = load_module()
    local_app_data = tmp_path / "Local"

    result = module.pub_cache_root(
        {"LOCALAPPDATA": str(local_app_data)},
        platform="nt",
        home=tmp_path / "home",
    )

    assert result == (local_app_data / "Pub" / "Cache").resolve()


def test_posix_pub_cache_uses_home_directory(tmp_path: Path) -> None:
    module = load_module()
    home = tmp_path / "home"

    result = module.pub_cache_root({}, platform="posix", home=home)

    assert result == (home / ".pub-cache").resolve()
