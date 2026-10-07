"""HTTP proofs for assisted recurrence suggestions against a real PostgreSQL (ADR-0028).

Everything runs through the non-superuser runtime role with forced RLS, over the
public API. A suggestion is derived and never stored: these proofs repeatedly show
the ledger, the balance and the statement never move because of a suggestion, and
that accepting creates exactly one recurrence and no Movement or occurrence.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from meufinanceiro_persistence import OperatorRole, OperatorSessionPrincipal
from meufinanceiro_persistence.bootstrap import normalize_psycopg_url
from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_balance_query import (
    FinancialBalanceQueryService,
)
from meufinanceiro_persistence.financial_category_store import FinancialCategoryStore
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationStore,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceStore,
)
from meufinanceiro_persistence.financial_recurrence_schema import (
    financial_recurrence_occurrences,
    financial_recurrences,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceStore,
)
from meufinanceiro_persistence.financial_recurrence_suggestion_schema import (
    financial_recurrence_suggestion_decisions,
)
from meufinanceiro_persistence.financial_recurrence_suggestion_store import (
    FinancialRecurrenceSuggestionStore,
)
from meufinanceiro_persistence.financial_transfer_store import FinancialTransferStore
from meufinanceiro_persistence.migrations import upgrade
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)
from meufinanceiro_security.keyring import initialize_keyring_file
from sqlalchemy import Engine, create_engine, func, insert, select
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.main import create_app
from app.services.financial_core import FinancialCoreService
from app.services.financial_recurrence_suggestions import (
    FinancialRecurrenceSuggestionService,
)
from app.services.financial_recurrences import FinancialRecurrenceService
from app.services.operator_auth import InvalidOperatorSessionError

_RUNTIME_PASSWORD = "disposable-api-test-password"
_NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 20)
_LEAKS = (
    "SELECT",
    "constraint",
    "violates",
    "psycopg",
    "sqlalchemy",
    "finance.",
    "Traceback",
    "row-level security",
)


@dataclass(frozen=True)
class PgEnv:
    owner_engine: Engine
    runtime_engine: Engine
    installation_id: UUID


@dataclass(frozen=True)
class Household:
    residence_id: UUID
    owner_id: UUID
    member_id: UUID


@pytest.fixture(scope="module")
def pg_env() -> Iterator[PgEnv]:
    base_url = os.environ.get("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")

    database = f"mf_api_suggestions_{secrets.token_hex(4)}"
    role = f"mf_api_suggestions_{secrets.token_hex(4)}"
    admin_url = make_url(base_url)
    database_url = admin_url.set(database=database).render_as_string(
        hide_password=False
    )
    runtime_url = (
        admin_url.set(database=database, username=role, password=_RUNTIME_PASSWORD)
    ).render_as_string(hide_password=False)

    with psycopg.connect(
        normalize_psycopg_url(admin_url.render_as_string(hide_password=False)),
        autocommit=True,
    ) as connection:
        connection.execute(f'CREATE DATABASE "{database}"')
        connection.execute(
            f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{_RUNTIME_PASSWORD}' "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        )

    owner_engine = create_engine(database_url, pool_pre_ping=True)
    runtime_engine = create_engine(runtime_url, pool_pre_ping=True)
    installation_id = uuid4()
    try:
        upgrade(database_url, app_database_user=role)
        with owner_engine.begin() as connection:
            connection.execute(
                insert(identity_installation).values(
                    singleton=True,
                    id=installation_id,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
        yield PgEnv(owner_engine, runtime_engine, installation_id)
    finally:
        runtime_engine.dispose()
        owner_engine.dispose()
        with psycopg.connect(
            normalize_psycopg_url(admin_url.render_as_string(hide_password=False)),
            autocommit=True,
        ) as connection:
            connection.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            connection.execute(f'DROP ROLE IF EXISTS "{role}"')


def _make_household(pg_env: PgEnv) -> Household:
    residence_id, owner_id, member_id = uuid4(), uuid4(), uuid4()
    with pg_env.owner_engine.begin() as connection:
        connection.execute(
            insert(household_residences).values(
                id=residence_id,
                installation_id=pg_env.installation_id,
                name=f"Synthetic residence {residence_id.hex[:6]}",
                status="active",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        for index, (operator_id, role) in enumerate(
            ((owner_id, "owner"), (member_id, "member"))
        ):
            connection.execute(
                insert(identity_operators).values(
                    id=operator_id,
                    installation_id=pg_env.installation_id,
                    login_name=f"op-{operator_id.hex[:12]}",
                    password_hash="synthetic-password-hash-material-000000000000",
                    role="installation_admin",
                    status="active",
                    failed_attempts=0,
                    locked_until=None,
                    last_authenticated_at=None,
                    password_changed_at=_NOW,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            connection.execute(
                insert(household_memberships).values(
                    id=uuid4(),
                    installation_id=pg_env.installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    role=role,
                    status="active",
                    is_primary=index == 0,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
    return Household(residence_id, owner_id, member_id)


@pytest.fixture
def household(pg_env: PgEnv) -> Household:
    return _make_household(pg_env)


@pytest.fixture
def other_household(pg_env: PgEnv) -> Household:
    return _make_household(pg_env)


class _Authentication:
    def __init__(self) -> None:
        self.principals: dict[str, OperatorSessionPrincipal] = {}

    def resolve(self, token: str) -> OperatorSessionPrincipal:
        principal = self.principals.get(token)
        if principal is None:
            raise InvalidOperatorSessionError("operator session is invalid")
        return principal


class Api:
    """Tiny HTTP facade; ``who`` selects the authenticated operator."""

    def __init__(
        self, client: TestClient, authentication: _Authentication, pg_env: PgEnv
    ) -> None:
        self.client = client
        self.authentication = authentication
        self.pg_env = pg_env
        self.residence_id: UUID | None = None
        self._tokens: dict[str, str] = {}

    def login(self, who: str, operator_id: UUID, residence_id: UUID) -> None:
        token = secrets.token_urlsafe(32)
        self.authentication.principals[token] = OperatorSessionPrincipal(
            session_id=uuid4(),
            installation_id=self.pg_env.installation_id,
            operator_id=operator_id,
            login_name=who,
            role=OperatorRole.INSTALLATION_ADMIN,
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
            primary_residence_id=residence_id,
        )
        self._tokens[who] = token

    def _headers(self, who: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._tokens[who]}"}

    def get(self, who: str, path: str) -> httpx.Response:
        return self.client.get(f"/api/v1/finance{path}", headers=self._headers(who))

    def post(
        self, who: str, path: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        return self.client.post(
            f"/api/v1/finance{path}", headers=self._headers(who), json=body
        )

    def put(self, who: str, path: str, body: dict[str, Any]) -> httpx.Response:
        return self.client.put(
            f"/api/v1/finance{path}", headers=self._headers(who), json=body
        )

    # -- ledger helpers (all through the public API) --------------------------

    def account(
        self, who: str, *, scope: str = "HOUSEHOLD", opening: str | None = "1000.00"
    ) -> UUID:
        response = self.post(
            who,
            "/accounts",
            {
                "name": f"Conta {uuid4().hex[:6]}",
                "accountType": "CHECKING",
                "customTypeName": None,
                "currency": "BRL",
                "visibilityScope": scope,
            },
        )
        assert response.status_code == 201, response.text
        account_id = UUID(response.json()["accountId"])
        if opening is not None:
            opened = self.post(
                who,
                f"/accounts/{account_id}/opening-balance",
                {"amount": opening, "currency": "BRL", "effectiveDate": "2026-01-01"},
            )
            assert opened.status_code == 201, opened.text
        return account_id

    # -- suggestion helpers ----------------------------------------------------

    def expense(
        self,
        who: str,
        account_id: UUID,
        when: str,
        amount: str = "39.90",
        description: str = "Streaming",
    ) -> str:
        response = self.post(
            who,
            f"/accounts/{account_id}/expense",
            {
                "idempotencyKey": str(uuid4()),
                "amount": amount,
                "currency": "BRL",
                "effectiveDate": when,
                "competenceDate": when,
                "description": description,
            },
        )
        assert response.status_code == 201, response.text
        return str(response.json()["movementId"])

    def streaming(
        self,
        who: str,
        account_id: UUID,
        months: tuple[str, ...] = ("2026-08-10", "2026-09-10", "2026-10-10"),
        description: str = "Streaming",
        amount: str = "39.90",
    ) -> list[str]:
        return [self.expense(who, account_id, d, amount, description) for d in months]

    def suggestions(self, who: str) -> list[dict[str, Any]]:
        response = self.get(who, "/recurrence-suggestions")
        assert response.status_code == 200, response.text
        return list(response.json()["items"])

    def accept_body(self, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "idempotencyKey": str(uuid4()),
            "description": "Streaming",
            "expectedAmount": "39.90",
            "startDate": "2026-11-10",
            "dayOfMonth": 10,
            "endDate": None,
        }
        body.update(overrides)
        return body


@pytest.fixture
def api(pg_env: PgEnv, household: Household, tmp_path: Path) -> Iterator[Api]:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )
    engine = pg_env.runtime_engine
    accounts = FinancialAccountStore(engine)
    openings = FinancialOpeningBalanceStore(engine)
    movements = FinancialMovementStore(engine)
    service = FinancialCoreService(
        accounts,
        openings,
        movements,
        FinancialTransferStore(engine),
        FinancialBalanceQueryService(accounts, openings, movements),
        FinancialCategoryStore(engine),
        FinancialMovementAllocationStore(engine),
    )
    authentication = _Authentication()
    with TestClient(create_app(settings)) as client:
        client.app.state.operator_authentication = authentication
        client.app.state.financial_core = service
        client.app.state.financial_recurrences = FinancialRecurrenceService(
            FinancialRecurrenceStore(engine), clock=lambda: _TODAY
        )
        client.app.state.financial_recurrence_suggestions = (
            FinancialRecurrenceSuggestionService(
                FinancialRecurrenceSuggestionStore(engine), clock=lambda: _TODAY
            )
        )
        facade = Api(client, authentication, pg_env)
        facade.residence_id = household.residence_id
        facade.login("owner", household.owner_id, household.residence_id)
        facade.login("member", household.member_id, household.residence_id)
        yield facade


# --- helpers --------------------------------------------------------------------


def _ledger_rows(api: Api, residence_id: UUID) -> list[Any]:
    with api.pg_env.owner_engine.begin() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                select(financial_movements)
                .where(financial_movements.c.residence_id == residence_id)
                .order_by(financial_movements.c.id)
            )
        ]


def _ledger_views(api: Api, who: str, account_id: UUID) -> list[Any]:
    views = [
        api.get(who, f"/accounts/{account_id}/{part}").json()
        for part in ("balance", "statement")
    ]
    for view in views:
        view.pop("calculatedAt", None)  # a read timestamp, not ledger state
    return views


def _clean(response: httpx.Response, status_code: int, detail: str) -> None:
    assert response.status_code == status_code, response.text
    assert response.json() == {"detail": detail}
    for leak in _LEAKS:
        assert leak not in response.text
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", response.text)


def _count(api: Api, table: Any) -> int:
    with api.pg_env.owner_engine.begin() as connection:
        value = connection.scalar(
            select(func.count())
            .select_from(table)
            .where(table.c.residence_id == api.residence_id)
        )
    assert isinstance(value, int)
    return value


def _counts(api: Api) -> tuple[int, int, int, int]:
    return (
        _count(api, financial_movements),
        _count(api, financial_recurrences),
        _count(api, financial_recurrence_occurrences),
        _count(api, financial_recurrence_suggestion_decisions),
    )


# --- GET ------------------------------------------------------------------------


def test_get_derives_a_suggestion_with_evidence_and_never_writes(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    ids = api.streaming("owner", account)
    ledger = _ledger_views(api, "owner", account)
    before = _counts(api)

    response = api.get("owner", "/recurrence-suggestions")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["windowFrom"] == "2025-11-01" and body["windowThrough"] == "2026-10-20"
    (item,) = body["items"]
    assert len(item["fingerprint"]) == 64
    assert item["accountId"] == str(account) and item["currency"] == "BRL"
    assert item["description"] == "Streaming"
    assert item["normalizedDescription"] == "streaming"
    assert item["movementIds"] == ids
    assert item["observedDates"] == ["2026-08-10", "2026-09-10", "2026-10-10"]
    assert [a["amount"] for a in item["observedAmounts"]] == ["39.9"] * 3
    assert [e["movementId"] for e in item["evidence"]] == ids
    assert item["suggestedDayOfMonth"] == 10
    assert item["suggestedExpectedAmount"] == {"amount": "39.9", "currency": "BRL"}
    assert item["amountBehavior"] == "FIXED"
    assert item["minAmount"] == item["maxAmount"] == item["lastAmount"]
    assert item["reasonCodes"] == [
        "EXACT_DESCRIPTION",
        "CONSECUTIVE_MONTHS",
        "ONE_PER_MONTH",
        "DAY_WINDOW",
        "AMOUNT_FIXED",
    ]
    assert item["canAccept"] is True
    # Reading is free of side effects, however many times it happens.
    api.get("owner", "/recurrence-suggestions")
    api.get("member", "/recurrence-suggestions")
    assert _counts(api) == before == (3, 0, 0, 0)
    assert _ledger_views(api, "owner", account) == ledger
    assert api.get("owner", "/recurrences").json() == {"items": []}


def test_get_rejects_query_parameters_and_unknown_routes_do_not_exist(
    api: Api,
) -> None:
    assert api.get("owner", "/recurrence-suggestions?x=1").status_code == 422
    for method in (api.client.put, api.client.patch, api.client.delete):
        response = method(
            "/api/v1/finance/recurrence-suggestions",
            headers=api._headers("owner"),
        )
        assert response.status_code in (404, 405)
    assert api.client.get("/api/v1/finance/recurrence-suggestions").status_code == 401


def test_audience_follows_the_account_over_http(api: Api) -> None:
    household_account = api.account("owner", scope="HOUSEHOLD")
    personal_account = api.account("owner", scope="PERSONAL")
    api.streaming("owner", household_account, description="Streaming")
    api.streaming("owner", personal_account, description="Terapia")

    owner_seen = {item["description"] for item in api.suggestions("owner")}
    member_seen = api.suggestions("member")

    assert owner_seen == {"Streaming", "Terapia"}
    assert [item["description"] for item in member_seen] == ["Streaming"]
    assert member_seen[0]["canAccept"] is False


# --- dismiss --------------------------------------------------------------------


def test_dismiss_is_personal_idempotent_and_clean(api: Api) -> None:
    account = api.account("owner")
    api.streaming("owner", account)
    (item,) = api.suggestions("member")
    path = f"/recurrence-suggestions/{item['fingerprint']}/dismiss"

    first = api.post("member", path)
    again = api.post("member", path)

    assert first.status_code == again.status_code == 200
    assert first.json()["decision"] == "DISMISSED"
    assert first.json()["created"] is True and again.json()["created"] is False
    assert first.json()["recurrenceId"] is None
    assert api.suggestions("member") == []
    assert len(api.suggestions("owner")) == 1  # the owner still sees it
    assert _counts(api)[1:] == (0, 0, 1)
    # Forged, unavailable and malformed fingerprints.
    _clean(
        api.post("owner", f"/recurrence-suggestions/{'0' * 64}/dismiss"),
        409,
        "financial recurrence suggestion is no longer available",
    )
    assert api.post("owner", "/recurrence-suggestions/abc/dismiss").status_code == 422
    assert (
        api.post("owner", f"/recurrence-suggestions/{'A' * 64}/dismiss").status_code
        == 422
    )


def test_a_personal_suggestion_cannot_be_probed_by_fingerprint(api: Api) -> None:
    account = api.account("owner", scope="PERSONAL")
    api.streaming("owner", account)
    (item,) = api.suggestions("owner")
    for action in ("dismiss", "accept"):
        body = api.accept_body() if action == "accept" else None
        _clean(
            api.post(
                "member",
                f"/recurrence-suggestions/{item['fingerprint']}/{action}",
                body,
            ),
            409,
            "financial recurrence suggestion is no longer available",
        )
    assert _counts(api)[1:] == (0, 0, 0)


# --- accept ---------------------------------------------------------------------


def test_accept_creates_one_recurrence_and_no_movement_or_occurrence(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    api.streaming("owner", account)
    ledger = _ledger_views(api, "owner", account)
    (item,) = api.suggestions("owner")
    key = str(uuid4())

    response = api.post(
        "owner",
        f"/recurrence-suggestions/{item['fingerprint']}/accept",
        api.accept_body(
            idempotencyKey=key,
            description="Streaming Premium",
            expectedAmount="44.90",
            startDate="2026-11-12",
            dayOfMonth=12,
            endDate="2027-12-12",
        ),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    recurrence = body["recurrence"]
    assert recurrence["accountId"] == str(account)
    assert recurrence["resultEffect"] == "EXPENSE"
    assert recurrence["expected"] == {"amount": "44.9", "currency": "BRL"}
    assert recurrence["description"] == "Streaming Premium"
    assert recurrence["dayOfMonth"] == 12 and recurrence["endDate"] == "2027-12-12"
    assert recurrence["canEdit"] is True and recurrence["version"] == 1
    assert body["decision"]["decision"] == "ACCEPTED"
    assert body["decision"]["recurrenceId"] == recurrence["id"]
    assert body["decision"]["created"] is True
    assert _counts(api) == (3, 1, 0, 1)  # no new Movement, no occurrence
    assert _ledger_views(api, "owner", account) == ledger
    assert api.suggestions("owner") == [] and api.suggestions("member") == []
    listed = api.get("owner", "/recurrences").json()["items"]
    assert [r["id"] for r in listed] == [recurrence["id"]]

    # An identical retry converges; anything else already accepted is refused.
    again = api.post(
        "owner",
        f"/recurrence-suggestions/{item['fingerprint']}/accept",
        api.accept_body(
            idempotencyKey=key,
            description="Streaming Premium",
            expectedAmount="44.90",
            startDate="2026-11-12",
            dayOfMonth=12,
            endDate="2027-12-12",
        ),
    )
    assert again.status_code == 201 and again.json()["decision"]["created"] is False
    assert again.json()["recurrence"]["id"] == recurrence["id"]
    other_key = api.post(
        "owner",
        f"/recurrence-suggestions/{item['fingerprint']}/accept",
        api.accept_body(),
    )
    _clean(
        other_key,
        409,
        "financial recurrence suggestion conflicts with a recorded decision",
    )
    _clean(
        api.post("owner", f"/recurrence-suggestions/{item['fingerprint']}/dismiss"),
        409,
        "financial recurrence suggestion conflicts with a recorded decision",
    )
    changed = api.post(
        "owner",
        f"/recurrence-suggestions/{item['fingerprint']}/accept",
        api.accept_body(idempotencyKey=key, description="Outra"),
    )
    _clean(changed, 409, "financial recurrence conflicts with canonical state")
    assert _counts(api) == (3, 1, 0, 1)


def test_accept_is_owner_only_and_the_client_cannot_widen_the_suggestion(
    api: Api,
) -> None:
    account = api.account("owner")
    other = api.account("owner")
    api.streaming("owner", account)
    (item,) = api.suggestions("member")
    path = f"/recurrence-suggestions/{item['fingerprint']}/accept"

    _clean(api.post("member", path, api.accept_body()), 403, "financial access denied")
    for widened in (
        {"accountId": str(other)},
        {"resultEffect": "INCOME"},
        {"currency": "USD"},
        {"frequency": "WEEKLY"},
        {"ownerOperatorId": str(uuid4())},
    ):
        assert api.post("owner", path, api.accept_body(**widened)).status_code == 422
    assert _counts(api)[1:] == (0, 0, 0)

    created = api.post("owner", path, api.accept_body())
    assert created.status_code == 201
    assert created.json()["recurrence"]["accountId"] == str(account)


@pytest.mark.parametrize(
    "override",
    [
        {"expectedAmount": "0"},
        {"expectedAmount": "-1"},
        {"expectedAmount": "1.123456789"},
        {"expectedAmount": "1e3"},
        {"startDate": "2026-13-01"},
        {"startDate": "2026-1-1"},
        {"dayOfMonth": 0},
        {"dayOfMonth": 32},
        {"dayOfMonth": "10"},
        {"endDate": "2026-01-01"},
        {"description": "   "},
        {"description": "x" * 257},
        {"idempotencyKey": "not-a-uuid"},
        {"idempotencyKey": "00000000-0000-0000-0000-000000000000"},
    ],
)
def test_invalid_accepts_are_rejected_without_writing(
    api: Api, override: dict[str, Any]
) -> None:
    account = api.account("owner")
    api.streaming("owner", account)
    (item,) = api.suggestions("owner")
    response = api.post(
        "owner",
        f"/recurrence-suggestions/{item['fingerprint']}/accept",
        api.accept_body(**override),
    )
    assert response.status_code == 422, response.text
    assert _counts(api)[1:] == (0, 0, 0)
    assert len(api.suggestions("owner")) == 1


def test_a_stale_candidate_is_a_clean_conflict_and_a_refetch_fixes_it(
    api: Api,
) -> None:
    account = api.account("owner")
    ids = api.streaming("owner", account)
    (item,) = api.suggestions("owner")
    reversal = api.post(
        "owner",
        f"/movements/{ids[-1]}/reversal",
        {
            "idempotencyKey": str(uuid4()),
            "effectiveDate": "2026-10-12",
            "competenceDate": "2026-10-12",
            "reason": "Cobrança duplicada",
        },
    )
    assert reversal.status_code == 201, reversal.text

    stale = api.post(
        "owner",
        f"/recurrence-suggestions/{item['fingerprint']}/accept",
        api.accept_body(),
    )

    _clean(stale, 409, "financial recurrence suggestion is no longer available")
    assert api.suggestions("owner") == []
    assert _counts(api)[1:] == (0, 0, 0)


def test_concurrent_accepts_over_http_never_duplicate_the_recurrence(
    api: Api,
) -> None:
    account = api.account("owner")
    api.streaming("owner", account)
    (item,) = api.suggestions("owner")
    shared_key = str(uuid4())
    barrier = Barrier(6)

    def attempt(index: int) -> int:
        barrier.wait()
        key = shared_key if index % 2 == 0 else str(uuid4())
        return api.post(
            "owner",
            f"/recurrence-suggestions/{item['fingerprint']}/accept",
            api.accept_body(idempotencyKey=key),
        ).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = [f.result() for f in [pool.submit(attempt, i) for i in range(6)]]

    assert 201 in statuses and set(statuses) <= {201, 409}
    assert _counts(api)[1:] == (1, 0, 1)


def test_smoke_the_issue_vertical_streaming_over_http(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    api.streaming("owner", account)  # Streaming 39,90 in Aug / Sep / Oct
    ledger = _ledger_views(api, "owner", account)

    # GET suggests it with evidence; balance and statement are untouched.
    (for_owner,) = api.suggestions("owner")
    (for_member,) = api.suggestions("member")
    assert for_owner["fingerprint"] == for_member["fingerprint"]
    assert for_owner["canAccept"] is True and for_member["canAccept"] is False
    assert _ledger_views(api, "owner", account) == ledger

    # Member A dismisses: it disappears for A only; B (the owner) still sees it.
    assert (
        api.post(
            "member", f"/recurrence-suggestions/{for_member['fingerprint']}/dismiss"
        ).status_code
        == 200
    )
    assert api.suggestions("member") == []
    assert len(api.suggestions("owner")) == 1

    # The owner reviews value and day, then confirms.
    key = str(uuid4())
    review = api.accept_body(
        idempotencyKey=key,
        expectedAmount="41.90",
        dayOfMonth=11,
        startDate="2026-11-11",
    )
    accepted = api.post(
        "owner", f"/recurrence-suggestions/{for_owner['fingerprint']}/accept", review
    )
    assert accepted.status_code == 201, accepted.text
    rule = accepted.json()["recurrence"]
    assert rule["expected"]["amount"] == "41.9" and rule["dayOfMonth"] == 11

    # Exactly one recurrence + provenance; zero occurrence and zero new Movement.
    assert _counts(api) == (3, 1, 0, 2)  # 1 DISMISSED (member) + 1 ACCEPTED (owner)
    assert _ledger_views(api, "owner", account) == ledger
    # A retry does not duplicate and the suggestion is gone for everyone.
    retry = api.post(
        "owner", f"/recurrence-suggestions/{for_owner['fingerprint']}/accept", review
    )
    assert retry.status_code == 201 and retry.json()["recurrence"]["id"] == rule["id"]
    fresh = api.post(
        "owner",
        f"/recurrence-suggestions/{for_owner['fingerprint']}/accept",
        api.accept_body(),
    )
    assert fresh.status_code == 409
    assert _counts(api) == (3, 1, 0, 2)
    assert api.suggestions("owner") == [] and api.suggestions("member") == []
