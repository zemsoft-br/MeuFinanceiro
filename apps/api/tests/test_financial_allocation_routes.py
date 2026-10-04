"""Route-boundary tests for category and Movement allocation endpoints.

The financial rules themselves are enforced by the domain/store and proven by the
PostgreSQL-backed suite; these tests prove the FastAPI boundary only: wire shape,
scope derivation, sanitized status mapping, and absence of destructive verbs.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from meufinanceiro_finance import (
    FinancialCategoryDraft,
    FinancialCategoryRecord,
    FinancialCategoryStatus,
    FinancialMovementAllocationRecord,
    FinancialMovementAllocationRevisionDraft,
    FinancialMovementAllocationSetDraft,
    FinancialMovementAllocationSetRecord,
    FinancialVisibilityScope,
    Money,
)
from meufinanceiro_persistence import OperatorRole, OperatorSessionPrincipal
from meufinanceiro_persistence.financial_category_store import (
    FinancialCategoryAccessError,
    FinancialCategoryNotFoundError,
    FinancialCategoryParentNotFoundError,
    FinancialCategoryPersistenceError,
)
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationAccessError,
    FinancialMovementAllocationAccountNotFoundError,
    FinancialMovementAllocationCategoryNotFoundError,
    FinancialMovementAllocationConflictError,
    FinancialMovementAllocationInvalidShapeError,
    FinancialMovementAllocationMovementNotFoundError,
    FinancialMovementAllocationPersistenceError,
)
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    FinancialMovementNotFoundError,
    FinancialMovementPersistenceError,
)
from meufinanceiro_security.keyring import initialize_keyring_file

from app.core.config import Settings
from app.main import create_app
from app.services.operator_auth import InvalidOperatorSessionError

TOKEN = "F" * 43
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
OPERATOR_ID = UUID("30000000-0000-4000-8000-000000000003")
ACCOUNT_ID = UUID("40000000-0000-4000-8000-000000000004")
MOVEMENT_ID = UUID("60000000-0000-4000-8000-000000000006")
CATEGORY_A = UUID("a1000000-0000-4000-8000-0000000000a1")
CATEGORY_B = UUID("b2000000-0000-4000-8000-0000000000b2")
SET_ID = UUID("c3000000-0000-4000-8000-0000000000c3")
SUCCESSOR_ID = UUID("d4000000-0000-4000-8000-0000000000d4")
SHARE_ID = UUID("e5000000-0000-4000-8000-0000000000e5")
SHARE_ID_2 = UUID("e6000000-0000-4000-8000-0000000000e6")
IDEMPOTENCY_KEY = UUID("f7000000-0000-4000-8000-0000000000f7")
NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)

_SENSITIVE = (
    "SELECT secret FROM finance.movement_allocation_sets "
    "violates constraint uq_finance_allocation_sets_one_successor psycopg RLS"
)
_FORBIDDEN_LEAKS = (
    "SELECT",
    "constraint",
    "psycopg",
    "RLS",
    "finance.",
    "Traceback",
)


def _principal() -> OperatorSessionPrincipal:
    return OperatorSessionPrincipal(
        session_id=uuid4(),
        installation_id=INSTALLATION_ID,
        operator_id=OPERATOR_ID,
        login_name="admin",
        role=OperatorRole.INSTALLATION_ADMIN,
        expires_at=datetime(2027, 8, 13, tzinfo=UTC),
        primary_residence_id=RESIDENCE_ID,
    )


class FakeAuthentication:
    def resolve(self, token: str) -> OperatorSessionPrincipal:
        if token != TOKEN:
            raise InvalidOperatorSessionError("operator session is invalid")
        return _principal()


def _category(category_id: UUID, name: str, scope: str = "HOUSEHOLD") -> Any:
    return FinancialCategoryRecord(
        id=category_id,
        residence_id=RESIDENCE_ID,
        owner_operator_id=OPERATOR_ID,
        visibility_scope=FinancialVisibilityScope(scope),
        parent_id=None,
        name=name,
        status=FinancialCategoryStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
        disabled_at=None,
    )


def _set_record(
    *,
    set_id: UUID = SET_ID,
    revision: int = 1,
    supersedes_id: UUID | None = None,
    shares: tuple[tuple[UUID, str], ...] = ((CATEGORY_A, "-75.25"),),
) -> FinancialMovementAllocationSetRecord:
    share_ids = (SHARE_ID, SHARE_ID_2)
    return FinancialMovementAllocationSetRecord(
        id=set_id,
        movement_id=MOVEMENT_ID,
        revision=revision,
        supersedes_id=supersedes_id,
        created_by_operator_id=OPERATOR_ID,
        created_at=NOW,
        allocations=tuple(
            FinancialMovementAllocationRecord(
                id=share_ids[index],
                allocation_set_id=set_id,
                category_id=category_id,
                amount=Money(Decimal(amount), "BRL"),
                created_at=NOW,
            )
            for index, (category_id, amount) in enumerate(shares)
        ),
    )


class FakeFinancialService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.error: Exception | None = None
        self.current: FinancialMovementAllocationSetRecord | None = None
        self.listed: tuple[FinancialMovementAllocationSetRecord, ...] = ()

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))
        if self.error is not None:
            raise self.error

    def list_categories(self, **kwargs: Any) -> tuple[FinancialCategoryRecord, ...]:
        self._record("list_categories", **kwargs)
        return (
            _category(CATEGORY_A, "Mercado"),
            _category(CATEGORY_B, "Pessoal", "PERSONAL"),
        )

    def create_category(self, **kwargs: Any) -> FinancialCategoryRecord:
        self._record("create_category", **kwargs)
        draft = kwargs["draft"]
        assert isinstance(draft, FinancialCategoryDraft)
        return FinancialCategoryRecord(
            id=CATEGORY_A,
            residence_id=RESIDENCE_ID,
            owner_operator_id=OPERATOR_ID,
            visibility_scope=draft.visibility_scope,
            parent_id=draft.parent_id,
            name=draft.name,
            status=FinancialCategoryStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            disabled_at=None,
        )

    def get_current_allocation(
        self, **kwargs: Any
    ) -> FinancialMovementAllocationSetRecord | None:
        self._record("get_current_allocation", **kwargs)
        return self.current

    def list_current_allocations(
        self, **kwargs: Any
    ) -> tuple[FinancialMovementAllocationSetRecord, ...]:
        self._record("list_current_allocations", **kwargs)
        return self.listed

    def create_allocation(self, **kwargs: Any) -> FinancialMovementAllocationSetRecord:
        self._record("create_allocation", **kwargs)
        return _set_record()

    def revise_allocation(self, **kwargs: Any) -> FinancialMovementAllocationSetRecord:
        self._record("revise_allocation", **kwargs)
        return _set_record(
            set_id=SUCCESSOR_ID,
            revision=2,
            supersedes_id=SET_ID,
            shares=((CATEGORY_A, "-50.00"), (CATEGORY_B, "-25.25")),
        )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, FakeFinancialService]]:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )
    service = FakeFinancialService()
    with TestClient(create_app(settings)) as test_client:
        test_client.app.state.operator_authentication = FakeAuthentication()
        test_client.app.state.financial_core = service
        yield test_client, service


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _share(category_id: UUID, amount: str, currency: str = "BRL") -> dict[str, str]:
    return {"categoryId": str(category_id), "amount": amount, "currency": currency}


def _create_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "idempotencyKey": str(IDEMPOTENCY_KEY),
        "allocations": [_share(CATEGORY_A, "-75.25")],
    }
    body.update(overrides)
    return body


def _revision_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "idempotencyKey": str(IDEMPOTENCY_KEY),
        "supersedesId": str(SET_ID),
        "allocations": [
            _share(CATEGORY_A, "-50.00"),
            _share(CATEGORY_B, "-25.25"),
        ],
    }
    body.update(overrides)
    return body


def _assert_sanitized(response: httpx.Response) -> None:
    assert response.headers["cache-control"] == "no-store"
    for leak in _FORBIDDEN_LEAKS:
        assert leak not in response.text
    for identifier in (MOVEMENT_ID, ACCOUNT_ID, CATEGORY_A, SET_ID):
        assert str(identifier) not in response.text


# --- categories -----------------------------------------------------------


def test_categories_list_uses_camel_case_wire_contract_and_authenticated_scope(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    response = test_client.get("/api/v1/finance/categories", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {
        "categories": [
            {
                "categoryId": str(CATEGORY_A),
                "ownerOperatorId": str(OPERATOR_ID),
                "visibilityScope": "HOUSEHOLD",
                "parentId": None,
                "name": "Mercado",
                "status": "ACTIVE",
                "createdAt": "2026-09-20T03:00:00Z",
                "updatedAt": "2026-09-20T03:00:00Z",
                "disabledAt": None,
            },
            {
                "categoryId": str(CATEGORY_B),
                "ownerOperatorId": str(OPERATOR_ID),
                "visibilityScope": "PERSONAL",
                "parentId": None,
                "name": "Pessoal",
                "status": "ACTIVE",
                "createdAt": "2026-09-20T03:00:00Z",
                "updatedAt": "2026-09-20T03:00:00Z",
                "disabledAt": None,
            },
        ]
    }
    assert service.calls == [
        (
            "list_categories",
            {
                "installation_id": INSTALLATION_ID,
                "residence_id": RESIDENCE_ID,
                "operator_id": OPERATOR_ID,
            },
        )
    ]
    assert response.headers["cache-control"] == "no-store"


def test_category_create_builds_canonical_draft_with_optional_parent(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    response = test_client.post(
        "/api/v1/finance/categories",
        headers=_headers(),
        json={
            "name": "  Mercado  ",
            "visibilityScope": "PERSONAL",
            "parentId": str(CATEGORY_B),
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Mercado"
    assert response.json()["parentId"] == str(CATEGORY_B)
    draft = service.calls[0][1]["draft"]
    assert isinstance(draft, FinancialCategoryDraft)
    assert draft.visibility_scope is FinancialVisibilityScope.PERSONAL
    assert draft.parent_id == CATEGORY_B

    root = test_client.post(
        "/api/v1/finance/categories",
        headers=_headers(),
        json={"name": "Casa", "visibilityScope": "HOUSEHOLD"},
    )
    assert root.status_code == 201
    assert root.json()["parentId"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Casa", "visibilityScope": "SHARED"},
        {"name": "Casa", "visibilityScope": "PUBLIC"},
        {"name": "   ", "visibilityScope": "HOUSEHOLD"},
        {"name": "Casa\u0007", "visibilityScope": "HOUSEHOLD"},
        {"name": "x" * 97, "visibilityScope": "HOUSEHOLD"},
        {"name": "Casa", "visibilityScope": "HOUSEHOLD", "parentId": "not-a-uuid"},
        {
            "name": "Casa",
            "visibilityScope": "HOUSEHOLD",
            "parentId": "11111111-1111-1111-8111-111111111111",
        },
        {"name": 12, "visibilityScope": "HOUSEHOLD"},
        {"name": "Casa", "visibilityScope": "HOUSEHOLD", "status": "DISABLED"},
        {"name": "Casa", "visibilityScope": "HOUSEHOLD", "ownerOperatorId": "x"},
        {"name": "Casa", "visibilityScope": "HOUSEHOLD", "residenceId": "x"},
    ],
)
def test_category_create_rejects_shared_invalid_and_client_supplied_scope(
    client: tuple[TestClient, FakeFinancialService], body: dict[str, Any]
) -> None:
    test_client, service = client
    response = test_client.post(
        "/api/v1/finance/categories", headers=_headers(), json=body
    )

    assert response.status_code == 422
    assert response.json()["detail"] in {
        "invalid financial request",
        "invalid financial category request",
    }
    assert service.calls == []


def test_category_boundary_exposes_no_edit_move_disable_or_delete(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    for method in ("patch", "put", "delete"):
        collection = getattr(test_client, method)(
            "/api/v1/finance/categories", headers=_headers()
        )
        assert collection.status_code == 405
        item = getattr(test_client, method)(
            f"/api/v1/finance/categories/{CATEGORY_A}", headers=_headers()
        )
        assert item.status_code == 404
    assert (
        test_client.get(
            f"/api/v1/finance/categories/{CATEGORY_A}", headers=_headers()
        ).status_code
        == 404
    )
    assert service.calls == []


# --- current allocation / bulk -------------------------------------------


def test_current_allocation_is_explicit_null_for_unclassified_movement(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    response = test_client.get(
        f"/api/v1/finance/movements/{MOVEMENT_ID}/allocation", headers=_headers()
    )

    assert response.status_code == 200
    assert response.json() == {"allocation": None}
    assert service.calls == [
        (
            "get_current_allocation",
            {
                "installation_id": INSTALLATION_ID,
                "residence_id": RESIDENCE_ID,
                "operator_id": OPERATOR_ID,
                "movement_id": MOVEMENT_ID,
            },
        )
    ]


def test_current_allocation_wire_contract_exposes_exact_money_strings(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    service.current = _set_record(
        set_id=SUCCESSOR_ID,
        revision=2,
        supersedes_id=SET_ID,
        shares=((CATEGORY_A, "-50.00"), (CATEGORY_B, "-25.25")),
    )
    response = test_client.get(
        f"/api/v1/finance/movements/{MOVEMENT_ID}/allocation", headers=_headers()
    )

    assert response.status_code == 200
    assert response.json() == {
        "allocation": {
            "allocationSetId": str(SUCCESSOR_ID),
            "movementId": str(MOVEMENT_ID),
            "revision": 2,
            "supersedesId": str(SET_ID),
            "allocations": [
                {
                    "categoryId": str(CATEGORY_A),
                    "money": {"amount": "-50", "currency": "BRL"},
                },
                {
                    "categoryId": str(CATEGORY_B),
                    "money": {"amount": "-25.25", "currency": "BRL"},
                },
            ],
            "createdAt": "2026-09-20T03:00:00Z",
        }
    }


def test_bulk_current_allocations_are_keyed_by_movement_and_never_history(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    service.listed = (_set_record(),)
    response = test_client.get(
        f"/api/v1/finance/accounts/{ACCOUNT_ID}/movement-allocations",
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"accountId", "movementAllocations"}
    assert body["accountId"] == str(ACCOUNT_ID)
    assert [item["movementId"] for item in body["movementAllocations"]] == [
        str(MOVEMENT_ID)
    ]
    assert len(service.calls) == 1
    assert service.calls[0][0] == "list_current_allocations"
    assert service.calls[0][1]["account_id"] == ACCOUNT_ID


def test_bulk_current_allocations_empty_account_is_empty_list(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, _ = client
    response = test_client.get(
        f"/api/v1/finance/accounts/{ACCOUNT_ID}/movement-allocations",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "accountId": str(ACCOUNT_ID),
        "movementAllocations": [],
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/finance/movements/{m}/allocation",
        "/api/v1/finance/accounts/{a}/movement-allocations",
        "/api/v1/finance/categories",
    ],
)
def test_read_endpoints_reject_query_parameters_and_unauthenticated_calls(
    client: tuple[TestClient, FakeFinancialService], path: str
) -> None:
    test_client, service = client
    url = path.format(m=MOVEMENT_ID, a=ACCOUNT_ID)

    assert (
        test_client.get(url + "?include=history", headers=_headers()).status_code == 422
    )
    assert test_client.get(url).status_code == 401
    assert service.calls == []


def test_non_v4_resource_ids_are_not_found_without_touching_service(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    non_v4 = "11111111-1111-1111-8111-111111111111"

    for url in (
        f"/api/v1/finance/movements/{non_v4}/allocation",
        f"/api/v1/finance/accounts/{non_v4}/movement-allocations",
    ):
        response = test_client.get(url, headers=_headers())
        assert response.status_code == 404
        assert response.json() == {"detail": "financial resource was not found"}
    assert service.calls == []


# --- create / revise ------------------------------------------------------


def test_create_allocation_builds_canonical_set_draft_from_path_movement(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    response = test_client.post(
        f"/api/v1/finance/movements/{MOVEMENT_ID}/allocation",
        headers=_headers(),
        json=_create_body(
            allocations=[
                _share(CATEGORY_A, "-50.00"),
                _share(CATEGORY_B, "-25.25"),
            ]
        ),
    )

    assert response.status_code == 201
    assert response.json()["allocationSetId"] == str(SET_ID)
    name, kwargs = service.calls[0]
    assert name == "create_allocation"
    assert kwargs["installation_id"] == INSTALLATION_ID
    assert kwargs["residence_id"] == RESIDENCE_ID
    assert kwargs["operator_id"] == OPERATOR_ID
    assert kwargs["idempotency_key"] == IDEMPOTENCY_KEY
    draft = kwargs["draft"]
    assert isinstance(draft, FinancialMovementAllocationSetDraft)
    assert draft.movement_id == MOVEMENT_ID
    assert draft.total == Money(Decimal("-75.25"), "BRL")
    assert {item.category_id for item in draft.allocations} == {CATEGORY_A, CATEGORY_B}


def test_create_allocation_cannot_diverge_movement_between_path_and_payload(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    response = test_client.post(
        f"/api/v1/finance/movements/{MOVEMENT_ID}/allocation",
        headers=_headers(),
        json=_create_body(movementId=str(uuid4())),
    )

    assert response.status_code == 422
    assert service.calls == []


def test_revision_builds_append_only_draft_with_explicit_predecessor(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    response = test_client.post(
        f"/api/v1/finance/movements/{MOVEMENT_ID}/allocation/revisions",
        headers=_headers(),
        json=_revision_body(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["revision"] == 2
    assert body["supersedesId"] == str(SET_ID)
    name, kwargs = service.calls[0]
    assert name == "revise_allocation"
    draft = kwargs["draft"]
    assert isinstance(draft, FinancialMovementAllocationRevisionDraft)
    assert draft.movement_id == MOVEMENT_ID
    assert draft.supersedes_id == SET_ID


def test_revision_requires_explicit_predecessor(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    body = _revision_body()
    del body["supersedesId"]

    response = test_client.post(
        f"/api/v1/finance/movements/{MOVEMENT_ID}/allocation/revisions",
        headers=_headers(),
        json=body,
    )

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"allocations": []},
        {"allocations": [_share(CATEGORY_A, "0")]},
        {"allocations": [_share(CATEGORY_A, "0.00")]},
        {"allocations": [_share(CATEGORY_A, "-1"), _share(CATEGORY_A, "-2")]},
        {"allocations": [_share(CATEGORY_A, "-1"), _share(CATEGORY_B, "2")]},
        {
            "allocations": [
                _share(CATEGORY_A, "-1", "BRL"),
                _share(CATEGORY_B, "-2", "USD"),
            ]
        },
        {"allocations": [_share(CATEGORY_A, "-1.123456789")]},
        {"allocations": [_share(CATEGORY_A, "1e3")]},
        {"allocations": [_share(CATEGORY_A, "NaN")]},
        {"allocations": [_share(CATEGORY_A, "Infinity")]},
        {"allocations": [_share(CATEGORY_A, " -1 ")]},
        {"allocations": [_share(CATEGORY_A, "-1", "br")]},
        {"allocations": [_share(CATEGORY_A, "-1", "BRLX")]},
        {
            "allocations": [
                {"categoryId": str(CATEGORY_A), "amount": -1.5, "currency": "BRL"}
            ]
        },
        {
            "allocations": [
                {"categoryId": str(CATEGORY_A), "amount": 10, "currency": "BRL"}
            ]
        },
        {"allocations": [{"categoryId": "nope", "amount": "-1", "currency": "BRL"}]},
        {
            "allocations": [
                {
                    "categoryId": "11111111-1111-1111-8111-111111111111",
                    "amount": "-1",
                    "currency": "BRL",
                }
            ]
        },
        {"allocations": [{"amount": "-1", "currency": "BRL"}]},
        {
            "allocations": [
                {**_share(CATEGORY_A, "-1"), "percentage": "100"},
            ]
        },
        {"allocations": [_share(uuid4(), "-1") for _ in range(51)]},
        {"idempotencyKey": "not-a-uuid"},
        {"idempotencyKey": "11111111-1111-1111-8111-111111111111"},
        {"extra": "field"},
    ],
)
def test_create_allocation_rejects_malformed_money_shares_before_the_service(
    client: tuple[TestClient, FakeFinancialService], overrides: dict[str, Any]
) -> None:
    test_client, service = client
    response = test_client.post(
        f"/api/v1/finance/movements/{MOVEMENT_ID}/allocation",
        headers=_headers(),
        json=_create_body(**overrides),
    )

    assert response.status_code == 422
    assert response.json()["detail"] in {
        "invalid financial request",
        "invalid financial allocation request",
        "invalid financial operation request",
    }
    assert service.calls == []


def test_allocation_boundary_exposes_no_destructive_or_in_place_verbs(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    for method in ("patch", "put", "delete"):
        for path in (
            f"/api/v1/finance/movements/{MOVEMENT_ID}/allocation",
            f"/api/v1/finance/movements/{MOVEMENT_ID}/allocation/revisions",
            f"/api/v1/finance/accounts/{ACCOUNT_ID}/movement-allocations",
            f"/api/v1/finance/movements/{MOVEMENT_ID}",
        ):
            response = getattr(test_client, method)(path, headers=_headers())
            assert response.status_code == 405
    assert service.calls == []


# --- sanitized error mapping ---------------------------------------------

_ALLOCATION_ERRORS: list[tuple[Exception, int, str]] = [
    (
        FinancialMovementAllocationMovementNotFoundError(_SENSITIVE),
        404,
        "financial resource was not found",
    ),
    (
        FinancialMovementAllocationAccountNotFoundError(_SENSITIVE),
        404,
        "financial resource was not found",
    ),
    (
        FinancialMovementAllocationCategoryNotFoundError(_SENSITIVE),
        404,
        "financial category was not found",
    ),
    (
        FinancialMovementAllocationAccessError(_SENSITIVE),
        403,
        "financial access denied",
    ),
    (
        FinancialMovementAllocationInvalidShapeError(_SENSITIVE),
        422,
        "invalid financial allocation request",
    ),
    (
        FinancialMovementAllocationConflictError(_SENSITIVE),
        409,
        "financial operation conflicts with canonical state",
    ),
    (
        FinancialMovementAllocationPersistenceError(_SENSITIVE),
        503,
        "financial service is unavailable",
    ),
]


@pytest.mark.parametrize(("error", "status_code", "detail"), _ALLOCATION_ERRORS)
@pytest.mark.parametrize(
    ("method", "path_template", "body"),
    [
        ("post", "/movements/{m}/allocation", _create_body()),
        ("post", "/movements/{m}/allocation/revisions", _revision_body()),
        ("get", "/accounts/{a}/movement-allocations", None),
    ],
)
def test_allocation_failures_map_to_sanitized_public_statuses(
    client: tuple[TestClient, FakeFinancialService],
    error: Exception,
    status_code: int,
    detail: str,
    method: str,
    path_template: str,
    body: dict[str, Any] | None,
) -> None:
    test_client, service = client
    service.error = error
    path = "/api/v1/finance" + path_template.format(m=MOVEMENT_ID, a=ACCOUNT_ID)

    response = (
        test_client.get(path, headers=_headers())
        if method == "get"
        else test_client.post(path, headers=_headers(), json=body)
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    _assert_sanitized(response)


def test_stale_predecessor_conflict_is_never_retried_silently(
    client: tuple[TestClient, FakeFinancialService],
) -> None:
    test_client, service = client
    service.error = FinancialMovementAllocationConflictError(
        "financial Movement allocation revision is stale"
    )

    response = test_client.post(
        f"/api/v1/finance/movements/{MOVEMENT_ID}/allocation/revisions",
        headers=_headers(),
        json=_revision_body(),
    )

    assert response.status_code == 409
    assert [name for name, _ in service.calls] == ["revise_allocation"]


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            FinancialMovementNotFoundError(_SENSITIVE),
            404,
            "financial resource was not found",
        ),
        (FinancialMovementAccessError(_SENSITIVE), 403, "financial access denied"),
        (
            FinancialMovementPersistenceError(_SENSITIVE),
            503,
            "financial service is unavailable",
        ),
        (
            FinancialMovementAllocationPersistenceError(_SENSITIVE),
            503,
            "financial service is unavailable",
        ),
    ],
)
def test_current_allocation_failures_are_sanitized(
    client: tuple[TestClient, FakeFinancialService],
    error: Exception,
    status_code: int,
    detail: str,
) -> None:
    test_client, service = client
    service.error = error

    response = test_client.get(
        f"/api/v1/finance/movements/{MOVEMENT_ID}/allocation", headers=_headers()
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    _assert_sanitized(response)


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            FinancialCategoryNotFoundError(_SENSITIVE),
            404,
            "financial category was not found",
        ),
        (
            FinancialCategoryParentNotFoundError(_SENSITIVE),
            404,
            "financial category was not found",
        ),
        (FinancialCategoryAccessError(_SENSITIVE), 403, "financial access denied"),
        (
            FinancialCategoryPersistenceError(_SENSITIVE),
            503,
            "financial service is unavailable",
        ),
    ],
)
def test_category_failures_are_sanitized(
    client: tuple[TestClient, FakeFinancialService],
    error: Exception,
    status_code: int,
    detail: str,
) -> None:
    test_client, service = client
    service.error = error

    listed = test_client.get("/api/v1/finance/categories", headers=_headers())
    created = test_client.post(
        "/api/v1/finance/categories",
        headers=_headers(),
        json={"name": "Casa", "visibilityScope": "HOUSEHOLD"},
    )

    for response in (listed, created):
        assert response.status_code == status_code
        assert response.json() == {"detail": detail}
        _assert_sanitized(response)


def test_application_wiring_injects_both_stores_into_the_financial_service(
    tmp_path: Path,
) -> None:
    from meufinanceiro_persistence.financial_category_store import (
        FinancialCategoryStore,
    )
    from meufinanceiro_persistence.financial_movement_allocation_store import (
        FinancialMovementAllocationStore,
    )

    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:", app_keyring_file=keyring
    )
    with TestClient(create_app(settings)) as test_client:
        service = test_client.app.state.financial_core
        assert isinstance(service._categories, FinancialCategoryStore)
        assert isinstance(service._allocations, FinancialMovementAllocationStore)
