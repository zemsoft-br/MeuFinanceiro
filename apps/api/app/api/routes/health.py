from typing import Literal

from fastapi import APIRouter, Request, Response, status
from meufinanceiro_persistence.database import Database
from meufinanceiro_persistence.health import inspect_persistence_health
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "api"
    process: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str = "api"
    process: Literal["ok"] = "ok"
    database: Literal["ok", "unavailable"]
    schema_state: Literal["ok", "outdated", "unavailable"] = Field(alias="schema")
    current_revision: str | None
    expected_revision: str

    model_config = ConfigDict(populate_by_name=True)


@router.get("/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return HealthResponse()


@router.get("/ready", response_model=ReadinessResponse)
def readiness(request: Request, response: Response) -> ReadinessResponse:
    database: Database = request.app.state.database
    persistence = inspect_persistence_health(database.engine)
    if not persistence.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ok" if persistence.ready else "degraded",
        database=persistence.database,
        schema=persistence.schema,
        current_revision=persistence.current_revision,
        expected_revision=persistence.expected_revision,
    )
