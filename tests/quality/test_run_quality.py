from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra" / "scripts" / "run-quality.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_quality", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_313_is_supported() -> None:
    module = load_module()

    module.validate_python_version((3, 13))


@pytest.mark.parametrize("version", [(3, 12), (3, 14), (4, 0)])
def test_unsupported_python_versions_are_rejected(version: tuple[int, int]) -> None:
    module = load_module()

    with pytest.raises(RuntimeError, match="Python 3.13.x is required"):
        module.validate_python_version(version)


def test_windows_command_shims_are_invoked_through_comspec() -> None:
    module = load_module()

    prepared = module.prepare_subprocess_command(
        ["npm", "ci", "--no-audit"],
        platform="nt",
        resolver=lambda _command: r"C:\Program Files\nodejs\npm.cmd",
        comspec=r"C:\Windows\System32\cmd.exe",
    )

    assert prepared[:4] == [
        r"C:\Windows\System32\cmd.exe",
        "/d",
        "/s",
        "/c",
    ]
    assert prepared[4] == '"C:\\Program Files\\nodejs\\npm.cmd" ci --no-audit'


def test_native_command_uses_resolved_executable_directly() -> None:
    module = load_module()

    prepared = module.prepare_subprocess_command(
        ["node", "--version"],
        platform="posix",
        resolver=lambda _command: "/usr/bin/node",
    )

    assert prepared == ["/usr/bin/node", "--version"]


def test_required_commands_are_accepted_when_all_resolve() -> None:
    module = load_module()

    module.validate_required_commands(lambda command: f"/tools/{command}")


def test_missing_required_commands_are_reported_together() -> None:
    module = load_module()

    with pytest.raises(RuntimeError, match="node, npm"):
        module.validate_required_commands(
            lambda command: None if command in {"node", "npm"} else f"/tools/{command}"
        )


def test_complete_run_requires_explicit_database_environment() -> None:
    module = load_module()
    source = {
        "PATH": "safe-path",
        "TEST_DATABASE_URL": "postgresql://another-project",
        "TEST_APP_DATABASE_USER": "another_user",
    }

    with pytest.raises(RuntimeError, match="dedicated PostgreSQL test database"):
        module.build_python_test_environment(False, False, source)

    assert source["TEST_DATABASE_URL"] == "postgresql://another-project"


def test_partial_diagnostic_removes_inherited_database_environment() -> None:
    module = load_module()
    source = {
        "PATH": "safe-path",
        "TEST_DATABASE_URL": "postgresql://another-project",
        "TEST_APP_DATABASE_USER": "another_user",
    }

    environment = module.build_python_test_environment(False, True, source)

    assert environment == {"PATH": "safe-path"}
    assert source["TEST_DATABASE_URL"] == "postgresql://another-project"


def test_explicit_database_environment_requires_both_values() -> None:
    module = load_module()

    with pytest.raises(RuntimeError, match="TEST_APP_DATABASE_USER"):
        module.build_python_test_environment(
            True,
            False,
            {"TEST_DATABASE_URL": "postgresql://meufinanceiro-test"},
        )


def test_explicit_database_environment_is_preserved() -> None:
    module = load_module()
    source = {
        "TEST_DATABASE_URL": "postgresql://meufinanceiro-test",
        "TEST_APP_DATABASE_USER": "meufinanceiro_app",
    }

    environment = module.build_python_test_environment(True, False, source)

    assert environment == source
