#!/usr/bin/env python3
"""Run the same mandatory quality gates locally and in GitHub Actions."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = ROOT / ".quality-venv"
SUPPORTED_PYTHON_MIN = (3, 13)
SUPPORTED_PYTHON_MAX = (3, 14)
TEST_DATABASE_ENV_VARS = ("TEST_DATABASE_URL", "TEST_APP_DATABASE_USER")
TOOLS = (
    "mypy==2.3.0",
    "pip-audit==2.10.1",
    "ruff==0.15.22",
)
PYTHON_PATHS = (
    "packages/security",
    "packages/persistence",
    "apps/api",
    "apps/worker",
    "infra/scripts",
    "tests/quality",
)


def run(
    command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None
) -> None:
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def validate_python_version(version: tuple[int, int] | None = None) -> None:
    """Reject interpreters outside the repository's supported Python range."""
    current = version or (sys.version_info.major, sys.version_info.minor)
    if SUPPORTED_PYTHON_MIN <= current < SUPPORTED_PYTHON_MAX:
        return

    rendered = ".".join(str(part) for part in current)
    raise RuntimeError(
        "Python 3.13.x is required by the repository; "
        f"the current interpreter is Python {rendered}. "
        "On Windows, run: py -3.13 infra/scripts/run-quality.py --recreate"
    )


def build_python_test_environment(
    use_test_database_env: bool,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Prevent unrelated project database settings from reaching pytest by default."""
    environment = dict(source if source is not None else os.environ)

    if not use_test_database_env:
        for name in TEST_DATABASE_ENV_VARS:
            environment.pop(name, None)
        return environment

    missing = [name for name in TEST_DATABASE_ENV_VARS if not environment.get(name)]
    if missing:
        raise RuntimeError(
            "--use-test-database-env requires explicit values for " + ", ".join(missing)
        )
    return environment


def venv_python() -> Path:
    scripts = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return VENV_DIR / scripts / executable


def ensure_python_environment(recreate: bool) -> Path:
    if recreate and VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)
    if not venv_python().exists():
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV_DIR)

    python = venv_python()
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            *TOOLS,
            "-e",
            "./packages/security[test]",
            "-e",
            "./packages/persistence[test]",
            "-e",
            "./apps/api[test]",
            "-e",
            "./apps/worker[test]",
        ]
    )
    return python


def run_python_quality(python: Path, *, test_env: dict[str, str]) -> None:
    run([str(python), "-m", "ruff", "check", *PYTHON_PATHS])
    run([str(python), "-m", "ruff", "format", "--check", *PYTHON_PATHS])
    run(
        [
            str(python),
            "-m",
            "mypy",
            "--strict",
            "packages/security/src",
            "packages/persistence/src",
            "apps/api/app",
            "apps/worker/worker",
        ]
    )
    run(
        [
            str(python),
            "-m",
            "pytest",
            "packages/security/tests",
            "packages/persistence/tests",
            "apps/api/tests",
            "apps/worker/tests",
            "tests/quality",
        ],
        env=test_env,
    )
    run([str(python), "infra/scripts/check-python-licenses.py"])
    run([str(python), "-m", "pip_audit", "--local"])


def run_react_quality() -> None:
    web = ROOT / "apps" / "web"
    if not (web / "package-lock.json").exists():
        raise RuntimeError(
            "apps/web/package-lock.json is required; generate and commit it first"
        )

    run(["npm", "ci", "--no-audit", "--no-fund"], cwd=web)
    run(["npm", "run", "lint"], cwd=web)
    run(["npm", "run", "typecheck"], cwd=web)
    run(["npm", "test"], cwd=web)
    run(["npm", "run", "build"], cwd=web)
    run(["npm", "audit", "--audit-level=high"], cwd=web)
    run(["node", "infra/scripts/check-node-licenses.mjs", "apps/web"])


def run_flutter_quality() -> None:
    app = ROOT / "apps" / "app"
    lockfile = app / "pubspec.lock"
    if not lockfile.exists():
        raise RuntimeError(
            "apps/app/pubspec.lock is required; run flutter pub get and commit it first"
        )

    run(["node", "--check", "apps/app/web/app_bootstrap.js"])
    run(["node", "--check", "apps/app/web/sw.js"])
    run(["node", "--test", "tests/quality/flutter-service-worker.test.mjs"])
    run([sys.executable, "infra/scripts/check-flutter-toolchain.py"])
    run(["flutter", "pub", "get", "--enforce-lockfile"], cwd=app)
    run([sys.executable, "infra/scripts/check-flutter-licenses.py"])
    run(
        ["dart", "format", "--output=none", "--set-exit-if-changed", "lib", "test"],
        cwd=app,
    )
    run(["flutter", "analyze"], cwd=app)
    run(["flutter", "test"], cwd=app)
    run(
        [
            "flutter",
            "build",
            "web",
            "--release",
            "--no-web-resources-cdn",
            "--pwa-strategy=none",
        ],
        cwd=app,
    )
    run(
        [
            sys.executable,
            "infra/scripts/finalize-flutter-web-build.py",
            "--build-dir",
            "apps/app/build/web",
        ]
    )
    run([sys.executable, "infra/scripts/check-flutter-web-contract.py"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recreate", action="store_true", help="Recreate the quality virtualenv"
    )
    parser.add_argument(
        "--use-test-database-env",
        action="store_true",
        help=(
            "Run PostgreSQL integration tests using explicit TEST_DATABASE_URL and "
            "TEST_APP_DATABASE_USER values from the current environment"
        ),
    )
    args = parser.parse_args()

    try:
        validate_python_version()
        test_env = build_python_test_environment(args.use_test_database_env)
    except RuntimeError as exc:
        print(f"Quality runner configuration error: {exc}", file=sys.stderr)
        return 2

    run([sys.executable, "infra/scripts/check-repository-safety.py"])
    python = ensure_python_environment(args.recreate)

    run_python_quality(python, test_env=test_env)
    run_react_quality()
    run_flutter_quality()

    print("All mandatory quality gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
