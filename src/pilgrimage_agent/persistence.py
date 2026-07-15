"""Project-owned persistence records with explicit namespace columns."""

from datetime import date, datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from pilgrimage_agent.db import Base


class TripRecord(Base):
    __tablename__ = "trips"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_user_id: Mapped[str] = mapped_column(String(120), index=True)
    thread_id: Mapped[str] = mapped_column(String(120), index=True)
    state: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TripEventRecord(Base):
    __tablename__ = "trip_events"
    __table_args__ = (Index("ix_trip_events_namespace", "owner_user_id", "trip_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserPreferenceRecord(Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "preference_key", name="uq_preference_namespace_key"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_user_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    preference_key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    explicit_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class KnowledgeRecord(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("ix_knowledge_namespace", "owner_user_id", "namespace"),
        UniqueConstraint("namespace", "content_sha256", name="uq_knowledge_namespace_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    namespace: Mapped[str] = mapped_column(String(120), nullable=False)
    trip_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="Untitled")
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="synthetic_test")
    authority_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="und")
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    accessed_at: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    subject_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    location_tags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    point_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="0" * 64)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    extraction_warning: Mapped[str | None] = mapped_column(String(300), nullable=True)
    document_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class KnowledgeChunkRecord(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "ordinal", name="uq_chunk_ordinal"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(nullable=False)
    section_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page_start: Mapped[int | None] = mapped_column(nullable=True)
    page_end: Mapped[int | None] = mapped_column(nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(nullable=False)
    lexical_tokens: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    chunk_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ToolCacheRecord(Base):
    __tablename__ = "tool_cache"

    fingerprint: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SubjectRecord(Base):
    __tablename__ = "subjects"

    subject_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TripSubjectIntentRecord(Base):
    __tablename__ = "trip_subject_intents"
    __table_args__ = (
        Index("ix_trip_subject_intents_trip_priority", "trip_id", "priority"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    query: Mapped[str] = mapped_column(String(200), nullable=False)
    confirmed_subject_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("subjects.subject_id"), nullable=True
    )
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    minimum_place_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class SceneEvidenceRecord(Base):
    __tablename__ = "scene_evidence"
    __table_args__ = (
        UniqueConstraint(
            "trip_id",
            "provider",
            "provider_record_id",
            "subject_id",
            name="uq_scene_evidence_provider_record",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_record_id: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution_status: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class VisitPlaceRecord(Base):
    __tablename__ = "visit_places"
    __table_args__ = (Index("ix_visit_places_trip", "trip_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(30), nullable=False)
    resolution_version: Mapped[str] = mapped_column(String(40), nullable=False)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class PlaceEvidenceLinkRecord(Base):
    __tablename__ = "place_evidence_links"

    place_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("visit_places.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scene_evidence.id", ondelete="CASCADE"),
        primary_key=True,
    )


class PlaceSubjectAppearanceRecord(Base):
    __tablename__ = "place_subject_appearances"

    place_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("visit_places.id", ondelete="CASCADE"),
        primary_key=True,
    )
    subject_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


class PlaceResolutionOverrideRecord(Base):
    __tablename__ = "place_resolution_overrides"
    __table_args__ = (Index("ix_place_resolution_overrides_trip", "trip_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AreaClusterRecord(Base):
    __tablename__ = "area_clusters"
    __table_args__ = (Index("ix_area_clusters_trip_version", "trip_id", "graph_version"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(40), nullable=False)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class AreaClusterMemberRecord(Base):
    __tablename__ = "area_cluster_members"

    area_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("area_clusters.id", ondelete="CASCADE"),
        primary_key=True,
    )
    place_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("visit_places.id", ondelete="CASCADE"),
        primary_key=True,
    )


class CandidateGraphVersionRecord(Base):
    __tablename__ = "candidate_graph_versions"
    __table_args__ = (
        UniqueConstraint("trip_id", "version", name="uq_candidate_graph_trip_version"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_status: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ItineraryVersionRecord(Base):
    __tablename__ = "itinerary_versions"
    __table_args__ = (
        UniqueConstraint(
            "trip_id", "branch_key", "version", name="uq_itinerary_branch_version"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    candidate_graph_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("candidate_graph_versions.id"), nullable=False
    )
    branch_key: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlanPatchRecord(Base):
    __tablename__ = "plan_patches"
    __table_args__ = (
        UniqueConstraint("trip_id", "idempotency_key", name="uq_plan_patch_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    expected_base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentHandoffRecord(Base):
    __tablename__ = "agent_handoffs"
    __table_args__ = (Index("ix_agent_handoffs_trip_run", "trip_id", "run_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    sender: Mapped[str] = mapped_column(String(40), nullable=False)
    receiver: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DerivedKnowledgeRuleRecord(Base):
    __tablename__ = "derived_knowledge_rules"
    __table_args__ = (Index("ix_derived_knowledge_rules_trip_status", "trip_id", "status"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    rule_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
