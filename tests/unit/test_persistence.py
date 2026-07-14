import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr

import pilgrimage_agent.db as database
from pilgrimage_agent.config import Settings
from pilgrimage_agent.db import Base
from pilgrimage_agent.persistence import TripRecord


def test_foundation_metadata_contains_namespaced_trip_indexes() -> None:
    assert TripRecord.__tablename__ == "trips"
    assert set(Base.metadata.tables["trips"].columns.keys()) == {
        "id",
        "owner_user_id",
        "thread_id",
        "state",
        "created_at",
        "updated_at",
    }


def test_engine_uses_async_postgres_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_URL=SecretStr(
            "postgresql+asyncpg://pilgrimage:pilgrimage@localhost:5432/pilgrimage"
        ),
    )
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    engine = database.create_engine()
    try:
        assert engine.url.drivername == "postgresql+asyncpg"
    finally:
        engine.sync_engine.dispose()


def test_remediation_metadata_and_migration_head_are_additive() -> None:
    required = {
        "subjects",
        "trip_subject_intents",
        "scene_evidence",
        "visit_places",
        "place_evidence_links",
        "place_subject_appearances",
        "place_resolution_overrides",
        "area_clusters",
        "area_cluster_members",
        "candidate_graph_versions",
        "itinerary_versions",
        "plan_patches",
        "agent_handoffs",
        "derived_knowledge_rules",
    }
    assert required.issubset(Base.metadata.tables)
    assert {
        column.name for column in Base.metadata.tables["trip_subject_intents"].columns
    } >= {"trip_id", "query", "priority", "is_primary", "status"}
    assert {
        column.name for column in Base.metadata.tables["scene_evidence"].columns
    } >= {"provider", "provider_record_id", "resolution_status"}

    config = Config("alembic.ini")
    assert ScriptDirectory.from_config(config).get_current_head() == "0004"
