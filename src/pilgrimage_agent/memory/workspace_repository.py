"""Transactional normalized persistence for remediated workspace projections."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pilgrimage_agent.agent.workspace import WorkspaceState
from pilgrimage_agent.persistence import (
    AgentHandoffRecord,
    AreaClusterMemberRecord,
    AreaClusterRecord,
    CandidateGraphVersionRecord,
    DerivedKnowledgeRuleRecord,
    ItineraryVersionRecord,
    PlaceEvidenceLinkRecord,
    PlaceSubjectAppearanceRecord,
    PlanPatchRecord,
    SceneEvidenceRecord,
    SubjectRecord,
    TripSubjectIntentRecord,
    VisitPlaceRecord,
)


class SqlWorkspaceRepository:
    """Upsert immutable/versioned workspace entities after the trip JSON transaction."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def save_projection(self, state: WorkspaceState) -> None:
        async with self.sessions.begin() as session:
            for confirmed in state.confirmed_subjects:
                payload = confirmed.subject.model_dump(mode="json")
                statement = insert(SubjectRecord).values(
                    subject_id=confirmed.subject.subject_id,
                    normalized_payload=payload,
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[SubjectRecord.subject_id],
                        set_={"normalized_payload": statement.excluded.normalized_payload},
                    )
                )
            for intent in state.requirements.subject_intents:
                statement = insert(TripSubjectIntentRecord).values(
                    id=intent.intent_id,
                    trip_id=state.trip_id,
                    query=intent.query,
                    confirmed_subject_id=intent.confirmed_subject_id,
                    priority=intent.priority,
                    minimum_place_count=intent.minimum_place_count,
                    is_primary=intent.is_primary,
                    status=intent.status,
                    normalized_payload=intent.model_dump(mode="json"),
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[TripSubjectIntentRecord.id],
                        set_={
                            "query": statement.excluded.query,
                            "confirmed_subject_id": statement.excluded.confirmed_subject_id,
                            "priority": statement.excluded.priority,
                            "minimum_place_count": statement.excluded.minimum_place_count,
                            "is_primary": statement.excluded.is_primary,
                            "status": statement.excluded.status,
                            "normalized_payload": statement.excluded.normalized_payload,
                        },
                    )
                )
            for evidence in state.evidence:
                coordinate = evidence.coordinate
                statement = insert(SceneEvidenceRecord).values(
                    id=evidence.evidence_id,
                    trip_id=state.trip_id,
                    subject_id=evidence.subject_id,
                    provider=evidence.provider,
                    provider_record_id=evidence.provider_record_id,
                    latitude=coordinate.latitude if coordinate else None,
                    longitude=coordinate.longitude if coordinate else None,
                    resolution_status=evidence.resolution_status.value,
                    normalized_payload=evidence.model_dump(mode="json"),
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[SceneEvidenceRecord.id],
                        set_={
                            "resolution_status": statement.excluded.resolution_status,
                            "normalized_payload": statement.excluded.normalized_payload,
                        },
                    )
                )
            for place in state.places:
                statement = insert(VisitPlaceRecord).values(
                    id=place.place_id,
                    trip_id=state.trip_id,
                    canonical_name=place.canonical_name,
                    latitude=place.coordinate.latitude,
                    longitude=place.coordinate.longitude,
                    verification_status=place.verification_status,
                    resolution_version=place.resolution_version,
                    normalized_payload=place.model_dump(mode="json"),
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[VisitPlaceRecord.id],
                        set_={
                            "canonical_name": statement.excluded.canonical_name,
                            "latitude": statement.excluded.latitude,
                            "longitude": statement.excluded.longitude,
                            "verification_status": statement.excluded.verification_status,
                            "resolution_version": statement.excluded.resolution_version,
                            "normalized_payload": statement.excluded.normalized_payload,
                        },
                    )
                )
                for evidence_id in place.scene_evidence_ids:
                    await session.execute(
                        insert(PlaceEvidenceLinkRecord)
                        .values(place_id=place.place_id, evidence_id=evidence_id)
                        .on_conflict_do_nothing()
                    )
                for appearance in place.subject_appearances:
                    appearance_statement = insert(PlaceSubjectAppearanceRecord).values(
                        place_id=place.place_id,
                        subject_id=appearance.subject_id,
                        evidence_ids=[str(item) for item in appearance.evidence_ids],
                    )
                    await session.execute(
                        appearance_statement.on_conflict_do_update(
                            index_elements=[
                                PlaceSubjectAppearanceRecord.place_id,
                                PlaceSubjectAppearanceRecord.subject_id,
                            ],
                            set_={"evidence_ids": appearance_statement.excluded.evidence_ids},
                        )
                    )
            graph_version = (
                state.candidate_graph.version
                if state.candidate_graph is not None
                else state.state_version
            )
            itinerary_by_id = {
                item.itinerary_id: item
                for item in (*state.archived_itineraries, *state.itineraries)
            }
            itinerary_delete = delete(ItineraryVersionRecord).where(
                ItineraryVersionRecord.trip_id == state.trip_id
            )
            if itinerary_by_id:
                itinerary_delete = itinerary_delete.where(
                    ItineraryVersionRecord.id.not_in(tuple(itinerary_by_id))
                )
            await session.execute(itinerary_delete)
            for area in state.areas:
                statement = insert(AreaClusterRecord).values(
                    id=area.area_id,
                    trip_id=state.trip_id,
                    graph_version=graph_version,
                    algorithm=area.algorithm,
                    normalized_payload=area.model_dump(mode="json"),
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[AreaClusterRecord.id],
                        set_={
                            "graph_version": statement.excluded.graph_version,
                            "algorithm": statement.excluded.algorithm,
                            "normalized_payload": statement.excluded.normalized_payload,
                        },
                    )
                )
                for place_id in area.place_ids:
                    await session.execute(
                        insert(AreaClusterMemberRecord)
                        .values(area_id=area.area_id, place_id=place_id)
                        .on_conflict_do_nothing()
                    )
            if state.candidate_graph is not None:
                graph = state.candidate_graph
                graph_statement = insert(CandidateGraphVersionRecord).values(
                    id=graph.graph_id,
                    trip_id=state.trip_id,
                    version=graph.version,
                    evidence_status=graph.evidence_status,
                    normalized_payload=graph.model_dump(mode="json"),
                    created_at=graph.created_at,
                )
                await session.execute(
                    graph_statement.on_conflict_do_update(
                        index_elements=[CandidateGraphVersionRecord.id],
                        set_={
                            "evidence_status": graph_statement.excluded.evidence_status,
                            "normalized_payload": graph_statement.excluded.normalized_payload,
                        },
                    )
                )
                for itinerary in itinerary_by_id.values():
                    itinerary_statement = insert(ItineraryVersionRecord).values(
                        id=itinerary.itinerary_id,
                        trip_id=state.trip_id,
                        candidate_graph_id=graph.graph_id,
                        branch_key=itinerary.strategy.value,
                        version=itinerary.version,
                        parent_version=itinerary.parent_version,
                        strategy=itinerary.strategy.value,
                        normalized_payload=itinerary.model_dump(mode="json"),
                        created_at=itinerary.created_at,
                    )
                    await session.execute(
                        itinerary_statement.on_conflict_do_update(
                            index_elements=[ItineraryVersionRecord.id],
                            set_={
                                "normalized_payload": (
                                    itinerary_statement.excluded.normalized_payload
                                )
                            },
                        )
                    )
            for patch in state.patches:
                patch_statement = insert(PlanPatchRecord).values(
                    id=patch.patch_id,
                    trip_id=state.trip_id,
                    idempotency_key=patch.idempotency_key,
                    expected_base_version=patch.expected_base_version,
                    status=patch.status,
                    normalized_payload=patch.model_dump(mode="json"),
                    created_at=patch.created_at,
                )
                await session.execute(
                    patch_statement.on_conflict_do_update(
                        index_elements=[PlanPatchRecord.id],
                        set_={
                            "status": patch_statement.excluded.status,
                            "normalized_payload": patch_statement.excluded.normalized_payload,
                        },
                    )
                )
            for handoff in state.handoffs:
                handoff_statement = insert(AgentHandoffRecord).values(
                    id=handoff.handoff_id,
                    trip_id=state.trip_id,
                    run_id=handoff.run_id,
                    sender=handoff.sender.value,
                    receiver=handoff.receiver.value,
                    status=handoff.status,
                    normalized_payload=handoff.model_dump(mode="json"),
                    created_at=handoff.created_at,
                    completed_at=handoff.completed_at,
                )
                await session.execute(
                    handoff_statement.on_conflict_do_update(
                        index_elements=[AgentHandoffRecord.id],
                        set_={
                            "status": handoff_statement.excluded.status,
                            "normalized_payload": handoff_statement.excluded.normalized_payload,
                            "completed_at": handoff_statement.excluded.completed_at,
                        },
                    )
                )
            for rule in state.knowledge_rules:
                rule_statement = insert(DerivedKnowledgeRuleRecord).values(
                    id=rule.rule_id,
                    trip_id=state.trip_id,
                    rule_type=rule.rule_type,
                    status=rule.status,
                    normalized_payload=rule.model_dump(mode="json"),
                    created_at=rule.created_at,
                )
                await session.execute(
                    rule_statement.on_conflict_do_update(
                        index_elements=[DerivedKnowledgeRuleRecord.id],
                        set_={
                            "status": rule_statement.excluded.status,
                            "normalized_payload": rule_statement.excluded.normalized_payload,
                        },
                    )
                )
