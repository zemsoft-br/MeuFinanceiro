from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from meufinanceiro_finance import (
    FinancialAccountBalanceSnapshot,
    FinancialAccountStatement,
    FinancialManualEntryDraft,
    FinancialManualEntryType,
    FinancialMovementRecord,
    FinancialMovementReversalDraft,
    FinancialMovementRole,
    FinancialResultEffect,
    FinancialStatementEntry,
    FinancialTransferDraft,
    FinancialTransferRecord,
    FinancialTransferReversalDraft,
    FinancialTransferRole,
    Money,
)
from meufinanceiro_persistence import OperatorRole, OperatorSessionPrincipal
from meufinanceiro_security.keyring import initialize_keyring_file

from app.core.config import Settings
from app.main import create_app
from app.services.operator_auth import InvalidOperatorSessionError

TOKEN = "F" * 43
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
OPERATOR_ID = UUID("30000000-0000-4000-8000-000000000003")
ACCOUNT_ID = UUID("40000000-0000-4000-8000-000000000004")
OTHER_ACCOUNT_ID = UUID("50000000-0000-4000-8000-000000000005")
MOVEMENT_ID = UUID("60000000-0000-4000-8000-000000000006")
REVERSAL_ID = UUID("70000000-0000-4000-8000-000000000007")
TRANSFER_ID = UUID("80000000-0000-4000-8000-000000000008")
TRANSFER_REVERSAL_ID = UUID("90000000-0000-4000-8000-000000000009")
SOURCE_LEG_ID = UUID("a0000000-0000-4000-8000-00000000000a")
DESTINATION_LEG_ID = UUID("b0000000-0000-4000-8000-00000000000b")
IDEMPOTENCY_KEY = UUID("c0000000-0000-4000-8000-00000000000c")
SECOND_IDEMPOTENCY_KEY = UUID("d0000000-0000-4000-8000-00000000000d")
NOW = datetime(2026, 9, 20, 3, 30, tzinfo=UTC)


class FakeAuthentication:
    def resolve(self, token: str) -> OperatorSessionPrincipal:
        if token != TOKEN:
            raise InvalidOperatorSessionError("operator session is invalid")
        return OperatorSessionPrincipal(
            session_id=UUID("e0000000-0000-4000-8000-00000000000e"),
            installation_id=INSTALLATION_ID,
            operator_id=OPERATOR_ID,
            login_name="admin",
            role=OperatorRole.INSTALLATION_ADMIN,
            expires_at=datetime(2027, 9, 20, tzinfo=UTC),
            primary_residence_id=RESIDENCE_ID,
        )


class FakeSemanticFinancialService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def record_manual_entry(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialManualEntryDraft,
    ) -> FinancialMovementRecord:
        self.calls.append(
            (
                "manual",
                (
                    installation_id,
                    residence_id,
                    operator_id,
                    idempotency_key,
                    draft,
                ),
            )
        )
        amount = (
            draft.magnitude
            if draft.entry_type is FinancialManualEntryType.INCOME
            else -draft.magnitude
        )
        effect = (
            FinancialResultEffect.INCOME
            if draft.entry_type is FinancialManualEntryType.INCOME
            else FinancialResultEffect.EXPENSE
        )
        return FinancialMovementRecord(
            id=MOVEMENT_ID,
            account_id=draft.account_id,
            amount=amount,
            result_effect=effect,
            role=FinancialMovementRole.STANDARD,
            effective_date=draft.effective_date,
            competence_date=draft.competence_date,
            description=draft.description,
            reversal_of_id=None,
            reversal_reason=None,
            created_by_operator_id=operator_id,
            created_at=NOW,
        )

    def reverse_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialMovementReversalDraft,
    ) -> FinancialMovementRecord:
        self.calls.append(
            (
                "reverse_movement",
                (
                    installation_id,
                    residence_id,
                    operator_id,
                    idempotency_key,
                    draft,
                ),
            )
        )
        return FinancialMovementRecord(
            id=REVERSAL_ID,
            account_id=ACCOUNT_ID,
            amount=Money(Decimal("25"), "BRL"),
            result_effect=FinancialResultEffect.EXPENSE,
            role=FinancialMovementRole.REVERSAL,
            effective_date=draft.effective_date,
            competence_date=draft.competence_date,
            description=None,
            reversal_of_id=draft.movement_id,
            reversal_reason=draft.reason,
            created_by_operator_id=operator_id,
            created_at=NOW,
        )

    def create_transfer(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialTransferDraft,
    ) -> FinancialTransferRecord:
        self.calls.append(
            (
                "transfer",
                (
                    installation_id,
                    residence_id,
                    operator_id,
                    idempotency_key,
                    draft,
                ),
            )
        )
        return _transfer_record(
            transfer_id=TRANSFER_ID,
            role=FinancialTransferRole.STANDARD,
            reversal_of_id=None,
        )

    def reverse_transfer(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialTransferReversalDraft,
    ) -> FinancialTransferRecord:
        self.calls.append(
            (
                "reverse_transfer",
                (
                    installation_id,
                    residence_id,
                    operator_id,
                    idempotency_key,
                    draft,
                ),
            )
        )
        return _transfer_record(
            transfer_id=TRANSFER_REVERSAL_ID,
            role=FinancialTransferRole.REVERSAL,
            reversal_of_id=draft.transfer_id,
        )

    def get_balance_snapshot(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountBalanceSnapshot:
        self.calls.append(
            (
                "balance",
                (installation_id, residence_id, operator_id, account_id),
            )
        )
        return FinancialAccountBalanceSnapshot(
            account_id=account_id,
            currency="BRL",
            opening_balance=Money(Decimal("1000"), "BRL"),
            movement_net=Money(Decimal("250.50"), "BRL"),
            current_balance=Money(Decimal("1250.50"), "BRL"),
            movement_count=1,
            calculated_at=NOW,
        )

    def get_statement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountStatement:
        movement = FinancialMovementRecord(
            id=MOVEMENT_ID,
            account_id=account_id,
            amount=Money(Decimal("250.50"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            role=FinancialMovementRole.STANDARD,
            effective_date=date(2026, 9, 20),
            competence_date=date(2026, 9, 20),
            description="Receita teste",
            reversal_of_id=None,
            reversal_reason=None,
            created_by_operator_id=operator_id,
            created_at=NOW,
        )
        self.calls.append(
            (
                "statement",
                (installation_id, residence_id, operator_id, account_id),
            )
        )
        return FinancialAccountStatement(
            account_id=account_id,
            currency="BRL",
            opening_balance=Money(Decimal("1000"), "BRL"),
            entries=(
                FinancialStatementEntry(
                    movement=movement,
                    balance_after=Money(Decimal("1250.50"), "BRL"),
                ),
            ),
            closing_balance=Money(Decimal("1250.50"), "BRL"),
            calculated_at=NOW,
        )


def _transfer_record(
    *,
    transfer_id: UUID,
    role: FinancialTransferRole,
    reversal_of_id: UUID | None,
) -> FinancialTransferRecord:
    return FinancialTransferRecord(
        id=transfer_id,
        source_account_id=ACCOUNT_ID,
        destination_account_id=OTHER_ACCOUNT_ID,
        currency="BRL",
        source_movement_id=SOURCE_LEG_ID,
        destination_movement_id=DESTINATION_LEG_ID,
        role=role,
        reversal_of_id=reversal_of_id,
        created_by_operator_id=OPERATOR_ID,
        created_at=NOW,
    )


@pytest.fixture
def client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, FakeSemanticFinancialService]]:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )
    service = FakeSemanticFinancialService()
    with TestClient(create_app(settings)) as test_client:
        test_client.app.state.operator_authentication = FakeAuthentication()
        test_client.app.state.financial_core = service
        yield test_client, service


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _entry_payload(idempotency_key: UUID) -> dict[str, object]:
    return {
        "idempotencyKey": str(idempotency_key),
        "amount": "25.50",
        "currency": "BRL",
        "effectiveDate": "2026-09-20",
        "competenceDate": "2026-09-20",
        "description": "Lançamento teste",
    }


def test_income_and_expense_are_explicit_semantic_commands(
    client: tuple[TestClient, FakeSemanticFinancialService],
) -> None:
    test_client, service = client

    income = test_client.post(
        f"/api/v1/finance/accounts/{ACCOUNT_ID}/income",
        headers=headers(),
        json=_entry_payload(IDEMPOTENCY_KEY),
    )
    expense = test_client.post(
        f"/api/v1/finance/accounts/{ACCOUNT_ID}/expense",
        headers=headers(),
        json=_entry_payload(SECOND_IDEMPOTENCY_KEY),
    )

    assert income.status_code == 201
    assert income.json()["money"] == {"amount": "25.5", "currency": "BRL"}
    assert income.json()["resultEffect"] == "INCOME"
    assert expense.status_code == 201
    assert expense.json()["money"] == {"amount": "-25.5", "currency": "BRL"}
    assert expense.json()["resultEffect"] == "EXPENSE"

    manual_calls = [call for call in service.calls if call[0] == "manual"]
    assert len(manual_calls) == 2
    income_draft = manual_calls[0][1][-1]
    expense_draft = manual_calls[1][1][-1]
    assert isinstance(income_draft, FinancialManualEntryDraft)
    assert isinstance(expense_draft, FinancialManualEntryDraft)
    assert income_draft.entry_type is FinancialManualEntryType.INCOME
    assert expense_draft.entry_type is FinancialManualEntryType.EXPENSE
    assert income_draft.magnitude == Money(Decimal("25.50"), "BRL")
    assert expense_draft.magnitude == Money(Decimal("25.50"), "BRL")


def test_semantic_entry_rejects_numeric_amount_and_non_v4_idempotency(
    client: tuple[TestClient, FakeSemanticFinancialService],
) -> None:
    test_client, service = client
    numeric = _entry_payload(IDEMPOTENCY_KEY)
    numeric["amount"] = 25.50
    invalid_key = _entry_payload(
        UUID("10000000-0000-1000-8000-000000000001")
    )

    numeric_response = test_client.post(
        f"/api/v1/finance/accounts/{ACCOUNT_ID}/income",
        headers=headers(),
        json=numeric,
    )
    invalid_key_response = test_client.post(
        f"/api/v1/finance/accounts/{ACCOUNT_ID}/income",
        headers=headers(),
        json=invalid_key,
    )

    assert numeric_response.status_code == 422
    assert invalid_key_response.status_code == 422
    assert service.calls == []


def test_movement_reversal_has_no_caller_supplied_amount(
    client: tuple[TestClient, FakeSemanticFinancialService],
) -> None:
    test_client, service = client
    payload = {
        "idempotencyKey": str(IDEMPOTENCY_KEY),
        "effectiveDate": "2026-09-20",
        "competenceDate": "2026-09-20",
        "reason": "Correção",
    }
    response = test_client.post(
        f"/api/v1/finance/movements/{MOVEMENT_ID}/reversal",
        headers=headers(),
        json=payload,
    )
    forbidden_amount = test_client.post(
        f"/api/v1/finance/movements/{MOVEMENT_ID}/reversal",
        headers=headers(),
        json={**payload, "amount": "25.50"},
    )

    assert response.status_code == 201
    assert response.json()["role"] == "REVERSAL"
    assert response.json()["reversalOfId"] == str(MOVEMENT_ID)
    call = next(call for call in service.calls if call[0] == "reverse_movement")
    draft = call[1][-1]
    assert isinstance(draft, FinancialMovementReversalDraft)
    assert forbidden_amount.status_code == 422


def test_transfer_and_reversal_use_atomic_transfer_contract(
    client: tuple[TestClient, FakeSemanticFinancialService],
) -> None:
    test_client, service = client
    response = test_client.post(
        "/api/v1/finance/transfers",
        headers=headers(),
        json={
            "idempotencyKey": str(IDEMPOTENCY_KEY),
            "sourceAccountId": str(ACCOUNT_ID),
            "destinationAccountId": str(OTHER_ACCOUNT_ID),
            "amount": "50.00",
            "currency": "BRL",
            "effectiveDate": "2026-09-20",
            "competenceDate": "2026-09-20",
            "description": "Reserva",
        },
    )
    reversal = test_client.post(
        f"/api/v1/finance/transfers/{TRANSFER_ID}/reversal",
        headers=headers(),
        json={
            "idempotencyKey": str(SECOND_IDEMPOTENCY_KEY),
            "effectiveDate": "2026-09-20",
            "competenceDate": "2026-09-20",
            "reason": "Correção",
        },
    )

    assert response.status_code == 201
    assert response.json()["transferId"] == str(TRANSFER_ID)
    assert response.json()["role"] == "STANDARD"
    assert reversal.status_code == 201
    assert reversal.json()["role"] == "REVERSAL"
    assert reversal.json()["reversalOfId"] == str(TRANSFER_ID)

    transfer_call = next(call for call in service.calls if call[0] == "transfer")
    transfer_draft = transfer_call[1][-1]
    assert isinstance(transfer_draft, FinancialTransferDraft)
    assert transfer_draft.magnitude == Money(Decimal("50"), "BRL")


def test_balance_and_statement_return_derived_money_as_decimal_strings(
    client: tuple[TestClient, FakeSemanticFinancialService],
) -> None:
    test_client, _ = client

    balance = test_client.get(
        f"/api/v1/finance/accounts/{ACCOUNT_ID}/balance",
        headers=headers(),
    )
    statement = test_client.get(
        f"/api/v1/finance/accounts/{ACCOUNT_ID}/statement",
        headers=headers(),
    )

    assert balance.status_code == 200
    assert balance.json()["openingBalance"] == {
        "amount": "1000",
        "currency": "BRL",
    }
    assert balance.json()["movementNet"] == {
        "amount": "250.5",
        "currency": "BRL",
    }
    assert balance.json()["currentBalance"] == {
        "amount": "1250.5",
        "currency": "BRL",
    }
    assert balance.json()["movementCount"] == 1

    assert statement.status_code == 200
    assert statement.json()["closingBalance"] == {
        "amount": "1250.5",
        "currency": "BRL",
    }
    assert statement.json()["entries"][0]["balanceAfter"] == {
        "amount": "1250.5",
        "currency": "BRL",
    }


def test_openapi_keeps_generic_movement_writer_absent_and_semantic_paths_present(
    client: tuple[TestClient, FakeSemanticFinancialService],
) -> None:
    test_client, _ = client
    paths = test_client.get("/api/v1/openapi.json").json()["paths"]

    assert "/api/v1/finance/movements" not in paths
    assert "/api/v1/finance/accounts/{account_id}/income" in paths
    assert "/api/v1/finance/accounts/{account_id}/expense" in paths
    assert "/api/v1/finance/movements/{movement_id}/reversal" in paths
    assert "/api/v1/finance/transfers" in paths
    assert "/api/v1/finance/transfers/{transfer_id}/reversal" in paths
    assert "/api/v1/finance/accounts/{account_id}/balance" in paths
    assert "/api/v1/finance/accounts/{account_id}/statement" in paths
