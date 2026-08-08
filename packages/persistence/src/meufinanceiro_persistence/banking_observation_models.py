"""Immutable normalized transaction-observation persistence contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from meufinanceiro_persistence.banking_models import (
    clean_external_account_id,
    clean_opaque_text,
    clean_optional_text,
    require_aware,
)

_FINGERPRINT_NAMESPACE = "meufinanceiro:transaction-observation:v1"
_NORMALIZED_PAYLOAD_VERSION = 1
_MAX_AMOUNT_PRECISION = 24
_MAX_AMOUNT_SCALE = 8


class StoredTransactionObservationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    PENDING = "PENDING"
    INFERRED = "INFERRED"
    DELETED = "DELETED"


@dataclass(frozen=True, slots=True, repr=False)
class TransactionObservationSnapshot:
    external_account_id: str
    status: StoredTransactionObservationStatus
    effective_date: date
    amount: Decimal
    currency: str
    observed_at: datetime
    external_resource_id: str | None = None
    provider_updated_at: datetime | None = None
    description: str | None = None
    category: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, StoredTransactionObservationStatus):
            raise TypeError("status must be StoredTransactionObservationStatus")
        if not isinstance(self.effective_date, date) or isinstance(
            self.effective_date,
            datetime,
        ):
            raise TypeError("effective_date must be a date")
        object.__setattr__(
            self,
            "external_account_id",
            clean_external_account_id(self.external_account_id),
        )
        external_resource_id = _clean_optional_opaque(
            self.external_resource_id,
            "external_resource_id",
            512,
        )
        if (
            self.status is StoredTransactionObservationStatus.INFERRED
            and external_resource_id is not None
        ):
            raise ValueError("inferred observation cannot claim a provider resource ID")
        object.__setattr__(self, "external_resource_id", external_resource_id)
        object.__setattr__(self, "amount", _clean_amount(self.amount))
        object.__setattr__(self, "currency", _clean_currency(self.currency))
        object.__setattr__(
            self,
            "description",
            clean_optional_text(self.description, "description", 512),
        )
        object.__setattr__(
            self,
            "category",
            clean_optional_text(self.category, "category", 128),
        )
        require_aware(self.observed_at, "observed_at")
        require_aware(self.provider_updated_at, "provider_updated_at")

    @property
    def stable_fingerprint(self) -> str:
        external_resource_id = self.external_resource_id
        if external_resource_id is not None:
            material = _join_fingerprint_parts(
                "provider-id",
                self.external_account_id,
                external_resource_id,
            )
        else:
            material = _join_fingerprint_parts(
                "content",
                self.external_account_id,
                self.effective_date.isoformat(),
                _canonical_decimal(self.amount),
                self.currency,
                self.description or "",
                self.category or "",
            )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @property
    def normalized_payload_version(self) -> int:
        return _NORMALIZED_PAYLOAD_VERSION

    @property
    def deleted_at(self) -> datetime | None:
        if self.status is StoredTransactionObservationStatus.DELETED:
            return self.observed_at
        return None

    def __repr__(self) -> str:
        return (
            "TransactionObservationSnapshot("
            f"status={self.status.value!r}, currency={self.currency!r}, "
            "<financial-material-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class TransactionObservationRecord:
    id: UUID
    residence_id: UUID
    connection_id: UUID
    external_account_id: str
    external_resource_id: str | None
    status: StoredTransactionObservationStatus
    provider_updated_at: datetime | None
    effective_date: date
    amount: Decimal
    currency: str
    description: str | None
    category: str | None
    stable_fingerprint: str
    first_seen_at: datetime
    last_seen_at: datetime
    deleted_at: datetime | None
    normalized_payload_version: int
    updated_at: datetime

    def __repr__(self) -> str:
        return (
            "TransactionObservationRecord("
            f"status={self.status.value!r}, currency={self.currency!r}, "
            f"payload_version={self.normalized_payload_version}, "
            "<financial-material-redacted>)"
        )


@dataclass(frozen=True, slots=True)
class AppliedTransactionPage:
    records_seen: int
    records_applied: int
    committed_at: datetime

    def __post_init__(self) -> None:
        if (
            isinstance(self.records_seen, bool)
            or not isinstance(self.records_seen, int)
            or isinstance(self.records_applied, bool)
            or not isinstance(self.records_applied, int)
            or self.records_seen < 0
            or self.records_applied < 0
            or self.records_applied > self.records_seen
        ):
            raise ValueError("transaction page counters are invalid")
        require_aware(self.committed_at, "committed_at")


def _clean_optional_opaque(
    value: str | None,
    field_name: str,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    return clean_opaque_text(value, field_name, max_length)


def _clean_currency(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or value != value.upper()
    ):
        raise ValueError("currency must be a three-letter uppercase ASCII code")
    return value


def _clean_amount(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("amount must be Decimal")
    if not value.is_finite():
        raise ValueError("amount must be finite")
    if value == 0:
        return Decimal(0)

    sign, raw_digits, raw_exponent = value.as_tuple()
    if not isinstance(raw_exponent, int):
        raise ValueError("amount must be finite")
    digits = list(raw_digits)
    exponent = raw_exponent
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1

    precision = len(digits)
    if exponent >= 0:
        scale = 0
        integer_digits = precision + exponent
    else:
        scale = -exponent
        integer_digits = max(precision - scale, 0)
    if scale > _MAX_AMOUNT_SCALE or integer_digits > (
        _MAX_AMOUNT_PRECISION - _MAX_AMOUNT_SCALE
    ):
        raise ValueError("amount exceeds the supported precision")
    return Decimal((sign, tuple(digits), exponent))


def _canonical_decimal(value: Decimal) -> str:
    return format(_clean_amount(value), "f")


def _join_fingerprint_parts(kind: str, *parts: str) -> str:
    escaped = [
        part.replace("\\", "\\\\").replace("\x1f", "\\x1f")
        for part in parts
    ]
    return "\x1f".join((_FINGERPRINT_NAMESPACE, kind, *escaped))


__all__ = [
    "AppliedTransactionPage",
    "StoredTransactionObservationStatus",
    "TransactionObservationRecord",
    "TransactionObservationSnapshot",
]
