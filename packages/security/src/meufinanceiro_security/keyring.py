"""Versioned local keyring management using only the Python standard library."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from meufinanceiro_security.errors import KeyringError

KEYRING_VERSION = 1
KEY_SIZE_BYTES = 32
MAX_KEYRING_BYTES = 64 * 1024
MAX_KEYS = 32
KEY_ID_PATTERN = re.compile(r"^k_[A-Za-z0-9_-]{12,64}$")


def _encode_material(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_material(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise KeyringError("key material must be a non-empty base64url string")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise KeyringError("key material contains invalid base64url characters")
    padded = value + "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise KeyringError("key material is not valid base64url") from exc
    if len(decoded) != KEY_SIZE_BYTES:
        raise KeyringError("each key must contain exactly 256 bits")
    return decoded


def _new_key_id() -> str:
    return f"k_{secrets.token_urlsafe(12)}"


@dataclass(frozen=True, slots=True)
class Keyring:
    version: int
    active_key_id: str
    keys: Mapping[str, bytes]

    def __post_init__(self) -> None:
        normalized = {key_id: bytes(material) for key_id, material in self.keys.items()}
        object.__setattr__(self, "keys", MappingProxyType(normalized))
        _validate_keyring(self)

    @property
    def active_key(self) -> bytes:
        return self.keys[self.active_key_id]

    def key(self, key_id: str) -> bytes | None:
        return self.keys.get(key_id)


def _validate_keyring(keyring: Keyring) -> None:
    if keyring.version != KEYRING_VERSION:
        raise KeyringError(f"unsupported keyring version: {keyring.version}")
    if not KEY_ID_PATTERN.fullmatch(keyring.active_key_id):
        raise KeyringError("active key id is invalid")
    if not 1 <= len(keyring.keys) <= MAX_KEYS:
        raise KeyringError(f"keyring must contain between 1 and {MAX_KEYS} keys")
    for key_id, material in keyring.keys.items():
        if not KEY_ID_PATTERN.fullmatch(key_id):
            raise KeyringError("keyring contains an invalid key id")
        if len(material) != KEY_SIZE_BYTES:
            raise KeyringError("each key must contain exactly 256 bits")
    if keyring.active_key_id not in keyring.keys:
        raise KeyringError("active key id does not exist in keyring")


def create_keyring() -> Keyring:
    key_id = _new_key_id()
    return Keyring(
        version=KEYRING_VERSION,
        active_key_id=key_id,
        keys={key_id: secrets.token_bytes(KEY_SIZE_BYTES)},
    )


def rotate_keyring(keyring: Keyring) -> Keyring:
    if len(keyring.keys) >= MAX_KEYS:
        raise KeyringError("keyring reached the maximum number of retained keys")
    key_id = _new_key_id()
    keys = dict(keyring.keys)
    keys[key_id] = secrets.token_bytes(KEY_SIZE_BYTES)
    return Keyring(version=KEYRING_VERSION, active_key_id=key_id, keys=keys)


def serialize_keyring(keyring: Keyring) -> str:
    _validate_keyring(keyring)
    payload = {
        "active_key_id": keyring.active_key_id,
        "keys": {
            key_id: _encode_material(material)
            for key_id, material in sorted(keyring.keys.items())
        },
        "version": keyring.version,
    }
    return (
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    )


def parse_keyring(raw: str) -> Keyring:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise KeyringError("keyring is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "active_key_id",
        "keys",
    }:
        raise KeyringError("keyring schema is invalid")
    version = payload["version"]
    active_key_id = payload["active_key_id"]
    encoded_keys = payload["keys"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise KeyringError("keyring version must be an integer")
    if not isinstance(active_key_id, str):
        raise KeyringError("active key id must be a string")
    if not isinstance(encoded_keys, dict):
        raise KeyringError("keyring keys must be an object")
    keys: dict[str, bytes] = {}
    for key_id, encoded_material in encoded_keys.items():
        if not isinstance(key_id, str):
            raise KeyringError("key ids must be strings")
        keys[key_id] = _decode_material(encoded_material)
    return Keyring(version=version, active_key_id=active_key_id, keys=keys)


def load_keyring(path: str | Path) -> Keyring:
    resolved = Path(path)
    try:
        file_stat = resolved.stat()
    except FileNotFoundError as exc:
        raise KeyringError("keyring file does not exist") from exc
    except OSError as exc:
        raise KeyringError("keyring file cannot be inspected") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise KeyringError("keyring path must reference a regular file")
    if file_stat.st_size <= 0 or file_stat.st_size > MAX_KEYRING_BYTES:
        raise KeyringError("keyring file size is invalid")
    if os.name != "nt" and file_stat.st_mode & 0o022:
        raise KeyringError("keyring file must not be writable by group or others")
    try:
        raw = resolved.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise KeyringError("keyring file cannot be read") from exc
    return parse_keyring(raw)


def write_keyring(path: str | Path, keyring: Keyring) -> None:
    resolved = Path(path)
    parent = resolved.parent
    parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        parent.chmod(0o700)
    content = serialize_keyring(keyring).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{resolved.name}.", dir=parent
    )
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, resolved)
        if os.name != "nt":
            # The private parent directory protects the host path. Read permission for
            # others is required because Compose file secrets are bind-mounted into
            # fixed non-root service UIDs.
            resolved.chmod(0o644)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def initialize_keyring_file(path: str | Path) -> Keyring:
    resolved = Path(path)
    if resolved.exists():
        raise KeyringError("keyring file already exists")
    keyring = create_keyring()
    write_keyring(resolved, keyring)
    return keyring


def rotate_keyring_file(path: str | Path) -> Keyring:
    resolved = Path(path)
    rotated = rotate_keyring(load_keyring(resolved))
    write_keyring(resolved, rotated)
    return rotated
