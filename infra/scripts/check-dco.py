#!/usr/bin/env python3
"""Validate DCO sign-offs for every commit in a Git range."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SIGNOFF_PATTERN = re.compile(
    r"^Signed-off-by:\s+.+\s+<[^<>\s@]+@[^<>\s]+>$",
    re.IGNORECASE | re.MULTILINE,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def validate(repo: Path, base: str, head: str) -> list[str]:
    commit_range = f"{base}..{head}"
    commits = [line for line in git(repo, "rev-list", "--reverse", commit_range).splitlines() if line]
    failures: list[str] = []

    for commit in commits:
        message = git(repo, "show", "-s", "--format=%B", commit)
        if not SIGNOFF_PATTERN.search(message):
            subject = git(repo, "show", "-s", "--format=%s", commit).strip()
            failures.append(f"{commit[:12]} {subject}")

    return failures


def main() -> int:
    if len(sys.argv) not in {3, 4}:
        print("usage: check-dco.py <base-sha> <head-sha> [repository]", file=sys.stderr)
        return 2

    base, head = sys.argv[1:3]
    repo = Path(sys.argv[3] if len(sys.argv) == 4 else ".").resolve()

    try:
        failures = validate(repo, base, head)
    except RuntimeError as exc:
        print(f"DCO validation could not run: {exc}", file=sys.stderr)
        return 2

    if failures:
        print("Commits without a valid DCO sign-off:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        print("Create or amend commits with: git commit --signoff", file=sys.stderr)
        return 1

    print("DCO validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
