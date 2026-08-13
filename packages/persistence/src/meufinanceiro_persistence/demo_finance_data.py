"""Synthetic financial rows for the residencia-ipe-v1 demo contract."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

from meufinanceiro_finance import Money

from meufinanceiro_persistence.demo_contract import (
    DEMO_CHECKING_ACCOUNT_ID,
    DEMO_CURRENCY,
    DEMO_OPERATOR_ID,
    DEMO_REFERENCE_DATE,
)

_REQUEST_DIGEST_NAMESPACE: Final = "meufinanceiro:financial-movement-operation:v1"


@dataclass(frozen=True, slots=True)
class DemoAccountSpec:
    id: UUID
    visibility_scope: str
    account_type: str
    name: str


@dataclass(frozen=True, slots=True)
class DemoCategorySpec:
    id: UUID
    visibility_scope: str
    name: str


@dataclass(frozen=True, slots=True)
class DemoMovementSpec:
    id: UUID
    idempotency_key: UUID
    amount: Decimal
    result_effect: str
    role: str
    effective_date: date
    competence_date: date
    description: str | None
    reversal_of_id: UUID | None
    reversal_reason: str | None
    created_at: datetime

    @property
    def request_digest(self) -> str:
        if self.role == "STANDARD":
            if self.description is None:
                raise ValueError("STANDARD demo Movement requires description")
            return _request_digest(
                "STANDARD",
                str(DEMO_OPERATOR_ID),
                str(DEMO_CHECKING_ACCOUNT_ID),
                DEMO_CURRENCY,
                Money(self.amount, DEMO_CURRENCY).canonical_amount,
                self.result_effect,
                self.effective_date.isoformat(),
                self.competence_date.isoformat(),
                self.description,
            )
        if self.reversal_of_id is None or self.reversal_reason is None:
            raise ValueError("REVERSAL demo Movement requires reversal fields")
        return _request_digest(
            "REVERSAL",
            str(DEMO_OPERATOR_ID),
            str(self.reversal_of_id),
            self.effective_date.isoformat(),
            self.competence_date.isoformat(),
            self.reversal_reason,
        )


def _at_reference(days: int) -> datetime:
    return datetime(2026, 11, 1, 12, 0, tzinfo=UTC) + timedelta(days=days)


DEMO_ACCOUNTS: Final = (
    DemoAccountSpec(
        id=UUID("55555555-5555-4555-8555-555555555551"),
        visibility_scope="PERSONAL",
        account_type="CHECKING",
        name="Conta Corrente Ipê",
    ),
    DemoAccountSpec(
        id=UUID("55555555-5555-4555-8555-555555555552"),
        visibility_scope="HOUSEHOLD",
        account_type="CASH",
        name="Carteira da Casa",
    ),
)

DEMO_CATEGORIES: Final = (
    DemoCategorySpec(
        id=UUID("66666666-6666-4666-8666-666666666661"),
        visibility_scope="HOUSEHOLD",
        name="Moradia",
    ),
    DemoCategorySpec(
        id=UUID("66666666-6666-4666-8666-666666666662"),
        visibility_scope="PERSONAL",
        name="Alimentação",
    ),
)

_REVERSED_EXPENSE_ID: Final = UUID("88888888-8888-4888-8888-888888888884")

DEMO_MOVEMENTS: Final = (
    DemoMovementSpec(
        id=UUID("88888888-8888-4888-8888-888888888881"),
        idempotency_key=UUID("99999999-9999-4999-8999-999999999981"),
        amount=Decimal("4500"),
        result_effect="INCOME",
        role="STANDARD",
        effective_date=DEMO_REFERENCE_DATE,
        competence_date=DEMO_REFERENCE_DATE,
        description="Salário demonstrativo",
        reversal_of_id=None,
        reversal_reason=None,
        created_at=_at_reference(0),
    ),
    DemoMovementSpec(
        id=UUID("88888888-8888-4888-8888-888888888882"),
        idempotency_key=UUID("99999999-9999-4999-8999-999999999982"),
        amount=Decimal("-1600"),
        result_effect="EXPENSE",
        role="STANDARD",
        effective_date=DEMO_REFERENCE_DATE + timedelta(days=1),
        competence_date=DEMO_REFERENCE_DATE + timedelta(days=1),
        description="Aluguel demonstrativo",
        reversal_of_id=None,
        reversal_reason=None,
        created_at=_at_reference(1),
    ),
    DemoMovementSpec(
        id=UUID("88888888-8888-4888-8888-888888888883"),
        idempotency_key=UUID("99999999-9999-4999-8999-999999999983"),
        amount=Decimal("-420.75"),
        result_effect="EXPENSE",
        role="STANDARD",
        effective_date=DEMO_REFERENCE_DATE + timedelta(days=2),
        competence_date=DEMO_REFERENCE_DATE + timedelta(days=2),
        description="Mercado demonstrativo",
        reversal_of_id=None,
        reversal_reason=None,
        created_at=_at_reference(2),
    ),
    DemoMovementSpec(
        id=_REVERSED_EXPENSE_ID,
        idempotency_key=UUID("99999999-9999-4999-8999-999999999984"),
        amount=Decimal("-90"),
        result_effect="EXPENSE",
        role="STANDARD",
        effective_date=DEMO_REFERENCE_DATE + timedelta(days=3),
        competence_date=DEMO_REFERENCE_DATE + timedelta(days=3),
        description="Despesa demonstrativa a estornar",
        reversal_of_id=None,
        reversal_reason=None,
        created_at=_at_reference(3),
    ),
    DemoMovementSpec(
        id=UUID("88888888-8888-4888-8888-888888888885"),
        idempotency_key=UUID("99999999-9999-4999-8999-999999999985"),
        amount=Decimal("90"),
        result_effect="EXPENSE",
        role="REVERSAL",
        effective_date=DEMO_REFERENCE_DATE + timedelta(days=4),
        competence_date=DEMO_REFERENCE_DATE + timedelta(days=4),
        description=None,
        reversal_of_id=_REVERSED_EXPENSE_ID,
        reversal_reason="Correção demonstrativa",
        created_at=_at_reference(4),
    ),
)


def _request_digest(*parts: str) -> str:
    material = "\x1f".join((_REQUEST_DIGEST_NAMESPACE, *parts))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


__all__ = [
    "DEMO_ACCOUNTS",
    "DEMO_CATEGORIES",
    "DEMO_MOVEMENTS",
    "DemoAccountSpec",
    "DemoCategorySpec",
    "DemoMovementSpec",
]
