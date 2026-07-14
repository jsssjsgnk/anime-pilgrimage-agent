"""Exercise normalized workspace persistence against the project PostgreSQL database."""

from __future__ import annotations

import asyncio
import json
import selectors
from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pilgrimage_agent.agent.mcp_client import FixtureAgentToolClient
from pilgrimage_agent.agent.workspace import (
    ConfirmWorkspaceSubjectsRequest,
    PlanWorkspaceRequest,
    SubjectConfirmation,
    WorkspaceAgent,
    WorkspaceStartRequest,
)
from pilgrimage_agent.config import get_settings
from pilgrimage_agent.domain.models import SubjectIntent, TripRequest
from pilgrimage_agent.memory.schemas import StoredTrip
from pilgrimage_agent.memory.store import SqlProjectStore
from pilgrimage_agent.memory.workspace_repository import SqlWorkspaceRepository
from pilgrimage_agent.persistence import (
    AgentHandoffRecord,
    AreaClusterRecord,
    CandidateGraphVersionRecord,
    ItineraryVersionRecord,
    SceneEvidenceRecord,
    TripRecord,
    VisitPlaceRecord,
)


async def main() -> None:
    database_url = get_settings().database_url.get_secret_value().replace(
        "@postgres:", "@localhost:"
    )
    engine = create_async_engine(
        database_url, pool_pre_ping=True
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    agent = WorkspaceAgent(FixtureAgentToolClient())
    start_date = date.today() + timedelta(days=45)
    initial = await agent.start(
        WorkspaceStartRequest(
            owner_user_id="workspace-smoke",
            thread_id="normalized-projection",
            request_summary="两天巡礼《孤独摇滚》。",
            requirements=TripRequest(
                start_date=start_date,
                end_date=start_date + timedelta(days=1),
                anime_query="孤独摇滚",
                subject_intents=(
                    SubjectIntent(query="孤独摇滚", priority=5, is_primary=True),
                ),
            ),
        )
    )
    persisted = False
    try:
        group = initial.subject_groups[0]
        curated = await agent.confirm_subjects(
            initial,
            ConfirmWorkspaceSubjectsRequest(
                owner_user_id=initial.owner_user_id,
                thread_id=initial.thread_id,
                expected_state_version=initial.state_version,
                confirmations=(
                    SubjectConfirmation(
                        intent_id=group.intent.intent_id,
                        decision="accept",
                        selected_subject_id=group.candidates[0].subject_id,
                    ),
                ),
            ),
        )
        planned = agent.plan(
            curated,
            PlanWorkspaceRequest(
                owner_user_id=curated.owner_user_id,
                thread_id=curated.thread_id,
                expected_state_version=curated.state_version,
                base_id=curated.base_candidates[0].base_id,
            ),
        )
        store = SqlProjectStore(sessions)
        await store.save_trip(
            StoredTrip(
                trip_id=planned.trip_id,
                owner_user_id=planned.owner_user_id,
                thread_id=planned.thread_id,
                state=planned.model_dump(mode="json"),
            )
        )
        persisted = True
        await SqlWorkspaceRepository(sessions).save_projection(planned)
        record_types = (
            SceneEvidenceRecord,
            VisitPlaceRecord,
            AreaClusterRecord,
            CandidateGraphVersionRecord,
            ItineraryVersionRecord,
            AgentHandoffRecord,
        )
        async with sessions() as session:
            counts = {
                record.__tablename__: await session.scalar(
                    select(func.count()).select_from(record).where(
                        record.trip_id == planned.trip_id
                    )
                )
                for record in record_types
            }
        if any(not value for value in counts.values()):
            raise RuntimeError("normalized workspace projection is incomplete")
        print(json.dumps({"status": "pass", "counts": counts}, sort_keys=True))
    finally:
        if persisted:
            async with sessions.begin() as session:
                await session.execute(
                    delete(TripRecord).where(TripRecord.id == initial.trip_id)
                )
        await engine.dispose()


if __name__ == "__main__":
    with asyncio.Runner(
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
    ) as runner:
        runner.run(main())
