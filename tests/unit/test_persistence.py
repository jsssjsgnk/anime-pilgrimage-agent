import pytest
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
