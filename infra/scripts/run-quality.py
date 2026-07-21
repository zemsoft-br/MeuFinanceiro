#!/usr/bin/env python3
"""Run the same mandatory quality gates locally and in GitHub Actions."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from collections.abc import Callable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = ROOT / ".quality-venv"
SUPPORTED_PYTHON_MIN = (3, 13)
SUPPORTED_PYTHON_MAX = (3, 14)
TEST_DATABASE_ENV_VARS = ("TEST_DATABASE_URL", "TEST_APP_DATABASE_USER")
REQUIRED_COMMANDS = ("node", "npm", "flutter", "dart")
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


def prepare_subprocess_command(
    command: list[str],
    *,
    platform: str | None = None,
    resolver: Callable[[str], str | None] = shutil.which,
    comspec: str | None = None,
) -> list[str]:
    """Resolve PATH commands and invoke Windows batch shims through cmd.exe."""
    if not command:
        raise ValueError("command must not be empty")

    executable = command[0]
    resolved = executable if Path(executable).is_absolute() else resolver(executable)
    prepared = [resolved or executable, *command[1:]]

    current_platform = platform or os.name
    suffix = Path(prepared[0]).suffix.lower()
    if current_platform != "nt" or suffix not in {".bat", ".cmd"}:
        return prepared

    shell = comspec or os.environ.get("COMSPEC") or "cmd.exe"
    return [shell, "/d", "/s", "/c", subprocess.list2cmdline(prepared)]


def run(
    command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None
) -> None:
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(prepare_subprocess_command(command), cwd=cwd, env=env, check=True)


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


def validate_required_commands(
    resolver: Callable[[str], str | None] = shutil.which,
) -> None:
    """Fail before the long suite when a frontend toolchain is unavailable."""
    missing = [command for command in REQUIRED_COMMANDS if resolver(command) is None]
    if not missing:
        return

    raise RuntimeError(
        "Missing required command(s): "
        + ", ".join(missing)
        + ". Install Node.js 24.18.0 and Flutter 3.44.6, then ensure their "
        "executables are available on PATH."
    )


def build_python_test_environment(
    use_test_database_env: bool,
    allow_skipped_postgres_tests: bool,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Require an explicit dedicated database for a complete local quality run."""
    environment = dict(source if source is not None else os.environ)

    if use_test_database_env:
        missing = [name for name in TEST_DATABASE_ENV_VARS if not environment.get(name)]
        if missing:
            raise RuntimeError(
                "--use-test-database-env requires explicit values for "
                + ", ".join(missing)
            )
        return environment

    for name in TEST_DATABASE_ENV_VARS:
        environment.pop(name, None)

    if allow_skipped_postgres_tests:
        return environment

    raise RuntimeError(
        "A complete local quality run requires a dedicated PostgreSQL test database. "
        "Set TEST_DATABASE_URL and TEST_APP_DATABASE_USER, then pass "
        "--use-test-database-env. Use --allow-skipped-postgres-tests only for a "
        "partial diagnostic run; skipped PostgreSQL tests do not approve a PR."
    )


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
    parser.add_argument(
        "--allow-skipped-postgres-tests",
        action="store_true",
        help=(
            "Allow a partial diagnostic run without PostgreSQL integration tests; "
            "this mode cannot approve a pull request"
        ),
    )
    args = parser.parse_args()

    try:
        validate_python_version()
        validate_required_commands()
        test_env = build_python_test_environment(
            args.use_test_database_env,
            args.allow_skipped_postgres_tests,
        )
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
