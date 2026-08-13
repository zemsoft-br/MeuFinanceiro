from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountRecord,
    FinancialAccountStatus,
    FinancialAccountType,
    FinancialMovementRecord,
    FinancialMovementRole,
    FinancialOpeningBalanceDraft,
    FinancialOpeningBalanceRecord,
    FinancialResultEffect,
    FinancialVisibilityScope,
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
OPENING_ID = UUID("50000000-0000-4000-8000-000000000005")
MOVEMENT_ID = UUID("60000000-0000-4000-8000-000000000006")
REVERSAL_ID = UUID("70000000-0000-4000-8000-000000000007")
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def principal(*, residence_id: UUID | None = RESIDENCE_ID) -> OperatorSessionPrincipal:
    return OperatorSessionPrincipal(
        session_id=uuid4(),
        installation_id=INSTALLATION_ID,
        operator_id=OPERATOR_ID,
        login_name="admin",
        role=OperatorRole.INSTALLATION_ADMIN,
        expires_at=datetime(2027, 8, 13, tzinfo=UTC),
        primary_residence_id=residence_id,
    )


class FakeAuthentication:
    def __init__(self) -> None:
        self.principal = principal()

    def resolve(self, token: str) -> OperatorSessionPrincipal:
        if token != TOKEN:
            raise InvalidOperatorSessionError("operator session is invalid")
        return self.principal


class FakeFinancialCoreService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.account = FinancialAccountRecord(
            id=ACCOUNT_ID,
            residence_id=RESIDENCE_ID,
            owner_operator_id=OPERATOR_ID,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
            account_type=FinancialAccountType.CHECKING,
            custom_type_name=None,
            name="Conta principal",
            currency="BRL",
            status=FinancialAccountStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            archived_at=None,
        )
        self.opening_balance: FinancialOpeningBalanceRecord | None = (
            FinancialOpeningBalanceRecord(
                id=OPENING_ID,
                residence_id=RESIDENCE_ID,
                account_id=ACCOUNT_ID,
                amount=Money(Decimal("1234.50"), "BRL"),
                effective_date=date(2026, 8, 1),
                created_by_operator_id=OPERATOR_ID,
                created_at=NOW,
            )
        )
        self.movements: tuple[FinancialMovementRecord, ...] = (
            FinancialMovementRecord(
                id=MOVEMENT_ID,
                account_id=ACCOUNT_ID,
                amount=Money(Decimal("-75.25"), "BRL"),
                result_effect=FinancialResultEffect.EXPENSE,
                role=FinancialMovementRole.STANDARD,
                effective_date=date(2026, 8, 12),
                competence_date=date(2026, 8, 12),
                description="Mercado",
                reversal_of_id=None,
                reversal_reason=None,
                created_by_operator_id=OPERATOR_ID,
                created_at=NOW,
            ),
            FinancialMovementRecord(
                id=REVERSAL_ID,
                account_id=ACCOUNT_ID,
                amount=Money(Decimal("75.25"), "BRL"),
                result_effect=FinancialResultEffect.EXPENSE,
                role=FinancialMovementRole.REVERSAL,
                effective_date=date(2026, 8, 13),
                competence_date=date(2026, 8, 13),
                description=None,
                reversal_of_id=MOVEMENT_ID,
                reversal_reason="Lançamento incorreto",
                created_by_operator_id=OPERATOR_ID,
                created_at=NOW,
            ),
        )

    def _scope(self, name: str, installation_id: UUID, residence_id: UUID, operator_id: UUID) -> None:
        self.calls.append((name, (installation_id, residence_id, operator_id)))

    def list_accounts(self, *, installation_id: UUID, residence_id: UUID, operator_id: UUID):
        self._scope("list_accounts", installation_id, residence_id, operator_id)
        return (self.account,)

    def create_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        draft: FinancialAccountDraft,
    ) -> FinancialAccountRecord:
        self._scope("create_account", installation_id, residence_id, operator_id)
        self.calls.append(("account_draft", (draft,)))
        return self.account

    def get_account(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialAccountRecord:
        self._scope("get_account", installation_id, residence_id, operator_id)
        self.calls.append(("account_id", (account_id,)))
        return self.account

    def get_opening_balance(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> FinancialOpeningBalanceRecord | None:
        self._scope("get_opening_balance", installation_id, residence_id, operator_id)
        self.calls.append(("opening_account_id", (account_id,)))
        return self.opening_balance

    def create_opening_balance(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
        draft: FinancialOpeningBalanceDraft,
    ) -> FinancialOpeningBalanceRecord:
        self._scope("create_opening_balance", installation_id, residence_id, operator_id)
        self.calls.append(("opening_draft", (account_id, draft)))
        assert self.opening_balance is not None
        return self.opening_balance

    def list_movements(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialMovementRecord, ...]:
        self._scope("list_movements", installation_id, residence_id, operator_id)
        self.calls.append(("movement_account_id", (account_id,)))
        return self.movements

    def get_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> FinancialMovementRecord:
        self._scope("get_movement", installation_id, residence_id, operator_id)
        self.calls.append(("movement_id", (movement_id,)))
        return self.movements[0]


@pytest.fixture
def client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, FakeAuthentication, FakeFinancialCoreService]]:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )
    authentication = FakeAuthentication()
    service = FakeFinancialCoreService()
    with TestClient(create_app(settings)) as test_client:
        test_client.app.state.operator_authentication = authentication
        test_client.app.state.financial_core = service
        yield test_client, authentication, service


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def assert_no_store(response: httpx.Response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_accounts_list_derives_scope_and_uses_camel_case_wire_contract(
    client: tuple[TestClient, FakeAuthentication, FakeFinancialCoreService],
) -> None:
    test_client, _, service = client
    response = test_client.get("/api/v1/finance/accounts", headers=headers())

    assert response.status_code == 200
    assert response.json() == {
        "accounts": [
            {
                "accountId": str(ACCOUNT_ID),
                "ownerOperatorId": str(OPERATOR_ID),
                "visibilityScope": "PERSONAL",
                "accountType": "CHECKING",
                "customTypeName": None,
                "name": "Conta principal",
                "currency": "BRL",
                "status": "ACTIVE",
                "createdAt": "2026-08-13T12:00:00Z",
                "updatedAt": "2026-08-13T12:00:00Z",
                "archivedAt": None,
            }
        ]
    }
    assert service.calls[0] == (
        "list_accounts",
        (INSTALLATION_ID, RESIDENCE_ID, OPERATOR_ID),
    )
    assert_no_store(response)


def test_account_create_accepts_only_domain_creation_fields(
    client: tuple[TestClient, FakeAuthentication, FakeFinancialCoreService],
) -> None:
    test_client, _, service = client
    response = test_client.post(
        "/api/v1/finance/accounts",
        headers=headers(),
        json={
            "name": "  Conta principal  ",
            "accountType": "CHECKING",
            "customTypeName": None,
            "currency": "BRL",
            "visibilityScope": "PERSONAL",
        },
    )

    assert response.status_code == 201
    draft = next(call[1][0] for call in service.calls if call[0] == "account_draft")
    assert isinstance(draft, FinancialAccountDraft)
    assert draft.name == "Conta principal"
    assert draft.account_type is FinancialAccountType.CHECKING

    forbidden_scope = test_client.post(
        "/api/v1/finance/accounts",
        headers=headers(),
        json={
            "name": "Conta",
            "accountType": "CHECKING",
            "customTypeName": None,
            "currency": "BRL",
            "visibilityScope": "PERSONAL",
            "residenceId": str(uuid4()),
        },
    )
    assert forbidden_scope.status_code == 422
    assert forbidden_scope.json() == {"detail": "invalid financial request"}
    assert_no_store(response)
    assert_no_store(forbidden_scope)


def test_opening_balance_uses_decimal_string_and_never_json_number(
    client: tuple[TestClient, FakeAuthentication, FakeFinancialCoreService],
) -> None:
    test_client, _, service = client
    path = f"/api/v1/finance/accounts/{ACCOUNT_ID}/opening-balance"

    response = test_client.post(
        path,
        headers=headers(),
        json={"amount": "1234.50", "currency": "BRL", "effectiveDate": "2026-08-01"},
    )
    assert response.status_code == 201
    assert response.json()["money"] == {"amount": "1234.5", "currency": "BRL"}
    draft = next(call[1][1] for call in service.calls if call[0] == "opening_draft")
    assert isinstance(draft, FinancialOpeningBalanceDraft)
    assert draft.amount == Money(Decimal("1234.5"), "BRL")

    calls_before = len(service.calls)
    numeric = test_client.post(
        path,
        headers=headers(),
        json={"amount": 1234.50, "currency": "BRL", "effectiveDate": "2026-08-01"},
    )
    assert numeric.status_code == 422
    assert numeric.json() == {"detail": "invalid financial request"}
    assert len(service.calls) == calls_before
    assert_no_store(response)
    assert_no_store(numeric)


def test_opening_balance_absence_is_explicit_null_not_zero(
    client: tuple[TestClient, FakeAuthentication, FakeFinancialCoreService],
) -> None:
    test_client, _, service = client
    service.opening_balance = None
    response = test_client.get(
        f"/api/v1/finance/accounts/{ACCOUNT_ID}/opening-balance",
        headers=headers(),
    )
    assert response.status_code == 200
    assert response.json() == {"openingBalance": None}
    assert "0.0" not in response.text
    assert_no_store(response)


def test_movement_list_preserves_standard_and_reversal_events(
    client: tuple[TestClient, FakeAuthentication, FakeFinancialCoreService],
) -> None:
    test_client, _, _ = client
    response = test_client.get(
        f"/api/v1/finance/accounts/{ACCOUNT_ID}/movements",
        headers=headers(),
    )

    assert response.status_code == 200
    body = response.json()["movements"]
    assert [item["role"] for item in body] == ["STANDARD", "REVERSAL"]
    assert body[0]["money"] == {"amount": "-75.25", "currency": "BRL"}
    assert body[1]["money"] == {"amount": "75.25", "currency": "BRL"}
    assert body[1]["reversalOfId"] == str(MOVEMENT_ID)
    assert body[1]["description"] is None
    assert body[1]["reversalReason"] == "Lançamento incorreto"
    assert_no_store(response)


def test_finance_routes_require_session_and_primary_residence(
    client: tuple[TestClient, FakeAuthentication, FakeFinancialCoreService],
) -> None:
    test_client, authentication, service = client
    path = "/api/v1/finance/accounts"

    unauthenticated = test_client.get(path)
    authentication.principal = principal(residence_id=None)
    missing_residence = test_client.get(path, headers=headers())

    assert unauthenticated.status_code == 401
    assert missing_residence.status_code == 409
    assert service.calls == []
    assert_no_store(unauthenticated)
    assert_no_store(missing_residence)


def test_finance_routes_reject_query_parameters(
    client: tuple[TestClient, FakeAuthentication, FakeFinancialCoreService],
) -> None:
    test_client, _, service = client
    response = test_client.get(
        "/api/v1/finance/accounts",
        headers=headers(),
        params={"residenceId": str(RESIDENCE_ID)},
    )
    assert response.status_code == 422
    assert service.calls == []
    assert_no_store(response)


def test_openapi_has_no_generic_movement_writer_or_client_scope_fields(
    client: tuple[TestClient, FakeAuthentication, FakeFinancialCoreService],
) -> None:
    test_client, _, _ = client
    schema = test_client.get("/api/v1/openapi.json").json()

    assert "/api/v1/finance/movements" not in schema["paths"]
    assert "post" not in schema["paths"]["/api/v1/finance/movements/{movement_id}"]

    account_post = schema["paths"]["/api/v1/finance/accounts"]["post"]
    request_schema = str(account_post["requestBody"])
    for forbidden in ("residenceId", "installationId", "operatorId", "balance"):
        assert forbidden not in request_schema

    opening_schema = str(
        schema["paths"]["/api/v1/finance/accounts/{account_id}/opening-balance"][
            "post"
        ]["requestBody"]
    )
    assert "number" not in opening_schema.lower()
