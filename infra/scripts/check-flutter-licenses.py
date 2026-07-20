#!/usr/bin/env python3
"""Validate licenses for the pinned Flutter SDK and direct hosted packages."""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCKFILE = ROOT / "apps" / "app" / "pubspec.lock"
PACKAGE_PATTERN = re.compile(r"^  ([A-Za-z0-9_]+):$")
VERSION_PATTERN = re.compile(r'^    version: "([^"]+)"$')
BSD_MARKER = "Redistribution and use in source and binary forms"


@dataclass(frozen=True)
class DirectPackagePolicy:
    version: str
    license_name: str
    required_marker: str


DIRECT_PACKAGES = {
    "flutter_riverpod": DirectPackagePolicy("3.3.2", "MIT", "MIT License"),
    "go_router": DirectPackagePolicy("17.3.0", "BSD-3-Clause", BSD_MARKER),
    "flutter_lints": DirectPackagePolicy("6.0.0", "BSD-3-Clause", BSD_MARKER),
}


class FlutterLicenseError(RuntimeError):
    """Raised when a direct Flutter dependency license cannot be verified."""


def parse_locked_versions(raw: str) -> dict[str, str]:
    """Parse package versions from the stable subset used by pubspec.lock."""
    versions: dict[str, str] = {}
    current_package: str | None = None

    for line in raw.splitlines():
        package_match = PACKAGE_PATTERN.fullmatch(line)
        if package_match is not None:
            current_package = package_match.group(1)
            continue

        version_match = VERSION_PATTERN.fullmatch(line)
        if current_package is not None and version_match is not None:
            versions[current_package] = version_match.group(1)
            current_package = None

    return versions


def load_locked_versions(path: Path = LOCKFILE) -> dict[str, str]:
    try:
        return parse_locked_versions(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FlutterLicenseError(f"Flutter lockfile not found: {path}") from exc


def pub_cache_root() -> Path:
    configured = os.environ.get("PUB_CACHE")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".pub-cache").resolve()


def find_package_license(cache: Path, package: str, version: str) -> Path:
    candidates = sorted(cache.glob(f"hosted/*/{package}-{version}/LICENSE*"))
    if len(candidates) != 1:
        raise FlutterLicenseError(
            f"expected one license file for {package}@{version} in {cache}, "
            f"found {len(candidates)}"
        )
    return candidates[0]


def flutter_sdk_license() -> Path:
    executable = shutil.which("flutter")
    if executable is None:
        raise FlutterLicenseError("Flutter is not available on PATH")
    sdk_root = Path(executable).resolve().parent.parent
    license_path = sdk_root / "LICENSE"
    if not license_path.is_file():
        raise FlutterLicenseError(f"Flutter SDK license not found: {license_path}")
    return license_path


def require_marker(path: Path, marker: str, description: str) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if marker not in text:
        raise FlutterLicenseError(
            f"expected {description} license marker in {path}, but it was not found"
        )


def validate_licenses() -> list[str]:
    locked = load_locked_versions()
    cache = pub_cache_root()
    reports: list[str] = []

    sdk_license = flutter_sdk_license()
    require_marker(sdk_license, BSD_MARKER, "BSD-3-Clause")
    reports.append(f"flutter-sdk\tBSD-3-Clause\t{sdk_license}")

    for package, policy in DIRECT_PACKAGES.items():
        locked_version = locked.get(package)
        if locked_version != policy.version:
            raise FlutterLicenseError(
                f"lockfile mismatch for {package}: expected {policy.version}, "
                f"found {locked_version or 'missing'}"
            )

        license_path = find_package_license(cache, package, policy.version)
        require_marker(license_path, policy.required_marker, policy.license_name)
        reports.append(
            f"{package}@{policy.version}\t{policy.license_name}\t{license_path}"
        )

    return reports


def main() -> int:
    try:
        reports = validate_licenses()
    except FlutterLicenseError as exc:
        print(f"Flutter license validation failed: {exc}", file=sys.stderr)
        return 1

    for report in reports:
        print(report)
    print("Flutter direct dependency license validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
