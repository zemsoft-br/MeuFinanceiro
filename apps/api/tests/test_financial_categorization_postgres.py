"""PostgreSQL-backed end-to-end tests for deterministic categorization rules.

Every request crosses the real FastAPI routes, the real services and the real
stores under the non-superuser runtime role with forced RLS, so preview/apply,
provenance, replay and concurrency are proven where they are enforced.

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
from meufinanceiro_persistence.financial_categorization_rule_schema import (
    financial_categorization_rules,
    financial_movement_allocation_rule_origins,
)
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
from sqlalchemy import Engine, create_engine, event, func, insert, select, update
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.main import create_app
from app.services.financial_categorization import FinancialCategorizationService
from app.services.financial_core import FinancialCoreService
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


# --- the vertical smoke from the issue --------------------------------------


def test_vertical_rule_flow_preview_apply_replay_manual_override_and_ambiguity(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    mercado = api.category("owner", "HOUSEHOLD", "Mercado")
    lazer = api.category("owner", "HOUSEHOLD", "Lazer")
    account = api.account("owner")
    rule_id = _create_rule(api, "owner", mercado, "Padaria")

    listed = api.get("owner", "/categorization-rules").json()["rules"]
    assert [item["ruleId"] for item in listed] == [rule_id]
    assert listed[0]["status"] == "ACTIVE" and listed[0]["priority"] == 10

    movement = api.entry(
        "owner", account, "expense", "37.45", description="PADARIA Pão Quente"
    )
    before = _economic_snapshot(api, "owner", account)

    preview = _preview(api, "owner", account)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["counts"]["matched"] == 1 and body["totalMovements"] == 1
    assert body["items"] == [
        {
            "movementId": str(movement),
            "status": "MATCHED",
            "ruleId": rule_id,
            "targetCategoryId": str(mercado),
        }
    ]
    # Preview writes nothing at all.
    assert api.current("owner", movement).json() == {"allocation": None}
    assert (
        _table_count(pg_env, financial_movement_allocation_sets, household.residence_id)
        == 0
    )
    assert _economic_snapshot(api, "owner", account) == before

    applied = _apply(api, "owner", account, [(movement, rule_id)])
    assert applied.status_code == 200, applied.text
    assert applied.json()["counts"]["classified"] == 1
    result = applied.json()["results"][0]
    assert result["status"] == "CLASSIFIED" and result["ruleId"] == rule_id

    current = api.current("owner", movement).json()["allocation"]
    assert current["revision"] == 1 and current["supersedesId"] is None
    assert current["allocationSetId"] == result["allocationSetId"]
    assert current["allocations"] == [
        {"categoryId": str(mercado), "money": {"amount": "-37.45", "currency": "BRL"}}
    ]
    assert [
        (o["movementId"], o["allocationSetId"], o["ruleId"])
        for o in _origins(api, "owner", account)
    ] == [(str(movement), current["allocationSetId"], rule_id)]
    assert _economic_snapshot(api, "owner", account) == before
    assert _audit_events(pg_env, household.residence_id, "ALLOCATION_SET_CREATED") == 1

    # Replay: nothing new is created.
    again = _apply(api, "owner", account, [(movement, rule_id)])
    assert again.status_code == 200
    assert again.json()["counts"]["alreadyClassified"] == 1
    assert again.json()["counts"]["classified"] == 0
    assert _set_count(pg_env, movement) == 1

    # Manual override through the #245 flow stays current and drops the origin.
    revision = api.revise(
        "owner", movement, current["allocationSetId"], [(lazer, "-37.45")]
    )
    assert revision.status_code == 201, revision.text
    assert _origins(api, "owner", account) == []
    after_manual = _apply(api, "owner", account, [(movement, rule_id)])
    assert after_manual.json()["counts"]["alreadyClassified"] == 1
    assert api.current("owner", movement).json()["allocation"]["revision"] == 2
    assert _set_count(pg_env, movement) == 2
    assert _preview(api, "owner", account).json()["counts"]["alreadyClassified"] == 1

    # Tied rules on another Movement are AMBIGUOUS everywhere and never write.
    tied = api.entry("owner", account, "expense", "12.00", description="Cinema Sábado")
    first = _create_rule(api, "owner", mercado, "Cinema", priority=5)
    _create_rule(api, "owner", lazer, "Cinema", priority=5)
    preview = _preview(api, "owner", account).json()
    assert preview["counts"]["ambiguous"] == 1
    ambiguous = next(i for i in preview["items"] if i["movementId"] == str(tied))
    assert ambiguous["status"] == "AMBIGUOUS" and ambiguous["ruleId"] is None
    outcome = _apply(api, "owner", account, [(tied, first)])
    assert outcome.json()["results"][0]["status"] == "AMBIGUOUS"
    assert outcome.json()["counts"]["classified"] == 0
    assert api.current("owner", tied).json() == {"allocation": None}
    assert _set_count(pg_env, tied) == 0


# --- contract: lifecycle, validation, authorization -----------------------


def test_create_replay_conflict_disable_and_no_semantic_verbs(api: Api) -> None:
    category = api.category("owner")
    key = uuid4()
    body = _rule_body(category, "Mercado", key=key)
    first = api.post("owner", "/categorization-rules", body)
    assert first.status_code == 201
    replay = api.post("owner", "/categorization-rules", body)
    assert replay.status_code == 201 and replay.json() == first.json()
    changed = api.post("owner", "/categorization-rules", {**body, "priority": 11})
    _clean(changed, 409, "financial operation conflicts with canonical state")

    rule_id = first.json()["ruleId"]
    disabled = api.post("owner", f"/categorization-rules/{rule_id}/disable", {})
    assert disabled.status_code == 200 and disabled.json()["status"] == "DISABLED"
    assert disabled.json()["disabledAt"] is not None
    assert disabled.json()["descriptionPattern"] == "Mercado"
    again = api.post("owner", f"/categorization-rules/{rule_id}/disable", {})
    assert again.status_code == 200 and again.json() == disabled.json()

    headers = api._headers("owner")
    for path in (
        f"/api/v1/finance/categorization-rules/{rule_id}",
        "/api/v1/finance/categorization-rules",
    ):
        for verb in (api.client.put, api.client.patch, api.client.delete):
            assert verb(path, headers=headers).status_code in (404, 405)


@pytest.mark.parametrize(
    "override",
    [
        {"descriptionMatcher": "REGEX"},
        {"descriptionMatcher": "exact"},
        {"descriptionPattern": "   "},
        {"descriptionPattern": "x" * 257},
        {"descriptionPattern": "a\nb"},
        {"priority": 0},
        {"priority": 1001},
        {"priority": True},
        {"priority": 1.5},
        {"priority": "10"},
        {"resultEffect": "NEUTRAL"},
        {"resultEffect": "income"},
        {"idempotencyKey": "not-a-uuid"},
        {"idempotencyKey": "00000000-0000-0000-0000-000000000000"},
        {"amountMin": "10"},
        {"merchant": "x"},
        {"regex": ".*"},
    ],
)
def test_rule_creation_rejects_anything_outside_the_v1_contract(
    api: Api, override: dict[str, Any]
) -> None:
    category = api.category("owner")
    response = api.post(
        "owner", "/categorization-rules", {**_rule_body(category), **override}
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] in {
        "invalid financial request",
        "invalid financial categorization request",
    }
    for leak in _LEAKS:
        assert leak not in response.text


def test_rule_creation_targets_are_fail_closed_and_sanitized(
    api: Api, other_household: Household
) -> None:
    api.login("stranger", other_household.owner_id, other_household.residence_id)
    foreign_category = api.category("stranger")
    member_private = api.category("member", "PERSONAL", "Dele")
    household_account = api.account("owner", scope="HOUSEHOLD")
    owner_private = api.category("owner", "PERSONAL", "Meu")
    member_account = api.account("member")

    for category in (foreign_category, member_private, uuid4()):
        response = api.post("owner", "/categorization-rules", _rule_body(category))
        _clean(response, 404, "financial category was not found")
    mismatch = api.post(
        "owner",
        "/categorization-rules",
        _rule_body(owner_private, account=household_account),
    )
    _clean(mismatch, 404, "financial category was not found")
    other_owner_account = api.post(
        "owner",
        "/categorization-rules",
        _rule_body(api.category("owner"), account=member_account),
    )
    _clean(other_owner_account, 404, "financial resource was not found")


def test_rules_are_residence_scoped_and_only_the_creator_disables(
    api: Api, other_household: Household
) -> None:
    api.login("stranger", other_household.owner_id, other_household.residence_id)
    category = api.category("owner")
    rule_id = _create_rule(api, "owner", category)

    assert api.get("stranger", "/categorization-rules").json() == {"rules": []}
    member_rules = api.get("member", "/categorization-rules").json()["rules"]
    assert [r["ruleId"] for r in member_rules] == [rule_id]
    for who in ("stranger", "member"):
        _clean(
            api.post(who, f"/categorization-rules/{rule_id}/disable", {}),
            404,
            "financial resource was not found",
        )
    _clean(
        api.post("owner", f"/categorization-rules/{uuid4()}/disable", {}),
        404,
        "financial resource was not found",
    )
    owner_rules = api.get("owner", "/categorization-rules").json()["rules"]
    assert owner_rules[0]["status"] == "ACTIVE"


def test_only_the_account_owner_can_preview_apply_and_foreigners_cannot_read(
    api: Api, other_household: Household
) -> None:
    api.login("stranger", other_household.owner_id, other_household.residence_id)
    category = api.category("owner")
    rule_id = _create_rule(api, "owner", category)
    account = api.account("owner", scope="HOUSEHOLD")
    movement = api.entry("owner", account, "expense", "10.00", description="padaria")

    for who in ("member", "stranger"):
        _clean(_preview(api, who, account), 404, "financial resource was not found")
        _clean(
            _apply(api, who, account, [(movement, rule_id)]),
            404,
            "financial resource was not found",
        )
    # Reading provenance is read-only and follows the account audience.
    origins_path = f"/accounts/{account}/categorization-rules/origins"
    assert api.get("member", origins_path).status_code == 200
    _clean(api.get("stranger", origins_path), 404, "financial resource was not found")
    assert api.current("owner", movement).json() == {"allocation": None}


def test_malformed_requests_and_query_params_are_rejected_without_leaks(
    api: Api,
) -> None:
    account = api.account("owner")
    pair = {"movementId": str(uuid4()), "ruleId": str(uuid4())}
    too_many = [
        {"movementId": str(uuid4()), "ruleId": str(uuid4())} for _ in range(201)
    ]
    for body in (
        {},
        {"items": []},
        {"items": [pair, pair]},
        {"items": [{"movementId": "x", "ruleId": str(uuid4())}]},
        {"items": [pair], "extra": 1},
        {"items": [{**pair, "extra": 1}]},
        {"items": [{**pair, "ruleId": "00000000-0000-0000-0000-000000000000"}]},
        {"items": too_many},
    ):
        response = api.post(
            "owner", f"/accounts/{account}/categorization-rules/apply", body
        )
        assert response.status_code == 422, (body, response.text)
        for leak in _LEAKS:
            assert leak not in response.text
    for path in (
        "/categorization-rules?x=1",
        f"/accounts/{account}/categorization-rules/origins?x=1",
    ):
        assert api.get("owner", path).status_code == 422
    preview = api.post(
        "owner", f"/accounts/{account}/categorization-rules/preview?x=1", {}
    )
    assert preview.status_code == 422


# --- behaviour --------------------------------------------------------------


def test_priority_tie_stale_confirmation_and_disabled_rule_fail_closed(
    pg_env: PgEnv, api: Api
) -> None:
    low_cat = api.category("owner", name="Baixa")
    high_cat = api.category("owner", name="Alta")
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "9.90", description="Padaria 24h")
    low = _create_rule(api, "owner", low_cat, "padaria", priority=1)
    high = _create_rule(api, "owner", high_cat, "padaria", priority=9)

    assert _preview(api, "owner", account).json()["items"][0]["ruleId"] == high

    # The operator confirmed the lower-priority rule: not what canonical state says.
    stale = _apply(api, "owner", account, [(movement, low)]).json()
    assert stale["results"][0]["status"] == "CONFLICT"
    assert _set_count(pg_env, movement) == 0

    # After `high` is disabled the canonical winner is `low`: confirming the
    # disabled rule is a CONFLICT, confirming the real winner classifies.
    api.post("owner", f"/categorization-rules/{high}/disable", {})
    assert _preview(api, "owner", account).json()["items"][0]["ruleId"] == low
    stale_disabled = _apply(api, "owner", account, [(movement, high)]).json()
    assert stale_disabled["results"][0]["status"] == "CONFLICT"
    assert _set_count(pg_env, movement) == 0
    done = _apply(api, "owner", account, [(movement, low)]).json()
    assert done["results"][0]["status"] == "CLASSIFIED"
    allocation = api.current("owner", movement).json()["allocation"]
    assert allocation["allocations"][0]["categoryId"] == str(low_cat)


def test_unusable_target_category_never_classifies(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    category = api.category("owner", name="Vai desligar")
    account = api.account("owner")
    movement = api.entry("owner", account, "expense", "9.90", description="padaria")
    rule = _create_rule(api, "owner", category, "padaria")
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
    counts = _preview(api, "owner", account).json()["counts"]
    assert counts["noMatch"] == 1 and counts["matched"] == 0
    applied = _apply(api, "owner", account, [(movement, rule)]).json()
    assert applied["results"][0]["status"] == "NO_MATCH"
    assert _set_count(pg_env, movement) == 0
    assert (
        _table_count(
            pg_env, financial_movement_allocation_rule_origins, household.residence_id
        )
        == 0
    )


def test_neutral_reversal_and_income_expense_filters(pg_env: PgEnv, api: Api) -> None:
    category = api.category("owner")
    income_category = api.category("owner", name="Receita")
    account = api.account("owner")
    other_account = api.account("owner")
    expense = api.entry("owner", account, "expense", "20.00", description="Padaria X")
    income = api.entry("owner", account, "income", "20.00", description="Padaria Y")
    reversed_id = api.entry(
        "owner", account, "expense", "5.00", description="Padaria Z"
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
    transfer = api.post(
        "owner",
        "/transfers",
        {
            "idempotencyKey": str(uuid4()),
            "sourceAccountId": str(account),
            "destinationAccountId": str(other_account),
            "amount": "10.00",
            "currency": "BRL",
            "effectiveDate": "2026-09-21",
            "competenceDate": "2026-09-21",
            "description": "Padaria transferência",
        },
    )
    assert transfer.status_code == 201, transfer.text

    expense_rule = _create_rule(
        api, "owner", category, "padaria", effect="EXPENSE", priority=5
    )
    income_rule = _create_rule(
        api, "owner", income_category, "padaria", effect="INCOME", priority=5
    )
    preview = _preview(api, "owner", account).json()
    # expense, income, reversed original => 3 matched; reversal + neutral leg => 2.
    assert preview["counts"]["matched"] == 3
    assert preview["counts"]["ineligible"] == 2
    by_movement = {i["movementId"]: i for i in preview["items"]}
    assert by_movement[str(expense)]["ruleId"] == expense_rule
    assert by_movement[str(income)]["ruleId"] == income_rule

    applied = _apply(
        api, "owner", account, [(expense, expense_rule), (income, income_rule)]
    ).json()
    assert applied["counts"]["classified"] == 2
    expense_alloc = api.current("owner", expense).json()["allocation"]
    income_alloc = api.current("owner", income).json()["allocation"]
    assert expense_alloc["allocations"][0]["money"]["amount"] == "-20"
    assert income_alloc["allocations"][0]["money"]["amount"] == "20"


def test_preview_statement_count_does_not_grow_with_movement_count(
    pg_env: PgEnv, api: Api
) -> None:
    category = api.category("owner")
    few = api.account("owner")
    many = api.account("owner")
    _create_rule(api, "owner", category, "padaria")
    for _ in range(2):
        api.entry("owner", few, "expense", "10.00", description="padaria")
    for _ in range(14):
        api.entry("owner", many, "expense", "10.00", description="padaria")

    statements: list[str] = []

    def count(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(pg_env.runtime_engine, "before_cursor_execute", count)
    try:
        small = _preview(api, "owner", few)
        small_count, statements[:] = len(statements), []
        large = _preview(api, "owner", many)
        large_count = len(statements)
        statements.clear()
        origins = api.get("owner", f"/accounts/{many}/categorization-rules/origins")
        origins_count = len(statements)
    finally:
        event.remove(pg_env.runtime_engine, "before_cursor_execute", count)

    assert small.json()["counts"]["matched"] == 2
    assert large.json()["counts"]["matched"] == 14
    assert small_count == large_count  # not proportional to Movement count
    assert origins.status_code == 200 and origins_count <= 6


def test_partial_outcomes_are_reported_per_movement(pg_env: PgEnv, api: Api) -> None:
    category, other = api.category("owner"), api.category("owner")
    account = api.account("owner")
    rule = _create_rule(api, "owner", category, "padaria")
    fresh = api.entry("owner", account, "expense", "10.00", description="padaria 1")
    manual = api.entry("owner", account, "expense", "10.00", description="padaria 2")
    nomatch = api.entry("owner", account, "expense", "10.00", description="cinema")
    assert api.classify("owner", manual, [(other, "-10.00")]).status_code == 201

    result = _apply(
        api,
        "owner",
        account,
        [(fresh, rule), (manual, rule), (nomatch, rule), (uuid4(), rule)],
    ).json()
    assert [r["status"] for r in result["results"]] == [
        "CLASSIFIED",
        "ALREADY_CLASSIFIED",
        "NO_MATCH",
        "INELIGIBLE",
    ]
    assert result["requested"] == 4 and result["counts"]["classified"] == 1
    assert api.current("owner", manual).json()["allocation"]["revision"] == 1
    assert _set_count(pg_env, manual) == 1


def test_concurrent_apply_requests_never_double_classify(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    category = api.category("owner")
    account = api.account("owner")
    rule = _create_rule(api, "owner", category, "padaria")
    movements = [
        api.entry("owner", account, "expense", "10.00", description=f"padaria {i}")
        for i in range(6)
    ]
    pairs = [(m, rule) for m in movements]
    workers = 4
    barrier = Barrier(workers)

    def attempt(_: int) -> dict[str, Any]:
        barrier.wait()
        response = _apply(api, "owner", account, pairs)
        assert response.status_code == 200, response.text
        return dict(response.json()["counts"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        counts = list(pool.map(attempt, range(workers)))

    assert sum(c["classified"] for c in counts) == len(movements)
    assert sum(c["alreadyClassified"] for c in counts) == len(movements) * (workers - 1)
    for movement in movements:
        assert _set_count(pg_env, movement) == 1
    assert _table_count(
        pg_env, financial_movement_allocation_rule_origins, household.residence_id
    ) == len(movements)
    assert _audit_events(
        pg_env, household.residence_id, "ALLOCATION_SET_CREATED"
    ) == len(movements)


def test_apply_never_touches_the_ledger(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    category = api.category("owner")
    account = api.account("owner")
    rule = _create_rule(api, "owner", category, "padaria")
    movement = api.entry("owner", account, "expense", "10.00", description="padaria")
    ledger_before = _ledger_rows(pg_env, household.residence_id)
    assert _apply(api, "owner", account, [(movement, rule)]).status_code == 200
    assert _ledger_rows(pg_env, household.residence_id) == ledger_before


def test_rule_lifecycle_does_not_write_the_financial_audit(
    pg_env: PgEnv, household: Household, api: Api
) -> None:
    category = api.category("owner")
    with pg_env.owner_engine.connect() as connection:
        before = connection.scalar(
            select(func.count())
            .select_from(financial_audit_events)
            .where(financial_audit_events.c.residence_id == household.residence_id)
        )
    rule = _create_rule(api, "owner", category)
    api.post("owner", f"/categorization-rules/{rule}/disable", {})
    with pg_env.owner_engine.connect() as connection:
        after = connection.scalar(
            select(func.count())
            .select_from(financial_audit_events)
            .where(financial_audit_events.c.residence_id == household.residence_id)
        )
    assert after == before
    assert (
        _table_count(pg_env, financial_categorization_rules, household.residence_id)
        == 1
    )
