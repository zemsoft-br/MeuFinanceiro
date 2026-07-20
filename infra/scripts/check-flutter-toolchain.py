#!/usr/bin/env python3
"""Validate that the active Flutter executable matches the pinned SDK identity."""

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
REVISION_FILE = ROOT / ".flutter-revision"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


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


def load_expected_revision(path: Path = REVISION_FILE) -> str:
    """Read and validate the repository's pinned Flutter Git revision."""
    try:
        revision = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise FlutterToolchainError(f"revision file not found: {path}") from exc

    if not REVISION_PATTERN.fullmatch(revision):
        raise FlutterToolchainError(
            f"invalid Flutter revision {revision!r} in {path}; expected 40 lowercase hex characters"
        )
    return revision


def parse_machine_identity(raw: str) -> tuple[str, str]:
    """Extract frameworkVersion and frameworkRevision from Flutter JSON."""
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

    revision = payload.get("frameworkRevision")
    if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
        raise FlutterToolchainError(
            "Flutter machine output does not contain a valid frameworkRevision"
        )

    return version, revision


def find_flutter() -> str:
    """Resolve Flutter from PATH with an actionable failure message."""
    executable = shutil.which("flutter")
    if executable is None:
        raise FlutterToolchainError(
            "Flutter is not available on PATH. Install the SDK identity from "
            ".flutter-version and .flutter-revision before running the quality gates."
        )
    return executable


def read_installed_identity(executable: str) -> tuple[str, str]:
    """Execute Flutter once and return its version and revision."""
    completed = subprocess.run(
        [executable, "--version", "--machine"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise FlutterToolchainError(f"could not execute {executable!r}: {detail}")
    return parse_machine_identity(completed.stdout)


def validate_toolchain() -> tuple[str, str, str]:
    """Return the trusted SDK identity and executable."""
    expected_version = load_expected_version()
    expected_revision = load_expected_revision()
    executable = find_flutter()
    installed_version, installed_revision = read_installed_identity(executable)

    if installed_version != expected_version:
        raise FlutterToolchainError(
            f"Flutter version mismatch: expected {expected_version}, found "
            f"{installed_version} at {executable}."
        )
    if installed_revision != expected_revision:
        raise FlutterToolchainError(
            f"Flutter revision mismatch: expected {expected_revision}, found "
            f"{installed_revision} at {executable}."
        )

    return expected_version, expected_revision, executable


def main() -> int:
    try:
        version, revision, executable = validate_toolchain()
    except FlutterToolchainError as exc:
        print(f"Flutter toolchain validation failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Flutter toolchain validation passed: {version} "
        f"({revision}, {executable})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
