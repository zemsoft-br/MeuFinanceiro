from __future__ import annotations

import json

import pytest

from meufinanceiro_security.envelope import Envelope, SecretCipher
from meufinanceiro_security.errors import EnvelopeError, EnvelopeIntegrityError
from meufinanceiro_security.keyring import create_keyring, rotate_keyring

AAD = "provider-credential:household-123:pluggy"


def test_encrypt_decrypt_round_trip() -> None:
    cipher = SecretCipher(create_keyring())

    envelope = cipher.encrypt("credential-value", aad=AAD)

    assert cipher.decrypt_text(envelope, aad=AAD) == "credential-value"
    parsed = Envelope.parse(envelope)
    assert parsed.key_id == cipher.active_key_id
    assert len(parsed.nonce) == 12


def test_same_value_uses_fresh_nonce() -> None:
    cipher = SecretCipher(create_keyring())

    first = cipher.encrypt("same", aad=AAD)
    second = cipher.encrypt("same", aad=AAD)

    assert first != second


def test_wrong_aad_fails_authentication() -> None:
    cipher = SecretCipher(create_keyring())
    envelope = cipher.encrypt("credential-value", aad=AAD)

    with pytest.raises(EnvelopeIntegrityError, match="authentication failed"):
        cipher.decrypt(envelope, aad="different-context")


def test_ciphertext_tampering_fails_authentication() -> None:
    cipher = SecretCipher(create_keyring())
    payload = json.loads(cipher.encrypt("credential-value", aad=AAD))
    payload["ciphertext"] = payload["ciphertext"][:-1] + (
        "A" if payload["ciphertext"][-1] != "A" else "B"
    )

    with pytest.raises(EnvelopeIntegrityError, match="authentication failed"):
        cipher.decrypt(json.dumps(payload), aad=AAD)


def test_rotation_rewraps_old_envelope_without_data_loss() -> None:
    original_keyring = create_keyring()
    old_cipher = SecretCipher(original_keyring)
    old_envelope = old_cipher.encrypt("credential-value", aad=AAD)
    rotated_cipher = SecretCipher(rotate_keyring(original_keyring))

    rewrapped = rotated_cipher.rewrap(old_envelope, aad=AAD)

    assert Envelope.parse(rewrapped).key_id == rotated_cipher.active_key_id
    assert rotated_cipher.decrypt_text(rewrapped, aad=AAD) == "credential-value"


def test_empty_aad_is_rejected() -> None:
    cipher = SecretCipher(create_keyring())

    with pytest.raises(EnvelopeError, match="must not be empty"):
        cipher.encrypt("credential-value", aad="")
