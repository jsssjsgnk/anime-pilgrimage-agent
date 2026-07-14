"""Add remediated evidence graph, plan versions, patches, and Agent handoffs.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subjects",
        sa.Column("subject_id", sa.String(50), primary_key=True),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "trip_subject_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query", sa.String(200), nullable=False),
        sa.Column("confirmed_subject_id", sa.String(50)),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("minimum_place_count", sa.SmallInteger()),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["confirmed_subject_id"], ["subjects.subject_id"]),
    )
    op.create_index(
        "ix_trip_subject_intents_trip_priority",
        "trip_subject_intents",
        ["trip_id", "priority"],
    )
    op.create_table(
        "scene_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("provider_record_id", sa.String(200), nullable=False),
        sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()),
        sa.Column("resolution_status", sa.String(20), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "trip_id",
            "provider",
            "provider_record_id",
            "subject_id",
            name="uq_scene_evidence_provider_record",
        ),
    )
    op.create_index(op.f("ix_scene_evidence_subject_id"), "scene_evidence", ["subject_id"])
    op.create_table(
        "visit_places",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_name", sa.String(300), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.Column("resolution_version", sa.String(40), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_visit_places_trip", "visit_places", ["trip_id"])
    op.create_table(
        "place_evidence_links",
        sa.Column("place_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(["place_id"], ["visit_places.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["scene_evidence.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "place_subject_appearances",
        sa.Column("place_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject_id", sa.String(50), primary_key=True),
        sa.Column("evidence_ids", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["place_id"], ["visit_places.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "place_resolution_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_place_resolution_overrides_trip", "place_resolution_overrides", ["trip_id"]
    )
    op.create_table(
        "area_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_version", sa.Integer(), nullable=False),
        sa.Column("algorithm", sa.String(40), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_area_clusters_trip_version", "area_clusters", ["trip_id", "graph_version"]
    )
    op.create_table(
        "area_cluster_members",
        sa.Column("area_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("place_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(["area_id"], ["area_clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["place_id"], ["visit_places.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "candidate_graph_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("evidence_status", sa.String(20), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("trip_id", "version", name="uq_candidate_graph_trip_version"),
    )
    op.create_table(
        "itinerary_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_graph_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_key", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version", sa.Integer()),
        sa.Column("strategy", sa.String(40), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_graph_id"], ["candidate_graph_versions.id"]),
        sa.UniqueConstraint(
            "trip_id", "branch_key", "version", name="uq_itinerary_branch_version"
        ),
    )
    op.create_table(
        "plan_patches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("expected_base_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("trip_id", "idempotency_key", name="uq_plan_patch_idempotency"),
    )
    op.create_table(
        "agent_handoffs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender", sa.String(40), nullable=False),
        sa.Column("receiver", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_handoffs_trip_run", "agent_handoffs", ["trip_id", "run_id"])
    op.create_table(
        "derived_knowledge_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_derived_knowledge_rules_trip_status",
        "derived_knowledge_rules",
        ["trip_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_derived_knowledge_rules_trip_status", table_name="derived_knowledge_rules"
    )
    op.drop_table("derived_knowledge_rules")
    op.drop_index("ix_agent_handoffs_trip_run", table_name="agent_handoffs")
    op.drop_table("agent_handoffs")
    op.drop_table("plan_patches")
    op.drop_table("itinerary_versions")
    op.drop_table("candidate_graph_versions")
    op.drop_table("area_cluster_members")
    op.drop_index("ix_area_clusters_trip_version", table_name="area_clusters")
    op.drop_table("area_clusters")
    op.drop_index(
        "ix_place_resolution_overrides_trip", table_name="place_resolution_overrides"
    )
    op.drop_table("place_resolution_overrides")
    op.drop_table("place_subject_appearances")
    op.drop_table("place_evidence_links")
    op.drop_index("ix_visit_places_trip", table_name="visit_places")
    op.drop_table("visit_places")
    op.drop_index(op.f("ix_scene_evidence_subject_id"), table_name="scene_evidence")
    op.drop_table("scene_evidence")
    op.drop_index(
        "ix_trip_subject_intents_trip_priority", table_name="trip_subject_intents"
    )
    op.drop_table("trip_subject_intents")
    op.drop_table("subjects")
