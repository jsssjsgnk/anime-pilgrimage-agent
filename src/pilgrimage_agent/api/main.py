"""HTTP API entrypoint."""

from typing import Literal

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from pilgrimage_agent import __version__
from pilgrimage_agent.config import get_settings
from pilgrimage_agent.db import session_scope
from pilgrimage_agent.domain.models import (
    ConfirmedSubject,
    PilgrimagePointQuery,
    RouteA,
    SubjectSearchQuery,
    SubjectSearchResult,
)
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.points import build_route_a
from pilgrimage_agent.providers.service import get_provider_services


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


@app.exception_handler(ProviderError)
async def provider_error_handler(_request: object, error: ProviderError) -> JSONResponse:
    status_by_kind = {
        ProviderErrorKind.VALIDATION: 422,
        ProviderErrorKind.AUTH: 503,
        ProviderErrorKind.QUOTA: 503,
        ProviderErrorKind.RATE_LIMIT: 503,
        ProviderErrorKind.TIMEOUT: 504,
        ProviderErrorKind.UPSTREAM: 502,
        ProviderErrorKind.NOT_FOUND: 404,
        ProviderErrorKind.PARTIAL_DATA: 206,
    }
    return JSONResponse(
        status_code=status_by_kind[error.kind],
        content={
            "kind": error.kind.value,
            "provider": error.provider,
            "detail": error.safe_message,
        },
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


@app.get("/api/subjects/search", response_model=SubjectSearchResult)
async def search_subjects(
    query: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=5, ge=1, le=20),
) -> SubjectSearchResult:
    services = get_provider_services()
    return await services.bangumi.fetch(SubjectSearchQuery(query=query, limit=limit))


@app.post("/api/subjects/{subject_id}/confirm", response_model=ConfirmedSubject)
async def confirm_subject(subject_id: str) -> ConfirmedSubject:
    """Record no external write; return the explicitly selected normalized subject."""

    services = get_provider_services()
    return await services.bangumi.get_subject(subject_id)


@app.get("/api/subjects/{subject_id}/route-a", response_model=RouteA)
async def route_a(subject_id: str) -> RouteA:
    services = get_provider_services()
    result = await services.points.fetch(
        PilgrimagePointQuery(subject_id=subject_id, provider="fixture")
    )
    return build_route_a(result, subject_id=subject_id)
