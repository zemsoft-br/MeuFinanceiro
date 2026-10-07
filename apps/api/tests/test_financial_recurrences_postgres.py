"""HTTP proofs for manual monthly recurrences against a real PostgreSQL.

Everything runs through the non-superuser runtime role with forced RLS, over the
public API. A recurrence is planning: these proofs repeatedly show the ledger,
the balance and the statement never move because of a rule or an occurrence that
was not explicitly registered.
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
from sqlalchemy import Engine, create_engine, func, insert, select
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.main import create_app
from app.services.financial_core import FinancialCoreService
from app.services.financial_recurrences import FinancialRecurrenceService
from app.services.operator_auth import InvalidOperatorSessionError

_RUNTIME_PASSWORD = "disposable-api-test-password"
_NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 6)
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

    database = f"mf_api_recurrences_{secrets.token_hex(4)}"
    role = f"mf_api_recurrences_{secrets.token_hex(4)}"
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
                {"amount": opening, "currency": "BRL", "effectiveDate": "2026-09-01"},
            )
            assert opened.status_code == 201, opened.text
        return account_id

    # -- recurrence helpers ----------------------------------------------------

    def recurrence_body(self, account_id: UUID, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "idempotencyKey": str(uuid4()),
            "accountId": str(account_id),
            "description": "Internet",
            "resultEffect": "EXPENSE",
            "expectedAmount": "120",
            "currency": "BRL",
            "startDate": "2026-01-10",
            "dayOfMonth": 10,
            "endDate": None,
        }
        body.update(overrides)
        return body

    def create(self, who: str, account_id: UUID, **overrides: Any) -> dict[str, Any]:
        response = self.post(
            who, "/recurrences", self.recurrence_body(account_id, **overrides)
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    def generate(
        self, who: str, recurrence_id: str, first: str, last: str | None = None
    ) -> httpx.Response:
        return self.post(
            who,
            f"/recurrences/{recurrence_id}/occurrences/generate",
            {"fromPeriod": first, "throughPeriod": last or first},
        )

    def occurrences(
        self, who: str, first: str, last: str | None = None, **query: str
    ) -> httpx.Response:
        params = f"fromPeriod={first}&throughPeriod={last or first}"
        for key, value in query.items():
            params += f"&{key}={value}"
        return self.get(who, f"/recurrence-occurrences?{params}")


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


def _occurrence_count(api: Api) -> int:
    with api.pg_env.owner_engine.begin() as connection:
        value = connection.scalar(
            select(func.count())
            .select_from(financial_recurrence_occurrences)
            .where(financial_recurrence_occurrences.c.residence_id == api.residence_id)
        )
    assert isinstance(value, int)
    return value


# --- create / read / list -------------------------------------------------------


def test_create_get_and_list_a_recurrence(api: Api, household: Household) -> None:
    account = api.account("owner")
    ledger = _ledger_views(api, "owner", account)

    created = api.create("owner", account)

    assert created["version"] == 1 and created["status"] == "ACTIVE"
    assert created["frequency"] == "MONTHLY"
    assert created["expected"] == {"amount": "120", "currency": "BRL"}
    assert created["resultEffect"] == "EXPENSE" and created["dayOfMonth"] == 10
    assert created["startDate"] == "2026-01-10" and created["endDate"] is None
    assert created["ownerOperatorId"] == str(household.owner_id)
    assert created["canEdit"] is True
    assert api.get("owner", f"/recurrences/{created['id']}").json() == created
    listed = api.get("owner", "/recurrences").json()["items"]
    assert [item["id"] for item in listed] == [created["id"]]
    assert api.get("owner", "/recurrences?status=PAUSED").json() == {"items": []}
    # A rule never touches the ledger.
    assert _ledger_rows(api, household.residence_id) == []
    assert _ledger_views(api, "owner", account) == ledger


def test_create_is_replay_safe_over_http(api: Api) -> None:
    account = api.account("owner")
    body = api.recurrence_body(account)
    first = api.post("owner", "/recurrences", body)
    again = api.post("owner", "/recurrences", body)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    changed = api.post("owner", "/recurrences", {**body, "description": "Outra"})
    _clean(changed, 409, "financial recurrence conflicts with canonical state")
    assert len(api.get("owner", "/recurrences").json()["items"]) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"expectedAmount": "0"},
        {"expectedAmount": "-1"},
        {"expectedAmount": "1.123456789"},
        {"expectedAmount": "1e3"},
        {"expectedAmount": "12,5"},
        {"resultEffect": "NEUTRAL"},
        {"resultEffect": "income"},
        {"currency": "br"},
        {"startDate": "2026-13-01"},
        {"startDate": "2026-1-1"},
        {"startDate": "2026-01-10T00:00"},
        {"dayOfMonth": 0},
        {"dayOfMonth": 32},
        {"dayOfMonth": "10"},
        {"dayOfMonth": True},
        {"endDate": "2025-12-31"},
        {"description": "   "},
        {"description": "x" * 257},
        {"idempotencyKey": "not-a-uuid"},
        {"frequency": "WEEKLY"},
        {"ownerOperatorId": str(uuid4())},
    ],
)
def test_invalid_creates_are_rejected_without_writing(
    api: Api, override: dict[str, Any]
) -> None:
    account = api.account("owner")
    response = api.post(
        "owner", "/recurrences", api.recurrence_body(account, **override)
    )
    assert response.status_code == 422, response.text
    assert api.get("owner", "/recurrences").json() == {"items": []}


def test_a_zero_idempotency_key_and_v1_keys_are_rejected(api: Api) -> None:
    account = api.account("owner")
    for key in ("00000000-0000-0000-0000-000000000000", str(UUID(int=1))):
        response = api.post(
            "owner", "/recurrences", api.recurrence_body(account, idempotencyKey=key)
        )
        assert response.status_code == 422


def test_audience_follows_the_account_and_writes_are_owner_only(
    api: Api, household: Household
) -> None:
    household_account = api.account("owner", scope="HOUSEHOLD")
    personal_account = api.account("owner", scope="PERSONAL")
    shared_rule = api.create("owner", household_account)
    private_rule = api.create("owner", personal_account, description="Pessoal")

    member_list = api.get("member", "/recurrences").json()["items"]
    assert [item["id"] for item in member_list] == [shared_rule["id"]]
    assert member_list[0]["canEdit"] is False
    _clean(
        api.get("member", f"/recurrences/{private_rule['id']}"),
        404,
        "financial resource was not found",
    )
    put = api.put(
        "member",
        f"/recurrences/{shared_rule['id']}",
        {
            "expectedVersion": 1,
            "description": "Hack",
            "expectedAmount": "1",
            "dayOfMonth": 1,
            "endDate": None,
        },
    )
    _clean(put, 403, "financial access denied")
    for action in ("pause", "resume"):
        _clean(
            api.post("member", f"/recurrences/{shared_rule['id']}/{action}"),
            403,
            "financial access denied",
        )
    _clean(
        api.generate("member", shared_rule["id"], "2026-10"),
        403,
        "financial access denied",
    )
    # A member cannot create a rule on the owner's account.
    _clean(
        api.post("member", "/recurrences", api.recurrence_body(household_account)),
        404,
        "financial account was not found",
    )


def test_cross_residence_ids_prove_nothing(
    api: Api, pg_env: PgEnv, other_household: Household
) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    api.login("outsider", other_household.owner_id, other_household.residence_id)
    assert api.get("outsider", "/recurrences").json() == {"items": []}
    _clean(
        api.get("outsider", f"/recurrences/{rule['id']}"),
        404,
        "financial resource was not found",
    )
    _clean(
        api.post("outsider", f"/recurrences/{rule['id']}/pause"),
        404,
        "financial resource was not found",
    )
    _clean(
        api.generate("outsider", rule["id"], "2026-10"),
        404,
        "financial resource was not found",
    )


def test_unknown_methods_and_extra_query_parameters_are_rejected(api: Api) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    for method in ("delete", "patch"):
        response = getattr(api.client, method)(
            f"/api/v1/finance/recurrences/{rule['id']}",
            headers=api._headers("owner"),
        )
        assert response.status_code == 405
    assert api.get("owner", "/recurrences?page=2").status_code == 422
    assert api.get("owner", f"/recurrences/{rule['id']}?x=1").status_code == 422
    assert api.get("owner", "/recurrences?status=BOGUS").status_code == 422
    assert api.get("owner", f"/recurrences/{uuid4()}").status_code == 404
    assert api.get("owner", "/recurrences/not-a-uuid").status_code == 422


# --- edit (CAS) -----------------------------------------------------------------


def _replace_body(version: int = 1, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "expectedVersion": version,
        "description": "Internet",
        "expectedAmount": "120",
        "dayOfMonth": 10,
        "endDate": None,
    }
    body.update(overrides)
    return body


def test_edit_is_cas_and_supersedes_future_pending_explicitly(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    generated = api.generate("owner", rule["id"], "2026-10", "2026-12").json()
    assert generated["createdCount"] == 3

    edited = api.put(
        "owner",
        f"/recurrences/{rule['id']}",
        _replace_body(expectedAmount="130.5", description="Internet fibra"),
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["version"] == 2 and body["supersededCount"] == 3
    assert body["expected"]["amount"] == "130.5"

    stale = api.put("owner", f"/recurrences/{rule['id']}", _replace_body(version=1))
    _clean(stale, 409, "financial recurrence version is stale")
    still = api.occurrences("owner", "2026-10", "2026-12").json()["items"]
    assert still == []  # the three live ones were superseded: history, not shown
    history = api.occurrences(
        "owner", "2026-10", "2026-12", status="SUPERSEDED"
    ).json()["items"]
    assert len(history) == 3 and all(item["ruleVersion"] == 1 for item in history)

    regenerated = api.generate("owner", rule["id"], "2026-10", "2026-12").json()
    assert regenerated["createdCount"] == 3
    assert {item["ruleVersion"] for item in regenerated["items"]} == {2}
    assert {item["expected"]["amount"] for item in regenerated["items"]} == {"130.5"}
    assert _ledger_rows(api, household.residence_id) == []


def test_an_edit_that_changes_nothing_keeps_the_version(api: Api) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    same = api.put("owner", f"/recurrences/{rule['id']}", _replace_body())
    assert same.status_code == 200
    assert same.json()["version"] == 1 and same.json()["supersededCount"] == 0


@pytest.mark.parametrize(
    "override",
    [
        {"expectedVersion": 0},
        {"expectedAmount": "0"},
        {"dayOfMonth": 40},
        {"endDate": "2025-01-01"},
        {"description": ""},
        {"accountId": str(uuid4())},
        {"currency": "USD"},
        {"startDate": "2026-02-01"},
        {"expected": "1"},
    ],
)
def test_invalid_edits_are_rejected(api: Api, override: dict[str, Any]) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    response = api.put("owner", f"/recurrences/{rule['id']}", _replace_body(**override))
    assert response.status_code == 422, response.text
    assert api.get("owner", f"/recurrences/{rule['id']}").json() == rule


def test_concurrent_edits_have_one_winner(api: Api) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    barrier = Barrier(4)

    def attempt(index: int) -> int:
        barrier.wait()
        return api.put(
            "owner",
            f"/recurrences/{rule['id']}",
            _replace_body(description=f"Racer {index}"),
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = [f.result() for f in [pool.submit(attempt, i) for i in range(4)]]
    assert sorted(codes) == [200, 409, 409, 409]


# --- generation -----------------------------------------------------------------


def test_generation_is_explicit_bounded_and_replay_safe(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    ledger = _ledger_views(api, "owner", account)

    # Nothing exists until the user asks.
    assert api.occurrences("owner", "2026-10").json() == {"items": []}
    assert _occurrence_count(api) == 0

    first = api.generate("owner", rule["id"], "2026-10")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["createdCount"] == 1
    october = body["items"][0]
    assert october["status"] == "PENDING" and october["realization"] is None
    assert october["scheduledDate"] == "2026-10-10"
    assert october["periodStart"] == "2026-10-01" and october["ruleVersion"] == 1
    assert october["expected"] == {"amount": "120", "currency": "BRL"}
    assert october["canEdit"] is True

    again = api.generate("owner", rule["id"], "2026-10").json()
    assert again["createdCount"] == 0 and again["items"] == body["items"]
    assert len(api.occurrences("owner", "2026-10").json()["items"]) == 1

    # Forecast is not fact: no Movement, same balance and statement.
    assert _ledger_rows(api, household.residence_id) == []
    assert _ledger_views(api, "owner", account) == ledger


@pytest.mark.parametrize(
    ("first", "last"),
    [
        ("2026-10", "2027-10"),  # 13 months
        ("2026-11", "2026-10"),  # reversed
        ("2026-10", "2029-01"),  # beyond the horizon
        ("2026-13", "2026-13"),
        ("2026-1", "2026-10"),
        ("abcd-ef", "2026-10"),
    ],
)
def test_generation_windows_are_bounded(api: Api, first: str, last: str) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    response = api.generate("owner", rule["id"], first, last)
    assert response.status_code == 422, response.text
    assert _occurrence_count(api) == 0


def test_twelve_months_and_the_horizon_edge_are_allowed(api: Api) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    year = api.generate("owner", rule["id"], "2026-10", "2027-09")
    assert year.status_code == 200 and year.json()["createdCount"] == 12
    horizon = api.generate("owner", rule["id"], "2028-10")  # today + 24 months
    assert horizon.status_code == 200 and horizon.json()["createdCount"] == 1
    assert api.generate("owner", rule["id"], "2028-11").status_code == 422


def test_unknown_fields_are_rejected_on_generate(api: Api) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    response = api.post(
        "owner",
        f"/recurrences/{rule['id']}/occurrences/generate",
        {"fromPeriod": "2026-10", "throughPeriod": "2026-10", "force": True},
    )
    assert response.status_code == 422


def test_concurrent_generation_over_http_creates_no_duplicates(api: Api) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    barrier = Barrier(5)

    def attempt() -> tuple[int, int]:
        barrier.wait()
        response = api.generate("owner", rule["id"], "2026-10", "2027-03")
        return response.status_code, response.json()["createdCount"]

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = [f.result() for f in [pool.submit(attempt) for _ in range(5)]]
    assert {code for code, _ in results} == {200}
    assert sum(created for _, created in results) == 6
    assert _occurrence_count(api) == 6


def test_the_occurrence_listing_is_windowed_filtered_and_audience_aware(
    api: Api,
) -> None:
    household_account = api.account("owner", scope="HOUSEHOLD")
    personal_account = api.account("owner", scope="PERSONAL")
    shared_rule = api.create("owner", household_account, description="Aluguel")
    private_rule = api.create("owner", personal_account, description="Pessoal")
    api.generate("owner", shared_rule["id"], "2026-10", "2026-11")
    api.generate("owner", private_rule["id"], "2026-10", "2026-11")

    owner_items = api.occurrences("owner", "2026-10", "2026-11").json()["items"]
    assert len(owner_items) == 4
    assert [item["periodStart"] for item in owner_items] == sorted(
        item["periodStart"] for item in owner_items
    )
    member_items = api.occurrences("member", "2026-10", "2026-11").json()["items"]
    assert {item["recurrenceId"] for item in member_items} == {shared_rule["id"]}
    assert all(item["canEdit"] is False for item in member_items)
    only = api.occurrences(
        "owner", "2026-10", "2026-11", recurrenceId=shared_rule["id"]
    ).json()["items"]
    assert {item["recurrenceId"] for item in only} == {shared_rule["id"]}
    _clean(
        api.occurrences(
            "member", "2026-10", "2026-11", recurrenceId=private_rule["id"]
        ),
        404,
        "financial resource was not found",
    )
    assert (
        api.occurrences("owner", "2026-10", "2027-10").status_code == 422
    )  # 13-month read window
    assert api.occurrences("owner", "2026-10", status="BOGUS").status_code == 422


# --- skip -----------------------------------------------------------------------


def test_skip_is_idempotent_and_never_creates_a_movement(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    ledger = _ledger_views(api, "owner", account)
    rule = api.create("owner", account)
    occurrence = api.generate("owner", rule["id"], "2026-12").json()["items"][0]

    first = api.post("owner", f"/recurrence-occurrences/{occurrence['id']}/skip")
    again = api.post("owner", f"/recurrence-occurrences/{occurrence['id']}/skip")

    assert first.status_code == again.status_code == 200
    assert first.json()["status"] == "SKIPPED" and first.json() == again.json()
    assert _ledger_rows(api, household.residence_id) == []
    assert _ledger_views(api, "owner", account) == ledger
    listed = api.occurrences("owner", "2026-12").json()["items"]
    assert [item["status"] for item in listed] == ["SKIPPED"]


def test_skip_is_owner_only_and_hidden_or_unknown_ids_are_not_found(
    api: Api,
) -> None:
    account = api.account("owner", scope="HOUSEHOLD")
    private = api.account("owner", scope="PERSONAL")
    rule = api.create("owner", account)
    private_rule = api.create("owner", private)
    visible = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    hidden = api.generate("owner", private_rule["id"], "2026-10").json()["items"][0]

    _clean(
        api.post("member", f"/recurrence-occurrences/{visible['id']}/skip"),
        403,
        "financial access denied",
    )
    _clean(
        api.post("member", f"/recurrence-occurrences/{hidden['id']}/skip"),
        404,
        "financial resource was not found",
    )
    _clean(
        api.post("owner", f"/recurrence-occurrences/{uuid4()}/skip"),
        404,
        "financial resource was not found",
    )


def test_a_superseded_occurrence_cannot_be_skipped(api: Api) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    occurrence = api.generate("owner", rule["id"], "2026-12").json()["items"][0]
    api.put(
        "owner",
        f"/recurrences/{rule['id']}",
        _replace_body(expectedAmount="999"),
    )
    _clean(
        api.post("owner", f"/recurrence-occurrences/{occurrence['id']}/skip"),
        409,
        "financial recurrence occurrence state does not allow this operation",
    )


# --- pause / resume / the issue's vertical (without a realization) --------------


def test_pause_blocks_generation_and_resume_restores_it_keeping_history(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    ledger = _ledger_views(api, "owner", account)
    rule = api.create("owner", account)
    october = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    api.generate("owner", rule["id"], "2026-11")

    paused = api.post("owner", f"/recurrences/{rule['id']}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED" and paused.json()["version"] == 2
    assert api.post("owner", f"/recurrences/{rule['id']}/pause").json() == paused.json()
    _clean(
        api.generate("owner", rule["id"], "2026-12"),
        409,
        "financial recurrence is paused",
    )
    assert api.occurrences("owner", "2026-12").json() == {"items": []}
    assert api.occurrences("owner", "2026-10", "2026-11").json()["items"][0] == october

    resumed = api.post("owner", f"/recurrences/{rule['id']}/resume")
    assert resumed.json()["status"] == "ACTIVE" and resumed.json()["version"] == 3
    assert api.occurrences("owner", "2026-12").json() == {"items": []}  # nothing yet
    december = api.generate("owner", rule["id"], "2026-12").json()["items"][0]
    skipped = api.post("owner", f"/recurrence-occurrences/{december['id']}/skip")
    assert skipped.json()["status"] == "SKIPPED"

    assert _ledger_rows(api, household.residence_id) == []
    assert _ledger_views(api, "owner", account) == ledger


# --- realize (explicit registration) ---------------------------------------------


def _realize_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "idempotencyKey": str(uuid4()),
        "actualAmount": "127.50",
        "currency": "BRL",
        "effectiveDate": "2026-10-11",
        "competenceDate": "2026-10-01",
    }
    body.update(overrides)
    return body


def _realize(
    api: Api, who: str, occurrence_id: str, **overrides: Any
) -> httpx.Response:
    return api.post(
        who,
        f"/recurrence-occurrences/{occurrence_id}/realize",
        _realize_body(**overrides),
    )


def _balance(api: Api, who: str, account_id: UUID) -> dict[str, Any]:
    return dict(api.get(who, f"/accounts/{account_id}/balance").json())


def test_smoke_the_issue_vertical_internet_expense_over_http(
    api: Api, household: Household
) -> None:
    """Internet EXPENSE 120 on day 10: forecast, register 127.50, retry, pause, skip."""
    account = api.account("owner", scope="HOUSEHOLD", opening="1000.00")
    before = _ledger_views(api, "owner", account)
    assert before[0]["currentBalance"]["amount"] == "1000"

    rule = api.create("owner", account, description="Internet", dayOfMonth=10)

    # October: a PENDING forecast. Balance and statement are unchanged.
    october = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    assert october["status"] == "PENDING" and october["scheduledDate"] == "2026-10-10"
    assert _ledger_rows(api, household.residence_id) == []
    assert _ledger_views(api, "owner", account) == before

    # Register with explicit dates and a real amount that differs from the plan.
    key = str(uuid4())
    realized = _realize(api, "owner", october["id"], idempotencyKey=key)
    assert realized.status_code == 200, realized.text
    body = realized.json()
    assert body["status"] == "REALIZED"
    assert body["expected"] == {"amount": "120", "currency": "BRL"}
    link = body["realization"]
    assert link["actual"] == {"amount": "127.5", "currency": "BRL"}
    assert link["effectiveDate"] == "2026-10-11"
    assert link["competenceDate"] == "2026-10-01"
    assert link["movementState"] == "ACTIVE"
    rows = _ledger_rows(api, household.residence_id)
    assert len(rows) == 1  # exactly one Movement
    movement = api.get("owner", f"/movements/{link['movementId']}").json()
    assert movement["role"] == "STANDARD" and movement["resultEffect"] == "EXPENSE"
    assert movement["money"] == {"amount": "-127.5", "currency": "BRL"}
    assert movement["description"] == "Internet"
    after = _balance(api, "owner", account)
    assert after["currentBalance"]["amount"] == "872.5"
    assert after["movementCount"] == 1

    # An identical retry does not duplicate and returns the same answer.
    retry = _realize(api, "owner", october["id"], idempotencyKey=key)
    assert retry.status_code == 200 and retry.json() == body
    assert len(_ledger_rows(api, household.residence_id)) == 1
    assert _balance(api, "owner", account)["currentBalance"]["amount"] == "872.5"

    # November is generated and stays a forecast.
    november = api.generate("owner", rule["id"], "2026-11").json()["items"][0]
    assert november["status"] == "PENDING"
    assert len(_ledger_rows(api, household.residence_id)) == 1

    # Pause: December is not generated.
    assert api.post("owner", f"/recurrences/{rule['id']}/pause").status_code == 200
    _clean(
        api.generate("owner", rule["id"], "2026-12"),
        409,
        "financial recurrence is paused",
    )
    assert api.occurrences("owner", "2026-12").json() == {"items": []}

    # Resume, generate December, skip it: no Movement for December.
    assert api.post("owner", f"/recurrences/{rule['id']}/resume").status_code == 200
    december = api.generate("owner", rule["id"], "2026-12").json()["items"][0]
    skipped = api.post("owner", f"/recurrence-occurrences/{december['id']}/skip")
    assert skipped.json()["status"] == "SKIPPED"
    assert len(_ledger_rows(api, household.residence_id)) == 1
    assert _balance(api, "owner", account)["currentBalance"]["amount"] == "872.5"

    # The listing shows expected x actual for the registered one.
    listed = api.occurrences("owner", "2026-10", "2026-12").json()["items"]
    assert [item["status"] for item in listed] == ["REALIZED", "PENDING", "SKIPPED"]
    assert listed[0]["expected"]["amount"] == "120"
    assert listed[0]["realization"]["actual"]["amount"] == "127.5"
    assert listed[1]["realization"] is None and listed[2]["realization"] is None


def test_pending_and_skipped_never_move_the_balance_or_statement(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    before = _ledger_views(api, "owner", account)
    rule = api.create("owner", account)
    items = api.generate("owner", rule["id"], "2026-10", "2026-12").json()["items"]
    api.post("owner", f"/recurrence-occurrences/{items[0]['id']}/skip")
    assert _ledger_views(api, "owner", account) == before
    assert _ledger_rows(api, household.residence_id) == []


@pytest.mark.parametrize(
    "override",
    [
        {"actualAmount": "0"},
        {"actualAmount": "-5"},
        {"actualAmount": "1.123456789"},
        {"actualAmount": "1e2"},
        {"actualAmount": "12,5"},
        {"actualAmount": ""},
        {"currency": "USD"},  # the occurrence is BRL
        {"currency": "br"},
        {"effectiveDate": "2026-13-01"},
        {"effectiveDate": "2026-10-1"},
        {"competenceDate": "2026-02-30"},
        {"idempotencyKey": "nope"},
        {"idempotencyKey": "00000000-0000-0000-0000-000000000000"},
        {"accountId": str(uuid4())},
        {"movementId": str(uuid4())},
        {"category": "x"},
    ],
)
def test_invalid_realizations_are_rejected_without_a_movement(
    api: Api, household: Household, override: dict[str, Any]
) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    occurrence = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    response = _realize(api, "owner", occurrence["id"], **override)
    assert response.status_code == 422, response.text
    assert _ledger_rows(api, household.residence_id) == []
    again = api.occurrences("owner", "2026-10").json()["items"][0]
    assert again["status"] == "PENDING"


def test_required_realization_fields_cannot_be_omitted(api: Api) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    occurrence = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    for field in (
        "idempotencyKey",
        "actualAmount",
        "currency",
        "effectiveDate",
        "competenceDate",
    ):
        body = _realize_body()
        del body[field]
        response = api.post(
            "owner", f"/recurrence-occurrences/{occurrence['id']}/realize", body
        )
        assert response.status_code == 422, field


def test_a_realization_before_the_opening_balance_fails_without_state(
    api: Api, household: Household
) -> None:
    account = api.account("owner", opening="1000.00")  # anchor 2026-09-01
    rule = api.create("owner", account)
    occurrence = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    response = _realize(api, "owner", occurrence["id"], effectiveDate="2026-08-31")
    _clean(response, 422, "financial operation precedes opening balance")
    assert _ledger_rows(api, household.residence_id) == []
    assert api.occurrences("owner", "2026-10").json()["items"][0]["status"] == "PENDING"


def test_incompatible_commands_fail_closed_with_409(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    first, second = api.generate("owner", rule["id"], "2026-10", "2026-11").json()[
        "items"
    ]
    key = str(uuid4())
    assert _realize(api, "owner", first["id"], idempotencyKey=key).status_code == 200

    changed = _realize(api, "owner", first["id"], idempotencyKey=key, actualAmount="1")
    _clean(changed, 409, "financial recurrence conflicts with canonical state")
    other_target = _realize(api, "owner", second["id"], idempotencyKey=key)
    _clean(other_target, 409, "financial recurrence conflicts with canonical state")
    already = _realize(api, "owner", first["id"])
    _clean(
        already,
        409,
        "financial recurrence occurrence state does not allow this operation",
    )
    skip_realized = api.post("owner", f"/recurrence-occurrences/{first['id']}/skip")
    _clean(
        skip_realized,
        409,
        "financial recurrence occurrence state does not allow this operation",
    )
    assert len(_ledger_rows(api, household.residence_id)) == 1


def test_a_skipped_occurrence_cannot_be_registered(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    occurrence = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    api.post("owner", f"/recurrence-occurrences/{occurrence['id']}/skip")
    _clean(
        _realize(api, "owner", occurrence["id"]),
        409,
        "financial recurrence occurrence state does not allow this operation",
    )
    assert _ledger_rows(api, household.residence_id) == []


def test_only_the_owner_registers_and_ids_prove_nothing(
    api: Api, household: Household, other_household: Household
) -> None:
    shared_account = api.account("owner", scope="HOUSEHOLD")
    private_account = api.account("owner", scope="PERSONAL")
    shared_rule = api.create("owner", shared_account)
    private_rule = api.create("owner", private_account)
    visible = api.generate("owner", shared_rule["id"], "2026-10").json()["items"][0]
    hidden = api.generate("owner", private_rule["id"], "2026-10").json()["items"][0]
    api.login("outsider", other_household.owner_id, other_household.residence_id)

    _clean(_realize(api, "member", visible["id"]), 403, "financial access denied")
    _clean(
        _realize(api, "member", hidden["id"]),
        404,
        "financial resource was not found",
    )
    _clean(
        _realize(api, "outsider", visible["id"]),
        404,
        "financial resource was not found",
    )
    _clean(
        _realize(api, "owner", str(uuid4())), 404, "financial resource was not found"
    )
    assert _ledger_rows(api, household.residence_id) == []


def test_concurrent_identical_registrations_over_http_create_one_movement(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    occurrence = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    key = str(uuid4())
    barrier = Barrier(5)

    def attempt() -> tuple[int, str | None]:
        barrier.wait()
        response = _realize(api, "owner", occurrence["id"], idempotencyKey=key)
        body = response.json()
        return response.status_code, (
            body["realization"]["movementId"] if response.status_code == 200 else None
        )

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = [f.result() for f in [pool.submit(attempt) for _ in range(5)]]
    assert {code for code, _ in results} == {200}
    assert len({movement for _, movement in results}) == 1
    assert len(_ledger_rows(api, household.residence_id)) == 1


def test_concurrent_registrations_with_different_keys_have_one_winner(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    occurrence = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    barrier = Barrier(5)

    def attempt() -> int:
        barrier.wait()
        return _realize(api, "owner", occurrence["id"]).status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        codes = [f.result() for f in [pool.submit(attempt) for _ in range(5)]]
    assert sorted(codes) == [200, 409, 409, 409, 409]
    assert len(_ledger_rows(api, household.residence_id)) == 1


def test_a_reversal_through_the_public_api_never_reopens_the_occurrence(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    occurrence = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    realized = _realize(api, "owner", occurrence["id"]).json()
    movement_id = realized["realization"]["movementId"]
    assert _balance(api, "owner", account)["currentBalance"]["amount"] == "872.5"

    reversal = api.post(
        "owner",
        f"/movements/{movement_id}/reversal",
        {
            "idempotencyKey": str(uuid4()),
            "effectiveDate": "2026-10-12",
            "competenceDate": "2026-10-01",
            "reason": "Cobrança duplicada",
        },
    )
    assert reversal.status_code == 201, reversal.text
    assert _balance(api, "owner", account)["currentBalance"]["amount"] == "1000"

    after = api.occurrences("owner", "2026-10").json()["items"][0]
    assert after["status"] == "REALIZED"
    assert after["realization"]["movementId"] == movement_id
    assert after["realization"]["movementState"] == "REVERSED"
    # Nothing is reopened, skipped, regenerated or registered again.
    _clean(
        _realize(api, "owner", occurrence["id"]),
        409,
        "financial recurrence occurrence state does not allow this operation",
    )
    assert api.generate("owner", rule["id"], "2026-10").json()["createdCount"] == 0
    assert len(_ledger_rows(api, household.residence_id)) == 2  # Movement + reversal


def test_registering_never_classifies_the_movement(api: Api) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    occurrence = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    movement_id = _realize(api, "owner", occurrence["id"]).json()["realization"][
        "movementId"
    ]
    allocation = api.get("owner", f"/movements/{movement_id}/allocation").json()
    assert allocation == {"allocation": None}


def test_an_edit_after_registering_leaves_the_fact_and_its_snapshot_alone(
    api: Api, household: Household
) -> None:
    account = api.account("owner")
    rule = api.create("owner", account)
    occurrence = api.generate("owner", rule["id"], "2026-10").json()["items"][0]
    realized = _realize(api, "owner", occurrence["id"]).json()
    edited = api.put(
        "owner",
        f"/recurrences/{rule['id']}",
        _replace_body(expectedAmount="999", description="Outra"),
    )
    assert edited.status_code == 200 and edited.json()["supersededCount"] == 0
    after = api.occurrences("owner", "2026-10").json()["items"][0]
    assert after == realized
    assert after["expected"]["amount"] == "120" and after["description"] == "Internet"
    assert len(_ledger_rows(api, household.residence_id)) == 1


def test_the_realize_route_is_the_only_writer_of_movements_in_this_surface(
    api: Api,
) -> None:
    paths = api.client.app.openapi()["paths"]  # type: ignore[attr-defined]
    operations = {
        (path, method.upper())
        for path, item in paths.items()
        if "recurrence" in path
        for method in item
    }
    posts = {path for path, method in operations if method == "POST"}
    assert "/api/v1/finance/recurrence-occurrences/{occurrence_id}/realize" in posts
    assert not any(method in ("DELETE", "PATCH") for _, method in operations)
    assert len(operations) == 10


def test_the_visible_cap_is_a_clean_422_not_a_silent_truncation(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    import meufinanceiro_persistence.financial_recurrence_store as store_module

    monkeypatch.setattr(store_module, "RECURRENCE_LIST_MAX", 2)
    account = api.account("owner")
    api.create("owner", account)
    api.create("owner", account)
    refused = api.post("owner", "/recurrences", api.recurrence_body(account))
    _clean(refused, 422, "financial recurrence limit reached")
    assert len(api.get("owner", "/recurrences").json()["items"]) == 2
