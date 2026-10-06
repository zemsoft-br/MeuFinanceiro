from __future__ import annotations

import os
import re
import secrets
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
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
from meufinanceiro_persistence.financial_categorization_rule_store import (
    FinancialCategorizationRuleStore,
)
from meufinanceiro_persistence.financial_budget_realization_store import (
    FinancialBudgetRealizationStore,
)
from meufinanceiro_persistence.financial_budget_store import FinancialBudgetStore
from meufinanceiro_persistence.financial_category_store import FinancialCategoryStore
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationStore,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_balance_query import (
    FinancialBalanceQueryService,
)
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
from sqlalchemy import Engine, create_engine, event, insert, select
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.main import create_app
from app.services.financial_categorization import FinancialCategorizationService
from app.services.financial_budgets import FinancialBudgetService
from app.services.financial_core import FinancialCoreService
from app.services.financial_pending_movements import (
    FinancialPendingMovementService,
)
from meufinanceiro_persistence.financial_pending_movement_store import (
    FinancialPendingMovementStore,
)
from app.services.operator_auth import InvalidOperatorSessionError

_RUNTIME_PASSWORD = "disposable-api-test-password"
_NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)
_PUBLIC_DETAILS = {
    "invalid financial categorization request",
    "financial resource was not found",
    "financial category was not found",
    "financial access denied",
    "invalid financial allocation request",
    "invalid financial request",
    "invalid financial category request",
    "financial operation conflicts with canonical state",
    "financial service is unavailable",
}
_LEAKS = (
    "SELECT",
    "constraint",
    "violates",
    "psycopg",
    "sqlalchemy",
    "movement_allocation",
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

    database = f"mf_api_budgets_{secrets.token_hex(4)}"
    role = f"mf_api_budgets_{secrets.token_hex(4)}"
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

    def post(self, who: str, path: str, body: dict[str, Any]) -> httpx.Response:
        return self.client.post(
            f"/api/v1/finance{path}", headers=self._headers(who), json=body
        )

    # -- ledger helpers (all through the public API) --------------------------

    def account(
        self, who: str, *, scope: str = "PERSONAL", opening: str | None = "1000.00"
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

    def entry(
        self,
        who: str,
        account_id: UUID,
        kind: str,
        amount: str = "75.25",
        description: str = "Synthetic",
    ) -> UUID:
        response = self.post(
            who,
            f"/accounts/{account_id}/{kind}",
            {
                "idempotencyKey": str(uuid4()),
                "amount": amount,
                "currency": "BRL",
                "effectiveDate": "2026-09-20",
                "competenceDate": "2026-09-20",
                "description": description,
            },
        )
        assert response.status_code == 201, response.text
        return UUID(response.json()["movementId"])

    def category(
        self, who: str, scope: str = "HOUSEHOLD", name: str | None = None
    ) -> UUID:
        response = self.post(
            who,
            "/categories",
            {"name": name or f"Cat {uuid4().hex[:6]}", "visibilityScope": scope},
        )
        assert response.status_code == 201, response.text
        return UUID(response.json()["categoryId"])

    def classify(
        self,
        who: str,
        movement_id: UUID,
        shares: list[tuple[UUID, str]],
        *,
        key: UUID | None = None,
        currency: str = "BRL",
    ) -> httpx.Response:
        return self.post(
            who,
            f"/movements/{movement_id}/allocation",
            {
                "idempotencyKey": str(key or uuid4()),
                "allocations": [
                    {"categoryId": str(c), "amount": a, "currency": currency}
                    for c, a in shares
                ],
            },
        )

    def revise(
        self,
        who: str,
        movement_id: UUID,
        supersedes_id: str,
        shares: list[tuple[UUID, str]],
        *,
        key: UUID | None = None,
    ) -> httpx.Response:
        return self.post(
            who,
            f"/movements/{movement_id}/allocation/revisions",
            {
                "idempotencyKey": str(key or uuid4()),
                "supersedesId": supersedes_id,
                "allocations": [
                    {"categoryId": str(c), "amount": a, "currency": "BRL"}
                    for c, a in shares
                ],
            },
        )

    def current(self, who: str, movement_id: UUID) -> httpx.Response:
        return self.get(who, f"/movements/{movement_id}/allocation")

    def bulk(self, who: str, account_id: UUID) -> httpx.Response:
        return self.get(who, f"/accounts/{account_id}/movement-allocations")


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
        client.app.state.financial_categorization = FinancialCategorizationService(
            FinancialCategorizationRuleStore(engine),
            accounts,
            movements,
            FinancialMovementAllocationStore(engine),
            FinancialCategoryStore(engine),
        )
        client.app.state.financial_budgets = FinancialBudgetService(
            FinancialBudgetStore(engine), FinancialBudgetRealizationStore(engine)
        )
        client.app.state.financial_pending = FinancialPendingMovementService(
            FinancialPendingMovementStore(engine),
            FinancialCategorizationRuleStore(engine),
            FinancialCategoryStore(engine),
        )
        facade = Api(client, authentication, pg_env)
        facade.login("owner", household.owner_id, household.residence_id)
        facade.login("member", household.member_id, household.residence_id)
        yield facade


# --- helpers --------------------------------------------------------------------


def _entry(
    api: Api,
    who: str,
    account_id: UUID,
    kind: str,
    amount: str,
    *,
    effective: str = "2026-10-10",
    competence: str | None = None,
    description: str = "Synthetic",
) -> UUID:
    response = api.post(
        who,
        f"/accounts/{account_id}/{kind}",
        {
            "idempotencyKey": str(uuid4()),
            "amount": amount,
            "currency": "BRL",
            "effectiveDate": effective,
            "competenceDate": competence or effective,
            "description": description,
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["movementId"])


def _reverse(
    api: Api, who: str, movement_id: UUID, *, effective: str = "2026-10-20"
) -> httpx.Response:
    return api.post(
        who,
        f"/movements/{movement_id}/reversal",
        {
            "idempotencyKey": str(uuid4()),
            "effectiveDate": effective,
            "competenceDate": effective,
            "reason": "Synthetic reversal",
        },
    )


def _line(category: UUID, effect: str, amount: str) -> dict[str, str]:
    return {
        "categoryId": str(category),
        "resultEffect": effect,
        "plannedAmount": amount,
    }


def _create_body(
    lines: list[dict[str, str]],
    *,
    scope: str = "HOUSEHOLD",
    basis: str = "CASH",
    period: str = "2026-10",
    currency: str = "BRL",
    name: str = "Outubro",
    key: UUID | None = None,
) -> dict[str, Any]:
    return {
        "idempotencyKey": str(key or uuid4()),
        "name": name,
        "visibilityScope": scope,
        "currency": currency,
        "period": period,
        "dateBasis": basis,
        "lines": lines,
    }


def _put(
    api: Api,
    who: str,
    budget_id: str,
    body: dict[str, Any],
) -> httpx.Response:
    return api.client.put(
        f"/api/v1/finance/budgets/{budget_id}", headers=api._headers(who), json=body
    )


def _summary(api: Api, who: str, budget_id: str) -> dict[str, Any]:
    response = api.get(who, f"/budgets/{budget_id}/summary")
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def _by_category(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (line["categoryId"], line["resultEffect"]): line for line in summary["lines"]
    }


def _ledger_rows(pg_env: PgEnv, residence_id: UUID) -> list[tuple[Any, ...]]:
    with pg_env.owner_engine.connect() as connection:
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


@pytest.fixture
def world(api: Api) -> dict[str, UUID]:
    return {
        "account": api.account("owner", scope="HOUSEHOLD"),
        "personal_account": api.account("owner", scope="PERSONAL"),
        "market": api.category("owner", name="Mercado"),
        "salary": api.category("owner", name="Salário"),
        "leisure": api.category("owner", name="Lazer"),
    }


# --- smoke: the issue's vertical flow over HTTP ---------------------------------


def test_vertical_smoke_plan_vs_ledger_coverage_split_reclassification_reversal(
    api: Api, pg_env: PgEnv, household: Household, world: dict[str, UUID]
) -> None:
    account, market, salary, leisure = (
        world["account"],
        world["market"],
        world["salary"],
        world["leisure"],
    )
    created = api.post(
        "owner",
        "/budgets",
        _create_body(
            [_line(market, "EXPENSE", "1000"), _line(salary, "INCOME", "5000")]
        ),
    )
    assert created.status_code == 201, created.text
    budget_id = created.json()["id"]
    assert created.json()["version"] == 1 and created.json()["canEdit"] is True

    groceries = _entry(api, "owner", account, "expense", "300")
    assert api.classify("owner", groceries, [(market, "-300")]).status_code == 201
    paycheck = _entry(api, "owner", account, "income", "4500")
    assert api.classify("owner", paycheck, [(salary, "4500")]).status_code == 201
    _entry(api, "owner", account, "expense", "100")  # unclassified

    first = _summary(api, "owner", budget_id)
    lines = _by_category(first)
    assert lines[(str(market), "EXPENSE")]["planned"] == {
        "amount": "1000",
        "currency": "BRL",
    }
    assert lines[(str(market), "EXPENSE")]["realized"] == {
        "amount": "300",
        "currency": "BRL",
    }
    assert lines[(str(market), "EXPENSE")]["remaining"] == {
        "amount": "700",
        "currency": "BRL",
    }
    assert lines[(str(market), "EXPENSE")]["status"] == "UNDER"
    assert lines[(str(market), "EXPENSE")]["progressPercent"] == "30.00"
    assert lines[(str(salary), "INCOME")]["realized"]["amount"] == "4500"
    assert lines[(str(salary), "INCOME")]["remaining"]["amount"] == "500"
    coverage = first["coverage"]
    assert coverage["unclassifiedExpenseCount"] == 1
    assert coverage["unclassifiedExpenseAmount"] == {"amount": "100", "currency": "BRL"}
    assert coverage["unclassifiedIncomeCount"] == 0

    ledger_before = _ledger_rows(pg_env, household.residence_id)
    views_before = _ledger_views(api, "owner", account)

    split = _entry(api, "owner", account, "expense", "200")
    split_set = api.classify("owner", split, [(market, "-120"), (leisure, "-80")])
    assert split_set.status_code == 201, split_set.text
    assert (
        _by_category(_summary(api, "owner", budget_id))[(str(market), "EXPENSE")][
            "realized"
        ]["amount"]
        == "420"
    )

    revised = api.revise(
        "owner", split, split_set.json()["allocationSetId"], [(leisure, "-200")]
    )
    assert revised.status_code == 201, revised.text
    assert (
        _by_category(_summary(api, "owner", budget_id))[(str(market), "EXPENSE")][
            "realized"
        ]["amount"]
        == "300"
    )

    reversed_ = _reverse(api, "owner", groceries)
    assert reversed_.status_code == 201, reversed_.text
    final = _summary(api, "owner", budget_id)
    assert _by_category(final)[(str(market), "EXPENSE")]["realized"]["amount"] == "0"
    assert (
        _by_category(final)[(str(market), "EXPENSE")]["remaining"]["amount"] == "1000"
    )

    # Ledger rows only grew by what the ledger operations themselves wrote; the
    # budget calls added nothing, and balance/statement are the ledger's alone.
    ledger_after = _ledger_rows(pg_env, household.residence_id)
    assert len(ledger_after) == len(ledger_before) + 2
    assert _ledger_views(api, "owner", account) != views_before  # the ledger moved...
    # ...and a pure budget read/plan change moves nothing.
    steady = _ledger_views(api, "owner", account)
    _summary(api, "owner", budget_id)
    assert (
        _put(
            api,
            "owner",
            budget_id,
            {
                "expectedVersion": 1,
                "name": "Outubro v2",
                "currency": "BRL",
                "lines": [_line(market, "EXPENSE", "2000")],
            },
        ).status_code
        == 200
    )
    assert _ledger_views(api, "owner", account) == steady
    assert _ledger_rows(pg_env, household.residence_id) == ledger_after


# --- contract: list / create / read / edit --------------------------------------


def test_create_list_get_and_edit_contract(api: Api, world: dict[str, UUID]) -> None:
    market, salary = world["market"], world["salary"]
    body = _create_body(
        [_line(salary, "INCOME", "5000"), _line(market, "EXPENSE", "1000.50")]
    )
    created = api.post("owner", "/budgets", body)
    assert created.status_code == 201, created.text
    payload = created.json()
    assert set(payload) == {
        "id",
        "ownerOperatorId",
        "visibilityScope",
        "name",
        "currency",
        "periodKind",
        "periodStart",
        "periodEnd",
        "dateBasis",
        "version",
        "createdAt",
        "updatedAt",
        "canEdit",
        "lines",
    }
    assert payload["periodKind"] == "MONTHLY"
    assert (payload["periodStart"], payload["periodEnd"]) == (
        "2026-10-01",
        "2026-11-01",
    )
    assert payload["dateBasis"] == "CASH" and payload["currency"] == "BRL"
    assert {tuple(line["planned"].values()) for line in payload["lines"]} == {
        ("5000", "BRL"),
        ("1000.5", "BRL"),
    }

    listed = api.get("owner", "/budgets?period=2026-10").json()
    assert [item["id"] for item in listed["items"]] == [payload["id"]]
    assert api.get("owner", "/budgets?period=2026-11").json() == {"items": []}
    fetched = api.get("owner", f"/budgets/{payload['id']}")
    assert fetched.status_code == 200 and fetched.json() == payload

    edited = _put(
        api,
        "owner",
        payload["id"],
        {
            "expectedVersion": 1,
            "name": "Outubro revisado",
            "currency": "BRL",
            "lines": [_line(market, "EXPENSE", "900")],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2 and edited.json()["name"] == "Outubro revisado"
    assert [line["planned"]["amount"] for line in edited.json()["lines"]] == ["900"]
    assert api.get("owner", f"/budgets/{payload['id']}").json() == edited.json()


def test_create_is_replay_safe_and_conflicts_fail_closed(
    api: Api, world: dict[str, UUID]
) -> None:
    market = world["market"]
    key = uuid4()
    body = _create_body([_line(market, "EXPENSE", "10")], key=key)
    first = api.post("owner", "/budgets", body)
    again = api.post("owner", "/budgets", body)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    assert len(api.get("owner", "/budgets?period=2026-10").json()["items"]) == 1

    reused = _create_body([_line(market, "EXPENSE", "11")], key=key)
    _clean(
        api.post("owner", "/budgets", reused),
        409,
        "financial budget conflicts with canonical state",
    )
    duplicate_month = _create_body([_line(market, "EXPENSE", "12")], name="Outro")
    _clean(
        api.post("owner", "/budgets", duplicate_month),
        409,
        "financial budget conflicts with canonical state",
    )
    assert len(api.get("owner", "/budgets?period=2026-10").json()["items"]) == 1


def test_stale_expected_version_is_a_conflict_that_writes_nothing(
    api: Api, world: dict[str, UUID]
) -> None:
    market = world["market"]
    budget = api.post(
        "owner", "/budgets", _create_body([_line(market, "EXPENSE", "10")])
    ).json()

    def body(version: int, amount: str) -> dict[str, Any]:
        return {
            "expectedVersion": version,
            "name": f"v{version}",
            "currency": "BRL",
            "lines": [_line(market, "EXPENSE", amount)],
        }

    assert _put(api, "owner", budget["id"], body(1, "20")).status_code == 200
    stale = _put(api, "owner", budget["id"], body(1, "30"))
    _clean(stale, 409, "financial budget version is stale")
    _clean(
        _put(api, "owner", budget["id"], body(5, "40")),
        409,
        "financial budget version is stale",
    )
    current = api.get("owner", f"/budgets/{budget['id']}").json()
    assert current["version"] == 2 and current["lines"][0]["planned"]["amount"] == "20"


def test_concurrent_edits_over_http_have_one_winner(
    api: Api, world: dict[str, UUID]
) -> None:
    market = world["market"]
    budget = api.post(
        "owner", "/budgets", _create_body([_line(market, "EXPENSE", "10")])
    ).json()
    barrier = Barrier(4)

    def edit(index: int) -> int:
        barrier.wait()
        return _put(
            api,
            "owner",
            budget["id"],
            {
                "expectedVersion": 1,
                "name": f"w{index}",
                "currency": "BRL",
                "lines": [_line(market, "EXPENSE", str(index + 1))],
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = sorted(pool.map(edit, range(4)))
    assert codes == [200, 409, 409, 409]
    assert api.get("owner", f"/budgets/{budget['id']}").json()["version"] == 2


# --- authorization --------------------------------------------------------------


def test_household_budget_is_read_only_for_members_and_personal_is_invisible(
    api: Api, world: dict[str, UUID]
) -> None:
    market = world["market"]
    mine = api.category("owner", scope="PERSONAL", name="Minha")
    household_budget = api.post(
        "owner", "/budgets", _create_body([_line(market, "EXPENSE", "10")])
    ).json()
    personal_budget = api.post(
        "owner",
        "/budgets",
        _create_body([_line(mine, "EXPENSE", "10")], scope="PERSONAL", name="Meu"),
    )
    assert personal_budget.status_code == 201, personal_budget.text

    seen = api.get("member", f"/budgets/{household_budget['id']}")
    assert seen.status_code == 200 and seen.json()["canEdit"] is False
    assert _summary(api, "member", household_budget["id"])["budget"]["canEdit"] is False
    listed = api.get("member", "/budgets?period=2026-10").json()["items"]
    assert [item["id"] for item in listed] == [household_budget["id"]]

    _clean(
        _put(
            api,
            "member",
            household_budget["id"],
            {
                "expectedVersion": 1,
                "name": "Hack",
                "currency": "BRL",
                "lines": [_line(market, "EXPENSE", "1")],
            },
        ),
        403,
        "financial access denied",
    )
    _clean(
        api.get("member", f"/budgets/{personal_budget.json()['id']}"),
        404,
        "financial resource was not found",
    )
    _clean(
        api.get("member", f"/budgets/{personal_budget.json()['id']}/summary"),
        404,
        "financial resource was not found",
    )
    assert api.get("owner", f"/budgets/{household_budget['id']}").json()["version"] == 1


def test_cross_residence_budget_is_not_found(
    api: Api, pg_env: PgEnv, other_household: Household, world: dict[str, UUID]
) -> None:
    budget = api.post(
        "owner", "/budgets", _create_body([_line(world["market"], "EXPENSE", "10")])
    ).json()
    api.login("outsider", other_household.owner_id, other_household.residence_id)
    _clean(
        api.get("outsider", f"/budgets/{budget['id']}"),
        404,
        "financial resource was not found",
    )
    _clean(
        api.get("outsider", f"/budgets/{budget['id']}/summary"),
        404,
        "financial resource was not found",
    )
    assert api.get("outsider", "/budgets?period=2026-10").json() == {"items": []}
    # A foreign category id never proves anything either.
    foreign_category = api.category("outsider", name="Deles")
    _clean(
        api.post(
            "owner",
            "/budgets",
            _create_body([_line(foreign_category, "EXPENSE", "10")], period="2026-12"),
        ),
        404,
        "financial category was not found",
    )


def test_incompatible_categories_are_rejected(api: Api, world: dict[str, UUID]) -> None:
    mine = api.category("owner", scope="PERSONAL", name="Minha")
    _clean(
        api.post(
            "owner",
            "/budgets",
            _create_body([_line(mine, "EXPENSE", "10")], scope="HOUSEHOLD"),
        ),
        404,
        "financial category was not found",
    )
    _clean(
        api.post(
            "owner",
            "/budgets",
            _create_body([_line(world["market"], "EXPENSE", "10")], scope="PERSONAL"),
        ),
        404,
        "financial category was not found",
    )
    membership_personal = api.category("member", scope="PERSONAL", name="Do membro")
    _clean(
        api.post(
            "owner",
            "/budgets",
            _create_body(
                [_line(membership_personal, "EXPENSE", "10")], scope="PERSONAL"
            ),
        ),
        404,
        "financial category was not found",
    )


def test_unauthenticated_requests_are_rejected(
    api: Api, world: dict[str, UUID]
) -> None:
    for call in (
        lambda: api.client.get("/api/v1/finance/budgets?period=2026-10"),
        lambda: api.client.post("/api/v1/finance/budgets", json={}),
        lambda: api.client.get(f"/api/v1/finance/budgets/{uuid4()}"),
        lambda: api.client.put(f"/api/v1/finance/budgets/{uuid4()}", json={}),
        lambda: api.client.get(f"/api/v1/finance/budgets/{uuid4()}/summary"),
    ):
        assert call().status_code == 401


# --- validation -------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"period": "2026-13"},
        {"period": "2026-1"},
        {"period": "2026-10-01"},
        {"currency": "br"},
        {"currency": "BRLX"},
        {"visibilityScope": "SHARED"},
        {"dateBasis": "ACCRUAL"},
        {"name": ""},
        {"name": "x" * 97},
        {"idempotencyKey": "not-a-uuid"},
        {"idempotencyKey": str(uuid.UUID(int=0))},
        {"extra": "field"},
        {"lines": []},
        {
            "lines": [
                {
                    "categoryId": str(uuid4()),
                    "resultEffect": "NEUTRAL",
                    "plannedAmount": "1",
                }
            ]
        },
        {
            "lines": [
                {
                    "categoryId": str(uuid4()),
                    "resultEffect": "EXPENSE",
                    "plannedAmount": "0",
                }
            ]
        },
        {
            "lines": [
                {
                    "categoryId": str(uuid4()),
                    "resultEffect": "EXPENSE",
                    "plannedAmount": "-5",
                }
            ]
        },
        {
            "lines": [
                {
                    "categoryId": str(uuid4()),
                    "resultEffect": "EXPENSE",
                    "plannedAmount": "1e3",
                }
            ]
        },
        {
            "lines": [
                {
                    "categoryId": str(uuid4()),
                    "resultEffect": "EXPENSE",
                    "plannedAmount": "1.123456789",
                }
            ]
        },
        {
            "lines": [
                {
                    "categoryId": str(uuid4()),
                    "resultEffect": "EXPENSE",
                    "plannedAmount": "NaN",
                }
            ]
        },
        {
            "lines": [
                {
                    "categoryId": str(uuid4()),
                    "resultEffect": "EXPENSE",
                    "plannedAmount": 10.5,
                }
            ]
        },
        {
            "lines": [
                {
                    "categoryId": str(uuid4()),
                    "resultEffect": "EXPENSE",
                    "plannedAmount": 10,
                }
            ]
        },
        {"lines": [{"categoryId": str(uuid4()), "resultEffect": "EXPENSE"}]},
        {
            "lines": [
                {
                    "categoryId": str(uuid4()),
                    "resultEffect": "EXPENSE",
                    "plannedAmount": "1",
                    "x": 1,
                }
            ]
        },
    ],
)
def test_malformed_create_requests_are_rejected_without_writing(
    api: Api, world: dict[str, UUID], mutation: dict[str, Any]
) -> None:
    body = {**_create_body([_line(world["market"], "EXPENSE", "10")]), **mutation}
    response = api.post("owner", "/budgets", body)
    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "invalid financial request"
    } or response.json() == {"detail": "invalid financial budget request"}
    assert api.get("owner", "/budgets?period=2026-10").json() == {"items": []}


def test_duplicate_and_oversized_line_sets_are_rejected(
    api: Api, world: dict[str, UUID]
) -> None:
    market = world["market"]
    duplicate = [_line(market, "EXPENSE", "1"), _line(market, "EXPENSE", "2")]
    assert api.post("owner", "/budgets", _create_body(duplicate)).status_code == 422
    too_many = [_line(uuid4(), "EXPENSE", "1") for _ in range(101)]
    assert api.post("owner", "/budgets", _create_body(too_many)).status_code == 422
    # Same category with both effects is two different lines and is valid.
    both = [_line(market, "EXPENSE", "1"), _line(market, "INCOME", "2")]
    assert api.post("owner", "/budgets", _create_body(both)).status_code == 201


def test_replace_rejects_bad_versions_and_currency_changes(
    api: Api, world: dict[str, UUID]
) -> None:
    market = world["market"]
    budget = api.post(
        "owner", "/budgets", _create_body([_line(market, "EXPENSE", "10")])
    ).json()
    base = {
        "name": "x",
        "currency": "BRL",
        "lines": [_line(market, "EXPENSE", "1")],
    }
    for version in (0, -1, "1", 1.5, None):
        assert (
            _put(
                api, "owner", budget["id"], {**base, "expectedVersion": version}
            ).status_code
            == 422
        )
    assert _put(api, "owner", budget["id"], base).status_code == 422  # missing version
    changed = _put(
        api, "owner", budget["id"], {**base, "expectedVersion": 1, "currency": "USD"}
    )
    assert changed.status_code == 422
    _clean(
        _put(api, "owner", str(uuid4()), {**base, "expectedVersion": 1}),
        404,
        "financial resource was not found",
    )
    assert api.get("owner", f"/budgets/{budget['id']}").json()["version"] == 1


def test_list_requires_exactly_a_valid_period_and_rejects_other_params(
    api: Api,
) -> None:
    for query in (
        "",
        "?period=2026-13",
        "?period=abc",
        "?period=2026-10&limit=5",
        "?period=2026-10&cursor=x",
        "?page=2&period=2026-10",
    ):
        assert api.get("owner", f"/budgets{query}").status_code == 422, query


def test_there_is_no_delete_or_patch_and_no_extra_paths(
    api: Api, world: dict[str, UUID]
) -> None:
    budget = api.post(
        "owner", "/budgets", _create_body([_line(world["market"], "EXPENSE", "10")])
    ).json()
    headers = api._headers("owner")
    url = f"/api/v1/finance/budgets/{budget['id']}"
    assert api.client.delete(url, headers=headers).status_code == 405
    assert api.client.patch(url, headers=headers, json={}).status_code == 405
    assert api.client.post(url, headers=headers, json={}).status_code == 405
    assert (
        api.client.post(f"{url}/summary", headers=headers, json={}).status_code == 405
    )
    assert (
        api.client.put("/api/v1/finance/budgets", headers=headers, json={}).status_code
        == 405
    )
    assert api.get("owner", f"/budgets/{budget['id']}").json()["version"] == 1


def test_money_is_text_on_the_wire_and_never_a_float(
    api: Api, world: dict[str, UUID]
) -> None:
    market = world["market"]
    budget = api.post(
        "owner",
        "/budgets",
        _create_body([_line(market, "EXPENSE", "1234567.12345678")]),
    ).json()
    movement = _entry(api, "owner", world["account"], "expense", "0.1")
    assert api.classify("owner", movement, [(market, "-0.1")]).status_code == 201
    summary = _summary(api, "owner", budget["id"])
    for line in summary["lines"]:
        for field in ("planned", "realized", "remaining"):
            assert isinstance(line[field]["amount"], str)
        assert isinstance(line["progressPercent"], str)
    assert summary["lines"][0]["planned"]["amount"] == "1234567.12345678"
    assert summary["lines"][0]["realized"]["amount"] == "0.1"
    assert summary["lines"][0]["remaining"]["amount"] == "1234567.02345678"
    assert isinstance(summary["coverage"]["unclassifiedExpenseCount"], int)


def test_over_and_at_status_are_computed_server_side(
    api: Api, world: dict[str, UUID]
) -> None:
    market, leisure = world["market"], world["leisure"]
    budget = api.post(
        "owner",
        "/budgets",
        _create_body(
            [_line(market, "EXPENSE", "100"), _line(leisure, "EXPENSE", "50")]
        ),
    ).json()
    spend = _entry(api, "owner", world["account"], "expense", "130")
    api.classify("owner", spend, [(market, "-130")])
    exact = _entry(api, "owner", world["account"], "expense", "50")
    api.classify("owner", exact, [(leisure, "-50")])
    lines = _by_category(_summary(api, "owner", budget["id"]))
    assert lines[(str(market), "EXPENSE")]["status"] == "OVER"
    assert lines[(str(market), "EXPENSE")]["remaining"]["amount"] == "-30"
    assert lines[(str(market), "EXPENSE")]["progressPercent"] == "130.00"
    assert lines[(str(leisure), "EXPENSE")]["status"] == "AT"
    assert lines[(str(leisure), "EXPENSE")]["remaining"]["amount"] == "0"


def test_cash_and_competence_budgets_disagree_over_http(
    api: Api, world: dict[str, UUID]
) -> None:
    market = world["market"]
    movement = _entry(
        api,
        "owner",
        world["account"],
        "expense",
        "90",
        effective="2026-10-31",
        competence="2026-11-02",
    )
    assert api.classify("owner", movement, [(market, "-90")]).status_code == 201
    lines = [_line(market, "EXPENSE", "100")]
    cash = api.post("owner", "/budgets", _create_body(lines, basis="CASH")).json()
    competence = api.post(
        "owner", "/budgets", _create_body(lines, basis="COMPETENCE")
    ).json()
    competence_nov = api.post(
        "owner", "/budgets", _create_body(lines, basis="COMPETENCE", period="2026-11")
    ).json()
    cash_line = _summary(api, "owner", cash["id"])["lines"][0]
    competence_line = _summary(api, "owner", competence["id"])["lines"][0]
    nov_line = _summary(api, "owner", competence_nov["id"])["lines"][0]
    assert cash_line["realized"]["amount"] == "90"
    assert competence_line["realized"]["amount"] == "0"
    assert nov_line["realized"]["amount"] == "90"


def test_household_summary_is_identical_for_members_and_hides_personal_accounts(
    api: Api, world: dict[str, UUID]
) -> None:
    market = world["market"]
    shared = _entry(api, "owner", world["account"], "expense", "40")
    api.classify("owner", shared, [(market, "-40")])
    secret = _entry(api, "owner", world["personal_account"], "expense", "999")
    api.classify("owner", secret, [(market, "-999")])
    _entry(api, "owner", world["personal_account"], "expense", "7")
    budget = api.post(
        "owner", "/budgets", _create_body([_line(market, "EXPENSE", "100")])
    ).json()
    owner_view = _summary(api, "owner", budget["id"])
    member_view = _summary(api, "member", budget["id"])
    assert owner_view["lines"] == member_view["lines"]
    assert owner_view["coverage"] == member_view["coverage"]
    assert owner_view["lines"][0]["realized"]["amount"] == "40"
    assert owner_view["coverage"]["unclassifiedExpenseCount"] == 0


def test_errors_are_sanitized_for_persistence_outages(
    api: Api, world: dict[str, UUID]
) -> None:
    budget = api.post(
        "owner", "/budgets", _create_body([_line(world["market"], "EXPENSE", "10")])
    ).json()
    original = api.client.app.state.financial_budgets
    api.client.app.state.financial_budgets = None
    try:
        _clean(
            api.get("owner", f"/budgets/{budget['id']}"),
            503,
            "financial service is unavailable",
        )
    finally:
        api.client.app.state.financial_budgets = original


def test_summary_statement_count_is_constant(
    api: Api, pg_env: PgEnv, world: dict[str, UUID]
) -> None:
    market, salary = world["market"], world["salary"]
    budget = api.post(
        "owner",
        "/budgets",
        _create_body([_line(market, "EXPENSE", "100"), _line(salary, "INCOME", "100")]),
    ).json()

    def cost() -> int:
        statements: list[str] = []

        def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
            statements.append(statement)

        event.listen(pg_env.runtime_engine, "before_cursor_execute", record)
        try:
            _summary(api, "owner", budget["id"])
        finally:
            event.remove(pg_env.runtime_engine, "before_cursor_execute", record)
        return len(statements)

    empty = cost()
    for index in range(12):
        movement = _entry(api, "owner", world["account"], "expense", str(index + 1))
        if index % 2:
            api.classify("owner", movement, [(market, f"-{index + 1}")])
    assert cost() == empty
