#!/usr/bin/env python3
"""Validate that the active Flutter executable matches the pinned SDK version."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / ".flutter-version"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class FlutterToolchainError(RuntimeError):
    """Raised when the configured Flutter toolchain cannot be trusted."""


def load_expected_version(path: Path = VERSION_FILE) -> str:
    """Read and validate the repository's pinned Flutter version."""
    try:
        version = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise FlutterToolchainError(f"version file not found: {path}") from exc

    if not VERSION_PATTERN.fullmatch(version):
        raise FlutterToolchainError(
            f"invalid Flutter version {version!r} in {path}; expected X.Y.Z"
        )
    return version


def parse_framework_version(raw: str) -> str:
    """Extract frameworkVersion from `flutter --version --machine` output."""
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FlutterToolchainError("Flutter returned invalid machine-readable JSON") from exc

    if not isinstance(payload, dict):
        raise FlutterToolchainError("Flutter machine output must be a JSON object")

    version = payload.get("frameworkVersion")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise FlutterToolchainError(
            "Flutter machine output does not contain a valid frameworkVersion"
        )
    return version


def find_flutter() -> str:
    """Resolve Flutter from PATH with an actionable failure message."""
    executable = shutil.which("flutter")
    if executable is None:
        raise FlutterToolchainError(
            "Flutter is not available on PATH. Install the version from .flutter-version "
            "before running the quality gates."
        )
    return executable


def read_installed_version(executable: str) -> str:
    """Execute Flutter once and return its framework version."""
    completed = subprocess.run(
        [executable, "--version", "--machine"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise FlutterToolchainError(
            f"could not execute {executable!r}: {detail}"
        )
    return parse_framework_version(completed.stdout)


def validate_toolchain() -> tuple[str, str]:
    """Return expected and installed versions when they are identical."""
    expected = load_expected_version()
    executable = find_flutter()
    installed = read_installed_version(executable)
    if installed != expected:
        raise FlutterToolchainError(
            f"Flutter version mismatch: expected {expected}, found {installed} at "
            f"{executable}."
        )
    return expected, executable


def main() -> int:
    try:
        version, executable = validate_toolchain()
    except FlutterToolchainError as exc:
        print(f"Flutter toolchain validation failed: {exc}", file=sys.stderr)
        return 1

    print(f"Flutter toolchain validation passed: {version} ({executable})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
