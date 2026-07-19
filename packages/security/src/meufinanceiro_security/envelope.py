"""Authenticated, versioned encryption envelopes for credentials and tokens."""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from meufinanceiro_security.errors import (
    EnvelopeError,
    EnvelopeIntegrityError,
    KeyUnavailableError,
)
from meufinanceiro_security.keyring import KEY_ID_PATTERN, Keyring

ENVELOPE_VERSION = 1
ALGORITHM = "A256GCM"
NONCE_BYTES = 12
MAX_PLAINTEXT_BYTES = 1024 * 1024
MAX_AAD_BYTES = 4096
MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
B64_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: object, field: str) -> bytes:
    if not isinstance(value, str) or not value or not B64_PATTERN.fullmatch(value):
        raise EnvelopeError(f"envelope {field} is not valid base64url")
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.b64decode(padded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EnvelopeError(f"envelope {field} is not valid base64url") from exc


def _as_bytes(
    value: bytes | str, field: str, maximum: int, *, allow_empty: bool
) -> bytes:
    encoded = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if not allow_empty and not encoded:
        raise EnvelopeError(f"{field} must not be empty")
    if len(encoded) > maximum:
        raise EnvelopeError(f"{field} exceeds the supported size")
    return encoded


@dataclass(frozen=True, slots=True)
class Envelope:
    version: int
    algorithm: str
    key_id: str
    nonce: bytes
    ciphertext: bytes

    def serialize(self) -> str:
        payload = {
            "algorithm": self.algorithm,
            "ciphertext": _encode(self.ciphertext),
            "key_id": self.key_id,
            "nonce": _encode(self.nonce),
            "version": self.version,
        }
        return json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )

    @classmethod
    def parse(cls, raw: str) -> Envelope:
        if (
            not isinstance(raw, str)
            or not raw
            or len(raw.encode("utf-8")) > MAX_ENVELOPE_BYTES
        ):
            raise EnvelopeError("encrypted envelope size is invalid")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EnvelopeError("encrypted envelope is not valid JSON") from exc
        expected = {"version", "algorithm", "key_id", "nonce", "ciphertext"}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise EnvelopeError("encrypted envelope schema is invalid")
        version = payload["version"]
        algorithm = payload["algorithm"]
        key_id = payload["key_id"]
        if version != ENVELOPE_VERSION:
            raise EnvelopeError("encrypted envelope version is unsupported")
        if algorithm != ALGORITHM:
            raise EnvelopeError("encrypted envelope algorithm is unsupported")
        if not isinstance(key_id, str) or not KEY_ID_PATTERN.fullmatch(key_id):
            raise EnvelopeError("encrypted envelope key id is invalid")
        nonce = _decode(payload["nonce"], "nonce")
        ciphertext = _decode(payload["ciphertext"], "ciphertext")
        if len(nonce) != NONCE_BYTES:
            raise EnvelopeError("encrypted envelope nonce must contain 96 bits")
        if len(ciphertext) < 16:
            raise EnvelopeError("encrypted envelope ciphertext is too short")
        return cls(
            version=version,
            algorithm=algorithm,
            key_id=key_id,
            nonce=nonce,
            ciphertext=ciphertext,
        )


class SecretCipher:
    def __init__(self, keyring: Keyring) -> None:
        self._keyring = keyring

    @property
    def active_key_id(self) -> str:
        return self._keyring.active_key_id

    def encrypt(self, plaintext: bytes | str, *, aad: bytes | str) -> str:
        cleartext = _as_bytes(
            plaintext,
            "plaintext",
            MAX_PLAINTEXT_BYTES,
            allow_empty=True,
        )
        associated_data = _as_bytes(aad, "aad", MAX_AAD_BYTES, allow_empty=False)
        nonce = secrets.token_bytes(NONCE_BYTES)
        ciphertext = AESGCM(self._keyring.active_key).encrypt(
            nonce,
            cleartext,
            associated_data,
        )
        return Envelope(
            version=ENVELOPE_VERSION,
            algorithm=ALGORITHM,
            key_id=self._keyring.active_key_id,
            nonce=nonce,
            ciphertext=ciphertext,
        ).serialize()

    def decrypt(self, raw_envelope: str, *, aad: bytes | str) -> bytes:
        envelope = Envelope.parse(raw_envelope)
        associated_data = _as_bytes(aad, "aad", MAX_AAD_BYTES, allow_empty=False)
        key = self._keyring.key(envelope.key_id)
        if key is None:
            raise KeyUnavailableError(
                "encrypted envelope references an unavailable key"
            )
        try:
            return AESGCM(key).decrypt(
                envelope.nonce,
                envelope.ciphertext,
                associated_data,
            )
        except InvalidTag as exc:
            raise EnvelopeIntegrityError(
                "encrypted envelope authentication failed"
            ) from exc

    def decrypt_text(self, raw_envelope: str, *, aad: bytes | str) -> str:
        try:
            return self.decrypt(raw_envelope, aad=aad).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EnvelopeError("decrypted value is not valid UTF-8") from exc

    def rewrap(self, raw_envelope: str, *, aad: bytes | str) -> str:
        envelope = Envelope.parse(raw_envelope)
        if envelope.key_id == self._keyring.active_key_id:
            return raw_envelope
        plaintext = self.decrypt(raw_envelope, aad=aad)
        return self.encrypt(plaintext, aad=aad)
