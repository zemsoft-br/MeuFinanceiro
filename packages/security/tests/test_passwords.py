from __future__ import annotations

import pytest

from meufinanceiro_security.errors import PasswordHashError
from meufinanceiro_security.passwords import PasswordService


def test_argon2id_hash_and_verify() -> None:
    service = PasswordService()

    encoded_hash = service.hash("correct horse battery staple")

    assert encoded_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert service.verify(encoded_hash, "correct horse battery staple") is True
    assert service.verify(encoded_hash, "wrong password") is False
    assert service.needs_rehash(encoded_hash) is False


def test_empty_password_is_rejected() -> None:
    with pytest.raises(PasswordHashError, match="non-empty"):
        PasswordService().hash("")


def test_malformed_hash_is_rejected_without_echoing_value() -> None:
    malformed = "not-a-password-hash"

    with pytest.raises(PasswordHashError) as exc_info:
        PasswordService().verify(malformed, "password")

    assert malformed not in str(exc_info.value)
