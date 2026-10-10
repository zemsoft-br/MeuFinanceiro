"""HTTP proofs of ``GET /finance/cash-flow`` against real PostgreSQL (ADR-0031).

The application runs with the non-superuser, NOBYPASSRLS runtime role and forced
RLS. Every ledger and recurrence write here goes through the public API; the cash
flow route itself only reads.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
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
from meufinanceiro_persistence.financial_cash_flow_store import FinancialCashFlowStore
from meufinanceiro_persistence.financial_category_store import FinancialCategoryStore
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationStore,
)
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceStore,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceStore,
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
from sqlalchemy import Engine, create_engine, insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

import meufinanceiro_persistence.financial_cash_flow_store as store_module
from app.core.config import Settings
from app.main import create_app
from app.services.financial_cash_flow import FinancialCashFlowService
from app.services.financial_core import FinancialCoreService
from app.services.financial_recurrences import FinancialRecurrenceService
from app.services.operator_auth import InvalidOperatorSessionError

_RUNTIME_PASSWORD = "disposable-api-test-password"
_NOW = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)
_LEAKS = (
    "SELECT",
    "constraint",
    "violates",
    "psycopg",
    "sqlalchemy",
    "finance.",
    "Traceback",
    "row-level security",
    "recurrence_occurrences",
)


@dataclass(frozen=True)
class PgEnv:
    owner_engine: Engine
    runtime_engine: Engine
    installation_id: UUID
    role: str


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

    database = f"mf_api_cash_flow_{secrets.token_hex(4)}"
    role = f"mf_api_cash_flow_{secrets.token_hex(4)}"
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
        yield PgEnv(owner_engine, runtime_engine, installation_id, role)
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


class _Authentication:
    def __init__(self) -> None:
        self.principals: dict[str, OperatorSessionPrincipal] = {}

    def resolve(self, token: str) -> OperatorSessionPrincipal:
        principal = self.principals.get(token)
        if principal is None:
            raise InvalidOperatorSessionError("operator session is invalid")
        return principal


class Api:
    def __init__(
        self, client: TestClient, authentication: _Authentication, pg_env: PgEnv
    ) -> None:
        self.client = client
        self.authentication = authentication
        self.pg_env = pg_env
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

    def headers(self, who: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._tokens[who]}"}

    def get(self, who: str, path: str) -> httpx.Response:
        return self.client.get(f"/api/v1/finance{path}", headers=self.headers(who))

    def post(self, who: str, path: str, body: dict[str, Any]) -> httpx.Response:
        return self.client.post(
            f"/api/v1/finance{path}", headers=self.headers(who), json=body
        )

    def cash_flow(self, who: str, query: str = "") -> httpx.Response:
        return self.get(who, f"/cash-flow{query}")

    def ok(self, who: str, query: str = "") -> dict[str, Any]:
        response = self.cash_flow(who, query)
        assert response.status_code == 200, response.text
        return dict(response.json())

    # -- writes through the public API ----------------------------------------

    def account(
        self,
        who: str,
        *,
        scope: str = "HOUSEHOLD",
        opening: str | None = "1000.00",
        currency: str = "BRL",
        name: str | None = None,
    ) -> UUID:
        response = self.post(
            who,
            "/accounts",
            {
                "name": name or f"Conta {uuid4().hex[:6]}",
                "accountType": "CHECKING",
                "customTypeName": None,
                "currency": currency,
                "visibilityScope": scope,
            },
        )
        assert response.status_code == 201, response.text
        account_id = UUID(response.json()["accountId"])
        if opening is not None:
            opened = self.post(
                who,
                f"/accounts/{account_id}/opening-balance",
                {
                    "amount": opening,
                    "currency": currency,
                    "effectiveDate": "2026-09-01",
                },
            )
            assert opened.status_code == 201, opened.text
        return account_id

    def entry(
        self, who: str, kind: str, account_id: UUID, amount: str, on: str
    ) -> UUID:
        response = self.post(
            who,
            f"/accounts/{account_id}/{kind}",
            {
                "idempotencyKey": str(uuid4()),
                "amount": amount,
                "currency": "BRL",
                "effectiveDate": on,
                "competenceDate": on,
                "description": f"Synthetic {kind}",
            },
        )
        assert response.status_code == 201, response.text
        return UUID(response.json()["movementId"])

    def transfer(self, who: str, source: UUID, destination: UUID, amount: str) -> UUID:
        response = self.post(
            who,
            "/transfers",
            {
                "idempotencyKey": str(uuid4()),
                "sourceAccountId": str(source),
                "destinationAccountId": str(destination),
                "amount": amount,
                "currency": "BRL",
                "effectiveDate": "2026-10-10",
                "competenceDate": "2026-10-10",
                "description": "Reserva",
            },
        )
        assert response.status_code == 201, response.text
        return UUID(response.json()["transferId"])

    def recurrence(
        self, who: str, account_id: UUID, *, amount: str, day: int, effect: str
    ) -> str:
        response = self.post(
            who,
            "/recurrences",
            {
                "idempotencyKey": str(uuid4()),
                "accountId": str(account_id),
                "description": "Aluguel" if effect == "EXPENSE" else "Salário",
                "resultEffect": effect,
                "expectedAmount": amount,
                "currency": "BRL",
                "startDate": "2026-09-01",
                "dayOfMonth": day,
                "endDate": None,
            },
        )
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    def generate(self, who: str, recurrence_id: str, period: str) -> list[str]:
        response = self.post(
            who,
            f"/recurrences/{recurrence_id}/occurrences/generate",
            {"fromPeriod": period, "throughPeriod": period},
        )
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()["items"]]


@pytest.fixture
def household(pg_env: PgEnv) -> Household:
    return _make_household(pg_env)


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
    authentication = _Authentication()
    today = date(2026, 10, 10)
    with TestClient(create_app(settings)) as client:
        client.app.state.operator_authentication = authentication
        client.app.state.financial_core = FinancialCoreService(
            accounts,
            openings,
            movements,
            FinancialTransferStore(engine),
            FinancialBalanceQueryService(accounts, openings, movements),
            FinancialCategoryStore(engine),
            FinancialMovementAllocationStore(engine),
        )
        client.app.state.financial_recurrences = FinancialRecurrenceService(
            FinancialRecurrenceStore(engine), clock=lambda: today
        )
        client.app.state.financial_cash_flow = FinancialCashFlowService(
            FinancialCashFlowStore(engine), clock=lambda: today
        )
        facade = Api(client, authentication, pg_env)
        facade.login("owner", household.owner_id, household.residence_id)
        facade.login("member", household.member_id, household.residence_id)
        yield facade


def _assert_sanitized(response: httpx.Response) -> None:
    for leak in _LEAKS:
        assert leak not in response.text, leak


def _counts(api: Api) -> dict[str, int]:
    with api.pg_env.owner_engine.begin() as connection:
        tables = connection.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'finance'")
        ).all()
        return {
            table: int(
                connection.scalar(text(f'SELECT count(*) FROM finance."{table}"')) or 0
            )
            for table in tables
        }


def _money(value: dict[str, str]) -> tuple[str, str]:
    return value["amount"], value["currency"]


def test_smoke_the_issue_vertical_over_http(api: Api) -> None:
    """saldo inicial → receita → despesa → transferência → recorrência prevista →
    saldo projetado → déficit futuro → realização explícita → estorno →
    reconciliação sem duplicação."""
    checking = api.account("owner", opening="1000.00", name="Corrente")
    savings = api.account("owner", opening="0.00", name="Poupança")
    api.entry("owner", "income", checking, "2000.00", "2026-10-02")
    api.entry("owner", "expense", checking, "300.00", "2026-10-05")
    api.transfer("owner", checking, savings, "500.00")
    rent = api.recurrence("owner", checking, amount="2500.00", day=20, effect="EXPENSE")
    salary = api.recurrence("owner", checking, amount="1500.00", day=5, effect="INCOME")
    (october_rent,) = api.generate("owner", rent, "2026-10")
    query = "?from=2026-10-01&through=2026-11-30&accountId=" + str(checking)

    before = _counts(api)
    body = api.ok("owner", query)
    assert _counts(api) == before  # a GET writes nothing, generates nothing

    assert body["referenceDate"] == "2026-10-10"
    assert body["from"] == "2026-10-01" and body["through"] == "2026-11-30"
    assert body["days"] == 61
    assert "BUDGETS" in body["excludedSources"]
    (group,) = body["groups"]
    assert group["currency"] == "BRL"
    assert _money(group["startingBalance"]) == ("1000", "BRL")
    assert _money(group["balanceAtReference"]) == ("2200", "BRL")
    events = group["events"]
    assert [(e["kind"], e["date"], e["amount"]["amount"]) for e in events] == [
        ("REALIZED", "2026-10-02", "2000"),
        ("REALIZED", "2026-10-05", "-300"),
        ("REALIZED", "2026-10-10", "-500"),
        ("EXPECTED_OCCURRENCE", "2026-10-20", "-2500"),
        ("EXPECTED_RULE", "2026-11-05", "1500"),
        ("EXPECTED_RULE", "2026-11-20", "-2500"),
    ]
    assert events[2]["resultEffect"] == "NEUTRAL" and events[2]["transferId"]
    assert events[3]["occurrenceId"] == october_rent
    assert events[4]["recurrenceId"] == salary and events[4]["ruleVersion"] == 1
    assert group["totals"]["neutralOut"]["amount"] == "500"
    assert group["totals"]["realizedExpense"]["amount"] == "300"
    # Projected deficit: rent on Oct 20 takes the account below zero.
    assert group["risk"]["firstNegativeDate"] == "2026-10-20"
    assert group["risk"]["minimumBalance"]["amount"] == "-1300"
    assert _money(group["closingBalance"]) == ("-1300", "BRL")
    negative_days = [d["date"] for d in group["days"] if d["negative"]]
    assert negative_days[0] == "2026-10-20"
    assert group["projectionStatus"] == "COMPLETE"
    # Salary is not due in the window before the 5th of October: it is reported.
    assert [i["code"] for i in group["issues"]] == ["UNGENERATED_PAST_OCCURRENCES"]

    # Explicit realization: exactly one Movement, the occurrence now covers October.
    realized = api.post(
        "owner",
        f"/recurrence-occurrences/{october_rent}/realize",
        {
            "idempotencyKey": str(uuid4()),
            "actualAmount": "2450.00",
            "currency": "BRL",
            "effectiveDate": "2026-10-10",
            "competenceDate": "2026-10-01",
        },
    )
    assert realized.status_code == 200, realized.text
    movement_id = realized.json()["realization"]["movementId"]
    body = api.ok("owner", query)
    events = body["groups"][0]["events"]
    rent_events = [e for e in events if e["recurrenceId"] == rent]
    assert [(e["kind"], e["date"]) for e in rent_events] == [
        ("REALIZED", "2026-10-10"),
        ("EXPECTED_RULE", "2026-11-20"),
    ]
    assert rent_events[0]["movementId"] == movement_id
    assert rent_events[0]["expectedAmount"]["amount"] == "-2500"
    assert rent_events[0]["amount"]["amount"] == "-2450"
    assert body["groups"][0]["balanceAtReference"]["amount"] == "-250"

    # Reversal: the reversing Movement appears, nothing is reopened or re-expected.
    reversed_ = api.post(
        "owner",
        f"/movements/{movement_id}/reversal",
        {
            "idempotencyKey": str(uuid4()),
            "effectiveDate": "2026-10-10",
            "competenceDate": "2026-10-10",
            "reason": "Cobrança indevida",
        },
    )
    assert reversed_.status_code == 201, reversed_.text
    body = api.ok("owner", query)
    group = body["groups"][0]
    october = [e for e in group["events"] if e["date"].startswith("2026-10")]
    assert [e["kind"] for e in october] == ["REALIZED"] * 5
    assert [e["movementRole"] for e in october][-1] == "REVERSAL"
    assert not any(
        e["kind"] != "REALIZED"
        and e["recurrenceId"] == rent
        and e["date"] < "2026-11-01"
        for e in group["events"]
    )
    # Reconciliation: the reference balance equals the canonical account balance.
    balance = api.get("owner", f"/accounts/{checking}/balance").json()
    assert group["balanceAtReference"]["amount"] == "2200"
    assert balance["currentBalance"]["amount"] == group["balanceAtReference"]["amount"]


def test_member_sees_only_its_audience_and_errors_are_indistinguishable(
    api: Api, pg_env: PgEnv
) -> None:
    household = api.account("owner", scope="HOUSEHOLD", name="Casa")
    personal = api.account("owner", scope="PERSONAL", name="Privada")
    api.entry("owner", "expense", personal, "10.00", "2026-10-11")

    owner = api.ok("owner")
    assert {a["accountId"] for a in owner["groups"][0]["accounts"]} == {
        str(household),
        str(personal),
    }
    member = api.ok("member")
    assert [a["accountId"] for a in member["groups"][0]["accounts"]] == [str(household)]
    assert member["groups"][0]["events"] == []

    hidden = api.cash_flow("member", f"?accountId={personal}")
    unknown = api.cash_flow("member", f"?accountId={uuid4()}")
    assert hidden.status_code == unknown.status_code == 404
    assert hidden.json() == unknown.json()
    _assert_sanitized(hidden)

    other = _make_household(pg_env)
    api.login("outsider", other.owner_id, other.residence_id)
    foreign = api.cash_flow("outsider", f"?accountId={household}")
    assert foreign.status_code == 404
    assert api.ok("outsider")["groups"] == []


@pytest.mark.parametrize(
    "query",
    [
        "?unknown=1",
        "?from=2026-10-01&from=2026-10-02",
        "?from=2026-10-1",
        "?from=2026-02-30",
        "?from=2026-10-11",
        "?from=2026-10-10&through=2026-10-09",
        "?from=2026-10-10&through=2027-01-10",
        "?currency=brl",
        "?currency=BRLX",
        "?accountId=not-a-uuid",
        "?accountId=00000000-0000-4000-8000-00000000000g",
        "?days=0",
        "?days=93",
        "?days=07",
        "?days=1.5",
        "?days=10&days=11",
        "?through=2026-10-20&days=5",
    ],
)
def test_invalid_requests_are_422_and_sanitized(api: Api, query: str) -> None:
    response = api.cash_flow("owner", query)
    assert response.status_code == 422, (query, response.text)
    assert response.json() == {"detail": "invalid financial cash flow request"}
    _assert_sanitized(response)


def test_duplicate_and_too_many_accounts_are_refused(api: Api) -> None:
    account = api.account("owner")
    duplicated = api.cash_flow(
        "owner", f"?accountId={account}&accountId={str(account).upper()}"
    )
    assert duplicated.status_code == 422
    many = "&".join(f"accountId={uuid4()}" for _ in range(51))
    assert api.cash_flow("owner", f"?{many}").status_code == 422


def test_non_v4_uuid_is_not_found_like_any_unknown_account(api: Api) -> None:
    response = api.cash_flow("owner", "?accountId=00000000-0000-1000-8000-000000000000")
    assert response.status_code == 404
    assert response.json() == {"detail": "financial account was not found"}


def test_session_is_required_and_the_route_is_read_only(api: Api) -> None:
    assert api.client.get("/api/v1/finance/cash-flow").status_code == 401
    for method in ("post", "put", "patch", "delete"):
        response = getattr(api.client, method)(
            "/api/v1/finance/cash-flow", headers=api.headers("owner")
        )
        assert response.status_code == 405, method


def test_money_is_decimal_text_and_the_read_is_deterministic(api: Api) -> None:
    account = api.account("owner", opening="1000.12345678")
    api.entry("owner", "expense", account, "0.00000001", "2026-10-11")
    first = api.ok("owner")
    second = api.ok("owner")
    first.pop("calculatedAt")
    second.pop("calculatedAt")
    assert first == second
    group = first["groups"][0]
    assert group["startingBalance"] == {"amount": "1000.12345678", "currency": "BRL"}
    assert group["closingBalance"] == {"amount": "1000.12345677", "currency": "BRL"}
    for day in group["days"]:
        assert isinstance(day["closing"]["amount"], str)


def test_multiple_currencies_are_separate_groups(api: Api) -> None:
    api.account("owner", opening="10.00", currency="BRL")
    api.account("owner", opening="5.00", currency="USD")
    body = api.ok("owner")
    assert [g["currency"] for g in body["groups"]] == ["BRL", "USD"]
    only_usd = api.ok("owner", "?currency=USD")
    assert [g["currency"] for g in only_usd["groups"]] == ["USD"]


def test_missing_opening_balance_is_reported_incomplete(api: Api) -> None:
    api.account("owner", opening=None)
    group = api.ok("owner")["groups"][0]
    assert group["projectionStatus"] == "INCOMPLETE"
    assert group["issues"][0]["code"] == "OPENING_BALANCE_MISSING"
    assert group["issues"][0]["severity"] == "INCOMPLETE"
    assert group["accounts"][0]["hasOpeningBalance"] is False


def test_historical_window_is_not_applicable(api: Api) -> None:
    api.account("owner")
    group = api.ok("owner", "?from=2026-09-01&through=2026-09-30")["groups"][0]
    assert group["projectionStatus"] == "NOT_APPLICABLE"
    assert all(day["projected"] is False for day in group["days"])


def test_event_overflow_is_refused_with_a_sanitized_422(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = api.account("owner")
    for day in ("2026-10-11", "2026-10-12", "2026-10-13"):
        api.entry("owner", "expense", account, "1.00", day)
    monkeypatch.setattr(store_module, "CASH_FLOW_EVENTS_MAX", 2)
    response = api.cash_flow("owner")
    assert response.status_code == 422
    assert response.json() == {
        "detail": "financial cash flow window has too many events"
    }
    _assert_sanitized(response)


def test_database_failure_is_a_sanitized_503(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    api.account("owner")

    def broken(*_: Any, **__: Any) -> Any:
        raise OperationalError("SELECT secret FROM finance.movements", {}, Exception())

    monkeypatch.setattr(store_module, "_aggregates", broken)
    response = api.cash_flow("owner")
    assert response.status_code == 503
    assert response.json() == {"detail": "financial service is unavailable"}
    _assert_sanitized(response)


def test_r2_relative_days_window_needs_no_client_reference_date(api: Api) -> None:
    api.account("owner")
    body = api.ok("owner", "?days=7")
    assert (body["from"], body["through"], body["days"]) == (
        "2026-10-10",
        "2026-10-16",
        7,
    )
    group = body["groups"][0]
    assert group["risk"]["evaluatedDays"] == 7
    assert group["historicalRisk"] is None
    assert all(day["anchored"] for day in group["days"])


def test_r2_risk_is_split_between_history_and_projection(api: Api) -> None:
    account = api.account("owner", opening="100.00")
    api.entry("owner", "expense", account, "300.00", "2026-10-02")
    api.entry("owner", "income", account, "300.00", "2026-10-04")

    group = api.ok("owner", "?from=2026-10-01&through=2026-10-31")["groups"][0]

    assert group["historicalRisk"]["firstNegativeDate"] == "2026-10-02"
    assert group["historicalRisk"]["negativeDays"] == 2
    # The deficit was recovered before the reference date: no future risk.
    assert group["risk"]["firstNegativeDate"] is None
    assert group["risk"]["negativeDays"] == 0
    (account_body,) = group["accounts"]
    assert account_body["historicalRisk"]["firstNegativeDate"] == "2026-10-02"
    assert account_body["risk"]["firstNegativeDate"] is None


def test_r2_days_before_the_opening_anchor_are_incomplete(api: Api) -> None:
    api.account("owner")  # opening effective 2026-09-01
    group = api.ok("owner", "?from=2026-08-25&through=2026-09-30")["groups"][0]
    assert group["projectionStatus"] == "NOT_APPLICABLE"
    issue = group["issues"][0]
    assert issue["code"] == "OPENING_BALANCE_AFTER_WINDOW_START"
    assert issue["severity"] == "INCOMPLETE"
    anchored = [day["anchored"] for day in group["days"]]
    assert anchored[:7] == [False] * 7 and all(anchored[7:])
    assert group["historicalRisk"]["evaluatedDays"] == 30
    assert group["risk"] is None


def test_r2_missing_opening_balance_has_no_evaluated_risk(api: Api) -> None:
    api.account("owner", opening=None)
    group = api.ok("owner")["groups"][0]
    assert group["risk"] is None
    assert group["accounts"][0]["risk"] is None
    assert not any(day["anchored"] for day in group["days"])
