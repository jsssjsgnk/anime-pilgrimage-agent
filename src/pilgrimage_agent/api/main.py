"""HTTP API entrypoint."""

from asyncio import Lock
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
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
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pilgrimage_agent import __version__
from pilgrimage_agent.agent.conversation import (
    ConversationResponder,
    DeterministicConversationAgent,
    LlmConversationAgent,
    ResilientConversationAgent,
    context_from_workflow,
)
from pilgrimage_agent.agent.graph import WorkflowGraph, WorkflowState, build_workflow
from pilgrimage_agent.agent.knowledge import SqlKnowledgeRetriever
from pilgrimage_agent.agent.llm import (
    JsonChatClient,
    LlmRequirementExtractor,
    LlmReviewer,
    ResilientRequirementExtractor,
    ResilientReviewer,
)
from pilgrimage_agent.agent.mcp_client import LangChainMcpToolClient
from pilgrimage_agent.agent.review import FixtureReviewer
from pilgrimage_agent.agent.schemas import (
    ConfirmationRequest,
    ConversationAction,
    ConversationEventPayload,
    ConversationIntent,
    ConversationMessage,
    ConversationRequest,
    ConversationResponse,
    ModifyWorkflowRequest,
    PlanModification,
    ResumeWorkflowRequest,
    StartWorkflowRequest,
    WorkflowResponse,
    WorkflowStatus,
)
from pilgrimage_agent.agent.workspace import (
    ConfirmWorkspaceSubjectsRequest,
    PlanWorkspaceRequest,
    WorkspaceAgent,
    WorkspaceEvidenceView,
    WorkspacePatchPreview,
    WorkspaceStartRequest,
    WorkspaceState,
    WorkspaceView,
    workspace_view,
)
from pilgrimage_agent.config import ProviderRuntimeDiagnostic, get_settings
from pilgrimage_agent.db import session_scope
from pilgrimage_agent.domain.models import (
    ConfirmedSubject,
    PilgrimagePointQuery,
    RouteA,
    SubjectCandidate,
    SubjectSearchQuery,
    SubjectSearchResult,
    TripRequest,
    WeatherForecastResult,
)
from pilgrimage_agent.domain.planning import (
    PlanningOptions,
    RouteBPlan,
    RouteBRequest,
    ValidationIssue,
)
from pilgrimage_agent.domain.workspace import DerivedKnowledgeRule, KnowledgeOperation, PlanPatch
from pilgrimage_agent.memory.schemas import StoredEvent, StoredPreference, StoredTrip
from pilgrimage_agent.memory.store import ProjectStore, SqlProjectStore
from pilgrimage_agent.memory.workspace_repository import SqlWorkspaceRepository
from pilgrimage_agent.planning.demo import plan_demo_route_b, planning_options
from pilgrimage_agent.planning.modification import (
    parse_local_modification,
    replan_local_walking,
)
from pilgrimage_agent.planning.patches import (
    ApplyPlanPatchRequest,
    DirectPlanPatchRequest,
    NaturalLanguagePatchRequest,
    PlanPatchPreview,
    parse_patch_instruction,
)
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.points import build_route_a
from pilgrimage_agent.providers.service import get_provider_services
from pilgrimage_agent.rag.embedding import (
    EmbeddingProvider,
    FixtureE5Embedder,
    LazySentenceTransformerE5Embedder,
)
from pilgrimage_agent.rag.evaluation import evaluate
from pilgrimage_agent.rag.fixtures import load_fixture_index
from pilgrimage_agent.rag.ingestion import ingest_document
from pilgrimage_agent.rag.rules import (
    AcceptKnowledgeRuleRequest,
    WorkspaceKnowledgeRuleRequest,
    accept_derived_rule,
    validate_derived_rule,
)
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


class RuntimeDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: dict[str, ProviderRuntimeDiagnostic]


class WorkspaceConversationResponse(BaseModel):
    """Persisted workspace transcript plus an optional typed change preview."""

    model_config = ConfigDict(extra="forbid")

    trip_id: UUID
    messages: tuple[ConversationMessage, ...] = Field(max_length=50)
    assistant_message: ConversationMessage
    workspace: WorkspaceView
    preview: PlanPatchPreview | None = None


class PreferenceWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: str = Field(min_length=1, max_length=120)
    value: object
    explicit_consent: Literal[True]


class PreferenceDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted_count: int = Field(ge=0)


class ApplicationResources:
    """Reusable process resources; external connections are opened lazily."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.engine = create_async_engine(
            self.settings.database_url.get_secret_value(), pool_pre_ping=True
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.rag_repository = SqlRagRepository(
            self.sessions,
            _rag_embedder(),
            bm25_root=self.settings.rag_bm25_index_dir,
        )
        self.store = SqlProjectStore(self.sessions)
        self.tool_client = LangChainMcpToolClient(
            url=self.settings.mcp_tools_url,
            timeout_seconds=self.settings.provider_timeout_seconds,
        )
        self.chat_client: JsonChatClient | None = None
        self.requirement_extractor = None
        self.reviewer = None
        self.conversation_responder: ConversationResponder = (
            DeterministicConversationAgent()
        )
        if (
            self.settings.llm_api_key
            and self.settings.llm_base_url
            and self.settings.llm_model
        ):
            self.chat_client = JsonChatClient(
                base_url=self.settings.llm_base_url,
                model=self.settings.llm_model,
                api_key=self.settings.llm_api_key.get_secret_value(),
                timeout_seconds=self.settings.provider_timeout_seconds,
                max_attempts=self.settings.provider_max_attempts,
            )
            self.requirement_extractor = ResilientRequirementExtractor(
                LlmRequirementExtractor(self.chat_client)
            )
            self.reviewer = ResilientReviewer(
                LlmReviewer(self.chat_client), FixtureReviewer()
            )
            self.conversation_responder = ResilientConversationAgent(
                LlmConversationAgent(self.chat_client)
            )
        self.workspace_agent = WorkspaceAgent(
            self.tool_client, self.requirement_extractor
        )
        self._graph: WorkflowGraph | None = None
        self._checkpoint_context: (
            AbstractAsyncContextManager[AsyncPostgresSaver] | None
        ) = None
        self._graph_lock = Lock()

    async def workflow_graph(self) -> WorkflowGraph:
        """Initialize checkpoint tables once, on the first workflow operation."""

        if self._graph is not None:
            return self._graph
        async with self._graph_lock:
            if self._graph is not None:
                return self._graph
            checkpoint_url = self.settings.database_url.get_secret_value().replace(
                "postgresql+asyncpg://", "postgresql://", 1
            )
            checkpoint_context = AsyncPostgresSaver.from_conn_string(checkpoint_url)
            checkpointer = await checkpoint_context.__aenter__()
            try:
                await checkpointer.setup()
                self._graph = build_workflow(
                    checkpointer,
                    tool_client=self.tool_client,
                    requirement_extractor=self.requirement_extractor,
                    reviewer=self.reviewer,
                    knowledge_retriever=SqlKnowledgeRetriever(self.rag_repository),
                )
            except BaseException:
                await checkpoint_context.__aexit__(None, None, None)
                raise
            self._checkpoint_context = checkpoint_context
            return self._graph

    async def close(self) -> None:
        if self._checkpoint_context is not None:
            await self._checkpoint_context.__aexit__(None, None, None)
        if self.chat_client is not None:
            await self.chat_client.close()
        await self.engine.dispose()


@asynccontextmanager
async def _app_lifespan(application: FastAPI) -> AsyncIterator[None]:
    resources = ApplicationResources()
    application.state.resources = resources
    try:
        yield
    finally:
        await resources.close()


app = FastAPI(
    title="Anime Pilgrimage Agent API",
    version=__version__,
    description="Read-only planning API; booking and payment are intentionally unsupported.",
    lifespan=_app_lifespan,
)
RAG_FIXTURE_ROOT = Path.cwd() / "fixtures" / "rag"
CONVERSATION_EVENT = "conversation_message"
CONVERSATION_LIMIT = 50


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


@lru_cache
def _rag_embedder() -> EmbeddingProvider:
    if get_settings().rag_embedding_mode == "real":
        return LazySentenceTransformerE5Embedder()
    return FixtureE5Embedder()


@asynccontextmanager
async def _workflow_runtime() -> AsyncIterator[tuple[WorkflowGraph, SqlProjectStore]]:
    """Reuse lifespan resources, with a bounded fallback for direct unit calls."""

    resources = cast(ApplicationResources | None, getattr(app.state, "resources", None))
    if resources is not None:
        yield await resources.workflow_graph(), resources.store
        return

    settings = get_settings()
    database_url = settings.database_url.get_secret_value()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    rag_repository = SqlRagRepository(
        sessions, _rag_embedder(), bm25_root=settings.rag_bm25_index_dir
    )
    chat_client: JsonChatClient | None = None
    requirement_extractor = None
    reviewer = None
    if settings.llm_api_key and settings.llm_base_url and settings.llm_model:
        chat_client = JsonChatClient(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key.get_secret_value(),
            timeout_seconds=settings.provider_timeout_seconds,
            max_attempts=settings.provider_max_attempts,
        )
        requirement_extractor = ResilientRequirementExtractor(
            LlmRequirementExtractor(chat_client)
        )
        reviewer = ResilientReviewer(LlmReviewer(chat_client), FixtureReviewer())
    try:
        async with AsyncPostgresSaver.from_conn_string(_checkpoint_url()) as checkpointer:
            await checkpointer.setup()
            yield build_workflow(
                checkpointer,
                tool_client=LangChainMcpToolClient(
                    url=settings.mcp_tools_url,
                    timeout_seconds=settings.provider_timeout_seconds,
                ),
                requirement_extractor=requirement_extractor,
                reviewer=reviewer,
                knowledge_retriever=SqlKnowledgeRetriever(rag_repository),
            ), SqlProjectStore(sessions)
    finally:
        if chat_client is not None:
            await chat_client.close()
        await engine.dispose()


@asynccontextmanager
async def _knowledge_repository() -> AsyncIterator[SqlRagRepository]:
    resources = cast(ApplicationResources | None, getattr(app.state, "resources", None))
    if resources is not None:
        yield resources.rag_repository
        return
    settings = get_settings()
    database_url = settings.database_url.get_secret_value()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield SqlRagRepository(
            sessions, _rag_embedder(), bm25_root=settings.rag_bm25_index_dir
        )
    finally:
        await engine.dispose()


@asynccontextmanager
async def _project_store() -> AsyncIterator[SqlProjectStore]:
    resources = cast(ApplicationResources | None, getattr(app.state, "resources", None))
    if resources is not None:
        yield resources.store
        return
    engine = create_async_engine(
        get_settings().database_url.get_secret_value(), pool_pre_ping=True
    )
    try:
        yield SqlProjectStore(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


@asynccontextmanager
async def _workspace_runtime() -> AsyncIterator[tuple[WorkspaceAgent, ProjectStore]]:
    """Reuse the process Agent and project-owned store for one workspace operation."""

    resources = cast(ApplicationResources | None, getattr(app.state, "resources", None))
    if resources is not None:
        yield resources.workspace_agent, resources.store
        return
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url.get_secret_value(), pool_pre_ping=True
    )
    try:
        agent = WorkspaceAgent(
            LangChainMcpToolClient(
                url=settings.mcp_tools_url,
                timeout_seconds=settings.provider_timeout_seconds,
            )
        )
        yield agent, SqlProjectStore(
            async_sessionmaker(engine, expire_on_commit=False)
        )
    finally:
        await engine.dispose()


@asynccontextmanager
async def _conversation_runtime(
) -> AsyncIterator[tuple[ConversationResponder, SqlProjectStore]]:
    """Open one bounded conversation operation with an optional structured LLM."""

    resources = cast(ApplicationResources | None, getattr(app.state, "resources", None))
    if resources is not None:
        yield resources.conversation_responder, resources.store
        return

    settings = get_settings()
    engine = create_async_engine(
        settings.database_url.get_secret_value(), pool_pre_ping=True
    )
    client: JsonChatClient | None = None
    responder: ConversationResponder = DeterministicConversationAgent()
    if settings.llm_api_key and settings.llm_base_url and settings.llm_model:
        client = JsonChatClient(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key.get_secret_value(),
            timeout_seconds=settings.provider_timeout_seconds,
            max_attempts=settings.provider_max_attempts,
        )
        responder = ResilientConversationAgent(LlmConversationAgent(client))
    try:
        yield responder, SqlProjectStore(
            async_sessionmaker(engine, expire_on_commit=False)
        )
    finally:
        if client is not None:
            await client.close()
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
        requirements=(
            TripRequest.model_validate(result["requirements"])
            if "requirements" in result
            else None
        ),
        requirement_source=cast(
            Literal["provided", "llm", "deterministic_fallback"] | None,
            result.get("requirement_source"),
        ),
        requirement_assumptions=result.get("requirement_assumptions", ()),
        effective_walking_limit=result.get("effective_walking_limit"),
        applied_preference_keys=result.get("applied_preference_keys", ()),
        subject_candidates=tuple(
            SubjectCandidate.model_validate(item)
            for item in result.get("subject_candidates", ())
        ),
        confirmed_subject=(
            ConfirmedSubject.model_validate(result["confirmed_subject"])
            if "confirmed_subject" in result
            else None
        ),
        route_a=(
            RouteA.model_validate(result["route_a"]) if "route_a" in result else None
        ),
        planning_options=(
            PlanningOptions.model_validate(result["planning_options"])
            if "planning_options" in result
            else None
        ),
        route_b=(
            RouteBPlan.model_validate(result["route_b"]) if "route_b" in result else None
        ),
        weather=(
            WeatherForecastResult.model_validate(result["weather"])
            if "weather" in result
            else None
        ),
        knowledge=(
            KnowledgeSearchResult.model_validate(result["knowledge"])
            if "knowledge" in result
            else None
        ),
        validation_issues=tuple(
            ValidationIssue.model_validate(item)
            for item in result.get("validation_issues", ())
        ),
        reviewer_explanation=result.get("reviewer_explanation"),
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


async def _save_workspace(
    store: ProjectStore, state: WorkspaceState, event_type: str
) -> None:
    await store.save_trip(
        StoredTrip(
            trip_id=state.trip_id,
            owner_user_id=state.owner_user_id,
            thread_id=state.thread_id,
            state=cast(
                dict[str, object], state.model_dump(mode="json")
            ),
        )
    )
    if isinstance(store, SqlProjectStore):
        await SqlWorkspaceRepository(store.sessions).save_projection(state)
    await store.append_event(
        state.owner_user_id,
        state.trip_id,
        event_type,
        {
            "schema_version": state.schema_version,
            "state_version": state.state_version,
            "status": state.status.value,
        },
    )


async def _load_workspace(
    store: ProjectStore,
    owner_user_id: str,
    thread_id: str,
    trip_id: UUID,
) -> WorkspaceState:
    trip = await store.get_trip(owner_user_id, thread_id, trip_id)
    if trip is None:
        raise HTTPException(
            status_code=404, detail="Workspace was not found in this namespace"
        )
    try:
        return WorkspaceState.model_validate(trip.state)
    except ValidationError as error:
        raise HTTPException(
            status_code=409,
            detail="This trip uses the legacy workflow schema, not workspace schema v2",
        ) from error


def _workspace_value_error(error: ValueError) -> HTTPException:
    detail = str(error)
    conflict_markers = (
        "version conflict",
        "namespace mismatch",
        "must belong",
        "requires explicit confirmation",
    )
    status_code = 409 if any(item in detail for item in conflict_markers) else 422
    return HTTPException(status_code=status_code, detail=detail)


def _conversation_message(event: StoredEvent) -> ConversationMessage | None:
    """Validate a persisted chat event without trusting arbitrary historical JSON."""

    if event.event_type != CONVERSATION_EVENT:
        return None
    try:
        payload = ConversationEventPayload.model_validate(event.payload)
    except ValidationError:
        return None
    return ConversationMessage(
        message_id=event.event_id,
        created_at=event.created_at,
        **payload.model_dump(mode="python"),
    )


async def _list_conversation_messages(
    store: ProjectStore, owner_user_id: str, trip_id: UUID
) -> tuple[ConversationMessage, ...]:
    messages = tuple(
        message
        for event in await store.list_events(owner_user_id, trip_id)
        if (message := _conversation_message(event)) is not None
    )
    return messages[-CONVERSATION_LIMIT:]


async def _append_conversation_message(
    store: ProjectStore,
    owner_user_id: str,
    trip_id: UUID,
    payload: ConversationEventPayload,
) -> ConversationMessage:
    event = await store.append_event(
        owner_user_id,
        trip_id,
        CONVERSATION_EVENT,
        payload.model_dump(mode="json"),
    )
    message = _conversation_message(event)
    if message is None:  # pragma: no cover - store contract violation
        raise RuntimeError("Conversation event failed strict validation")
    return message


def _modified_workflow(
    current: WorkflowResponse, modification: PlanModification
) -> WorkflowResponse:
    if current.route_a is None or current.route_b is None:
        raise ValueError("Workflow has no editable itinerary")
    if current.revision_count >= 3:
        raise ValueError("The three-revision limit was reached")
    plan, warnings = replan_local_walking(
        current.route_b, current.route_a, modification
    )
    revision = current.revision_count + 1
    hashes = list(current.plan_day_hashes)
    while len(hashes) < len(plan.days):
        hashes.append("")
    changed_index = modification.target_day - 1
    hashes[changed_index] = sha256(
        f"{plan.days[changed_index].model_dump_json()}|revision={revision}".encode()
    ).hexdigest()[:16]
    return current.model_copy(
        update={
            "route_b": plan,
            "revision_count": revision,
            "plan_day_hashes": tuple(hashes),
            "warnings": (*current.warnings, *warnings),
            "reviewer_explanation": (
                f"Applied Day {modification.target_day} walking reduction of "
                f"{modification.walking_reduction_percent}% without changing other days."
            ),
        }
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


@app.get("/api/runtime/diagnostics", response_model=RuntimeDiagnosticsResponse)
async def runtime_diagnostics() -> RuntimeDiagnosticsResponse:
    """Expose provider selection and presence flags, never secret values."""

    return RuntimeDiagnosticsResponse(providers=get_settings().provider_diagnostics())


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
        PilgrimagePointQuery(
            subject_id=subject_id,
            provider=get_settings().pilgrimage_point_mode,
        )
    )
    return build_route_a(result, subject_id=subject_id)


@app.get("/api/planning/options", response_model=PlanningOptions)
async def get_planning_options() -> PlanningOptions:
    return await planning_options()


@app.post("/api/subjects/{subject_id}/route-b", response_model=RouteBPlan)
async def route_b(subject_id: str, request: RouteBRequest) -> RouteBPlan:
    # Route B must be a subset of the exact Route A provider selected for this
    # runtime.  Falling back to the three-point fixture here made the legacy
    # compatibility endpoint return foreign point IDs when Route A used live
    # Anitabi data.
    services = get_provider_services()
    result = await services.points.fetch(
        PilgrimagePointQuery(
            subject_id=subject_id,
            provider=get_settings().pilgrimage_point_mode,
        )
    )
    route = build_route_a(result, subject_id=subject_id)
    return await plan_demo_route_b(route, request)


@app.post("/api/workspaces", response_model=WorkspaceView)
async def start_workspace(request: WorkspaceStartRequest) -> WorkspaceView:
    """Start the multi-subject workspace without exposing raw evidence by default."""

    async with _workspace_runtime() as (agent, store):
        existing = await store.get_trip(
            request.owner_user_id, request.thread_id, request.trip_id
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="Workspace already exists")
        try:
            state = await agent.start(request)
        except ValueError as error:
            raise _workspace_value_error(error) from error
        await _save_workspace(store, state, "workspace_started")
    return workspace_view(state)


@app.get("/api/workspaces/{trip_id}", response_model=WorkspaceView)
async def get_workspace(
    trip_id: UUID,
    owner_user_id: str = Query(min_length=1, max_length=120),
    thread_id: str = Query(min_length=1, max_length=120),
) -> WorkspaceView:
    async with _workspace_runtime() as (_agent, store):
        state = await _load_workspace(store, owner_user_id, thread_id, trip_id)
    return workspace_view(state)


@app.get(
    "/api/workspaces/{trip_id}/evidence",
    response_model=WorkspaceEvidenceView,
)
async def get_workspace_evidence(
    trip_id: UUID,
    owner_user_id: str = Query(min_length=1, max_length=120),
    thread_id: str = Query(min_length=1, max_length=120),
) -> WorkspaceEvidenceView:
    """Return the opt-in evidence inspector projection for curation work."""

    async with _workspace_runtime() as (_agent, store):
        state = await _load_workspace(store, owner_user_id, thread_id, trip_id)
    return WorkspaceEvidenceView(
        trip_id=state.trip_id,
        evidence=state.evidence,
        quarantined=state.quarantined,
        ambiguous_merges=state.ambiguous_merges,
    )


@app.post(
    "/api/workspaces/{trip_id}/subjects/confirm",
    response_model=WorkspaceView,
)
async def confirm_workspace_subjects(
    trip_id: UUID, request: ConfirmWorkspaceSubjectsRequest
) -> WorkspaceView:
    async with _workspace_runtime() as (agent, store):
        state = await _load_workspace(
            store, request.owner_user_id, request.thread_id, trip_id
        )
        try:
            updated = await agent.confirm_subjects(state, request)
        except ValueError as error:
            raise _workspace_value_error(error) from error
        await _save_workspace(store, updated, "workspace_subjects_confirmed")
    return workspace_view(updated)


@app.post("/api/workspaces/{trip_id}/plan", response_model=WorkspaceView)
async def plan_workspace(
    trip_id: UUID, request: PlanWorkspaceRequest
) -> WorkspaceView:
    async with _workspace_runtime() as (agent, store):
        state = await _load_workspace(
            store, request.owner_user_id, request.thread_id, trip_id
        )
        try:
            updated = agent.plan(state, request)
        except ValueError as error:
            raise _workspace_value_error(error) from error
        await _save_workspace(store, updated, "workspace_planned")
    return workspace_view(updated)


@app.post(
    "/api/workspaces/{trip_id}/patches/preview",
    response_model=WorkspacePatchPreview,
)
async def preview_workspace_patch(
    trip_id: UUID, request: DirectPlanPatchRequest
) -> WorkspacePatchPreview:
    async with _workspace_runtime() as (agent, store):
        state = await _load_workspace(
            store, request.owner_user_id, request.thread_id, trip_id
        )
        try:
            updated, preview = agent.propose_patch(state, request.patch)
        except ValueError as error:
            raise _workspace_value_error(error) from error
        await _save_workspace(store, updated, "workspace_patch_proposed")
    return WorkspacePatchPreview(workspace=workspace_view(updated), preview=preview)


@app.post(
    "/api/workspaces/{trip_id}/patches/parse",
    response_model=WorkspacePatchPreview,
)
async def parse_workspace_patch(
    trip_id: UUID, request: NaturalLanguagePatchRequest
) -> WorkspacePatchPreview:
    async with _workspace_runtime() as (agent, store):
        state = await _load_workspace(
            store, request.owner_user_id, request.thread_id, trip_id
        )
        try:
            patch = parse_patch_instruction(
                trip_id=trip_id,
                expected_base_version=request.expected_base_version,
                instruction=request.instruction,
                idempotency_key=request.idempotency_key,
            )
            updated, preview = agent.propose_patch(state, patch)
        except ValueError as error:
            raise _workspace_value_error(error) from error
        await _save_workspace(store, updated, "workspace_patch_proposed")
    return WorkspacePatchPreview(workspace=workspace_view(updated), preview=preview)


@app.post(
    "/api/workspaces/{trip_id}/patches/{patch_id}/apply",
    response_model=WorkspaceView,
)
async def apply_workspace_patch(
    trip_id: UUID,
    patch_id: UUID,
    request: ApplyPlanPatchRequest,
) -> WorkspaceView:
    async with _workspace_runtime() as (agent, store):
        state = await _load_workspace(
            store, request.owner_user_id, request.thread_id, trip_id
        )
        try:
            updated = await agent.apply_patch(
                state, patch_id, confirm=request.confirm
            )
        except ValueError as error:
            raise _workspace_value_error(error) from error
        await _save_workspace(store, updated, "workspace_patch_applied")
    return workspace_view(updated)


@app.get(
    "/api/workspaces/{trip_id}/messages",
    response_model=tuple[ConversationMessage, ...],
)
async def list_workspace_messages(
    trip_id: UUID,
    owner_user_id: str = Query(min_length=1, max_length=120),
    thread_id: str = Query(min_length=1, max_length=120),
) -> tuple[ConversationMessage, ...]:
    """Restore the project-owned, trip-scoped workspace transcript."""

    async with _workspace_runtime() as (_agent, store):
        await _load_workspace(store, owner_user_id, thread_id, trip_id)
        return await _list_conversation_messages(store, owner_user_id, trip_id)


@app.post(
    "/api/workspaces/{trip_id}/messages",
    response_model=WorkspaceConversationResponse,
)
async def send_workspace_message(
    trip_id: UUID, request: ConversationRequest
) -> WorkspaceConversationResponse:
    """Turn a persisted message into status guidance or a typed PlanPatch preview."""

    async with _workspace_runtime() as (agent, store):
        state = await _load_workspace(
            store, request.owner_user_id, request.thread_id, trip_id
        )
        user_message = await _append_conversation_message(
            store,
            request.owner_user_id,
            trip_id,
            ConversationEventPayload(
                role="user",
                content=request.message,
                intent=ConversationIntent.GENERAL,
            ),
        )
        normalized = request.message.casefold()
        preview: PlanPatchPreview | None = None
        intent = ConversationIntent.STATUS
        action = ConversationAction()
        updated = state
        if any(term in normalized for term in ("状态", "进展", "还缺", "status")):
            answer = (
                f"当前状态是 {state.status.value}。已确认 "
                f"{len(state.confirmed_subjects)} 部作品, 归并 {len(state.places)} 个地点, "
                f"形成 {len(state.areas)} 个区域, 共有 {len(state.itineraries)} 个行程版本。"
            )
        elif not state.itineraries:
            intent = ConversationIntent.CONFIRMATION_HELP
            answer = (
                "当前还不能生成行程修改: 请先确认作品并生成首个行程版本。"
                "已确认的数据会保留在这个工作区中。"
            )
            action = ConversationAction(kind="confirmation_required")
        else:
            try:
                patch = parse_patch_instruction(
                    trip_id=trip_id,
                    expected_base_version=state.state_version,
                    instruction=request.message,
                    idempotency_key=f"workspace-chat:{user_message.message_id}",
                )
                updated, preview = agent.propose_patch(state, patch)
                await _save_workspace(store, updated, "workspace_patch_proposed")
                intent = ConversationIntent.MODIFY_PLAN
                action = ConversationAction(kind="confirmation_required")
                affected = "、".join(preview.impact.invalidated_nodes)
                answer = (
                    f"我已生成 PlanPatch 预览: {preview.patch.rationale}。"
                    f"会重新计算 {affected}; 确认前不会改变当前行程。"
                )
            except ValueError:
                intent = ConversationIntent.UNSUPPORTED_CHANGE
                action = ConversationAction(kind="unsupported_change")
                answer = (
                    "这条消息暂时不能安全转换为结构化修改。你可以修改日期、步行偏好、"
                    "住宿基点, 或使用地点卡片排除和移动地点; 我不会猜测未识别的操作。"
                )
        assistant = await _append_conversation_message(
            store,
            request.owner_user_id,
            trip_id,
            ConversationEventPayload(
                role="assistant", content=answer, intent=intent, action=action
            ),
        )
        messages = await _list_conversation_messages(
            store, request.owner_user_id, trip_id
        )
    return WorkspaceConversationResponse(
        trip_id=trip_id,
        messages=messages,
        assistant_message=assistant,
        workspace=workspace_view(updated),
        preview=preview,
    )


@app.post(
    "/api/workspaces/{trip_id}/knowledge/rules/propose",
    response_model=DerivedKnowledgeRule,
)
async def propose_workspace_knowledge_rule(
    trip_id: UUID, request: WorkspaceKnowledgeRuleRequest
) -> DerivedKnowledgeRule:
    async with _workspace_runtime() as (_agent, store):
        state = await _load_workspace(
            store, request.owner_user_id, request.thread_id, trip_id
        )
        query = KnowledgeQuery(
            owner_user_id=request.owner_user_id,
            trip_id=trip_id,
            question=request.question,
            subject_ids=tuple(
                item.subject.subject_id for item in state.confirmed_subjects
            ),
            point_ids=tuple(
                item.entity_id
                for item in request.proposal.target_refs
                if item.entity_type == "place"
            ),
            travel_date=state.requirements.start_date,
        )
        async with _knowledge_repository() as repository:
            retrieval = await repository.search(query)
        try:
            rule = validate_derived_rule(
                trip_id=trip_id,
                proposal=request.proposal,
                retrieval=retrieval,
            )
        except ValueError as error:
            raise _workspace_value_error(error) from error
        evidence_documents = dict(state.knowledge_evidence_documents)
        evidence_documents.update(
            {item.evidence_id: item.document_id for item in retrieval.evidence}
        )
        updated = state.model_copy(
            update={
                "knowledge_rules": (*state.knowledge_rules, rule),
                "knowledge_evidence_documents": evidence_documents,
            }
        )
        await _save_workspace(store, updated, "workspace_knowledge_rule_proposed")
    return rule


@app.post(
    "/api/workspaces/{trip_id}/knowledge/rules/{rule_id}/accept",
    response_model=WorkspaceView,
)
async def accept_workspace_knowledge_rule(
    trip_id: UUID,
    rule_id: UUID,
    request: AcceptKnowledgeRuleRequest,
) -> WorkspaceView:
    async with _workspace_runtime() as (agent, store):
        state = await _load_workspace(
            store, request.owner_user_id, request.thread_id, trip_id
        )
        if request.expected_base_version != state.state_version:
            raise HTTPException(status_code=409, detail="workspace state version conflict")
        rule = next((item for item in state.knowledge_rules if item.rule_id == rule_id), None)
        if rule is None:
            raise HTTPException(status_code=404, detail="Knowledge rule was not found")
        try:
            active_rule = accept_derived_rule(rule)
            document_id = state.knowledge_evidence_documents[rule.evidence_ids[0]]
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        with_active_rule = state.model_copy(
            update={
                "knowledge_rules": tuple(
                    active_rule if item.rule_id == rule_id else item
                    for item in state.knowledge_rules
                )
            }
        )
        patch = PlanPatch(
            trip_id=trip_id,
            expected_base_version=state.state_version,
            operations=(KnowledgeOperation(action="attach", document_id=document_id),),
            rationale=f"Accept derived knowledge rule {rule_id}.",
            requires_confirmation=True,
            idempotency_key=request.idempotency_key,
            created_at=datetime.now(UTC),
        )
        try:
            proposed, preview = agent.propose_patch(with_active_rule, patch)
            updated = await agent.apply_patch(
                proposed, preview.patch.patch_id, confirm=request.confirm
            )
        except ValueError as error:
            raise _workspace_value_error(error) from error
        await _save_workspace(store, updated, "workspace_knowledge_rule_accepted")
    return workspace_view(updated)


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
    if request.requirements is not None:
        initial["requirements"] = cast(
            dict[str, object], request.requirements.model_dump(mode="json")
        )
    async with _workflow_runtime() as (graph, store):
        if request.apply_saved_preferences:
            preferences = await store.list_preferences(request.owner_user_id)
            allowed = {
                "budget_level",
                "walking_preference",
                "max_walking_meters_per_day",
            }
            initial["preference_defaults"] = {
                item.preference_key: item.value.get("value")
                for item in preferences
                if item.preference_key in allowed and "value" in item.value
            }
        result = cast(WorkflowState, await graph.ainvoke(initial, config))
        response = _workflow_response(result)
        await _save_workflow(store, request.owner_user_id, response)
        await _append_conversation_message(
            store,
            request.owner_user_id,
            response.trip_id,
            ConversationEventPayload(
                role="user",
                content=request.request_summary,
                intent=ConversationIntent.TRIP_STARTED,
            ),
        )
        await _append_conversation_message(
            store,
            request.owner_user_id,
            response.trip_id,
            ConversationEventPayload(
                role="assistant",
                content=(
                    "我已建立这次行程的持续对话。当前事实、确认进度和后续修改都会"
                    "绑定在这个行程中; 关键选择仍需要你在可见卡片中明确确认。"
                ),
                intent=ConversationIntent.TRIP_STARTED,
                action=ConversationAction(
                    kind=(
                        "confirmation_required"
                        if response.pending_confirmation is not None
                        else "none"
                    )
                ),
            ),
        )
    return response


@app.get("/api/preferences", response_model=tuple[StoredPreference, ...])
async def list_preferences(
    owner_user_id: str = Query(min_length=1, max_length=120),
) -> tuple[StoredPreference, ...]:
    async with _project_store() as store:
        return tuple(await store.list_preferences(owner_user_id))


@app.put("/api/preferences/{preference_key}", response_model=StoredPreference)
async def save_preference(
    preference_key: Literal[
        "budget_level",
        "walking_preference",
        "max_walking_meters_per_day",
    ],
    request: PreferenceWriteRequest,
) -> StoredPreference:
    normalized = getattr(
        TripRequest.model_validate({preference_key: request.value}), preference_key
    )
    preference = StoredPreference(
        owner_user_id=request.owner_user_id,
        preference_key=preference_key,
        value={"value": normalized},
        explicit_consent=request.explicit_consent,
    )
    async with _project_store() as store:
        await store.save_preference(preference)
    return preference


@app.delete("/api/preferences", response_model=PreferenceDeleteResponse)
async def delete_preferences(
    owner_user_id: str = Query(min_length=1, max_length=120),
) -> PreferenceDeleteResponse:
    async with _project_store() as store:
        deleted = await store.delete_preferences(owner_user_id)
    return PreferenceDeleteResponse(deleted_count=deleted)


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


@app.get(
    "/api/workflows/{trip_id}/messages",
    response_model=tuple[ConversationMessage, ...],
)
async def list_workflow_messages(
    trip_id: UUID,
    owner_user_id: str = Query(min_length=1, max_length=120),
    thread_id: str = Query(min_length=1, max_length=120),
) -> tuple[ConversationMessage, ...]:
    async with _project_store() as store:
        trip = await store.get_trip(owner_user_id, thread_id, trip_id)
        if trip is None:
            raise HTTPException(
                status_code=404,
                detail="Workflow was not found in this namespace",
            )
        return await _list_conversation_messages(store, owner_user_id, trip_id)


@app.post(
    "/api/workflows/{trip_id}/messages",
    response_model=ConversationResponse,
)
async def converse_workflow(
    trip_id: UUID, request: ConversationRequest
) -> ConversationResponse:
    async with _conversation_runtime() as (responder, store):
        trip = await store.get_trip(request.owner_user_id, request.thread_id, trip_id)
        if trip is None:
            raise HTTPException(
                status_code=404,
                detail="Workflow was not found in this namespace",
            )
        current = WorkflowResponse.model_validate(trip.state)
        await _append_conversation_message(
            store,
            request.owner_user_id,
            trip_id,
            ConversationEventPayload(
                role="user",
                content=request.message,
                intent=ConversationIntent.GENERAL,
            ),
        )
        messages = await _list_conversation_messages(
            store, request.owner_user_id, trip_id
        )
        decision = await responder.respond(
            context_from_workflow(current), messages[:-1][-8:], request.message
        )
        workflow = current
        content = decision.answer
        action = ConversationAction()
        intent = decision.intent
        if decision.modification is not None:
            try:
                workflow = _modified_workflow(current, decision.modification)
            except ValueError as error:
                intent = ConversationIntent.UNSUPPORTED_CHANGE
                action = ConversationAction(kind="unsupported_change")
                if "three-revision" in str(error):
                    content = "这次行程已达到三轮局部修订上限; 我没有继续改动计划。"
                elif "editable itinerary" in str(error):
                    content = (
                        "当前还没有可修改的 Route B。完成必要确认并生成计划后, "
                        "我才能执行局部重规划。"
                    )
                else:
                    content = f"这项修改无法安全执行: {error}。当前计划保持不变。"
            else:
                await _save_workflow(store, request.owner_user_id, workflow)
                action = ConversationAction(
                    kind="workflow_modified",
                    target_day=decision.modification.target_day,
                    revision_count=workflow.revision_count,
                )
                content = (
                    f"{decision.answer} 已应用为计划版本 {workflow.revision_count + 1}; "
                    "请复核变化后的步行距离和遗漏点。"
                )[:2000]
        elif decision.intent in {
            ConversationIntent.CONFIRMATION_HELP,
            ConversationIntent.UNSUPPORTED_CHANGE,
        }:
            action = ConversationAction(
                kind=(
                    "confirmation_required"
                    if decision.intent is ConversationIntent.CONFIRMATION_HELP
                    else "unsupported_change"
                )
            )
        assistant = await _append_conversation_message(
            store,
            request.owner_user_id,
            trip_id,
            ConversationEventPayload(
                role="assistant",
                content=content,
                intent=intent,
                action=action,
            ),
        )
        messages = await _list_conversation_messages(
            store, request.owner_user_id, trip_id
        )
        return ConversationResponse(
            trip_id=trip_id,
            messages=messages,
            assistant_message=assistant,
            workflow=workflow,
        )


@app.post("/api/workflows/{trip_id}/modify", response_model=WorkflowResponse)
async def modify_workflow(
    trip_id: UUID, request: ModifyWorkflowRequest
) -> WorkflowResponse:
    async with _project_store() as store:
        trip = await store.get_trip(request.owner_user_id, request.thread_id, trip_id)
        if trip is None:
            raise HTTPException(
                status_code=404, detail="Workflow was not found in this namespace"
            )
        current = WorkflowResponse.model_validate(trip.state)
        try:
            modification = parse_local_modification(request.instruction)
            response = _modified_workflow(current, modification)
        except ValueError as error:
            status = 409 if "Workflow" in str(error) or "revision" in str(error) else 422
            raise HTTPException(status_code=status, detail=str(error)) from error
        await _save_workflow(store, request.owner_user_id, response)
    return response


@app.post("/api/knowledge/documents", response_model=IngestedDocument)
async def create_knowledge_document(request: KnowledgeDocumentInput) -> IngestedDocument:
    ingested = ingest_document(request, _rag_embedder())
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
