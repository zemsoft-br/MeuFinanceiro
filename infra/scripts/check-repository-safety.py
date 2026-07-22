#!/usr/bin/env python3
"""Reject secrets, real financial files, and forbidden legacy frontend artifacts."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MAX_TEXT_SIZE = 2 * 1024 * 1024
SENSITIVE_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "service-account.json",
}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".ofx", ".qif"}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b"
    ),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox(?:a|b|p|r|s)-[A-Za-z0-9-]{20,}\b"),
}
FORBIDDEN_PATH_PREFIXES = ("apps/web/",)
FORBIDDEN_TRACKED_PATHS = {
    "infra/scripts/check-node-licenses.mjs",
    "tests/quality/check-node-licenses.test.mjs",
}
FORBIDDEN_RUNTIME_TOKENS = ("WEB_RUNTIME_TARGET", "react-runtime")
RUNTIME_CONTRACT_FILES = {"compose.yaml", ".env.example"}
RUNTIME_CONTRACT_PREFIXES = (
    ".github/workflows/",
    "infra/caddy/",
    "infra/web/",
    "infra/scripts/dev-up",
    "tests/smoke/",
)


def tracked_files(repo: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    return [repo / item.decode() for item in result.stdout.split(b"\0") if item]


def is_runtime_contract(relative: Path) -> bool:
    relative_posix = relative.as_posix()
    return relative_posix in RUNTIME_CONTRACT_FILES or relative_posix.startswith(
        RUNTIME_CONTRACT_PREFIXES
    )


def validate(repo: Path) -> list[str]:
    failures: list[str] = []

    for path in tracked_files(repo):
        relative = path.relative_to(repo)
        relative_posix = relative.as_posix()
        lowered_name = path.name.lower()
        suffix = path.suffix.lower()

        if relative_posix in FORBIDDEN_TRACKED_PATHS or relative_posix.startswith(
            FORBIDDEN_PATH_PREFIXES
        ):
            failures.append(f"legacy React frontend artifact tracked: {relative}")
            continue
        if lowered_name in SENSITIVE_NAMES and relative_posix != ".env.example":
            failures.append(f"sensitive filename tracked: {relative}")
            continue
        if suffix in SENSITIVE_SUFFIXES:
            failures.append(f"sensitive or financial file tracked: {relative}")
            continue
        if not path.is_file() or path.stat().st_size > MAX_TEXT_SIZE:
            continue

        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        for description, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{description} detected in {relative}")

        if is_runtime_contract(relative):
            for token in FORBIDDEN_RUNTIME_TOKENS:
                if token in text:
                    failures.append(
                        f"legacy React runtime token {token!r} detected in {relative}"
                    )

    return failures


def main() -> int:
    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    try:
        failures = validate(repo)
    except RuntimeError as exc:
        print(f"Repository safety validation could not run: {exc}", file=sys.stderr)
        return 2

    if failures:
        print("Repository safety validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("Repository safety validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
