"""PostgreSQL-backed end-to-end tests for the classification/allocation API.

Every request crosses the real FastAPI routes, the real ``FinancialCoreService``
and the real stores under the non-superuser runtime role with forced RLS, so the
financial rules (closing sum, sign, currency, audience, ownership, predecessor,
idempotency, concurrency, audit) are proven where they are enforced.

Each module run provisions its own throw-away database inside the server named by
``TEST_DATABASE_URL``; nothing here shares state with the persistence suite.
"""

from __future__ import annotations

import os
import re
import secrets
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
from meufinanceiro_persistence.financial_audit_schema import financial_audit_events
from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.financial_category_store import FinancialCategoryStore
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
    financial_movement_allocations,
)
from meufinanceiro_persistence import (
    financial_movement_allocation_store as allocation_store,
)
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationStore,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_balance_query import (
    FinancialBalanceQueryService,
)
from meufinanceiro_persistence.financial_opening_balance_schema import (
    financial_opening_balances,
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
from sqlalchemy import Engine, create_engine, event, func, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.main import create_app
from app.services.financial_core import FinancialCoreService
from app.services.operator_auth import InvalidOperatorSessionError

_RUNTIME_PASSWORD = "disposable-api-test-password"
_NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)
_PUBLIC_DETAILS = {
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

    database = f"mf_api_alloc_{secrets.token_hex(4)}"
    role = f"mf_api_alloc_{secrets.token_hex(4)}"
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
        self, who: str, account_id: UUID, kind: str, amount: str = "75.25"
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
                "description": "Synthetic",
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
        facade = Api(client, authentication, pg_env)
        facade.login("owner", household.owner_id, household.residence_id)
        facade.login("member", household.member_id, household.residence_id)
        yield facade


def _clean(response: httpx.Response, status_code: int, detail: str) -> None:
    assert response.status_code == status_code, response.text
    assert response.json() == {"detail": detail}
    assert detail in _PUBLIC_DETAILS
    for leak in _LEAKS:
        assert leak not in response.text
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", response.text)


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


def _set_count(pg_env: PgEnv, movement_id: UUID) -> int:
    with pg_env.owner_engine.connect() as connection:
        return int(
            connection.scalar(
                select(func.count())
                .select_from(financial_movement_allocation_sets)
                .where(financial_movement_allocation_sets.c.movement_id == movement_id)
            )
            or 0
        )


def _share_count(pg_env: PgEnv, movement_id: UUID) -> int:
    with pg_env.owner_engine.connect() as connection:
        return int(
            connection.scalar(
                select(func.count())
                .select_from(financial_movement_allocations)
                .where(financial_movement_allocations.c.movement_id == movement_id)
            )
            or 0
        )


def _chain(pg_env: PgEnv, movement_id: UUID) -> list[tuple[int, UUID, UUID | None]]:
    sets = financial_movement_allocation_sets
    with pg_env.owner_engine.connect() as connection:
        return [
            (row.revision, row.id, row.supersedes_id)
            for row in connection.execute(
                select(sets.c.revision, sets.c.id, sets.c.supersedes_id)
                .where(sets.c.movement_id == movement_id)
                .order_by(sets.c.revision)
            )
        ]


def _audit_rows(
    pg_env: PgEnv, residence_id: UUID, event_type: str
) -> list[tuple[UUID, UUID | None, UUID]]:
    events = financial_audit_events
    with pg_env.owner_engine.connect() as connection:
        return [
            (row.subject_id, row.related_subject_id, row.actor_operator_id)
            for row in connection.execute(
                select(
                    events.c.subject_id,
                    events.c.related_subject_id,
                    events.c.actor_operator_id,
                ).where(
                    events.c.residence_id == residence_id,
                    events.c.event_type == event_type,
                )
            )
        ]


def _audit_events(pg_env: PgEnv, residence_id: UUID, event_type: str) -> int:
    with pg_env.owner_engine.connect() as connection:
        return int(
            connection.scalar(
                select(func.count())
                .select_from(financial_audit_events)
                .where(
                    financial_audit_events.c.residence_id == residence_id,
                    financial_audit_events.c.event_type == event_type,
                )
            )
            or 0
        )


# --- categories -----------------------------------------------------------


def test_categories_list_create_tree_and_audience_visibility(api: Api) -> None:
    household_cat = api.category("owner", "HOUSEHOLD", "Mercado")
    child = api.post(
        "owner",
        "/categories",
        {
            "name": "Feira",
            "visibilityScope": "HOUSEHOLD",
            "parentId": str(household_cat),
        },
    )
    assert child.status_code == 201
    assert child.json()["parentId"] == str(household_cat)
    owner_personal = api.category("owner", "PERSONAL", "Meu")
    member_personal = api.category("member", "PERSONAL", "Dele")

    owner_view = {
        item["name"]: item
        for item in api.get("owner", "/categories").json()["categories"]
    }
    member_view = {
        item["name"]: item
        for item in api.get("member", "/categories").json()["categories"]
    }

    assert set(owner_view) == {"Mercado", "Feira", "Meu"}
    assert set(member_view) == {"Mercado", "Feira", "Dele"}
    assert owner_view["Meu"]["categoryId"] == str(owner_personal)
    assert member_view["Dele"]["categoryId"] == str(member_personal)
    assert owner_view["Mercado"]["status"] == "ACTIVE"


def test_category_shared_scope_and_foreign_or_wrong_scope_parent_are_rejected(
    api: Api,
) -> None:
    shared = api.post(
        "owner", "/categories", {"name": "Casa", "visibilityScope": "SHARED"}
    )
    _clean(shared, 422, "invalid financial category request")

    personal = api.category("owner", "PERSONAL", "Privada")
    wrong_scope_parent = api.post(
        "owner",
        "/categories",
        {"name": "Filha", "visibilityScope": "HOUSEHOLD", "parentId": str(personal)},
    )
    _clean(wrong_scope_parent, 404, "financial category was not found")

    foreign_parent = api.post(
        "member",
        "/categories",
        {"name": "Intrusa", "visibilityScope": "PERSONAL", "parentId": str(personal)},
    )
    _clean(foreign_parent, 404, "financial category was not found")


def test_category_creation_is_audited_in_the_authoritative_transaction(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    before = _audit_events(pg_env, household.residence_id, "CATEGORY_CREATED")
    api.category("owner")
    assert (
        _audit_events(pg_env, household.residence_id, "CATEGORY_CREATED") == before + 1
    )


# --- current allocation ---------------------------------------------------


def test_unclassified_movement_has_explicit_null_current_allocation(api: Api) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense")

    response = api.current("owner", movement)

    assert response.status_code == 200
    assert response.json() == {"allocation": None}


def test_missing_and_foreign_movement_keep_the_sanitized_not_found_contract(
    api: Api, household: Household
) -> None:
    account = api.account("owner", scope="PERSONAL")
    personal_movement = api.entry("owner", account, "expense")

    _clean(api.current("owner", uuid4()), 404, "financial resource was not found")
    # A household member cannot see the owner's PERSONAL-account Movement at all:
    # no "null classification" answer may leak its existence.
    _clean(
        api.current("member", personal_movement),
        404,
        "financial resource was not found",
    )


def test_simple_allocation_then_current_returns_exact_persisted_state(
    api: Api,
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "75.25")
    category = api.category("owner")

    created = api.classify("owner", movement, [(category, "-75.25")])

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["movementId"] == str(movement)
    assert body["revision"] == 1
    assert body["supersedesId"] is None
    assert body["allocations"] == [
        {"categoryId": str(category), "money": {"amount": "-75.25", "currency": "BRL"}}
    ]
    assert api.current("owner", movement).json() == {"allocation": body}


def test_income_is_classifiable_with_positive_shares(api: Api) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "income", "300.00")
    category = api.category("owner")

    created = api.classify("owner", movement, [(category, "300.00")])

    assert created.status_code == 201, created.text
    assert created.json()["allocations"][0]["money"]["amount"] == "300"


def test_split_allocation_closes_exactly_and_lists_every_share(api: Api) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "100.00")
    food, home, other = (api.category("owner") for _ in range(3))

    created = api.classify(
        "owner",
        movement,
        [(food, "-33.33"), (home, "-33.33"), (other, "-33.34")],
    )

    assert created.status_code == 201, created.text
    shares = {
        item["categoryId"]: item["money"]["amount"]
        for item in created.json()["allocations"]
    }
    assert shares == {str(food): "-33.33", str(home): "-33.33", str(other): "-33.34"}
    assert (
        api.current("owner", movement).json()["allocation"]["allocations"]
        == (created.json()["allocations"])
    )


# --- revision / append-only ------------------------------------------------


def test_revision_is_append_only_and_current_follows_the_new_version(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "80.00")
    first_cat, second_cat = api.category("owner"), api.category("owner")
    first = api.classify("owner", movement, [(first_cat, "-80.00")]).json()

    revised = api.revise(
        "owner",
        movement,
        first["allocationSetId"],
        [(first_cat, "-50.00"), (second_cat, "-30.00")],
    )

    assert revised.status_code == 201, revised.text
    second = revised.json()
    assert second["revision"] == 2
    assert second["supersedesId"] == first["allocationSetId"]
    assert second["allocationSetId"] != first["allocationSetId"]
    assert api.current("owner", movement).json() == {"allocation": second}
    # Append-only: the predecessor row and its shares are untouched and persisted.
    assert [(rev, sup) for rev, _, sup in _chain(pg_env, movement)] == [
        (1, None),
        (2, UUID(first["allocationSetId"])),
    ]
    with pg_env.owner_engine.connect() as connection:
        old_shares = connection.execute(
            select(financial_movement_allocations.c.amount).where(
                financial_movement_allocations.c.allocation_set_id
                == UUID(first["allocationSetId"])
            )
        ).all()
    assert [str(row[0]) for row in old_shares] == ["-80.00000000"]
    assert _share_count(pg_env, movement) == 3
    # Exactly one audit event per mutation, typed and linked to the predecessor.
    created = _audit_rows(pg_env, household.residence_id, "ALLOCATION_SET_CREATED")
    revised_events = _audit_rows(
        pg_env, household.residence_id, "ALLOCATION_SET_REVISED"
    )
    assert created == [(UUID(first["allocationSetId"]), None, household.owner_id)]
    assert revised_events == [
        (
            UUID(second["allocationSetId"]),
            UUID(first["allocationSetId"]),
            household.owner_id,
        )
    ]


def test_second_first_classification_conflicts_and_current_is_unchanged(
    api: Api,
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "10.00")
    category, other = api.category("owner"), api.category("owner")
    first = api.classify("owner", movement, [(category, "-10.00")])
    assert first.status_code == 201

    again = api.classify("owner", movement, [(other, "-10.00")])

    _clean(again, 409, "financial operation conflicts with canonical state")
    assert api.current("owner", movement).json() == {"allocation": first.json()}


def test_stale_predecessor_returns_409_without_mutating_current(
    pg_env: PgEnv, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "60.00")
    a, b = api.category("owner"), api.category("owner")
    first = api.classify("owner", movement, [(a, "-60.00")]).json()
    current = api.revise(
        "owner", movement, first["allocationSetId"], [(b, "-60.00")]
    ).json()

    stale = api.revise(
        "owner", movement, first["allocationSetId"], [(a, "-20.00"), (b, "-40.00")]
    )

    _clean(stale, 409, "financial operation conflicts with canonical state")
    assert api.current("owner", movement).json() == {"allocation": current}
    assert _set_count(pg_env, movement) == 2

    unknown_predecessor = api.revise("owner", movement, str(uuid4()), [(a, "-60.00")])
    _clean(
        unknown_predecessor, 409, "financial operation conflicts with canonical state"
    )


def test_revision_without_prior_classification_is_a_conflict_not_a_create(
    pg_env: PgEnv, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "12.00")
    category = api.category("owner")

    response = api.revise("owner", movement, str(uuid4()), [(category, "-12.00")])

    _clean(response, 409, "financial operation conflicts with canonical state")
    assert _set_count(pg_env, movement) == 0
    assert api.current("owner", movement).json() == {"allocation": None}


def test_concurrent_revisions_of_one_predecessor_never_fork_the_chain(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "90.00")
    first_category = api.category("owner")
    contenders = [api.category("owner") for _ in range(4)]
    first = api.classify("owner", movement, [(first_category, "-90.00")]).json()
    barrier = Barrier(len(contenders))

    def attempt(category: UUID) -> tuple[int, dict[str, Any]]:
        barrier.wait(timeout=10)
        response = api.revise(
            "owner", movement, first["allocationSetId"], [(category, "-90.00")]
        )
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=len(contenders)) as pool:
        results = list(pool.map(attempt, contenders))

    assert sorted(code for code, _ in results) == [201, 409, 409, 409]
    winner = next(body for code, body in results if code == 201)
    for code, body in results:
        if code == 409:
            assert body == {
                "detail": "financial operation conflicts with canonical state"
            }
    # One linear chain, one current version, no fork, no orphan rows.
    chain = _chain(pg_env, movement)
    assert [(rev, sup) for rev, _, sup in chain] == [
        (1, None),
        (2, UUID(first["allocationSetId"])),
    ]
    assert chain[1][1] == UUID(winner["allocationSetId"])
    assert api.current("owner", movement).json() == {"allocation": winner}
    assert [
        item["allocationSetId"]
        for item in api.bulk("owner", account).json()["movementAllocations"]
    ] == [winner["allocationSetId"]]
    assert _share_count(pg_env, movement) == 2
    assert (
        len(_audit_rows(pg_env, household.residence_id, "ALLOCATION_SET_REVISED")) == 1
    )


def test_concurrent_first_classifications_create_exactly_one_set(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "50.00")
    contenders = [api.category("owner") for _ in range(3)]
    barrier = Barrier(len(contenders))

    def attempt(category: UUID) -> int:
        barrier.wait(timeout=10)
        return api.classify("owner", movement, [(category, "-50.00")]).status_code

    with ThreadPoolExecutor(max_workers=len(contenders)) as pool:
        statuses = sorted(pool.map(attempt, contenders))

    assert statuses == [201, 409, 409]
    assert [(rev, sup) for rev, _, sup in _chain(pg_env, movement)] == [(1, None)]
    assert _share_count(pg_env, movement) == 1
    assert (
        len(_audit_rows(pg_env, household.residence_id, "ALLOCATION_SET_CREATED")) == 1
    )


# --- idempotency -----------------------------------------------------------


def test_idempotent_replay_returns_the_same_set_without_duplicating(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "40.00")
    a, b = api.category("owner"), api.category("owner")
    key = uuid4()

    first = api.classify("owner", movement, [(a, "-25.00"), (b, "-15.00")], key=key)
    replay = api.classify("owner", movement, [(b, "-15.00"), (a, "-25.00")], key=key)

    assert first.status_code == replay.status_code == 201
    assert replay.json() == first.json()
    assert _set_count(pg_env, movement) == 1
    assert _share_count(pg_env, movement) == 2
    created = _audit_rows(pg_env, household.residence_id, "ALLOCATION_SET_CREATED")
    assert len(created) == 1


def test_revision_replay_is_idempotent_and_key_reuse_with_new_body_conflicts(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "40.00")
    a, b = api.category("owner"), api.category("owner")
    first = api.classify("owner", movement, [(a, "-40.00")]).json()
    key = uuid4()

    revised = api.revise(
        "owner", movement, first["allocationSetId"], [(b, "-40.00")], key=key
    )
    replay = api.revise(
        "owner", movement, first["allocationSetId"], [(b, "-40.00")], key=key
    )
    diverged = api.revise(
        "owner", movement, first["allocationSetId"], [(a, "-40.00")], key=key
    )
    other_predecessor = api.revise(
        "owner", movement, str(uuid4()), [(b, "-40.00")], key=key
    )

    assert revised.status_code == replay.status_code == 201
    assert replay.json() == revised.json()
    _clean(diverged, 409, "financial operation conflicts with canonical state")
    _clean(other_predecessor, 409, "financial operation conflicts with canonical state")
    assert _set_count(pg_env, movement) == 2
    assert _share_count(pg_env, movement) == 2
    residence = household.residence_id
    assert len(_audit_rows(pg_env, residence, "ALLOCATION_SET_CREATED")) == 1
    assert len(_audit_rows(pg_env, residence, "ALLOCATION_SET_REVISED")) == 1
    assert api.current("owner", movement).json() == {"allocation": revised.json()}


def test_idempotency_key_cannot_be_replayed_onto_another_movement(
    pg_env: PgEnv, api: Api
) -> None:
    account = api.account("owner")
    first_movement = api.entry("owner", account, "expense", "40.00")
    second_movement = api.entry("owner", account, "expense", "40.00")
    category = api.category("owner")
    key = uuid4()
    created = api.classify("owner", first_movement, [(category, "-40.00")], key=key)
    assert created.status_code == 201

    reused = api.classify("owner", second_movement, [(category, "-40.00")], key=key)

    _clean(reused, 409, "financial operation conflicts with canonical state")
    assert _set_count(pg_env, second_movement) == 0
    assert api.current("owner", second_movement).json() == {"allocation": None}


def test_idempotency_key_reuse_with_different_body_conflicts(
    pg_env: PgEnv, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "40.00")
    a, b = api.category("owner"), api.category("owner")
    key = uuid4()
    assert api.classify("owner", movement, [(a, "-40.00")], key=key).status_code == 201

    response = api.classify("owner", movement, [(b, "-40.00")], key=key)

    _clean(response, 409, "financial operation conflicts with canonical state")
    assert _set_count(pg_env, movement) == 1


# --- economic shape (closing sum / sign / currency) ------------------------


def test_wrong_total_is_rejected_with_422_and_persists_nothing(
    pg_env: PgEnv, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "75.25")
    a, b = api.category("owner"), api.category("owner")

    short = api.classify("owner", movement, [(a, "-75.24")])
    excess = api.classify("owner", movement, [(a, "-50.00"), (b, "-25.26")])

    _clean(short, 422, "invalid financial allocation request")
    _clean(excess, 422, "invalid financial allocation request")
    assert _set_count(pg_env, movement) == 0


def test_wrong_sign_is_rejected_for_expense_and_income(pg_env: PgEnv, api: Api) -> None:
    account = api.account("owner")
    expense = api.entry("owner", account, "expense", "75.25")
    income = api.entry("owner", account, "income", "75.25")
    category = api.category("owner")

    _clean(
        api.classify("owner", expense, [(category, "75.25")]),
        422,
        "invalid financial allocation request",
    )
    _clean(
        api.classify("owner", income, [(category, "-75.25")]),
        422,
        "invalid financial allocation request",
    )
    assert _set_count(pg_env, expense) == _set_count(pg_env, income) == 0


def test_wrong_currency_is_rejected_with_422(pg_env: PgEnv, api: Api) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "75.25")
    category = api.category("owner")

    response = api.classify("owner", movement, [(category, "-75.25")], currency="USD")

    _clean(response, 422, "invalid financial allocation request")
    assert _set_count(pg_env, movement) == 0


def test_mixed_sign_and_duplicate_category_are_rejected_by_the_domain(
    api: Api,
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "75.25")
    a, b = api.category("owner"), api.category("owner")

    mixed = api.classify("owner", movement, [(a, "-100.00"), (b, "24.75")])
    duplicate = api.classify("owner", movement, [(a, "-50.00"), (a, "-25.25")])
    zero = api.classify("owner", movement, [(a, "-75.25"), (b, "0")])

    for response in (mixed, duplicate, zero):
        _clean(response, 422, "invalid financial allocation request")


# --- categories eligibility / audience ------------------------------------


def test_unknown_category_is_rejected_without_leaking_existence(
    pg_env: PgEnv, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "10.00")

    response = api.classify("owner", movement, [(uuid4(), "-10.00")])

    _clean(response, 404, "financial category was not found")
    assert _set_count(pg_env, movement) == 0


def test_disabled_category_stays_readable_but_never_receives_new_allocations(
    pg_env: PgEnv, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "10.00")
    active = api.category("owner", name="Ativa")
    retiring = api.category("owner", name="Aposentada")
    first = api.classify("owner", movement, [(retiring, "-10.00")])
    assert first.status_code == 201
    with pg_env.owner_engine.begin() as connection:
        connection.execute(
            update(financial_categories)
            .where(financial_categories.c.id == retiring)
            .values(status="DISABLED", disabled_at=func.now())
        )

    # Read side: the disabled category still resolves the historical classification.
    listed = {
        item["categoryId"]: item
        for item in api.get("owner", "/categories").json()["categories"]
    }
    assert listed[str(retiring)]["status"] == "DISABLED"
    assert listed[str(retiring)]["disabledAt"] is not None
    assert listed[str(retiring)]["name"] == "Aposentada"
    assert listed[str(active)]["status"] == "ACTIVE"
    historical = api.current("owner", movement).json()["allocation"]
    assert {item["categoryId"] for item in historical["allocations"]} <= set(listed)

    # Write side: neither a revision nor a first classification may use it.
    revision = api.revise(
        "owner", movement, first.json()["allocationSetId"], [(retiring, "-10.00")]
    )
    fresh_movement = api.entry("owner", account, "expense", "5.00")
    fresh = api.classify("owner", fresh_movement, [(retiring, "-5.00")])
    _clean(revision, 404, "financial category was not found")
    _clean(fresh, 404, "financial category was not found")
    assert api.current("owner", movement).json() == {"allocation": first.json()}
    assert _set_count(pg_env, fresh_movement) == 0
    ok = api.revise(
        "owner", movement, first.json()["allocationSetId"], [(active, "-10.00")]
    )
    assert ok.status_code == 201


@pytest.mark.parametrize(
    ("account_scope", "category_scope", "category_owner", "accepted"),
    [
        ("PERSONAL", "PERSONAL", "owner", True),
        ("PERSONAL", "HOUSEHOLD", "owner", True),
        ("PERSONAL", "PERSONAL", "member", False),
        ("SHARED", "HOUSEHOLD", "owner", True),
        ("SHARED", "PERSONAL", "owner", False),
        ("HOUSEHOLD", "HOUSEHOLD", "owner", True),
        ("HOUSEHOLD", "PERSONAL", "owner", False),
    ],
)
def test_adr_0022_audience_matrix_is_enforced_through_the_api(
    pg_env: PgEnv,
    api: Api,
    account_scope: str,
    category_scope: str,
    category_owner: str,
    accepted: bool,
) -> None:
    account = api.account("owner", scope=account_scope)
    movement = api.entry("owner", account, "expense", "20.00")
    category = api.category(category_owner, category_scope)

    response = api.classify("owner", movement, [(category, "-20.00")])

    if accepted:
        assert response.status_code == 201, response.text
    else:
        _clean(response, 404, "financial category was not found")
        assert _set_count(pg_env, movement) == 0


def test_only_the_account_owner_may_classify_but_household_members_may_read(
    pg_env: PgEnv, api: Api
) -> None:
    account = api.account("owner", scope="HOUSEHOLD")
    movement = api.entry("owner", account, "expense", "30.00")
    category = api.category("owner")
    other = api.category("owner")

    denied = api.classify("member", movement, [(category, "-30.00")])
    _clean(denied, 404, "financial resource was not found")
    assert _set_count(pg_env, movement) == 0

    created = api.classify("owner", movement, [(category, "-30.00")])
    assert created.status_code == 201
    assert api.current("member", movement).json() == {"allocation": created.json()}
    shared_bulk = api.bulk("member", account).json()["movementAllocations"]
    assert [item["movementId"] for item in shared_bulk] == [str(movement)]

    # Reading is broader than writing: a member cannot revise either.
    denied_revision = api.revise(
        "member", movement, created.json()["allocationSetId"], [(other, "-30.00")]
    )
    _clean(denied_revision, 404, "financial resource was not found")
    assert [rev for rev, _, _ in _chain(pg_env, movement)] == [1]
    assert api.current("owner", movement).json() == {"allocation": created.json()}


# --- ineligible Movements -------------------------------------------------


def test_neutral_transfer_movements_are_not_classifiable_but_read_as_unclassified(
    pg_env: PgEnv, api: Api
) -> None:
    source = api.account("owner")
    destination = api.account("owner")
    category = api.category("owner")
    transfer = api.post(
        "owner",
        "/transfers",
        {
            "idempotencyKey": str(uuid4()),
            "sourceAccountId": str(source),
            "destinationAccountId": str(destination),
            "amount": "100.00",
            "currency": "BRL",
            "effectiveDate": "2026-09-20",
            "competenceDate": "2026-09-20",
            "description": "Synthetic transfer",
        },
    )
    assert transfer.status_code == 201, transfer.text
    neutral = [
        item
        for account in (source, destination)
        for item in api.get("owner", f"/accounts/{account}/movements").json()[
            "movements"
        ]
        if item["resultEffect"] == "NEUTRAL"
    ]
    assert len(neutral) == 2

    for item in neutral:
        movement_id = UUID(item["movementId"])
        response = api.classify(
            "owner", movement_id, [(category, item["money"]["amount"])]
        )
        _clean(response, 404, "financial resource was not found")
        assert _set_count(pg_env, movement_id) == 0
        assert api.current("owner", movement_id).json() == {"allocation": None}


def test_reversal_movements_are_not_directly_classifiable(
    pg_env: PgEnv, api: Api
) -> None:
    account = api.account("owner")
    original = api.entry("owner", account, "expense", "55.00")
    category = api.category("owner")
    reversed_ = api.post(
        "owner",
        f"/movements/{original}/reversal",
        {
            "idempotencyKey": str(uuid4()),
            "effectiveDate": "2026-09-21",
            "competenceDate": "2026-09-21",
            "reason": "Synthetic reversal",
        },
    )
    assert reversed_.status_code == 201, reversed_.text
    reversal_id = UUID(reversed_.json()["movementId"])
    assert reversed_.json()["role"] == "REVERSAL"

    response = api.classify("owner", reversal_id, [(category, "55.00")])

    _clean(response, 404, "financial resource was not found")
    assert _set_count(pg_env, reversal_id) == 0
    assert api.current("owner", reversal_id).json() == {"allocation": None}


# --- bulk current allocations ---------------------------------------------


def test_bulk_returns_only_current_versions_keyed_by_movement(api: Api) -> None:
    account = api.account("owner")
    classified_once = api.entry("owner", account, "expense", "10.00")
    revised = api.entry("owner", account, "expense", "20.00")
    unclassified = api.entry("owner", account, "income", "30.00")
    split = api.entry("owner", account, "expense", "40.00")
    a, b = api.category("owner"), api.category("owner")
    api.classify("owner", classified_once, [(a, "-10.00")])
    first = api.classify("owner", revised, [(a, "-20.00")]).json()
    current_revision = api.revise(
        "owner", revised, first["allocationSetId"], [(b, "-20.00")]
    ).json()
    split_set = api.classify("owner", split, [(a, "-15.00"), (b, "-25.00")]).json()

    response = api.bulk("owner", account)

    assert response.status_code == 200
    body = response.json()
    assert body["accountId"] == str(account)
    by_movement = {item["movementId"]: item for item in body["movementAllocations"]}
    assert set(by_movement) == {str(classified_once), str(revised), str(split)}
    assert str(unclassified) not in by_movement
    assert len(body["movementAllocations"]) == len(by_movement)
    assert by_movement[str(revised)] == current_revision
    assert by_movement[str(revised)]["revision"] == 2
    assert by_movement[str(split)] == split_set
    for item in body["movementAllocations"]:
        assert "money" not in item  # no Movement amount/balance duplication
        assert set(item) == {
            "allocationSetId",
            "movementId",
            "revision",
            "supersedesId",
            "allocations",
            "createdAt",
        }


def test_bulk_for_an_account_without_classifications_is_an_empty_list(api: Api) -> None:
    account = api.account("owner")
    api.entry("owner", account, "expense")

    assert api.bulk("owner", account).json() == {
        "accountId": str(account),
        "movementAllocations": [],
    }


def test_bulk_is_scoped_to_the_requested_account(api: Api) -> None:
    first, second = api.account("owner"), api.account("owner")
    category = api.category("owner")
    m1 = api.entry("owner", first, "expense", "10.00")
    m2 = api.entry("owner", second, "expense", "20.00")
    api.classify("owner", m1, [(category, "-10.00")])
    api.classify("owner", m2, [(category, "-20.00")])

    first_ids = [
        i["movementId"] for i in api.bulk("owner", first).json()["movementAllocations"]
    ]
    second_ids = [
        i["movementId"] for i in api.bulk("owner", second).json()["movementAllocations"]
    ]

    assert first_ids == [str(m1)]
    assert second_ids == [str(m2)]


def test_bulk_respects_account_audience_and_unknown_accounts(api: Api) -> None:
    personal = api.account("owner", scope="PERSONAL")
    movement = api.entry("owner", personal, "expense", "10.00")
    api.classify("owner", movement, [(api.category("owner"), "-10.00")])

    _clean(api.bulk("member", personal), 404, "financial resource was not found")
    _clean(api.bulk("owner", uuid4()), 404, "financial resource was not found")
    assert len(api.bulk("owner", personal).json()["movementAllocations"]) == 1


def test_bulk_statement_count_does_not_grow_with_classified_movements(
    pg_env: PgEnv, api: Api
) -> None:
    category = api.category("owner")
    few = api.account("owner")
    many = api.account("owner")
    for _ in range(2):
        api.classify(
            "owner", api.entry("owner", few, "expense", "10.00"), [(category, "-10.00")]
        )
    for _ in range(12):
        api.classify(
            "owner",
            api.entry("owner", many, "expense", "10.00"),
            [(category, "-10.00")],
        )

    statements: list[str] = []

    def count(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(pg_env.runtime_engine, "before_cursor_execute", count)
    try:
        small = api.bulk("owner", few)
        small_count, statements[:] = len(statements), []
        large = api.bulk("owner", many)
        large_count = len(statements)
    finally:
        event.remove(pg_env.runtime_engine, "before_cursor_execute", count)

    assert len(small.json()["movementAllocations"]) == 2
    assert len(large.json()["movementAllocations"]) == 12
    assert small_count == large_count  # not proportional to Movement count
    assert large_count <= 6


# --- cross-residence isolation --------------------------------------------


def test_cross_residence_operators_cannot_read_classify_or_list_foreign_data(
    api: Api, other_household: Household
) -> None:
    api.login("stranger", other_household.owner_id, other_household.residence_id)
    account = api.account("owner", scope="HOUSEHOLD")
    movement = api.entry("owner", account, "expense", "10.00")
    category = api.category("owner")
    created = api.classify("owner", movement, [(category, "-10.00")])
    assert created.status_code == 201
    stranger_category = api.category("stranger")

    _clean(api.current("stranger", movement), 404, "financial resource was not found")
    _clean(api.bulk("stranger", account), 404, "financial resource was not found")
    _clean(
        api.classify("stranger", movement, [(stranger_category, "-10.00")]),
        404,
        "financial resource was not found",
    )
    _clean(
        api.revise(
            "stranger",
            movement,
            created.json()["allocationSetId"],
            [(stranger_category, "-10.00")],
        ),
        404,
        "financial resource was not found",
    )
    # A category from another residence is unknown to the owner's scope.
    foreign = api.classify("owner", movement, [(stranger_category, "-10.00")])
    _clean(foreign, 404, "financial category was not found")
    stranger_visible = {
        item["categoryId"]
        for item in api.get("stranger", "/categories").json()["categories"]
    }
    assert stranger_visible == {str(stranger_category)}
    other_move = api.entry("owner", api.account("owner"), "expense", "10.00")
    _clean(
        api.classify("owner", other_move, [(stranger_category, "-10.00")]),
        404,
        "financial category was not found",
    )


# --- ledger / balance invariance -----------------------------------------


def test_classification_never_changes_the_ledger_or_derived_balance(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    account = api.account("owner", opening="1000.00")
    movement = api.entry("owner", account, "expense", "75.25")
    api.entry("owner", account, "income", "10.00")
    a, b = api.category("owner"), api.category("owner")

    def observed() -> tuple[Any, ...]:
        balance = api.get("owner", f"/accounts/{account}/balance").json()
        statement = api.get("owner", f"/accounts/{account}/statement").json()
        balance.pop("calculatedAt")
        statement.pop("calculatedAt")
        with pg_env.owner_engine.connect() as connection:
            openings = [
                tuple(row)
                for row in connection.execute(
                    select(financial_opening_balances).where(
                        financial_opening_balances.c.residence_id
                        == household.residence_id
                    )
                )
            ]
        return (
            balance,
            statement,
            api.get("owner", f"/accounts/{account}/movements").json(),
            api.get("owner", f"/movements/{movement}").json(),
            # Raw rows: amount, currency, account, result_effect, role, dates...
            _ledger_rows(pg_env, household.residence_id),
            openings,
        )

    before = observed()
    first = api.classify("owner", movement, [(a, "-75.25")])
    assert first.status_code == 201
    after_create = observed()
    revised = api.revise(
        "owner",
        movement,
        first.json()["allocationSetId"],
        [(a, "-50.00"), (b, "-25.25")],
    )
    assert revised.status_code == 201
    after_revision = observed()
    # Every failure mode is side-effect free on the ledger as well.
    current = revised.json()["allocationSetId"]
    _clean(
        api.classify("owner", movement, [(a, "-75.25")]),
        409,
        "financial operation conflicts with canonical state",
    )
    _clean(
        api.revise("owner", movement, first.json()["allocationSetId"], [(a, "-75.25")]),
        409,
        "financial operation conflicts with canonical state",
    )
    _clean(
        api.revise("owner", movement, current, [(a, "-75.00")]),
        422,
        "invalid financial allocation request",
    )
    _clean(
        api.revise("owner", movement, current, [(uuid4(), "-75.25")]),
        404,
        "financial category was not found",
    )
    _clean(
        api.revise("member", movement, current, [(a, "-75.25")]),
        404,
        "financial resource was not found",
    )
    after_failures = observed()

    assert before == after_create == after_revision == after_failures
    assert before[0]["currentBalance"]["amount"] == "934.75"
    assert before[0]["movementNet"]["amount"] == "-65.25"
    assert before[5], "opening balance snapshot must not be vacuous"


def test_movement_ledger_table_still_has_no_classification_columns(
    pg_env: PgEnv,
) -> None:
    names = {column.name for column in financial_movements.c}
    assert not {name for name in names if "categor" in name or "allocation" in name}
    with pg_env.owner_engine.connect() as connection:
        live = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'finance' AND table_name = 'movements'"
            )
        }
    assert live == names


# --- sanitized unavailability ---------------------------------------------


def _failing_audit(*_args: Any, **_kwargs: Any) -> None:
    raise OperationalError("INSERT audit_events", {}, Exception("audit unavailable"))


def test_audit_failure_rolls_back_a_first_classification_atomically(
    pg_env: PgEnv,
    household: Household,
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "20.00")
    category = api.category("owner")
    monkeypatch.setattr(
        allocation_store, "_append_financial_audit_event", _failing_audit
    )

    response = api.classify("owner", movement, [(category, "-20.00")])

    _clean(response, 503, "financial service is unavailable")
    # Neither the set, nor its shares, nor an orphan audit event survive.
    assert _set_count(pg_env, movement) == 0
    assert _share_count(pg_env, movement) == 0
    assert _audit_rows(pg_env, household.residence_id, "ALLOCATION_SET_CREATED") == []
    monkeypatch.undo()
    assert api.current("owner", movement).json() == {"allocation": None}
    # The same request is still servable afterwards: nothing half-committed.
    assert api.classify("owner", movement, [(category, "-20.00")]).status_code == 201


def test_audit_failure_rolls_back_a_revision_atomically(
    pg_env: PgEnv,
    household: Household,
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "20.00")
    a, b = api.category("owner"), api.category("owner")
    first = api.classify("owner", movement, [(a, "-20.00")])
    assert first.status_code == 201
    monkeypatch.setattr(
        allocation_store, "_append_financial_audit_event", _failing_audit
    )

    response = api.revise(
        "owner", movement, first.json()["allocationSetId"], [(b, "-20.00")]
    )

    _clean(response, 503, "financial service is unavailable")
    assert [rev for rev, _, _ in _chain(pg_env, movement)] == [1]
    assert _share_count(pg_env, movement) == 1
    assert _audit_rows(pg_env, household.residence_id, "ALLOCATION_SET_REVISED") == []
    monkeypatch.undo()
    assert api.current("owner", movement).json() == {"allocation": first.json()}


def test_failed_requests_never_leave_audit_events(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "20.00")
    category = api.category("owner")
    api.classify("owner", movement, [(category, "-20.00")])
    baseline = (
        _audit_rows(pg_env, household.residence_id, "ALLOCATION_SET_CREATED"),
        _audit_rows(pg_env, household.residence_id, "ALLOCATION_SET_REVISED"),
    )

    for response in (
        api.classify("owner", movement, [(category, "-20.00")]),
        api.revise("owner", movement, str(uuid4()), [(category, "-20.00")]),
        api.revise("owner", movement, str(uuid4()), [(category, "-19.00")]),
        api.classify("owner", movement, [(uuid4(), "-20.00")]),
    ):
        assert response.status_code in {404, 409, 422}

    assert baseline == (
        _audit_rows(pg_env, household.residence_id, "ALLOCATION_SET_CREATED"),
        _audit_rows(pg_env, household.residence_id, "ALLOCATION_SET_REVISED"),
    )


def test_persistence_unavailability_is_a_sanitized_503(
    pg_env: PgEnv, api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "10.00")
    category = api.category("owner")
    movement_path = f"/movements/{movement}"

    # Authentication failure against the real server fails fast and deterministically.
    broken = create_engine(
        pg_env.runtime_engine.url.set(password="wrong-password"),
        connect_args={"connect_timeout": 5},
    )
    service = api.client.app.state.financial_core
    monkeypatch.setattr(
        service, "_allocations", FinancialMovementAllocationStore(broken)
    )
    monkeypatch.setattr(service, "_categories", FinancialCategoryStore(broken))
    try:
        _clean(
            api.classify("owner", movement, [(category, "-10.00")]),
            503,
            "financial service is unavailable",
        )
        _clean(api.bulk("owner", account), 503, "financial service is unavailable")
        _clean(api.get("owner", "/categories"), 503, "financial service is unavailable")
        _clean(
            api.post(
                "owner",
                "/categories",
                {"name": "Casa", "visibilityScope": "HOUSEHOLD"},
            ),
            503,
            "financial service is unavailable",
        )
        # The unavailable allocation store must not masquerade as "unclassified".
        _clean(
            api.get("owner", movement_path + "/allocation"),
            503,
            "financial service is unavailable",
        )
    finally:
        broken.dispose()
