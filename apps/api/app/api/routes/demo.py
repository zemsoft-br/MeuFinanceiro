from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Request
from meufinanceiro_persistence import DemoFixtureStore, unloaded_demo_status
from meufinanceiro_persistence.database import Database
from pydantic import BaseModel

from app.core.config import Settings

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoStatusResponse(BaseModel):
    enabled: bool
    loaded: bool
    fixture_id: str
    fixture_version: int
    reference_date: date
    timezone: str
    currency: str
    scope: Literal["finance_phase1"]
    contract_checksum: str
    loaded_at: datetime | None


@router.get("/status", response_model=DemoStatusResponse)
def demo_status(request: Request) -> DemoStatusResponse:
    settings: Settings = request.app.state.settings
    if not settings.app_demo_mode:
        status = unloaded_demo_status(enabled=False)
    else:
        database: Database = request.app.state.database
        status = DemoFixtureStore(database.engine, enabled=True).status()
    return DemoStatusResponse.model_validate(asdict(status))
