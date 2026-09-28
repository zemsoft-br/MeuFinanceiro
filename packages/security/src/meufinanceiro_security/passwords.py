"""Argon2id password hashing with an explicit RFC 9106 profile."""

from __future__ import annotations

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from meufinanceiro_security.errors import PasswordHashError

ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST_KIB = 64 * 1024
ARGON2_PARALLELISM = 4
ARGON2_HASH_LENGTH = 32
ARGON2_SALT_LENGTH = 16


class PasswordService:
    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=ARGON2_TIME_COST,
            memory_cost=ARGON2_MEMORY_COST_KIB,
            parallelism=ARGON2_PARALLELISM,
            hash_len=ARGON2_HASH_LENGTH,
            salt_len=ARGON2_SALT_LENGTH,
            type=Type.ID,
        )

    def hash(self, password: str) -> str:
        if not isinstance(password, str) or not password:
            raise PasswordHashError("password must be a non-empty string")
        return self._hasher.hash(password)

    def verify(self, encoded_hash: str, password: str) -> bool:
        if not isinstance(encoded_hash, str) or not isinstance(password, str):
            raise PasswordHashError("password verification inputs must be strings")
        try:
            return self._hasher.verify(encoded_hash, password)
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError) as exc:
            raise PasswordHashError("password hash cannot be verified") from exc

    def needs_rehash(self, encoded_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(encoded_hash)
        except (InvalidHashError, VerificationError) as exc:
            raise PasswordHashError("password hash cannot be inspected") from exc
