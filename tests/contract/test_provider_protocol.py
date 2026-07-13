from dataclasses import dataclass

import pytest
from pydantic import BaseModel, ConfigDict

from pilgrimage_agent.providers.base import Provider


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    subject_id: str


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str
    count: int


@dataclass(frozen=True)
class FixtureProvider:
    async def fetch(self, query: Query) -> Result:
        return Result(provider="fixture", count=1 if query.subject_id else 0)


@pytest.mark.asyncio
async def test_fixture_provider_obeys_typed_read_only_contract() -> None:
    provider: Provider[Query, Result] = FixtureProvider()
    result = await provider.fetch(Query(subject_id="1"))
    assert result == Result(provider="fixture", count=1)

