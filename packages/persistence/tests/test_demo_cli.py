from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from meufinanceiro_persistence.demo_cli import DemoCliSettings, _resolve_operator_password

_DATABASE_URL = "postgresql+psycopg://demo:demo@localhost/demo"


def _settings(
    *,
    direct: str | None = None,
    password_file: Path | None = None,
) -> DemoCliSettings:
    return DemoCliSettings(
        database_url=SecretStr(_DATABASE_URL),
        demo_operator_password=(SecretStr(direct) if direct is not None else None),
        demo_operator_password_file=password_file,
    )


def test_demo_operator_password_uses_file_without_environment_secret(
    tmp_path: Path,
) -> None:
    password_file = tmp_path / "operator_password.txt"
    password_file.write_text("synthetic-file-secret\n", encoding="utf-8")

    assert (
        _resolve_operator_password(_settings(password_file=password_file))
        == "synthetic-file-secret"
    )


def test_demo_operator_password_environment_fallback_remains_compatible() -> None:
    assert (
        _resolve_operator_password(_settings(direct="synthetic-env-secret"))
        == "synthetic-env-secret"
    )


def test_demo_operator_password_rejects_ambiguous_sources(tmp_path: Path) -> None:
    password_file = tmp_path / "operator_password.txt"
    password_file.write_text("synthetic-file-secret\n", encoding="utf-8")

    with pytest.raises(ValueError, match="configure only one"):
        _resolve_operator_password(
            _settings(
                direct="synthetic-env-secret",
                password_file=password_file,
            )
        )


def test_demo_operator_password_rejects_empty_or_missing_file(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="file is empty"):
        _resolve_operator_password(_settings(password_file=empty_file))

    missing_file = tmp_path / "missing.txt"
    with pytest.raises(ValueError, match="file could not be read"):
        _resolve_operator_password(_settings(password_file=missing_file))


def test_demo_operator_password_is_optional_for_non_load_commands() -> None:
    assert _resolve_operator_password(_settings()) is None
