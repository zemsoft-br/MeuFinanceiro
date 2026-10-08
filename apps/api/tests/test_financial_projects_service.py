"""FastAPI project contract tests against the service boundary.

These are hermetic and never connect to PostgreSQL. Database RLS and racing
writes are covered by separate tests against PostgreSQL 18.4 (#262).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from meufinanceiro_finance import (
    FinancialMovementRecord,
    FinancialMovementRole,
    FinancialProjectDraft,
    FinancialProjectExpenseFact,
    FinancialProjectLinkRevisionRecord,
    FinancialProjectRecord,
    FinancialProjectReplacement,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
)
from meufinanceiro_persistence.financial_project_store import (
    FinancialProjectAccessError,
    FinancialProjectConflictError,
)

from app.api.auth import require_primary_residence
from app.api.routes.finance_projects import router
from app.services.financial_projects import FinancialProjectService

_NOW = datetime(2026, 10, 8, 17, tzinfo=UTC)
_INSTALLATION = uuid4()
_RESIDENCE = uuid4()
_OWNER = uuid4()
_MEMBER = uuid4()
_ACCOUNT = uuid4()


def _record() -> FinancialProjectRecord:
    return FinancialProjectRecord(
        id=uuid4(), residence_id=_RESIDENCE,
        owner_operator_id=_OWNER,
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        title="Reforma", description=None,
        planned=Money(Decimal("500"), "BRL"),
        target_date=None, version=1, created_at=_NOW, updated_at=_NOW,
    )


def _expense() -> FinancialMovementRecord:
    return FinancialMovementRecord(
        id=uuid4(), account_id=_ACCOUNT,
        amount=Money(Decimal("-125"), "BRL"),
        result_effect=FinancialResultEffect.EXPENSE,
        role=FinancialMovementRole.STANDARD,
        effective_date=date(2026, 10, 8),
        competence_date=date(2026, 10, 8),
        description="Material",
        reversal_of_id=None,
        reversal_reason=None,
        created_by_operator_id=_OWNER,
        created_at=_NOW,
    )


class _FakeStore:
    def __init__(self) -> None:
        self.project = _record()
        self.expense = _expense()
        self.link: FinancialProjectLinkRevisionRecord | None = None
        self.history: list[FinancialProjectLinkRevisionRecord] = []
        self.create_keys: dict[UUID, tuple[tuple[object, ...], UUID]] = {}
        self.denied = False

    def _check(self) -> None:
        if self.denied:
            raise FinancialProjectAccessError("denied")

    def create_project(self, **kwargs: object) -> FinancialProjectRecord:
        self._check()
        draft = kwargs["draft"]
        key = kwargs["idempotency_key"]
        assert isinstance(draft, FinancialProjectDraft)
        assert isinstance(key, UUID)
        previous = self.create_keys.get(key)
        if previous is not None:
            if previous[0] != draft.canonical_material():
                raise FinancialProjectConflictError("changed material")
            return self.project
        self.create_keys[key] = (draft.canonical_material(), self.project.id)
        return self.project

    def list_projects(self, **kwargs: object) -> tuple[FinancialProjectRecord, ...]:
        self._check()
        return (self.project,)

    def get_project(self, **kwargs: object) -> FinancialProjectRecord:
        self._check()
        return self.project

    def replace_project(self, **kwargs: object) -> FinancialProjectRecord:
        self._check()
        replacement = kwargs["replacement"]
        assert isinstance(replacement, FinancialProjectReplacement)
        if replacement.expected_version != self.project.version:
            raise FinancialProjectConflictError("stale")
        return self.project

    def revise_link(self, **kwargs: object) -> FinancialProjectLinkRevisionRecord:
        self._check()
        draft = kwargs["draft"]
        assert getattr(draft, "movement_id") == self.expense.id
        if self.link is None:
            revision = 1
            predecessor = None
        else:
            if getattr(draft, "expected_predecessor_id") != self.link.id:
                raise FinancialProjectConflictError("stale predecessor")
            revision = self.link.revision + 1
            predecessor = self.link.id
        self.link = FinancialProjectLinkRevisionRecord(
            id=uuid4(),
            movement_id=self.expense.id,
            project_id=getattr(draft, "project_id"),
            supersedes_id=predecessor,
            revision=revision,
            actor_operator_id=_OWNER,
            created_at=_NOW,
        )
        self.history.append(self.link)
        return self.link

    def get_link(self, **kwargs: object) -> FinancialProjectLinkRevisionRecord | None:
        self._check()
        return self.link

    def read_link_history(
        self, **kwargs: object
    ) -> tuple[FinancialProjectLinkRevisionRecord, ...]:
        self._check()
        return tuple(self.history)

    def read_project_facts(self, **kwargs: object):
        self._check()
        return (
            self.project,
            (FinancialProjectExpenseFact(self.project.id, self.expense),),
        )


def _client(store: _FakeStore, operator_id: UUID = _OWNER) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.financial_projects = FinancialProjectService(store)
    principal = SimpleNamespace(
        installation_id=_INSTALLATION,
        primary_residence_id=_RESIDENCE,
        operator_id=operator_id,
    )
    app.dependency_overrides[require_primary_residence] = lambda: SimpleNamespace(
        principal=principal
    )
    return TestClient(app, raise_server_exceptions=False)


def test_project_create_is_strict_replay_safe_and_monetary_strings() -> None:
    store = _FakeStore()
    client = _client(store)
    payload = {
        "idempotencyKey": str(uuid4()),
        "title": "Reforma",
        "description": None,
        "visibilityScope": "HOUSEHOLD",
        "currency": "BRL",
        "plannedAmount": "500.00",
        "targetDate": None,
    }
    first = client.post("/api/v1/finance/projects", json=payload)
    assert first.status_code == 201
    assert first.json()["planned"] == {"amount": "500", "currency": "BRL"}
    assert first.json()["canEdit"] is True
    assert client.post("/api/v1/finance/projects", json=payload).json() == first.json()
    changed = {**payload, "title": "Mudou"}
    assert client.post("/api/v1/finance/projects", json=changed).status_code == 409
    assert client.post(
        "/api/v1/finance/projects", json={**payload, "plannedAmount": 500.0}
    ).status_code == 422
    assert client.post(
        "/api/v1/finance/projects", json={**payload, "unexpected": True}
    ).status_code == 422
    assert client.post(
        "/api/v1/finance/projects", json={**payload, "plannedAmount": "-10"}
    ).status_code == 422
    assert client.get("/api/v1/finance/projects?bad=1").status_code == 422


def test_project_readonly_member_and_derived_summary() -> None:
    store = _FakeStore()
    client = _client(store, _MEMBER)
    response = client.get(f"/api/v1/finance/projects/{store.project.id}")
    assert response.status_code == 200
    assert response.json()["canEdit"] is False
    summary = client.get(f"/api/v1/finance/projects/{store.project.id}/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert data["project"]["canEdit"] is False
    assert data["realized"]["amount"] == "125"
    assert data["remaining"]["amount"] == "375"
    assert data["progressPercent"] == "25.00"
    assert data["expenses"][0]["movementId"] == str(store.expense.id)
    assert data["expenses"][0]["originalAmount"]["amount"] == "125"


def test_project_link_revision_and_history_wire_contract() -> None:
    store = _FakeStore()
    client = _client(store)
    target = f"/api/v1/finance/movements/{store.expense.id}/project-link"
    assert client.get(target).json() == {"link": None}
    initial = {
        "idempotencyKey": str(uuid4()),
        "projectId": str(store.project.id),
        "expectedPredecessorId": None,
    }
    created = client.post(target, json=initial)
    assert created.status_code == 201
    assert created.json()["revision"] == 1
    first = created.json()["id"]
    assert client.post(
        target, json={**initial, "idempotencyKey": str(uuid4())}
    ).status_code == 409
    removed = client.post(target, json={
        "idempotencyKey": str(uuid4()),
        "projectId": None,
        "expectedPredecessorId": first,
    })
    assert removed.status_code == 201
    assert removed.json()["projectId"] is None
    assert removed.json()["supersedesId"] == first
    assert len(client.get(target + "/revisions").json()["items"]) == 2


def test_project_access_errors_are_sanitized() -> None:
    store = _FakeStore()
    store.denied = True
    client = _client(store)
    response = client.get("/api/v1/finance/projects")
    assert response.status_code == 403
    assert response.json() == {"detail": "financial access denied"}
