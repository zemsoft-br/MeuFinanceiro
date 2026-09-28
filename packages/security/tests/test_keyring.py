from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import meufinanceiro_security.keyring as keyring_module
from meufinanceiro_security.errors import KeyringError
from meufinanceiro_security.keyring import (
    KEY_SIZE_BYTES,
    Keyring,
    create_keyring,
    initialize_keyring_file,
    load_keyring,
    parse_keyring,
    rotate_keyring,
    rotate_keyring_file,
    serialize_keyring,
)


def test_keyring_round_trip() -> None:
    keyring = create_keyring()

    parsed = parse_keyring(serialize_keyring(keyring))

    assert parsed.version == 1
    assert parsed.active_key_id == keyring.active_key_id
    assert parsed.active_key == keyring.active_key
    assert len(parsed.active_key) == KEY_SIZE_BYTES


def test_separate_installations_never_share_default_key_material() -> None:
    first = create_keyring()
    second = create_keyring()

    assert first.active_key_id != second.active_key_id
    assert first.active_key != second.active_key


def test_rotation_preserves_old_key_and_changes_active_key() -> None:
    original = create_keyring()

    rotated = rotate_keyring(original)

    assert rotated.active_key_id != original.active_key_id
    assert rotated.key(original.active_key_id) == original.active_key
    assert len(rotated.keys) == 2


def test_file_initialization_and_rotation_are_atomic(tmp_path: Path) -> None:
    path = tmp_path / ".secrets" / "keyring.json"

    original = initialize_keyring_file(path)
    rotated = rotate_keyring_file(path)

    loaded = load_keyring(path)
    assert loaded.active_key_id == rotated.active_key_id
    assert loaded.key(original.active_key_id) == original.active_key
    assert not path.with_name(f".{path.name}.lock").exists()
    if os.name != "nt":
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert path.stat().st_mode & 0o777 == 0o644


def test_concurrent_rotation_is_rejected_without_changing_keyring(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".secrets" / "keyring.json"
    original = initialize_keyring_file(path)
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.write_text("pid=test\n", encoding="utf-8")

    with pytest.raises(KeyringError, match="already in progress"):
        rotate_keyring_file(path)

    assert load_keyring(path).active_key_id == original.active_key_id


def test_initialization_refuses_to_replace_existing_keyring(tmp_path: Path) -> None:
    path = tmp_path / "keyring.json"
    initialize_keyring_file(path)

    with pytest.raises(KeyringError, match="already exists"):
        initialize_keyring_file(path)


def test_parser_rejects_unknown_schema_fields() -> None:
    payload = json.loads(serialize_keyring(create_keyring()))
    payload["unexpected"] = True

    with pytest.raises(KeyringError, match="schema"):
        parse_keyring(json.dumps(payload))


def test_keyring_rejects_missing_active_key() -> None:
    with pytest.raises(KeyringError, match="does not exist"):
        Keyring(
            version=1,
            active_key_id="k_abcdefghijkl",
            keys={"k_mnopqrstuvwx": b"x" * 32},
        )


def test_group_writable_keyring_is_rejected_on_writable_mount(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(keyring_module.os, "ST_RDONLY", 1, raising=False)
    monkeypatch.setattr(
        keyring_module.os,
        "statvfs",
        lambda _path: SimpleNamespace(f_flag=0),
        raising=False,
    )

    with pytest.raises(KeyringError, match="writable by group or others"):
        keyring_module._validate_keyring_file_permissions(  # noqa: SLF001
            tmp_path / "keyring.json",
            0o666,
            platform="posix",
        )


def test_group_writable_keyring_is_accepted_on_read_only_mount(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(keyring_module.os, "ST_RDONLY", 1, raising=False)
    monkeypatch.setattr(
        keyring_module.os,
        "statvfs",
        lambda _path: SimpleNamespace(f_flag=1),
        raising=False,
    )

    keyring_module._validate_keyring_file_permissions(  # noqa: SLF001
        tmp_path / "keyring.json",
        0o666,
        platform="posix",
    )
