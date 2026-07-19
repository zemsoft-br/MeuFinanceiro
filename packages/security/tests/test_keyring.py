from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

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
    if os.name != "nt":
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert path.stat().st_mode & 0o777 == 0o644


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
        Keyring(version=1, active_key_id="k_abcdefghijkl", keys={"k_mnopqrstuvwx": b"x" * 32})
