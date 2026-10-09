from __future__ import annotations

import os
import re
import secrets
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
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
from meufinanceiro_persistence.financial_goal_store import FinancialGoalStore
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationStore,
)
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceStore,
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
from sqlalchemy import Engine, create_engine, event, insert, text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.main import create_app
from app.services.financial_core import FinancialCoreService
from app.services.financial_goals import FinancialGoalService
from app.services.operator_auth import InvalidOperatorSessionError

_RUNTIME_PASSWORD = "disposable-api-test-password"
_NOW = datetime(2026, 10, 7, 3, 0, tzinfo=UTC)
_LEAKS = (
    "SELECT",
    "constraint",
    "violates",
    "psycopg",
    "sqlalchemy",
    "goal_allocation",
    "finance.",
    "Traceback",
    "row-level security",
    "pg_advisory",
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

    database = f"mf_api_goals_{secrets.token_hex(4)}"
    role = f"mf_api_goals_{secrets.token_hex(4)}"
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
        self._tokens: dict[str, str] = {}
        self.today: list[date] = [date(2026, 10, 7)]  # the injected clock (mutable)

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

    def put(self, who: str, path: str, body: dict[str, Any]) -> httpx.Response:
        return self.client.put(
            f"/api/v1/finance{path}", headers=self.headers(who), json=body
        )

    # -- ledger helpers (all through the public API) --------------------------

    def account(
        self,
        who: str,
        *,
        scope: str = "HOUSEHOLD",
        opening: str | None = "1000.00",
        currency: str = "BRL",
    ) -> UUID:
        response = self.post(
            who,
            "/accounts",
            {
                "name": f"Conta {uuid4().hex[:6]}",
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

    def expense(self, who: str, account_id: UUID, amount: str) -> UUID:
        response = self.post(
            who,
            f"/accounts/{account_id}/expense",
            {
                "idempotencyKey": str(uuid4()),
                "amount": amount,
                "currency": "BRL",
                "effectiveDate": "2026-09-20",
                "competenceDate": "2026-09-20",
                "description": "Synthetic",
            },
        )
        assert response.status_code == 201, response.text
        return UUID(response.json()["movementId"])


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
        today = [date(2026, 10, 7)]
        client.app.state.financial_goals = FinancialGoalService(
            FinancialGoalStore(engine),
            clock=lambda: today[0],
        )
        facade = Api(client, authentication, pg_env)
        facade.today = today
        facade.login("owner", household.owner_id, household.residence_id)
        facade.login("member", household.member_id, household.residence_id)
        yield facade


# --- helpers --------------------------------------------------------------------


def _goal_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "idempotencyKey": str(uuid4()),
        "title": "Reserva de emergência",
        "description": None,
        "visibilityScope": "HOUSEHOLD",
        "currency": "BRL",
        "targetAmount": "1000.00",
        "targetDate": None,
    }
    body.update(overrides)
    return body


def _create(api: Api, who: str = "owner", **overrides: Any) -> dict[str, Any]:
    response = api.post(who, "/goals", _goal_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _allocation(
    account_id: UUID,
    operation: str,
    amount: str,
    *,
    key: UUID | None = None,
    currency: str = "BRL",
) -> dict[str, Any]:
    return {
        "idempotencyKey": str(key or uuid4()),
        "operation": operation,
        "accountId": str(account_id),
        "amount": amount,
        "currency": currency,
    }


def _move(
    api: Api,
    goal_id: str,
    account_id: UUID,
    operation: str,
    amount: str,
    who: str = "owner",
) -> httpx.Response:
    return api.post(
        who, f"/goals/{goal_id}/allocations", _allocation(account_id, operation, amount)
    )


def _summary(api: Api, goal_id: str, who: str = "owner") -> dict[str, Any]:
    response = api.get(who, f"/goals/{goal_id}/summary")
    assert response.status_code == 200, response.text
    return response.json()


def _ledger_rows(pg_env: PgEnv, residence_id: UUID) -> list[tuple[Any, ...]]:
    with pg_env.owner_engine.begin() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT id, account_id, amount, role FROM finance.movements "
                    "WHERE residence_id = :r ORDER BY id"
                ),
                {"r": residence_id},
            )
        ]


def _counts(pg_env: PgEnv, residence_id: UUID) -> tuple[int, ...]:
    with pg_env.owner_engine.begin() as connection:
        return tuple(
            connection.scalar(
                text(f"SELECT count(*) FROM {table} WHERE residence_id = :r"),
                {"r": residence_id},
            )
            for table in (
                "finance.movements",
                "finance.audit_events",
                "finance.budgets",
                "finance.recurrence_occurrences",
            )
        )


def _clean(response: httpx.Response, status_code: int, detail: str) -> None:
    assert response.status_code == status_code, response.text
    assert response.json() == {"detail": detail}
    for leak in _LEAKS:
        assert leak not in response.text
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", response.text)


# --- smoke: the issue's vertical flow over HTTP ---------------------------------


def test_vertical_smoke_goal_allocation_release_and_a_later_expense(
    api: Api, pg_env: PgEnv, household: Household
) -> None:
    account = api.account("owner", scope="HOUSEHOLD", opening="1000.00")
    second = api.account("owner", scope="HOUSEHOLD", opening="500.00")
    before = (
        _ledger_rows(pg_env, household.residence_id),
        _counts(pg_env, household.residence_id),
    )

    goal = _create(api, title="Viagem", targetAmount="1200.00", targetDate="2027-03-01")
    assert goal["canEdit"] is True and goal["version"] == 1
    goal_id = goal["id"]
    assert _move(api, goal_id, account, "ALLOCATE", "700.00").status_code == 201
    assert _move(api, goal_id, second, "ALLOCATE", "200.5").status_code == 201
    assert _move(api, goal_id, account, "RELEASE", "100").status_code == 201

    summary = _summary(api, goal_id)
    assert summary["target"] == {"amount": "1200", "currency": "BRL"}
    assert summary["allocated"] == {"amount": "800.5", "currency": "BRL"}
    assert summary["remainingTarget"] == {"amount": "399.5", "currency": "BRL"}
    assert summary["progressPercent"] == "66.71"
    assert summary["progressStatus"] == "IN_PROGRESS"
    assert summary["hasInsufficientBacking"] is False
    assert {row["accountId"] for row in summary["accounts"]} == {
        str(account),
        str(second),
    }
    assert [event["operation"] for event in summary["events"]] == [
        "ALLOCATE",
        "ALLOCATE",
        "RELEASE",
    ]
    # Virtual only: the ledger, its audit trail, budgets and occurrences are untouched.
    assert (
        _ledger_rows(pg_env, household.residence_id),
        _counts(pg_env, household.residence_id),
    ) == before

    # A later expense lowers the bank balance; the goal reports it, never rewrites.
    api.expense("owner", account, "500.00")
    after = _summary(api, goal_id)
    assert after["allocated"] == summary["allocated"]
    assert after["events"] == summary["events"]
    assert after["hasInsufficientBacking"] is True
    row = next(item for item in after["accounts"] if item["accountId"] == str(account))
    assert row["accountBalance"]["amount"] == "500"
    assert row["accountAllocatedTotal"]["amount"] == "600"
    assert row["backingStatus"] == "INSUFFICIENT"
    assert row["shortfall"]["amount"] == "100"
    assert _move(api, goal_id, account, "ALLOCATE", "0.01").status_code == 409
    assert _move(api, goal_id, account, "RELEASE", "600").status_code == 201
    assert _summary(api, goal_id)["hasInsufficientBacking"] is False

    # The member reads the household goal and cannot touch it.
    seen = _summary(api, goal_id, "member")
    assert seen["goal"]["canEdit"] is False
    assert _move(api, goal_id, account, "ALLOCATE", "1", "member").status_code == 403


# --- contract ---------------------------------------------------------------------


def test_create_list_get_and_edit_contract(api: Api) -> None:
    created = _create(
        api, description="Meta de teste", targetAmount="2500.5", targetDate="2027-06-01"
    )
    assert set(created) == {
        "id",
        "ownerOperatorId",
        "visibilityScope",
        "title",
        "description",
        "currency",
        "target",
        "targetDate",
        "version",
        "createdAt",
        "updatedAt",
        "canEdit",
    }
    assert created["target"] == {"amount": "2500.5", "currency": "BRL"}
    assert created["targetDate"] == "2027-06-01"

    listing = api.get("owner", "/goals").json()
    assert len(listing["items"]) == 1
    item = listing["items"][0]
    assert item["goal"]["id"] == created["id"]
    assert item["allocated"] == {"amount": "0", "currency": "BRL"}
    assert item["remainingTarget"] == {"amount": "2500.5", "currency": "BRL"}
    assert item["progressPercent"] == "0.00"
    assert item["progressStatus"] == "NOT_STARTED"

    assert api.get("owner", f"/goals/{created['id']}").json() == created
    edited = api.put(
        "owner",
        f"/goals/{created['id']}",
        {
            "expectedVersion": 1,
            "title": "Outro título",
            "description": None,
            "currency": "BRL",
            "targetAmount": "3000",
            "targetDate": None,
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2
    assert edited.json()["target"]["amount"] == "3000"
    assert edited.json()["targetDate"] is None
    assert edited.json()["id"] == created["id"]


def test_create_is_replay_safe_and_conflicts_fail_closed(api: Api) -> None:
    body = _goal_body()
    first = api.post("owner", "/goals", body)
    again = api.post("owner", "/goals", body)

    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    _clean(
        api.post("owner", "/goals", {**body, "targetAmount": "999"}),
        409,
        "financial goal conflicts with canonical state",
    )
    _clean(
        api.post("member", "/goals", body),
        409,
        "financial goal conflicts with canonical state",
    )
    assert len(api.get("owner", "/goals").json()["items"]) == 1


def test_replay_survives_the_window_moving_and_new_creation_stays_strict(
    api: Api,
) -> None:
    body = _goal_body(targetDate="2026-10-07")  # the earliest day accepted today
    first = api.post("owner", "/goals", body)
    assert first.status_code == 201, first.text

    api.today[0] = date(2026, 10, 9)  # the clock advances: that date is now expired

    # Same key and material: the same resource, even though the date aged out.
    replay = api.post("owner", "/goals", body)
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()
    # Same key, different material (expired date kept): a conflict, not a date error.
    _clean(
        api.post("owner", "/goals", {**body, "targetAmount": "999"}),
        409,
        "financial goal conflicts with canonical state",
    )
    # Another operator cannot replay it either.
    _clean(
        api.post("member", "/goals", body),
        409,
        "financial goal conflicts with canonical state",
    )
    # A genuinely new creation with the expired date is rejected and writes nothing.
    rejected = api.post("owner", "/goals", {**body, "idempotencyKey": str(uuid4())})
    assert rejected.status_code == 422, rejected.text
    assert rejected.json() == {"detail": "invalid financial goal request"}
    assert len(api.get("owner", "/goals").json()["items"]) == 1


def test_allocation_replay_and_conflict_over_http(api: Api) -> None:
    account = api.account("owner")
    goal = _create(api)["id"]
    key = uuid4()
    body = _allocation(account, "ALLOCATE", "100", key=key)

    first = api.post("owner", f"/goals/{goal}/allocations", body)
    again = api.post("owner", f"/goals/{goal}/allocations", body)

    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    assert set(first.json()) == {
        "id",
        "goalId",
        "accountId",
        "operation",
        "amount",
        "actorOperatorId",
        "createdAt",
    }
    _clean(
        api.post(
            "owner",
            f"/goals/{goal}/allocations",
            {**body, "amount": "101"},
        ),
        409,
        "financial goal conflicts with canonical state",
    )
    assert _summary(api, goal)["allocated"]["amount"] == "100"
    assert len(_summary(api, goal)["events"]) == 1


def test_stale_expected_version_is_a_conflict_that_writes_nothing(api: Api) -> None:
    goal = _create(api)
    url = f"/goals/{goal['id']}"
    body = {
        "expectedVersion": 1,
        "title": "Primeira",
        "description": None,
        "currency": "BRL",
        "targetAmount": "10",
        "targetDate": None,
    }
    assert api.put("owner", url, body).status_code == 200
    _clean(
        api.put("owner", url, {**body, "title": "Atrasada"}),
        409,
        "financial goal version is stale",
    )
    assert api.get("owner", url).json()["title"] == "Primeira"


def test_concurrent_edits_and_allocations_over_http(api: Api) -> None:
    account = api.account("owner", opening="100.00")
    goals = [_create(api, title=f"Meta {index}")["id"] for index in range(6)]
    barrier = Barrier(len(goals))

    def attempt(goal_id: str) -> int:
        barrier.wait()
        return _move(api, goal_id, account, "ALLOCATE", "30").status_code

    with ThreadPoolExecutor(len(goals)) as pool:
        codes = list(pool.map(attempt, goals))
    assert sorted(codes) == [201, 201, 201, 409, 409, 409]
    totals = [Decimal(_summary(api, goal)["allocated"]["amount"]) for goal in goals]
    assert sum(totals) == 90

    goal = goals[0]
    edit_barrier = Barrier(5)

    def edit(index: int) -> int:
        edit_barrier.wait()
        return api.put(
            "owner",
            f"/goals/{goal}",
            {
                "expectedVersion": 1,
                "title": f"Edit {index}",
                "description": None,
                "currency": "BRL",
                "targetAmount": "50",
                "targetDate": None,
            },
        ).status_code

    with ThreadPoolExecutor(5) as pool:
        codes = list(pool.map(edit, range(5)))
    assert sorted(codes) == [200, 409, 409, 409, 409]


# --- audience -----------------------------------------------------------------------


def test_household_goal_is_read_only_for_members_and_personal_is_invisible(
    api: Api,
) -> None:
    household_goal = _create(api, visibilityScope="HOUSEHOLD")
    personal_goal = _create(api, visibilityScope="PERSONAL", title="Pessoal")

    listing = api.get("member", "/goals").json()["items"]
    assert [item["goal"]["id"] for item in listing] == [household_goal["id"]]
    assert listing[0]["goal"]["canEdit"] is False
    assert (
        api.get("member", f"/goals/{household_goal['id']}").json()["canEdit"] is False
    )
    _clean(
        api.get("member", f"/goals/{personal_goal['id']}"),
        404,
        "financial resource was not found",
    )
    _clean(
        api.get("member", f"/goals/{personal_goal['id']}/summary"),
        404,
        "financial resource was not found",
    )
    _clean(
        api.put(
            "member",
            f"/goals/{household_goal['id']}",
            {
                "expectedVersion": 1,
                "title": "x",
                "description": None,
                "currency": "BRL",
                "targetAmount": "1",
                "targetDate": None,
            },
        ),
        403,
        "financial access denied",
    )
    account = api.account("owner")
    _clean(
        _move(api, personal_goal["id"], account, "ALLOCATE", "1", "member"),
        404,
        "financial resource was not found",
    )
    assert len(api.get("owner", "/goals").json()["items"]) == 2


def test_cross_residence_goal_is_not_found(
    api: Api, pg_env: PgEnv, other_household: Household
) -> None:
    goal = _create(api)
    api.login("outsider", other_household.owner_id, other_household.residence_id)

    _clean(
        api.get("outsider", f"/goals/{goal['id']}"),
        404,
        "financial resource was not found",
    )
    _clean(
        api.get("outsider", f"/goals/{goal['id']}/summary"),
        404,
        "financial resource was not found",
    )
    assert api.get("outsider", "/goals").json() == {"items": []}
    account = api.account("outsider")
    _clean(
        _move(api, goal["id"], account, "ALLOCATE", "1", "outsider"),
        404,
        "financial resource was not found",
    )


def test_ineligible_accounts_and_forged_ids_share_one_sanitized_error(
    api: Api,
) -> None:
    household_goal = _create(api, visibilityScope="HOUSEHOLD")["id"]
    personal_goal = _create(api, visibilityScope="PERSONAL", title="P")["id"]
    household_account = api.account("owner", scope="HOUSEHOLD")
    personal_account = api.account("owner", scope="PERSONAL")
    shared_account = api.account("owner", scope="SHARED")
    usd_account = api.account("owner", scope="HOUSEHOLD", currency="USD")
    member_account = api.account("member", scope="HOUSEHOLD")

    for goal, account in (
        (household_goal, personal_account),
        (personal_goal, household_account),
        (household_goal, shared_account),
        (personal_goal, shared_account),
        (household_goal, usd_account),
        (household_goal, member_account),
        (household_goal, uuid4()),
    ):
        _clean(
            _move(api, goal, account, "ALLOCATE", "1"),
            404,
            "financial account was not found",
        )
    assert (
        _move(api, household_goal, household_account, "ALLOCATE", "1").status_code
        == 201
    )
    assert (
        _move(api, personal_goal, personal_account, "ALLOCATE", "1").status_code == 201
    )
    assert (
        api.post(
            "owner",
            f"/goals/{household_goal}/allocations",
            _allocation(household_account, "ALLOCATE", "1", currency="USD"),
        ).status_code
        == 422
    )


def test_unavailable_and_over_release_are_distinct_clean_conflicts(api: Api) -> None:
    account = api.account("owner", opening="100.00")
    goal = _create(api)["id"]

    _clean(
        _move(api, goal, account, "ALLOCATE", "100.01"),
        409,
        "financial goal allocation exceeds the available balance",
    )
    assert _move(api, goal, account, "ALLOCATE", "40").status_code == 201
    _clean(
        _move(api, goal, account, "RELEASE", "40.01"),
        409,
        "financial goal release exceeds the allocated amount",
    )


def test_unauthenticated_requests_are_rejected(api: Api) -> None:
    goal_id = uuid4()
    for call in (
        lambda: api.client.get("/api/v1/finance/goals"),
        lambda: api.client.post("/api/v1/finance/goals", json={}),
        lambda: api.client.get(f"/api/v1/finance/goals/{goal_id}"),
        lambda: api.client.put(f"/api/v1/finance/goals/{goal_id}", json={}),
        lambda: api.client.get(f"/api/v1/finance/goals/{goal_id}/summary"),
        lambda: api.client.post(
            f"/api/v1/finance/goals/{goal_id}/allocations", json={}
        ),
    ):
        assert call().status_code == 401


# --- validation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"currency": "br"},
        {"currency": "BRLX"},
        {"visibilityScope": "SHARED"},
        {"visibilityScope": "OTHER"},
        {"title": ""},
        {"title": "x" * 97},
        {"title": "bad\ncontrol"},
        {"description": "x" * 281},
        {"idempotencyKey": "not-a-uuid"},
        {"idempotencyKey": str(uuid.UUID(int=0))},
        {"extra": "field"},
        {"targetAmount": "0"},
        {"targetAmount": "-5"},
        {"targetAmount": "1e3"},
        {"targetAmount": "1.123456789"},
        {"targetAmount": "NaN"},
        {"targetAmount": " 10"},
        {"targetAmount": 10.5},
        {"targetAmount": 10},
        {"targetAmount": "12345678901234567"},
        {"targetDate": "2027-13-01"},
        {"targetDate": "27-01-01"},
        {"targetDate": "2025-01-01"},  # in the past
        {"targetDate": "2200-01-01"},  # beyond the horizon
        {"targetDate": 20270101},
    ],
)
def test_malformed_create_requests_are_rejected_without_writing(
    api: Api, mutation: dict[str, Any]
) -> None:
    response = api.post("owner", "/goals", {**_goal_body(), **mutation})
    assert response.status_code == 422, response.text
    assert response.json() in (
        {"detail": "invalid financial request"},
        {"detail": "invalid financial goal request"},
    )
    assert api.get("owner", "/goals").json() == {"items": []}


def test_required_fields_cannot_be_omitted(api: Api) -> None:
    for field in (
        "idempotencyKey",
        "title",
        "visibilityScope",
        "currency",
        "targetAmount",
    ):
        body = _goal_body()
        del body[field]
        assert api.post("owner", "/goals", body).status_code == 422
    assert api.get("owner", "/goals").json() == {"items": []}


@pytest.mark.parametrize(
    "mutation",
    [
        {"operation": "TRANSFER"},
        {"operation": "allocate"},
        {"operation": ""},
        {"amount": "0"},
        {"amount": "-1"},
        {"amount": "1e2"},
        {"amount": "1.123456789"},
        {"amount": 5},
        {"amount": 5.5},
        {"currency": "br"},
        {"accountId": "nope"},
        {"idempotencyKey": "nope"},
        {"extra": 1},
    ],
)
def test_malformed_allocation_requests_are_rejected(
    api: Api, mutation: dict[str, Any]
) -> None:
    account = api.account("owner")
    goal = _create(api)["id"]
    body = {**_allocation(account, "ALLOCATE", "10"), **mutation}
    response = api.post("owner", f"/goals/{goal}/allocations", body)
    assert response.status_code == 422, response.text
    assert _summary(api, goal)["events"] == []


def test_replace_rejects_bad_versions_currency_changes_and_past_dates(
    api: Api,
) -> None:
    goal = _create(api, targetDate="2027-01-01")
    url = f"/goals/{goal['id']}"
    base = {
        "expectedVersion": 1,
        "title": "x",
        "description": None,
        "currency": "BRL",
        "targetAmount": "10",
        "targetDate": "2027-01-01",
    }
    for mutation in (
        {"expectedVersion": 0},
        {"expectedVersion": "1"},
        {"expectedVersion": True},
        {"currency": "USD"},
        {"targetDate": "2020-01-01"},
        {"targetAmount": "0"},
        {"visibilityScope": "PERSONAL"},
    ):
        assert api.put("owner", url, {**base, **mutation}).status_code == 422
    assert api.get("owner", url).json()["version"] == 1
    assert api.put("owner", url, base).status_code == 200


def test_an_old_target_date_stays_editable_when_unchanged(
    api: Api, pg_env: PgEnv, household: Household
) -> None:
    goal = _create(api, targetDate="2026-10-08")
    # Time passes: the stored date is now in the past (a version-advancing planning
    # update, the only kind the database lets through).
    with pg_env.owner_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE finance.goals SET target_date = DATE '2020-01-01', "
                "version = version + 1, updated_at = transaction_timestamp() "
                "WHERE id = :g"
            ),
            {"g": goal["id"]},
        )
    body = {
        "expectedVersion": 2,
        "title": "Ainda editável",
        "description": None,
        "currency": "BRL",
        "targetAmount": "10",
        "targetDate": "2020-01-01",
    }
    assert api.put("owner", f"/goals/{goal['id']}", body).status_code == 200
    assert (
        api.put(
            "owner",
            f"/goals/{goal['id']}",
            {**body, "expectedVersion": 3, "targetDate": "2020-01-02"},
        ).status_code
        == 422
    )


def test_unknown_query_parameters_and_malformed_ids(api: Api) -> None:
    goal = _create(api)
    assert api.get("owner", "/goals?page=2").status_code == 422
    assert api.get("owner", f"/goals/{goal['id']}?x=1").status_code == 422
    assert api.get("owner", f"/goals/{goal['id']}/summary?x=1").status_code == 422
    assert api.get("owner", "/goals/not-a-uuid").status_code == 422
    # A well-formed but non-v4 or unknown id is the same sanitized not-found.
    _clean(
        api.get("owner", f"/goals/{uuid.UUID(int=1)}"),
        404,
        "financial resource was not found",
    )
    _clean(
        api.get("owner", f"/goals/{uuid4()}/summary"),
        404,
        "financial resource was not found",
    )


def test_there_is_no_delete_or_patch_and_no_extra_paths(api: Api) -> None:
    goal = _create(api)
    headers = api.headers("owner")
    url = f"/api/v1/finance/goals/{goal['id']}"
    assert api.client.delete(url, headers=headers).status_code == 405
    assert api.client.patch(url, headers=headers, json={}).status_code == 405
    assert api.client.post(url, headers=headers, json={}).status_code == 405
    assert (
        api.client.post(f"{url}/summary", headers=headers, json={}).status_code == 405
    )
    assert api.client.get(f"{url}/allocations", headers=headers).status_code == 405
    assert api.client.delete(f"{url}/allocations", headers=headers).status_code == 405
    assert (
        api.client.put("/api/v1/finance/goals", headers=headers, json={}).status_code
        == 405
    )
    assert api.get("owner", f"/goals/{goal['id']}").json()["version"] == 1


def test_money_is_text_on_the_wire_and_never_a_float(api: Api) -> None:
    account = api.account("owner", opening="1234567.12345678")
    goal = _create(api, targetAmount="1234567.12345678")["id"]
    assert _move(api, goal, account, "ALLOCATE", "0.1").status_code == 201
    summary = _summary(api, goal)
    for field in ("target", "allocated", "remainingTarget", "surplus"):
        assert isinstance(summary[field]["amount"], str)
    assert isinstance(summary["progressPercent"], str)
    assert summary["allocated"]["amount"] == "0.1"
    assert summary["remainingTarget"]["amount"] == "1234567.02345678"
    row = summary["accounts"][0]
    for field in ("allocated", "accountBalance", "accountAllocatedTotal", "shortfall"):
        assert isinstance(row[field]["amount"], str)
    assert summary["events"][0]["amount"] == {"amount": "0.1", "currency": "BRL"}


def test_lowering_the_target_below_the_allocated_amount_is_explicit(api: Api) -> None:
    account = api.account("owner", opening="500.00")
    goal = _create(api, targetAmount="400")["id"]
    assert _move(api, goal, account, "ALLOCATE", "300").status_code == 201
    edited = api.put(
        "owner",
        f"/goals/{goal}",
        {
            "expectedVersion": 1,
            "title": "Menor",
            "description": None,
            "currency": "BRL",
            "targetAmount": "200",
            "targetDate": None,
        },
    )
    assert edited.status_code == 200
    summary = _summary(api, goal)
    assert summary["progressStatus"] == "EXCEEDED"
    assert summary["surplus"]["amount"] == "100"
    assert summary["remainingTarget"]["amount"] == "0"
    assert summary["progressPercent"] == "150.00"
    assert len(summary["events"]) == 1


def test_errors_are_sanitized_for_persistence_outages(api: Api) -> None:
    goal = _create(api)
    original = api.client.app.state.financial_goals
    api.client.app.state.financial_goals = None
    try:
        _clean(
            api.get("owner", f"/goals/{goal['id']}"),
            503,
            "financial service is unavailable",
        )
    finally:
        api.client.app.state.financial_goals = original


def test_summary_statement_count_does_not_follow_events_goals_or_movements(
    api: Api, pg_env: PgEnv
) -> None:
    account = api.account("owner", opening="100000.00")
    goal = _create(api, targetAmount="100000")["id"]
    assert _move(api, goal, account, "ALLOCATE", "1").status_code == 201

    def cost(call: Any) -> int:
        statements: list[str] = []

        def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
            statements.append(statement)

        event.listen(pg_env.runtime_engine, "before_cursor_execute", record)
        try:
            call()
        finally:
            event.remove(pg_env.runtime_engine, "before_cursor_execute", record)
        return len(statements)

    summary_cost = cost(lambda: _summary(api, goal))
    list_cost = cost(lambda: api.get("owner", "/goals"))
    for _ in range(15):
        assert _move(api, goal, account, "ALLOCATE", "1").status_code == 201
        api.expense("owner", account, "1")
    for index in range(4):
        _create(api, title=f"Extra {index}")
    assert cost(lambda: _summary(api, goal)) == summary_cost
    assert cost(lambda: api.get("owner", "/goals")) == list_cost


def test_the_listing_is_bounded_per_owner(api: Api) -> None:
    for index in range(200):
        assert (
            api.post("owner", "/goals", _goal_body(title=f"M{index}")).status_code
            == 201
        )
    _clean(
        api.post("owner", "/goals", _goal_body(title="201")),
        409,
        "financial goal limit reached",
    )
    assert len(api.get("owner", "/goals").json()["items"]) == 200
    assert (api.get("owner", "/goals").elapsed < timedelta(seconds=2)) is True


# --- project v1: authenticated HTTP -> service -> forced RLS -> ledger ----------


def test_project_vertical_http_store_ledger_and_household_permissions(
    api: Api, pg_env: PgEnv, household: Household
) -> None:
    """No mocks of finance endpoints or project store; real runtime PostgreSQL."""
    from app.services.financial_projects import FinancialProjectService
    from meufinanceiro_persistence.financial_project_store import (
        FinancialProjectStore,
    )

    api.client.app.state.financial_projects = FinancialProjectService(
        FinancialProjectStore(pg_env.runtime_engine)
    )
    account_id = api.account("owner", scope="HOUSEHOLD", opening="1000")
    expense_id = api.expense("owner", account_id, "125")
    ledger_before = _ledger_rows(pg_env, household.residence_id)

    def create(title: str) -> dict[str, Any]:
        response = api.post(
            "owner",
            "/projects",
            {
                "idempotencyKey": str(uuid4()),
                "title": title,
                "description": None,
                "visibilityScope": "HOUSEHOLD",
                "currency": "BRL",
                "plannedAmount": "500",
                "targetDate": None,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    original = create("Reforma")
    second = create("Viagem")
    first_project, second_project = original["id"], second["id"]
    assert api.get("member", f"/projects/{first_project}").json()["canEdit"] is False
    assert api.get("member", f"/projects/{first_project}/summary").status_code == 200

    path = f"/movements/{expense_id}/project-link"
    initial = {
        "idempotencyKey": str(uuid4()),
        "projectId": first_project,
        "expectedPredecessorId": None,
    }
    forbidden = api.post("member", path, initial)
    assert forbidden.status_code == 403, forbidden.text
    first = api.post("owner", path, initial)
    assert first.status_code == 201, first.text
    assert api.post("owner", path, initial).json() == first.json()
    assert api.get("owner", path).json()["link"]["id"] == first.json()["id"]
    summary = api.get("member", f"/projects/{first_project}/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["realized"] == {"amount": "125", "currency": "BRL"}
    assert summary.json()["expenses"][0]["movementId"] == str(expense_id)

    stale = api.post(
        "owner",
        path,
        {
            "idempotencyKey": str(uuid4()),
            "projectId": second_project,
            "expectedPredecessorId": None,
        },
    )
    assert stale.status_code == 409, stale.text
    replaced = api.post(
        "owner",
        path,
        {
            "idempotencyKey": str(uuid4()),
            "projectId": second_project,
            "expectedPredecessorId": first.json()["id"],
        },
    )
    assert replaced.status_code == 201, replaced.text
    assert (
        api.get("owner", f"/projects/{first_project}/summary").json()["realized"][
            "amount"
        ]
        == "0"
    )
    assert (
        api.get("owner", f"/projects/{second_project}/summary").json()["realized"][
            "amount"
        ]
        == "125"
    )
    assert len(api.get("owner", path + "/revisions").json()["items"]) == 2
    assert _ledger_rows(pg_env, household.residence_id) == ledger_before

    reversal = api.post(
        "owner",
        f"/movements/{expense_id}/reversal",
        {
            "idempotencyKey": str(uuid4()),
            "effectiveDate": "2026-10-20",
            "competenceDate": "2026-10-20",
            "reason": "Reembolso integral",
        },
    )
    assert reversal.status_code == 201, reversal.text
    after = api.get("owner", f"/projects/{second_project}/summary")
    assert after.status_code == 200, after.text
    assert after.json()["realized"] == {"amount": "0", "currency": "BRL"}
    assert after.json()["expenses"][0]["reversed"] is True
    assert len(_ledger_rows(pg_env, household.residence_id)) == len(ledger_before) + 1
