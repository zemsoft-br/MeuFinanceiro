"""PostgreSQL-backed end-to-end tests for the pending-classification inbox.

Every request crosses the real FastAPI route, service and stores under the
non-superuser runtime role with forced RLS. The inbox is derived from the ledger
and classification state; classification itself reuses the #245/#247 endpoints.

Each module run provisions its own throw-away database.
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
from meufinanceiro_persistence.financial_categorization_rule_store import (
    FinancialCategorizationRuleStore,
)
from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.financial_category_store import FinancialCategoryStore
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
    financial_movement_allocations,
)
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
from sqlalchemy import Engine, create_engine, event, func, insert, select, text, update
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.main import create_app
from app.services.financial_categorization import FinancialCategorizationService
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

    database = f"mf_api_rules_{secrets.token_hex(4)}"
    role = f"mf_api_rules_{secrets.token_hex(4)}"
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
        client.app.state.financial_pending = FinancialPendingMovementService(
            FinancialPendingMovementStore(engine),
            FinancialCategorizationRuleStore(engine),
            FinancialCategoryStore(engine),
        )
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


# --- categorization-rule helpers -------------------------------------------


def _rule_body(
    category: UUID,
    pattern: str = "padaria",
    *,
    matcher: str = "CONTAINS",
    priority: int = 10,
    account: UUID | None = None,
    effect: str | None = None,
    key: UUID | None = None,
) -> dict[str, Any]:
    return {
        "idempotencyKey": str(key or uuid4()),
        "descriptionMatcher": matcher,
        "descriptionPattern": pattern,
        "targetCategoryId": str(category),
        "priority": priority,
        "accountId": str(account) if account else None,
        "resultEffect": effect,
    }


def _create_rule(
    api: Api, who: str, category: UUID, pattern: str = "padaria", **kw: Any
) -> str:
    response = api.post(
        who, "/categorization-rules", _rule_body(category, pattern, **kw)
    )
    assert response.status_code == 201, response.text
    return str(response.json()["ruleId"])


def _preview(api: Api, who: str, account: UUID) -> httpx.Response:
    return api.post(who, f"/accounts/{account}/categorization-rules/preview", {})


def _apply(
    api: Api, who: str, account: UUID, pairs: list[tuple[Any, Any]]
) -> httpx.Response:
    return api.post(
        who,
        f"/accounts/{account}/categorization-rules/apply",
        {"items": [{"movementId": str(m), "ruleId": str(r)} for m, r in pairs]},
    )


def _origins(api: Api, who: str, account: UUID) -> list[dict[str, Any]]:
    response = api.get(who, f"/accounts/{account}/categorization-rules/origins")
    assert response.status_code == 200, response.text
    return list(response.json()["origins"])


def _table_count(pg_env: PgEnv, table: Any, residence_id: UUID) -> int:
    with pg_env.owner_engine.connect() as connection:
        return int(
            connection.scalar(
                select(func.count())
                .select_from(table)
                .where(table.c.residence_id == residence_id)
            )
            or 0
        )


def _without_timestamps(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _without_timestamps(v) for k, v in value.items() if k != "calculatedAt"
        }
    if isinstance(value, list):
        return [_without_timestamps(item) for item in value]
    return value


def _economic_snapshot(api: Api, who: str, account: UUID) -> tuple[Any, ...]:
    return tuple(
        _without_timestamps(api.get(who, f"/accounts/{account}/{part}").json())
        for part in ("balance", "statement", "movements")
    )


# --- inbox helpers -----------------------------------------------------------


def _pending(api: Api, who: str, **params: Any) -> httpx.Response:
    return api.client.get(
        "/api/v1/finance/pending-movements",
        params={k: v for k, v in params.items() if v is not None},
        headers=api._headers(who),
    )


def _items(response: httpx.Response) -> list[dict[str, Any]]:
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


def _ids(response: httpx.Response) -> list[str]:
    return [item["movementId"] for item in _items(response)]


def _walk(api: Api, who: str, **params: Any) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(100):
        response = _pending(api, who, cursor=cursor, **params)
        assert response.status_code == 200, response.text
        body = response.json()
        collected.extend(body["items"])
        cursor = body["nextCursor"]
        if cursor is None:
            return collected
    raise AssertionError("cursor chain did not terminate")


def _transfer(api: Api, who: str, source: UUID, destination: UUID) -> None:
    response = api.post(
        who,
        "/transfers",
        {
            "idempotencyKey": str(uuid4()),
            "sourceAccountId": str(source),
            "destinationAccountId": str(destination),
            "amount": "10.00",
            "currency": "BRL",
            "effectiveDate": "2026-09-21",
            "competenceDate": "2026-09-21",
            "description": "Padaria transferência",
        },
    )
    assert response.status_code == 201, response.text


def _residence_of(api: Api, who: str = "owner") -> UUID:
    principal = api.authentication.principals[api._tokens[who]]
    assert principal.primary_residence_id is not None
    return principal.primary_residence_id


# --- derivation and shape ------------------------------------------------------


def test_lists_only_classifiable_unclassified_movements_with_derived_status(
    pg_env: PgEnv, api: Api
) -> None:
    category = api.category("owner")
    other_category = api.category("owner", name="Outra")
    account = api.account("owner")
    other = api.account("owner")
    matched = api.entry("owner", account, "expense", "10.00", description="Padaria 1")
    tied = api.entry("owner", account, "expense", "11.00", description="Mercado Sul")
    none = api.entry("owner", account, "expense", "12.00", description="Cinema")
    income = api.entry("owner", account, "income", "13.00", description="Padaria 2")
    manual = api.entry("owner", account, "expense", "14.00", description="Manual")
    by_rule = api.entry("owner", account, "expense", "15.00", description="Padaria 3")
    reversed_id = api.entry(
        "owner", account, "expense", "5.00", description="Estornada"
    )
    reversal = api.post(
        "owner",
        f"/movements/{reversed_id}/reversal",
        {
            "idempotencyKey": str(uuid4()),
            "effectiveDate": "2026-09-21",
            "competenceDate": "2026-09-21",
            "reason": "Estorno de teste",
        },
    )
    assert reversal.status_code == 201, reversal.text
    _transfer(api, "owner", account, other)
    assert api.classify("owner", manual, [(category, "-14.00")]).status_code == 201

    rule = _create_rule(api, "owner", category, "padaria", priority=5)
    _create_rule(api, "owner", other_category, "mercado", priority=7)
    _create_rule(api, "owner", category, "mercado", priority=7)
    applied = _apply(api, "owner", account, [(by_rule, rule)]).json()
    assert applied["counts"]["classified"] == 1

    residence = _residence_of(api)
    ledger_before = _ledger_rows(pg_env, residence)
    response = _pending(api, "owner")
    items = {item["movementId"]: item for item in _items(response)}
    # manual, rule-classified, the REVERSAL and both NEUTRAL legs never appear;
    # the reversed STANDARD original remains classifiable.
    assert set(items) == {
        str(matched),
        str(tied),
        str(none),
        str(income),
        str(reversed_id),
    }
    assert items[str(matched)]["ruleStatus"] == "MATCHED"
    assert items[str(matched)]["matchedRuleId"] == rule
    assert items[str(matched)]["suggestedCategoryId"] == str(category)
    assert items[str(income)]["ruleStatus"] == "MATCHED"
    assert items[str(tied)]["ruleStatus"] == "AMBIGUOUS"
    assert items[str(none)]["ruleStatus"] == "NO_MATCH"
    for key in ("matchedRuleId", "suggestedCategoryId"):
        assert items[str(tied)][key] is None and items[str(none)][key] is None
    assert response.headers["cache-control"] == "no-store"
    assert _ledger_rows(pg_env, residence) == ledger_before


def test_item_shape_is_exact_and_exposes_no_internal_state(api: Api) -> None:
    account = api.account("owner", scope="HOUSEHOLD")
    movement = api.entry("owner", account, "expense", "75.25", description="Padaria")
    body = _pending(api, "owner").json()
    assert set(body) == {"items", "nextCursor"}
    (item,) = body["items"]
    assert set(item) == {
        "movementId",
        "accountId",
        "money",
        "resultEffect",
        "effectiveDate",
        "competenceDate",
        "description",
        "accountVisibilityScope",
        "accountOwnerOperatorId",
        "canClassify",
        "ruleStatus",
        "matchedRuleId",
        "suggestedCategoryId",
    }
    assert item["movementId"] == str(movement) and item["accountId"] == str(account)
    assert item["money"] == {"amount": "-75.25", "currency": "BRL"}
    assert item["resultEffect"] == "EXPENSE"
    assert item["effectiveDate"] == "2026-09-20"
    assert item["accountVisibilityScope"] == "HOUSEHOLD"
    assert item["canClassify"] is True and item["ruleStatus"] == "NO_MATCH"
    assert body["nextCursor"] is None


def test_status_equals_the_rule_preview_for_the_same_account(api: Api) -> None:
    category = api.category("owner")
    other = api.category("owner", name="Outra")
    account = api.account("owner")
    for description in ("padaria a", "mercado b", "cinema c", "padaria d"):
        api.entry("owner", account, "expense", "10.00", description=description)
    _create_rule(api, "owner", category, "padaria", priority=5)
    _create_rule(api, "owner", category, "mercado", priority=5)
    _create_rule(api, "owner", other, "mercado", priority=5)

    preview = {
        item["movementId"]: item
        for item in _preview(api, "owner", account).json()["items"]
    }
    inbox = {item["movementId"]: item for item in _items(_pending(api, "owner"))}
    assert set(inbox) == set(preview)
    for movement_id, item in inbox.items():
        assert item["ruleStatus"] == preview[movement_id]["status"]
        assert item["matchedRuleId"] == preview[movement_id]["ruleId"]
        assert item["suggestedCategoryId"] == preview[movement_id]["targetCategoryId"]


def test_disabled_rule_or_category_changes_the_derived_result(
    pg_env: PgEnv, api: Api
) -> None:
    category = api.category("owner")
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "9.00", description="Padaria")
    _create_rule(api, "owner", category, "padaria")

    def status() -> str:
        (item,) = _items(_pending(api, "owner"))
        assert item["movementId"] == str(movement)
        return str(item["ruleStatus"])

    assert status() == "MATCHED"
    with pg_env.owner_engine.begin() as connection:
        connection.execute(
            update(financial_categories)
            .where(financial_categories.c.id == category)
            .values(
                status="DISABLED",
                disabled_at=func.transaction_timestamp(),
                updated_at=func.transaction_timestamp(),
            )
        )
    assert status() == "NO_MATCH"  # the rule's target is no longer usable

    live = api.category("owner", name="Viva")
    second = _create_rule(api, "owner", live, "padaria")
    assert status() == "MATCHED"
    disabled = api.post("owner", f"/categorization-rules/{second}/disable", {})
    assert disabled.status_code == 200
    assert status() == "NO_MATCH"


# --- authorization -------------------------------------------------------------


def test_read_only_visibility_and_isolation(api: Api) -> None:
    category = api.category("owner")
    personal = api.account("owner")
    household = api.account("owner", scope="HOUSEHOLD")
    api.entry("owner", personal, "expense", "1.00", description="Privado")
    shared = api.entry("owner", household, "expense", "2.00", description="Da casa")
    own = api.account("member", scope="HOUSEHOLD")
    mine = api.entry("member", own, "expense", "3.00", description="Do membro")
    _create_rule(api, "owner", category, "casa")

    member_items = {i["movementId"]: i for i in _items(_pending(api, "member"))}
    assert set(member_items) == {str(shared), str(mine)}
    assert member_items[str(shared)]["canClassify"] is False
    assert member_items[str(mine)]["canClassify"] is True
    owner_items = _items(_pending(api, "owner"))
    assert len(owner_items) == 3
    for item in owner_items:
        assert item["canClassify"] is (item["accountId"] != str(own))


def test_other_residences_and_unknown_accounts_are_invisible(
    api: Api, other_household: Household
) -> None:
    mine = api.account("owner")
    api.entry("owner", mine, "expense", "1.00", description="Meu")
    api.login("outsider", other_household.owner_id, other_household.residence_id)
    theirs = api.account("outsider")
    outsider_movement = api.entry(
        "outsider", theirs, "expense", "2.00", description="Deles"
    )

    assert _ids(_pending(api, "outsider")) == [str(outsider_movement)]
    assert str(outsider_movement) not in _ids(_pending(api, "owner"))
    for who, account in (("outsider", mine), ("owner", theirs), ("owner", uuid4())):
        response = _pending(api, who, accountId=str(account))
        _clean(response, 404, "financial resource was not found")


def test_requires_authentication(api: Api) -> None:
    response = api.client.get("/api/v1/finance/pending-movements")
    assert response.status_code == 401
    forged = api.client.get(
        "/api/v1/finance/pending-movements",
        headers={"Authorization": "Bearer not-a-session"},
    )
    assert forged.status_code == 401


def test_the_inbox_is_read_only_over_http(api: Api) -> None:
    for method in ("post", "put", "patch", "delete"):
        response = getattr(api.client, method)(
            "/api/v1/finance/pending-movements", headers=api._headers("owner")
        )
        assert response.status_code == 405, method
    paths = api.client.get("/api/v1/openapi.json").json()["paths"]
    assert set(paths["/api/v1/finance/pending-movements"]) == {"get"}
    assert [p for p in paths if "pending" in p] == ["/api/v1/finance/pending-movements"]


# --- filters, cursor, bounds ---------------------------------------------------


def test_filters_and_cursor_through_http(api: Api) -> None:
    category = api.category("owner")
    first = api.account("owner")
    second = api.account("owner")
    expense_a = api.entry("owner", first, "expense", "1.00", description="Padaria A")
    income_a = api.entry("owner", first, "income", "2.00", description="Padaria B")
    expense_b = api.entry("owner", second, "expense", "3.00", description="Cinema")
    _create_rule(api, "owner", category, "padaria")

    assert set(_ids(_pending(api, "owner", accountId=str(first)))) == {
        str(expense_a),
        str(income_a),
    }
    assert _ids(_pending(api, "owner", accountId=str(second))) == [str(expense_b)]
    assert _ids(_pending(api, "owner", resultEffect="INCOME")) == [str(income_a)]
    assert set(_ids(_pending(api, "owner", resultEffect="EXPENSE"))) == {
        str(expense_a),
        str(expense_b),
    }
    assert set(_ids(_pending(api, "owner", ruleStatus="MATCHED"))) == {
        str(expense_a),
        str(income_a),
    }
    assert _ids(_pending(api, "owner", ruleStatus="NO_MATCH")) == [str(expense_b)]
    assert _ids(_pending(api, "owner", ruleStatus="AMBIGUOUS")) == []
    combined = _pending(
        api,
        "owner",
        accountId=str(first),
        resultEffect="EXPENSE",
        ruleStatus="MATCHED",
    )
    assert _ids(combined) == [str(expense_a)]

    page = _pending(api, "owner", limit=1).json()
    assert len(page["items"]) == 1 and page["nextCursor"]
    cursor = page["nextCursor"]
    for other in (
        {"ruleStatus": "MATCHED"},
        {"accountId": str(first)},
        {"resultEffect": "EXPENSE"},
    ):
        _clean(
            _pending(api, "owner", limit=1, cursor=cursor, **other),
            422,
            "invalid financial request",
        )


def test_keyset_pagination_over_http_never_repeats_or_skips(api: Api) -> None:
    category = api.category("owner")
    account = api.account("owner")
    expected: set[str] = set()
    for index in range(23):
        movement = api.entry(
            "owner",
            account,
            "expense" if index % 3 else "income",
            f"{index + 1}.00",
            description="Padaria" if index % 2 else "Cinema",
        )
        expected.add(str(movement))
    _create_rule(api, "owner", category, "padaria")

    everything = _walk(api, "owner", limit=100)
    assert {item["movementId"] for item in everything} == expected
    for params in ({}, {"ruleStatus": "MATCHED"}, {"ruleStatus": "NO_MATCH"}):
        seen = _walk(api, "owner", limit=4, **params)
        ids = [item["movementId"] for item in seen]
        assert len(ids) == len(set(ids))
        want = {
            item["movementId"]
            for item in everything
            if "ruleStatus" not in params or item["ruleStatus"] == params["ruleStatus"]
        }
        assert set(ids) == want
        dates = [item["effectiveDate"] for item in seen]
        assert dates == sorted(dates, reverse=True)


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": "abc"},
        {"resultEffect": "NEUTRAL"},
        {"resultEffect": "income"},
        {"ruleStatus": "ALREADY_CLASSIFIED"},
        {"ruleStatus": "INELIGIBLE"},
        {"accountId": "not-a-uuid"},
        {"accountId": "00000000-0000-1000-8000-000000000000"},
        {"cursor": "garbage"},
        {"cursor": "a" * 300},
        {"offset": 10},
        {"page": 2},
        {"search": "padaria"},
    ],
)
def test_bad_parameters_are_rejected_without_leaks(
    api: Api, params: dict[str, Any]
) -> None:
    api.entry("owner", api.account("owner"), "expense", "1.00")
    response = _pending(api, "owner", **params)
    _clean(response, 422, "invalid financial request")


def test_default_limit_and_page_bound(api: Api) -> None:
    account = api.account("owner", opening=None)
    for _ in range(3):
        api.entry("owner", account, "expense", "1.00")
    assert len(_items(_pending(api, "owner", limit=100))) == 3
    assert len(_items(_pending(api, "owner"))) == 3


# --- bounded cost --------------------------------------------------------------


def _statements_for(pg_env: PgEnv, call: Any) -> int:
    counter = [0]

    def count(*_args: Any) -> None:
        counter[0] += 1

    event.listen(pg_env.runtime_engine, "before_cursor_execute", count)
    try:
        response = call()
    finally:
        event.remove(pg_env.runtime_engine, "before_cursor_execute", count)
    assert response.status_code == 200, response.text
    return counter[0]


def test_statement_count_is_constant_and_has_no_per_row_queries(
    pg_env: PgEnv, api: Api
) -> None:
    category = api.category("owner")
    accounts = [api.account("owner") for _ in range(3)]
    _create_rule(api, "owner", category, "padaria")
    for rule_index in range(3):
        _create_rule(api, "owner", category, f"outro{rule_index}")

    def run(**params: Any) -> int:
        return _statements_for(pg_env, lambda: _pending(api, "owner", **params))

    empty = run(limit=100)
    api.entry("owner", accounts[0], "expense", "1.00", description="padaria")
    one = run(limit=100)
    for index in range(36):
        api.entry(
            "owner",
            accounts[index % 3],
            "expense",
            "1.00",
            description="padaria" if index % 2 else "cinema",
        )
    many = run(limit=100)
    small_page = run(limit=2)
    # rules (3) + categories (3) + one page read (3): nothing scales with rows,
    # accounts, allocations, rules or categories.
    assert empty == one == many == small_page == 9

    filtered = run(limit=5, ruleStatus="NO_MATCH")
    assert filtered <= 6 + 3 * 5  # fixed scan budget, never per row
    assert run(limit=100, accountId=str(accounts[0])) == 10  # + account existence


# --- concurrency: the canonical state always wins -------------------------------


def test_manual_classification_between_listing_and_apply_never_recreates(
    pg_env: PgEnv, api: Api
) -> None:
    category = api.category("owner")
    other = api.category("owner", name="Outra")
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "10.00", description="Padaria")
    rule = _create_rule(api, "owner", category, "padaria")

    (listed,) = _items(_pending(api, "owner"))
    assert listed["ruleStatus"] == "MATCHED" and listed["matchedRuleId"] == rule

    # A manual classification lands after the listing and before the action.
    assert api.classify("owner", movement, [(other, "-10.00")]).status_code == 201

    applied = _apply(api, "owner", account, [(movement, rule)]).json()
    assert applied["results"][0]["status"] == "ALREADY_CLASSIFIED"
    assert applied["counts"]["classified"] == 0
    # The next read drops the item and nothing was recreated or revised.
    assert _items(_pending(api, "owner")) == []
    assert _set_count(pg_env, movement) == 1
    current = api.current("owner", movement).json()["allocation"]
    assert current["allocations"][0]["categoryId"] == str(other)


def test_rule_disabled_before_apply_changes_the_result_and_writes_nothing(
    pg_env: PgEnv, api: Api
) -> None:
    category = api.category("owner")
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "10.00", description="Padaria")
    rule = _create_rule(api, "owner", category, "padaria")
    assert _items(_pending(api, "owner"))[0]["ruleStatus"] == "MATCHED"

    disabled = api.post("owner", f"/categorization-rules/{rule}/disable", {})
    assert disabled.status_code == 200
    applied = _apply(api, "owner", account, [(movement, rule)]).json()
    assert applied["results"][0]["status"] == "NO_MATCH"
    assert applied["counts"]["classified"] == 0
    (item,) = _items(_pending(api, "owner"))
    assert item["ruleStatus"] == "NO_MATCH" and item["matchedRuleId"] is None
    assert _set_count(pg_env, movement) == 0


def test_a_stronger_rule_before_apply_is_a_conflict_and_canonical_wins(
    pg_env: PgEnv, api: Api
) -> None:
    category = api.category("owner")
    stronger_category = api.category("owner", name="Forte")
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "10.00", description="Padaria")
    old = _create_rule(api, "owner", category, "padaria", priority=5)
    assert _items(_pending(api, "owner"))[0]["matchedRuleId"] == old

    newer = _create_rule(api, "owner", stronger_category, "padaria", priority=9)
    applied = _apply(api, "owner", account, [(movement, old)]).json()
    assert applied["results"][0]["status"] == "CONFLICT"
    assert _set_count(pg_env, movement) == 0
    (item,) = _items(_pending(api, "owner"))
    assert item["ruleStatus"] == "MATCHED" and item["matchedRuleId"] == newer
    assert item["suggestedCategoryId"] == str(stronger_category)

    # An equal rule now ties: AMBIGUOUS, no rule, nothing applicable.
    twin = _create_rule(api, "owner", category, "padaria", priority=9)
    (item,) = _items(_pending(api, "owner"))
    assert item["ruleStatus"] == "AMBIGUOUS" and item["matchedRuleId"] is None
    tied = _apply(api, "owner", account, [(movement, twin)]).json()
    assert tied["results"][0]["status"] == "AMBIGUOUS"
    assert _set_count(pg_env, movement) == 0


def test_concurrent_apply_and_manual_classification_leave_exactly_one_set(
    pg_env: PgEnv, api: Api
) -> None:
    category = api.category("owner")
    other = api.category("owner", name="Outra")
    account = api.account("owner")
    rule = _create_rule(api, "owner", category, "padaria")
    movements = [
        api.entry("owner", account, "expense", "10.00", description=f"padaria {i}")
        for i in range(6)
    ]
    barrier = Barrier(2)

    def apply_all() -> int:
        barrier.wait()
        response = _apply(api, "owner", account, [(m, rule) for m in movements])
        assert response.status_code == 200, response.text
        return int(response.json()["counts"]["classified"])

    def classify_all() -> int:
        barrier.wait()
        created = 0
        for movement in movements:
            response = api.classify("owner", movement, [(other, "-10.00")])
            assert response.status_code in (201, 409), response.text
            created += response.status_code == 201
        return created

    with ThreadPoolExecutor(max_workers=2) as pool:
        by_rule = pool.submit(apply_all)
        by_hand = pool.submit(classify_all)
        classified_by_rule, classified_by_hand = by_rule.result(), by_hand.result()

    # Every Movement has exactly one winner and the two writers never overlap.
    assert classified_by_rule + classified_by_hand == len(movements)
    for movement in movements:
        assert _set_count(pg_env, movement) == 1
    assert _items(_pending(api, "owner")) == []


def test_reads_do_not_block_or_alter_concurrent_writes(pg_env: PgEnv, api: Api) -> None:
    category = api.category("owner")
    account = api.account("owner")
    movements = [
        api.entry("owner", account, "expense", "5.00", description=f"item {i}")
        for i in range(8)
    ]
    barrier = Barrier(3)

    def writer() -> int:
        barrier.wait()
        done = 0
        for movement in movements:
            done += (
                api.classify("owner", movement, [(category, "-5.00")]).status_code
                == 201
            )
        return done

    def reader() -> int:
        barrier.wait()
        pages = 0
        for _ in range(15):
            response = _pending(api, "owner", limit=3)
            assert response.status_code == 200, response.text
            pages += 1
        return pages

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(writer), pool.submit(reader), pool.submit(reader)]
        results = [future.result() for future in futures]
    assert results == [len(movements), 15, 15]
    assert _items(_pending(api, "owner")) == []


# --- vertical smoke from the issue ----------------------------------------------


def test_vertical_smoke_from_inbox_to_empty_with_the_ledger_untouched(
    pg_env: PgEnv, api: Api
) -> None:
    mercado = api.category("owner", "HOUSEHOLD", "Mercado")
    lazer = api.category("owner", "HOUSEHOLD", "Lazer")
    outros = api.category("owner", "HOUSEHOLD", "Outros")
    account = api.account("owner")
    destination = api.account("owner")
    residence = _residence_of(api)

    unique_rule = _create_rule(api, "owner", mercado, "Padaria", priority=5)
    _create_rule(api, "owner", lazer, "Cinema", priority=5)
    _create_rule(api, "owner", outros, "Cinema", priority=5)

    matched = api.entry("owner", account, "expense", "37.45", description="Padaria Pão")
    ambiguous = api.entry("owner", account, "expense", "12.00", description="Cinema")
    no_match = api.entry("owner", account, "expense", "99.90", description="Oficina")
    _transfer(api, "owner", account, destination)  # NEUTRAL legs: never listed

    def snapshot() -> tuple[Any, ...]:
        return (
            _economic_snapshot(api, "owner", account),
            _economic_snapshot(api, "owner", destination),
            _ledger_rows(pg_env, residence),
        )

    before = snapshot()

    items = {item["movementId"]: item for item in _items(_pending(api, "owner"))}
    assert set(items) == {str(matched), str(ambiguous), str(no_match)}
    assert items[str(matched)]["ruleStatus"] == "MATCHED"
    assert items[str(matched)]["matchedRuleId"] == unique_rule
    assert items[str(matched)]["suggestedCategoryId"] == str(mercado)
    assert items[str(ambiguous)]["ruleStatus"] == "AMBIGUOUS"
    assert items[str(no_match)]["ruleStatus"] == "NO_MATCH"
    assert all(item["canClassify"] for item in items.values())
    assert snapshot() == before

    # 1. Apply the MATCHED suggestion explicitly (the #247 endpoint).
    applied = _apply(api, "owner", account, [(matched, unique_rule)]).json()
    assert applied["counts"]["classified"] == 1
    assert set(_ids(_pending(api, "owner"))) == {str(ambiguous), str(no_match)}

    # 2. The AMBIGUOUS one is resolved manually (the #245 endpoint).
    assert api.classify("owner", ambiguous, [(lazer, "-12.00")]).status_code == 201
    assert _ids(_pending(api, "owner")) == [str(no_match)]

    # 3. So is the NO_MATCH one: the inbox ends empty.
    assert api.classify("owner", no_match, [(outros, "-99.90")]).status_code == 201
    final = _pending(api, "owner")
    assert _items(final) == [] and final.json()["nextCursor"] is None

    # The ledger, balances and statements are exactly what they were.
    assert snapshot() == before
    assert _set_count(pg_env, matched) == 1
    assert _set_count(pg_env, ambiguous) == 1
    assert _set_count(pg_env, no_match) == 1
    assert _audit_events(pg_env, residence, "ALLOCATION_SET_CREATED") == 3


def test_the_inbox_persists_no_pending_state(pg_env: PgEnv, api: Api) -> None:
    account = api.account("owner")
    api.entry("owner", account, "expense", "1.00", description="Qualquer")
    with pg_env.owner_engine.connect() as connection:
        tables = {
            row.table_name
            for row in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'finance'"
                )
            )
        }
        movement_columns = {
            row.column_name
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'finance' AND table_name = 'movements'"
                )
            )
        }
    assert not {name for name in tables if "pending" in name or "inbox" in name}
    for column in movement_columns:
        for forbidden in ("pending", "inbox", "reviewed", "category", "dismiss"):
            assert forbidden not in column, column
    assert len(_items(_pending(api, "owner"))) == 1


def test_runtime_is_unprivileged_and_rls_is_forced_on_every_inbox_source(
    pg_env: PgEnv, api: Api
) -> None:
    with pg_env.runtime_engine.connect() as connection:
        superuser, bypass = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname = current_user"
            )
        ).one()
    assert superuser is False and bypass is False
    sources = {
        "movements",
        "accounts",
        "movement_allocation_sets",
        "categorization_rules",
        "categories",
    }
    with pg_env.owner_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'finance' AND c.relname = ANY(:names)
                """
            ),
            {"names": sorted(sources)},
        ).all()
    assert {row[0] for row in rows} == sources
    assert all(row[1] and row[2] for row in rows), rows
    # The runtime role has no way to write a pending state: it only reads here.
    with pg_env.runtime_engine.connect() as connection:
        can_insert_into_movements_pending = connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = 'finance' AND table_name = 'movements' "
                "AND column_name ILIKE '%pending%'"
            )
        )
    assert can_insert_into_movements_pending == 0
