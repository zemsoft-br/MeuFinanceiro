from __future__ import annotations

import ast
import fnmatch
import glob
import importlib.util
import os
import re
import stat
import subprocess
import sys
import types
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
        ["flutter", "analyze"],
        platform="nt",
        resolver=lambda _command: r"C:\DevPrograms\flutter\bin\flutter.bat",
        comspec=r"C:\Windows\System32\cmd.exe",
    )

    assert prepared[:4] == [
        r"C:\Windows\System32\cmd.exe",
        "/d",
        "/s",
        "/c",
    ]
    assert prepared[4] == r"C:\DevPrograms\flutter\bin\flutter.bat analyze"


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

    with pytest.raises(RuntimeError, match="node, flutter"):
        module.validate_required_commands(
            lambda command: (
                None if command in {"node", "flutter"} else f"/tools/{command}"
            )
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


def test_quality_environment_bootstraps_pinned_pip_before_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_module()
    fake_python = tmp_path / "python.exe"
    fake_python.touch()
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "venv_python", lambda: fake_python)
    monkeypatch.setattr(
        module,
        "run",
        lambda command, **_kwargs: calls.append(command),
    )

    result = module.ensure_python_environment(False)

    assert result == fake_python
    assert calls[0] == [
        str(fake_python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--upgrade",
        "pip==26.2",
    ]
    assert "pip-audit==2.10.1" in calls[1]


# --- pytest basetemp isolation (Issue 258) ---------------------------------

HEX_A = "a" * 32
HEX_B = "b" * 32


def make_link(link: Path, target: Path) -> None:
    """Create a directory symlink (POSIX) or junction (Windows, no privilege)."""
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        os.symlink(target, link, target_is_directory=True)


def remove_link(link: Path) -> None:
    if os.name == "nt":
        os.rmdir(link)
    else:
        link.unlink()


def basetemp_of(command: list[str]) -> Path:
    flags = [arg for arg in command if arg.startswith("--basetemp=")]
    assert len(flags) == 1
    return Path(flags[0].removeprefix("--basetemp="))


class RecordingRunner:
    def __init__(self, outcome: BaseException | None = None) -> None:
        self.commands: list[list[str]] = []
        self.outcome = outcome

    def __call__(self, command: list[str], **kwargs: object) -> None:
        self.commands.append(command)
        basetemp = basetemp_of(command)
        (basetemp / "artifact.txt").write_text("evidence", encoding="utf-8")
        assert kwargs["env"] == {"K": "V"}
        if self.outcome is not None:
            raise self.outcome


def test_pytest_receives_exact_basetemp_under_dedicated_root(tmp_path: Path) -> None:
    module = load_module()
    root = tmp_path / ".quality-tmp"
    runner = RecordingRunner()

    module.run_pytest_with_isolated_basetemp(
        Path("python"), test_env={"K": "V"}, tmp_root=root, runner=runner
    )

    (command,) = runner.commands
    assert command[1:3] == ["-m", "pytest"]
    basetemp = basetemp_of(command)
    assert basetemp.parent == root
    assert re.fullmatch(r"pytest-[0-9a-f]{32}", basetemp.name)
    assert command[3] == f"--basetemp={basetemp}"
    assert command[4:] == list(module.PYTEST_PATHS)
    assert "tests/quality" in command


def test_default_root_is_repository_dedicated_and_ignored_by_git() -> None:
    module = load_module()

    assert module.QUALITY_TMP_ROOT == module.ROOT / ".quality-tmp"
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", ".quality-tmp/pytest-x/file"],
        cwd=ROOT,
        check=False,
    )
    assert ignored.returncode == 0


def test_two_runs_get_distinct_basetemps(tmp_path: Path) -> None:
    module = load_module()
    root = tmp_path / ".quality-tmp"

    first = module.create_pytest_basetemp(root)
    second = module.create_pytest_basetemp(root)

    assert first != second
    assert first.is_dir()
    assert second.is_dir()


def test_run_id_collision_never_reuses_existing_basetemp(tmp_path: Path) -> None:
    module = load_module()
    root = tmp_path / ".quality-tmp"
    existing = module.create_pytest_basetemp(root, token_factory=lambda: HEX_A)
    (existing / "keep.txt").write_text("other run", encoding="utf-8")
    tokens = iter([HEX_A, HEX_A, HEX_B])

    created = module.create_pytest_basetemp(root, token_factory=lambda: next(tokens))

    assert created == root / f"pytest-{HEX_B}"
    assert (existing / "keep.txt").read_text(encoding="utf-8") == "other run"


def test_basetemp_creation_gives_up_instead_of_reusing(tmp_path: Path) -> None:
    module = load_module()
    root = tmp_path / ".quality-tmp"
    existing = module.create_pytest_basetemp(root, token_factory=lambda: HEX_A)

    with pytest.raises(module.BasetempError, match="unique basetemp"):
        module.create_pytest_basetemp(root, token_factory=lambda: HEX_A)

    assert existing.is_dir()


def test_creation_rejects_root_that_is_a_link(tmp_path: Path) -> None:
    module = load_module()
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / ".quality-tmp"
    make_link(root, outside)
    try:
        with pytest.raises(module.UnsafeBasetempError, match="regular directory"):
            module.create_pytest_basetemp(root)
        assert list(outside.iterdir()) == []
    finally:
        remove_link(root)


def test_cleanup_rejects_paths_outside_or_not_exactly_under_root(
    tmp_path: Path,
) -> None:
    module = load_module()
    root = tmp_path / ".quality-tmp"
    root.mkdir()
    own = module.create_pytest_basetemp(root, token_factory=lambda: HEX_A)
    outside = tmp_path / f"pytest-{HEX_B}"
    outside.mkdir()
    nested = own / f"pytest-{HEX_B}"
    nested.mkdir()
    traversal = root / ".." / f"pytest-{HEX_B}"
    foreign_name = root / "other-project"
    foreign_name.mkdir()

    rejected = [
        outside,
        root,
        tmp_path,
        nested,
        traversal,
        foreign_name,
        root / "pytest-",
        root / "pytest-*",
        Path(f"pytest-{HEX_A}"),
    ]
    for candidate in rejected:
        with pytest.raises(module.UnsafeBasetempError):
            module.remove_pytest_basetemp(candidate, root)

    for survivor in (own, outside, nested, foreign_name, root, tmp_path):
        assert survivor.exists()


def test_cleanup_rejects_malformed_root(tmp_path: Path) -> None:
    module = load_module()
    root = tmp_path / ".quality-tmp"
    root.mkdir()
    sneaky_root = root / ".." / ".quality-tmp"
    basetemp = sneaky_root / f"pytest-{HEX_A}"
    (root / f"pytest-{HEX_A}").mkdir()

    with pytest.raises(module.UnsafeBasetempError, match="normalized"):
        module.remove_pytest_basetemp(basetemp, sneaky_root)
    with pytest.raises(module.UnsafeBasetempError, match="absolute"):
        module.remove_pytest_basetemp(Path(f"x/pytest-{HEX_A}"), Path("x"))

    assert (root / f"pytest-{HEX_A}").is_dir()


def test_cleanup_does_not_follow_link_basetemp_or_link_root(tmp_path: Path) -> None:
    module = load_module()
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("data", encoding="utf-8")
    root = tmp_path / ".quality-tmp"
    root.mkdir()
    linked = root / f"pytest-{HEX_A}"
    make_link(linked, victim)
    try:
        with pytest.raises(module.UnsafeBasetempError, match="link or junction"):
            module.remove_pytest_basetemp(linked, root)
        assert (victim / "precious.txt").read_text(encoding="utf-8") == "data"
    finally:
        remove_link(linked)

    real_root = tmp_path / "real-root"
    real_root.mkdir()
    (real_root / f"pytest-{HEX_B}").mkdir()
    linked_root = tmp_path / "linked-root"
    make_link(linked_root, real_root)
    try:
        with pytest.raises(module.UnsafeBasetempError, match="regular directory"):
            module.remove_pytest_basetemp(linked_root / f"pytest-{HEX_B}", linked_root)
        assert (real_root / f"pytest-{HEX_B}").is_dir()
    finally:
        remove_link(linked_root)


def test_cleanup_removes_links_inside_basetemp_without_following_them(
    tmp_path: Path,
) -> None:
    module = load_module()
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("data", encoding="utf-8")
    root = tmp_path / ".quality-tmp"
    basetemp = module.create_pytest_basetemp(root, token_factory=lambda: HEX_A)
    make_link(basetemp / "escape", victim)

    module.remove_pytest_basetemp(basetemp, root)

    assert not basetemp.exists()
    assert (victim / "precious.txt").read_text(encoding="utf-8") == "data"


@pytest.mark.parametrize(
    ("mode", "attributes", "expected"),
    [
        (stat.S_IFLNK, 0, True),
        (stat.S_IFDIR, 0x400, True),
        (stat.S_IFDIR | stat.S_IFLNK, 0x400, True),
        (stat.S_IFDIR, 0x10, False),
        (stat.S_IFDIR, None, False),
    ],
)
def test_link_detection_covers_posix_symlinks_and_windows_reparse_points(
    mode: int, attributes: int | None, expected: bool
) -> None:
    module = load_module()
    info = types.SimpleNamespace(st_mode=mode)
    if attributes is not None:
        info.st_file_attributes = attributes

    assert module.is_link_or_reparse_point(Path("x"), lstat=lambda _p: info) is expected


def test_cleanup_never_uses_glob(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_module()
    root = tmp_path / ".quality-tmp"
    basetemp = module.create_pytest_basetemp(root, token_factory=lambda: HEX_A)
    sibling = module.create_pytest_basetemp(root, token_factory=lambda: HEX_B)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("glob-style expansion is forbidden in cleanup")

    monkeypatch.setattr(glob, "glob", forbidden)
    monkeypatch.setattr(glob, "iglob", forbidden)
    monkeypatch.setattr(fnmatch, "filter", forbidden)
    monkeypatch.setattr(Path, "glob", forbidden)
    monkeypatch.setattr(Path, "rglob", forbidden)

    module.remove_pytest_basetemp(basetemp, root)

    assert not basetemp.exists()
    assert sibling.is_dir()
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called.isdisjoint({"glob", "rglob", "iglob", "fnmatch"})
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported.isdisjoint({"glob", "fnmatch"})


def test_success_removes_only_its_own_basetemp(tmp_path: Path) -> None:
    module = load_module()
    root = tmp_path / ".quality-tmp"
    older = module.create_pytest_basetemp(root, token_factory=lambda: HEX_A)
    (older / "residue.txt").write_text("older run", encoding="utf-8")
    runner = RecordingRunner()

    module.run_pytest_with_isolated_basetemp(
        Path("python"), test_env={"K": "V"}, tmp_root=root, runner=runner
    )

    assert not basetemp_of(runner.commands[0]).exists()
    assert root.is_dir()
    assert (older / "residue.txt").read_text(encoding="utf-8") == "older run"


def test_failing_pytest_preserves_basetemp_and_reports_exact_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_module()
    root = tmp_path / ".quality-tmp"
    failure = subprocess.CalledProcessError(1, "pytest")
    runner = RecordingRunner(outcome=failure)

    with pytest.raises(subprocess.CalledProcessError):
        module.run_pytest_with_isolated_basetemp(
            Path("python"), test_env={"K": "V"}, tmp_root=root, runner=runner
        )

    basetemp = basetemp_of(runner.commands[0])
    assert (basetemp / "artifact.txt").read_text(encoding="utf-8") == "evidence"
    assert f"basetemp preserved for diagnosis: {basetemp}" in capsys.readouterr().err


def test_interrupted_pytest_also_preserves_basetemp(tmp_path: Path) -> None:
    module = load_module()
    root = tmp_path / ".quality-tmp"
    runner = RecordingRunner(outcome=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        module.run_pytest_with_isolated_basetemp(
            Path("python"), test_env={"K": "V"}, tmp_root=root, runner=runner
        )

    assert basetemp_of(runner.commands[0]).is_dir()


def test_failed_cleanup_reports_exact_path_and_tries_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    root = tmp_path / ".quality-tmp"
    sibling = module.create_pytest_basetemp(root, token_factory=lambda: HEX_B)
    runner = RecordingRunner()
    attempts: list[object] = []

    def locked(path: object, *_args: object, **_kwargs: object) -> None:
        attempts.append(path)
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(module.shutil, "rmtree", locked)
    monkeypatch.setattr(os, "remove", locked)
    monkeypatch.setattr(os, "rmdir", locked)

    with pytest.raises(module.BasetempCleanupError) as raised:
        module.run_pytest_with_isolated_basetemp(
            Path("python"), test_env={"K": "V"}, tmp_root=root, runner=runner
        )

    basetemp = basetemp_of(runner.commands[0])
    assert attempts == [basetemp]
    assert str(basetemp) in str(raised.value)
    assert "No other path was touched" in str(raised.value)
    assert basetemp.is_dir()
    assert sibling.is_dir()


def test_main_reports_cleanup_failure_as_failed_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_module()

    def failing_quality(*_args: object, **_kwargs: object) -> None:
        raise module.BasetempCleanupError("cannot remove /x")

    monkeypatch.setattr(
        sys, "argv", ["run-quality.py", "--allow-skipped-postgres-tests"]
    )
    monkeypatch.setattr(module, "validate_python_version", lambda: None)
    monkeypatch.setattr(module, "validate_required_commands", lambda: None)
    monkeypatch.setattr(module, "run", lambda *_a, **_k: None)
    monkeypatch.setattr(module, "ensure_python_environment", lambda _r: Path("python"))
    monkeypatch.setattr(module, "run_python_quality", failing_quality)
    monkeypatch.setattr(module, "run_flutter_quality", failing_quality)

    assert module.main() == 1
    assert "cannot remove /x" in capsys.readouterr().err


def test_recreate_only_replaces_quality_venv_and_spares_other_basetemps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_module()
    venv_dir = tmp_path / ".quality-venv"
    venv_dir.mkdir()
    (venv_dir / "stale.txt").write_text("old", encoding="utf-8")
    root = tmp_path / ".quality-tmp"
    other_run = module.create_pytest_basetemp(root, token_factory=lambda: HEX_A)
    (other_run / "artifact.txt").write_text("other run", encoding="utf-8")
    created: list[Path] = []

    class FakeBuilder:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def create(self, target: Path) -> None:
            created.append(target)
            fake = module.venv_python()
            fake.parent.mkdir(parents=True)
            fake.touch()

    monkeypatch.setattr(module, "VENV_DIR", venv_dir)
    monkeypatch.setattr(module, "QUALITY_TMP_ROOT", root)
    monkeypatch.setattr(module.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(module, "run", lambda *_a, **_k: None)

    module.ensure_python_environment(True)

    assert created == [venv_dir]
    assert not (venv_dir / "stale.txt").exists()
    assert (other_run / "artifact.txt").read_text(encoding="utf-8") == "other run"


@pytest.mark.parametrize("platform", ["nt", "posix"])
def test_basetemp_command_is_platform_safe(platform: str, tmp_path: Path) -> None:
    module = load_module()
    basetemp = tmp_path / "with space" / f"pytest-{HEX_A}"
    command = ["python", "-m", "pytest", f"--basetemp={basetemp}"]

    direct = module.prepare_subprocess_command(
        command, platform=platform, resolver=lambda _c: str(tmp_path / "python.exe")
    )
    shimmed = module.prepare_subprocess_command(
        command,
        platform=platform,
        resolver=lambda _c: str(tmp_path / "python.cmd"),
        comspec="cmd.exe",
    )

    assert direct == [str(tmp_path / "python.exe"), *command[1:]]
    if platform == "nt":
        assert shimmed[:4] == ["cmd.exe", "/d", "/s", "/c"]
        assert f'"--basetemp={basetemp}"' in shimmed[4]
    else:
        assert shimmed == [str(tmp_path / "python.cmd"), *command[1:]]


def test_pytest_command_goes_through_comspec_for_batch_shims_on_windows(
    tmp_path: Path,
) -> None:
    module = load_module()
    seen: list[list[str]] = []
    runner = RecordingRunner()

    def capture(command: list[str], **kwargs: object) -> None:
        seen.append(
            module.prepare_subprocess_command(
                command,
                platform="nt",
                resolver=lambda _c: r"C:\venv\python.bat",
                comspec=r"C:\Windows\System32\cmd.exe",
            )
        )
        runner(command, **kwargs)

    module.run_pytest_with_isolated_basetemp(
        Path("python"),
        test_env={"K": "V"},
        tmp_root=tmp_path / ".quality-tmp",
        runner=capture,
    )

    assert seen[0][:4] == [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c"]
    assert "--basetemp=" in seen[0][4]
