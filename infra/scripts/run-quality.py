#!/usr/bin/env python3
"""Run the same mandatory quality gates locally and in GitHub Actions."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
import venv
from collections.abc import Callable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = ROOT / ".quality-venv"
QUALITY_TMP_ROOT = ROOT / ".quality-tmp"
BASETEMP_NAME_PATTERN = re.compile(r"pytest-[0-9a-f]{32}")
BASETEMP_CREATE_ATTEMPTS = 8
FILE_ATTRIBUTE_READONLY = 0x1
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
SUPPORTED_PYTHON_MIN = (3, 13)
SUPPORTED_PYTHON_MAX = (3, 14)
TEST_DATABASE_ENV_VARS = ("TEST_DATABASE_URL", "TEST_APP_DATABASE_USER")
REQUIRED_COMMANDS = ("node", "flutter", "dart")
PIP_REQUIREMENT = "pip==26.2"
TOOLS = (
    "mypy==2.3.0",
    "pip-audit==2.10.1",
    "ruff==0.15.22",
)
PYTEST_PATHS = (
    "packages/finance/tests",
    "packages/banking/tests",
    "packages/banking-pluggy/tests",
    "packages/banking-pluggy-execution/tests",
    "packages/banking-sync/tests",
    "packages/security/tests",
    "packages/persistence/tests",
    "apps/api/tests",
    "apps/worker/tests",
    "tests/quality",
)
PYTHON_PATHS = (
    "packages/finance",
    "packages/banking",
    "packages/banking-pluggy",
    "packages/banking-pluggy-execution",
    "packages/banking-sync",
    "packages/security",
    "packages/persistence",
    "apps/api",
    "apps/worker",
    "infra/scripts",
    "tests/quality",
    "tools/pluggy-spike",
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


class BasetempError(RuntimeError):
    """Base class for pytest basetemp isolation failures."""


class UnsafeBasetempError(BasetempError):
    """The path is not an exact, regular child of the dedicated temp root."""


class BasetempCleanupError(BasetempError):
    """The basetemp of a passing run could not be removed."""


def is_link_or_reparse_point(
    path: Path, *, lstat: Callable[[Path], os.stat_result] = os.lstat
) -> bool:
    """Detect symlinks and any Windows reparse point (junction, mount point)."""
    info = lstat(path)
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes: int = getattr(info, "st_file_attributes", 0)
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _require_regular_directory(path: Path, description: str) -> None:
    try:
        redirected = is_link_or_reparse_point(path)
    except OSError as exc:
        raise UnsafeBasetempError(f"{description} cannot be inspected: {exc}") from exc
    if redirected or not path.is_dir():
        raise UnsafeBasetempError(
            f"{description} must be a regular directory, not a link or junction: {path}"
        )


def _require_exact_child(basetemp: Path, root: Path) -> None:
    """Lexical check only: no resolve() that could authorize root or a parent."""
    if not root.is_absolute() or ".." in root.parts:
        raise UnsafeBasetempError(f"temp root must be absolute and normalized: {root}")
    if not basetemp.is_absolute() or basetemp.parent != root:
        raise UnsafeBasetempError(
            f"basetemp must be a direct child of the dedicated root {root}: {basetemp}"
        )
    if BASETEMP_NAME_PATTERN.fullmatch(basetemp.name) is None:
        raise UnsafeBasetempError(
            f"basetemp name must match pytest-<32 hex run id>: {basetemp.name!r}"
        )


def create_pytest_basetemp(
    root: Path = QUALITY_TMP_ROOT,
    *,
    token_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> Path:
    """Atomically reserve a unique basetemp directory under the dedicated root."""
    if not root.is_absolute() or ".." in root.parts:
        raise UnsafeBasetempError(f"temp root must be absolute and normalized: {root}")
    root.mkdir(exist_ok=True)
    _require_regular_directory(root, "temp root")

    for _ in range(BASETEMP_CREATE_ATTEMPTS):
        basetemp = root / f"pytest-{token_factory()}"
        _require_exact_child(basetemp, root)
        try:
            basetemp.mkdir(mode=0o700)
        except FileExistsError:
            continue
        return basetemp
    raise BasetempError(f"could not reserve a unique basetemp under {root}")


def readonly_retry_handler(
    basetemp: Path,
) -> Callable[[Callable[..., object], str, BaseException], None]:
    """Build an rmtree onexc that only undoes the Windows read-only attribute.

    Git stores loose objects read-only, which makes unlink/rmdir fail on Windows.
    The handler clears that attribute on one regular entry strictly inside
    basetemp and repeats the failed call once; anything else is re-raised.
    """

    def handler(function: Callable[..., object], path: str, exc: BaseException) -> None:
        if not isinstance(exc, PermissionError):
            raise exc
        if function not in (os.unlink, os.remove, os.rmdir):
            raise exc
        target = Path(path)
        if ".." in target.parts or basetemp not in target.parents:
            raise exc
        try:
            info = os.lstat(target)
        except OSError:
            raise exc from None
        attributes: int = getattr(info, "st_file_attributes", 0)
        if is_link_or_reparse_point(target, lstat=lambda _path: info):
            raise exc
        if not attributes & FILE_ATTRIBUTE_READONLY:
            raise exc
        os.chmod(
            target, stat.S_IMODE(info.st_mode) | stat.S_IWRITE, follow_symlinks=False
        )
        function(path)

    return handler


def remove_pytest_basetemp(basetemp: Path, root: Path = QUALITY_TMP_ROOT) -> None:
    """Remove exactly one basetemp; never glob, never fall back to another path."""
    _require_exact_child(basetemp, root)
    _require_regular_directory(root, "temp root")
    try:
        if is_link_or_reparse_point(basetemp):
            raise UnsafeBasetempError(
                f"basetemp is a link or junction and will not be removed: {basetemp}"
            )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise UnsafeBasetempError(f"basetemp cannot be inspected: {exc}") from exc
    if not basetemp.is_dir():
        raise UnsafeBasetempError(f"basetemp is not a directory: {basetemp}")

    try:
        shutil.rmtree(basetemp, onexc=readonly_retry_handler(basetemp))
    except OSError as exc:
        raise BasetempCleanupError(
            f"pytest passed but its basetemp could not be removed: {basetemp} ({exc}). "
            "No other path was touched. Close whatever holds a handle on this exact "
            "directory and remove it by its literal path."
        ) from exc


def run_pytest_with_isolated_basetemp(
    python: Path,
    *,
    test_env: dict[str, str],
    tmp_root: Path = QUALITY_TMP_ROOT,
    runner: Callable[..., None] | None = None,
) -> None:
    """Run pytest in a per-run basetemp: removed on success, preserved on failure."""
    basetemp = create_pytest_basetemp(tmp_root)
    command = [str(python), "-m", "pytest", f"--basetemp={basetemp}", *PYTEST_PATHS]
    try:
        (runner or run)(command, env=test_env)
    except BaseException:
        print(
            f"pytest did not pass; basetemp preserved for diagnosis: {basetemp}",
            file=sys.stderr,
            flush=True,
        )
        raise
    remove_pytest_basetemp(basetemp, tmp_root)


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
    """Fail before the long suite when a required client toolchain is unavailable."""
    missing = [command for command in REQUIRED_COMMANDS if resolver(command) is None]
    if not missing:
        return

    raise RuntimeError(
        "Missing required command(s): "
        + ", ".join(missing)
        + ". Install Node.js 24.18.0 and Flutter 3.44.6, then ensure their "
        "executables are available on PATH. Node.js is used only for PWA JavaScript tests."
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
            "--upgrade",
            PIP_REQUIREMENT,
        ]
    )
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            *TOOLS,
            "-e",
            "./packages/finance[test]",
            "-e",
            "./packages/banking[test]",
            "-e",
            "./packages/banking-pluggy[test]",
            "-e",
            "./packages/banking-pluggy-execution[test]",
            "-e",
            "./packages/banking-sync[test]",
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
            "packages/finance/src",
            "packages/banking/src",
            "packages/banking-pluggy/src",
            "packages/banking-pluggy-execution/src",
            "packages/banking-sync/src",
            "packages/security/src",
            "packages/persistence/src",
            "apps/api/app",
            "apps/worker/worker",
            "tools/pluggy-spike/pluggy_spike.py",
        ]
    )
    run_pytest_with_isolated_basetemp(python, test_env=test_env)
    run([str(python), "infra/scripts/check-python-licenses.py"])
    run([str(python), "-m", "pip_audit", "--local"])


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

    try:
        run_python_quality(python, test_env=test_env)
    except BasetempError as exc:
        print(f"Quality runner temp isolation error: {exc}", file=sys.stderr)
        return 1
    run_flutter_quality()

    print("All mandatory quality gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
