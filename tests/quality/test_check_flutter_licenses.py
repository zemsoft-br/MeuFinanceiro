from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "infra"
    / "scripts"
    / "check-flutter-licenses.py"
)


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_flutter_licenses", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_locked_versions_reads_hosted_and_sdk_packages() -> None:
    module = load_module()
    raw = """packages:
  flutter:
    dependency: direct main
    description: flutter
    source: sdk
    version: \"0.0.0\"
  go_router:
    dependency: direct main
    description:
      name: go_router
    source: hosted
    version: \"17.3.0\"
"""

    assert module.parse_locked_versions(raw) == {
        "flutter": "0.0.0",
        "go_router": "17.3.0",
    }


def test_find_package_license_requires_exactly_one_match(tmp_path: Path) -> None:
    module = load_module()
    package = tmp_path / "hosted" / "pub.dev" / "go_router-17.3.0"
    package.mkdir(parents=True)
    license_path = package / "LICENSE"
    license_path.write_text("license", encoding="utf-8")

    assert (
        module.find_package_license(tmp_path, "go_router", "17.3.0")
        == license_path
    )


def test_find_package_license_rejects_missing_file(tmp_path: Path) -> None:
    module = load_module()

    with pytest.raises(module.FlutterLicenseError, match="found 0"):
        module.find_package_license(tmp_path, "go_router", "17.3.0")


def test_require_marker_rejects_unexpected_license(tmp_path: Path) -> None:
    module = load_module()
    license_path = tmp_path / "LICENSE"
    license_path.write_text("custom terms", encoding="utf-8")

    with pytest.raises(module.FlutterLicenseError, match="was not found"):
        module.require_marker(license_path, "MIT License", "MIT")


def test_validate_licenses_reports_direct_packages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_module()
    sdk_license = tmp_path / "flutter-LICENSE"
    sdk_license.write_text(module.BSD_MARKER, encoding="utf-8")

    package_licenses: dict[tuple[str, str], Path] = {}
    for package, policy in module.DIRECT_PACKAGES.items():
        path = tmp_path / f"{package}-{policy.version}-LICENSE"
        path.write_text(policy.required_marker, encoding="utf-8")
        package_licenses[(package, policy.version)] = path

    monkeypatch.setattr(
        module,
        "load_locked_versions",
        lambda: {
            package: policy.version
            for package, policy in module.DIRECT_PACKAGES.items()
        },
    )
    monkeypatch.setattr(module, "pub_cache_root", lambda: tmp_path)
    monkeypatch.setattr(module, "flutter_sdk_license", lambda: sdk_license)
    monkeypatch.setattr(
        module,
        "find_package_license",
        lambda cache, package, version: package_licenses[(package, version)],
    )

    reports = module.validate_licenses()

    assert len(reports) == 1 + len(module.DIRECT_PACKAGES)
    assert reports[0].startswith("flutter-sdk\tBSD-3-Clause")
    assert any(
        report.startswith("flutter_riverpod@3.3.2\tMIT") for report in reports
    )
