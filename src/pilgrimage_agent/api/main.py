"""HTTP API entrypoint."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from pilgrimage_agent import __version__
from pilgrimage_agent.config import get_settings
from pilgrimage_agent.db import session_scope


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    service: str
    version: str
    database: Literal["ok", "unavailable", "not_checked"]


class CapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: dict[str, bool]


app = FastAPI(
    title="Anime Pilgrimage Agent API",
    version=__version__,
    description="Read-only planning API; booking and payment are intentionally unsupported.",
)


@app.get("/health", response_model=HealthResponse)
async def health(check_database: bool = False) -> HealthResponse:
    database: Literal["ok", "unavailable", "not_checked"] = "not_checked"
    status: Literal["ok", "degraded"] = "ok"
    if check_database:
        try:
            async for session in session_scope():
                await session.execute(text("SELECT 1"))
            database = "ok"
        except Exception:
            database = "unavailable"
            status = "degraded"
    return HealthResponse(
        status=status,
        service="api",
        version=__version__,
        database=database,
    )


@app.get("/api/capabilities", response_model=CapabilityResponse)
async def capabilities() -> CapabilityResponse:
    return CapabilityResponse(capabilities=get_settings().capability_status())

