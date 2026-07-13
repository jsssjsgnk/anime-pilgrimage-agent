"""HTTP API entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from anyio import to_thread
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command, Interrupt
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pilgrimage_agent import __version__
from pilgrimage_agent.agent.graph import WorkflowGraph, WorkflowState, build_workflow
from pilgrimage_agent.agent.schemas import (
    ConfirmationRequest,
    ResumeWorkflowRequest,
    StartWorkflowRequest,
    WorkflowResponse,
    WorkflowStatus,
)
from pilgrimage_agent.config import get_settings
from pilgrimage_agent.db import session_scope
from pilgrimage_agent.domain.models import (
    ConfirmedSubject,
    PilgrimagePointQuery,
    RouteA,
    SubjectSearchQuery,
    SubjectSearchResult,
)
from pilgrimage_agent.domain.planning import PlanningOptions, RouteBPlan, RouteBRequest
from pilgrimage_agent.memory.schemas import StoredTrip
from pilgrimage_agent.memory.store import SqlProjectStore
from pilgrimage_agent.planning.demo import fixture_route_a, plan_demo_route_b, planning_options
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.points import build_route_a
from pilgrimage_agent.providers.service import get_provider_services
from pilgrimage_agent.rag.embedding import FixtureE5Embedder
from pilgrimage_agent.rag.evaluation import evaluate
from pilgrimage_agent.rag.fixtures import load_fixture_index
from pilgrimage_agent.rag.ingestion import ingest_document
from pilgrimage_agent.rag.schemas import (
    IngestedDocument,
    KnowledgeDeleteResponse,
    KnowledgeDocument,
    KnowledgeDocumentInput,
    KnowledgeQuery,
    KnowledgeSearchResult,
    RagEvaluationReport,
)
from pilgrimage_agent.rag.sql import SqlRagRepository


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
RAG_FIXTURE_ROOT = Path.cwd() / "fixtures" / "rag"


def _evaluate_fixture_knowledge() -> RagEvaluationReport:
    index, queries = load_fixture_index(RAG_FIXTURE_ROOT)
    return evaluate(index, queries)


def _checkpoint_url() -> str:
    """Convert the application SQLAlchemy URL to psycopg without exposing it."""

    return (
        get_settings()
        .database_url.get_secret_value()
        .replace("postgresql+asyncpg://", "postgresql://", 1)
    )


def _checkpoint_thread(owner_user_id: str, thread_id: str, trip_id: UUID) -> str:
    namespace = f"{owner_user_id}\x1f{thread_id}\x1f{trip_id}"
    return sha256(namespace.encode()).hexdigest()


@asynccontextmanager
async def _workflow_runtime() -> AsyncIterator[tuple[WorkflowGraph, SqlProjectStore]]:
    """Open bounded checkpoint/store resources for one HTTP operation."""

    database_url = get_settings().database_url.get_secret_value()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with AsyncPostgresSaver.from_conn_string(_checkpoint_url()) as checkpointer:
            await checkpointer.setup()
            yield build_workflow(checkpointer), SqlProjectStore(sessions)
    finally:
        await engine.dispose()


@asynccontextmanager
async def _knowledge_repository() -> AsyncIterator[SqlRagRepository]:
    settings = get_settings()
    database_url = settings.database_url.get_secret_value()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield SqlRagRepository(
            sessions, FixtureE5Embedder(), bm25_root=settings.rag_bm25_index_dir
        )
    finally:
        await engine.dispose()


def _workflow_response(result: WorkflowState) -> WorkflowResponse:
    raw_result = cast(dict[str, object], result)
    raw_interrupts = cast(tuple[Interrupt, ...], raw_result.get("__interrupt__", ()))
    pending: ConfirmationRequest | None = None
    if raw_interrupts:
        first = next(iter(raw_interrupts))
        if isinstance(first, Interrupt):
            pending = ConfirmationRequest.model_validate(first.value)
    status = WorkflowStatus(result.get("status", WorkflowStatus.RUNNING.value))
    if pending is not None:
        status = WorkflowStatus.WAITING
    return WorkflowResponse(
        trip_id=UUID(result["trip_id"]),
        thread_id=result["thread_id"],
        status=status,
        phase=result.get("phase", "unknown"),
        pending_confirmation=pending,
        revision_count=result.get("revision_count", 0),
        warnings=result.get("warnings", ()),
        plan_day_hashes=result.get("plan_day_hashes", ()),
    )


async def _save_workflow(
    store: SqlProjectStore, owner_user_id: str, response: WorkflowResponse
) -> None:
    await store.save_trip(
        StoredTrip(
            trip_id=response.trip_id,
            owner_user_id=owner_user_id,
            thread_id=response.thread_id,
            state=response.model_dump(mode="json"),
        )
    )
    await store.append_event(
        owner_user_id,
        response.trip_id,
        "workflow_transition",
        {"phase": response.phase, "status": response.status.value},
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


@app.get("/api/planning/options", response_model=PlanningOptions)
async def get_planning_options() -> PlanningOptions:
    return await planning_options()


@app.post("/api/subjects/{subject_id}/route-b", response_model=RouteBPlan)
async def route_b(subject_id: str, request: RouteBRequest) -> RouteBPlan:
    route = await fixture_route_a(subject_id)
    return await plan_demo_route_b(route, request)


@app.post("/api/workflows", response_model=WorkflowResponse)
async def start_workflow(request: StartWorkflowRequest) -> WorkflowResponse:
    config: RunnableConfig = {
        "configurable": {
            "thread_id": _checkpoint_thread(
                request.owner_user_id, request.thread_id, request.trip_id
            )
        }
    }
    initial: WorkflowState = {
        "owner_user_id": request.owner_user_id,
        "thread_id": request.thread_id,
        "trip_id": str(request.trip_id),
        "request_summary": request.request_summary,
    }
    async with _workflow_runtime() as (graph, store):
        result = cast(WorkflowState, await graph.ainvoke(initial, config))
        response = _workflow_response(result)
        await _save_workflow(store, request.owner_user_id, response)
    return response


@app.post("/api/workflows/{trip_id}/resume", response_model=WorkflowResponse)
async def resume_workflow(trip_id: UUID, request: ResumeWorkflowRequest) -> WorkflowResponse:
    config: RunnableConfig = {
        "configurable": {
            "thread_id": _checkpoint_thread(request.owner_user_id, request.thread_id, trip_id)
        }
    }
    async with _workflow_runtime() as (graph, store):
        trip = await store.get_trip(request.owner_user_id, request.thread_id, trip_id)
        if trip is None:
            raise HTTPException(status_code=404, detail="Workflow was not found in this namespace")
        result = cast(
            WorkflowState,
            await graph.ainvoke(Command(resume=request.decision.model_dump(mode="json")), config),
        )
        response = _workflow_response(result)
        await _save_workflow(store, request.owner_user_id, response)
    return response


@app.get("/api/workflows/{trip_id}", response_model=WorkflowResponse)
async def get_workflow(
    trip_id: UUID,
    owner_user_id: str = Query(min_length=1, max_length=120),
    thread_id: str = Query(min_length=1, max_length=120),
) -> WorkflowResponse:
    async with _workflow_runtime() as (_graph, store):
        trip = await store.get_trip(owner_user_id, thread_id, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Workflow was not found in this namespace")
    return WorkflowResponse.model_validate(trip.state)


@app.post("/api/knowledge/documents", response_model=IngestedDocument)
async def create_knowledge_document(request: KnowledgeDocumentInput) -> IngestedDocument:
    ingested = ingest_document(request, FixtureE5Embedder())
    async with _knowledge_repository() as repository:
        return await repository.save(ingested)


@app.get("/api/knowledge/documents", response_model=tuple[KnowledgeDocument, ...])
async def list_knowledge_documents(
    owner_user_id: str = Query(min_length=1, max_length=120),
    trip_id: UUID | None = None,
) -> tuple[KnowledgeDocument, ...]:
    async with _knowledge_repository() as repository:
        return tuple(await repository.list_documents(owner_user_id, trip_id))


@app.get("/api/knowledge/documents/{document_id}", response_model=KnowledgeDocument)
async def get_knowledge_document(
    document_id: UUID,
    owner_user_id: str = Query(min_length=1, max_length=120),
    trip_id: UUID | None = None,
) -> KnowledgeDocument:
    async with _knowledge_repository() as repository:
        document = await repository.get_document(owner_user_id, trip_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document was not found")
    return document


@app.delete("/api/knowledge/documents/{document_id}", response_model=KnowledgeDeleteResponse)
async def delete_knowledge_document(
    document_id: UUID,
    owner_user_id: str = Query(min_length=1, max_length=120),
    trip_id: UUID | None = None,
) -> KnowledgeDeleteResponse:
    async with _knowledge_repository() as repository:
        deleted = await repository.delete_document(owner_user_id, trip_id, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge document was not found")
    return KnowledgeDeleteResponse(deleted=True)


@app.post("/api/knowledge/search", response_model=KnowledgeSearchResult)
async def search_knowledge(request: KnowledgeQuery) -> KnowledgeSearchResult:
    async with _knowledge_repository() as repository:
        return await repository.search(request)


@app.post("/api/knowledge/evaluate", response_model=RagEvaluationReport)
async def evaluate_knowledge() -> RagEvaluationReport:
    return await to_thread.run_sync(_evaluate_fixture_knowledge)
