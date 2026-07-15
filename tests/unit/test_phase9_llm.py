"""Requirement extraction and asynchronous Reviewer boundary regressions."""

import json

import httpx

from pilgrimage_agent.agent.llm import (
    DeterministicRequirementExtractor,
    JsonChatClient,
    LlmRequirementExtractor,
    LlmReviewer,
    ResilientRequirementExtractor,
    ResilientReviewer,
)
from pilgrimage_agent.agent.review import FixtureReviewer, StructuredOutputError
from pilgrimage_agent.agent.schemas import RequirementExtraction, ReviewerInput, ReviewerOutput


async def test_chinese_requirement_fallback_is_editable_and_discloses_assumption() -> None:
    result = await DeterministicRequirementExtractor().extract(
        "我从京都出发, 九月去东京三天, 想巡礼《孤独摇滚!》, 预算中等, 希望少走路。"
    )

    assert result.source == "deterministic_fallback"
    assert result.requirements.origin == "京都"
    assert result.requirements.destination == "东京"
    assert result.requirements.anime_query == "孤独摇滚!"
    assert result.requirements.start_date is not None
    assert result.requirements.end_date is not None
    assert (result.requirements.start_date.month, result.requirements.start_date.day) == (9, 1)
    assert (result.requirements.end_date - result.requirements.start_date).days == 2
    assert result.requirements.max_walking_meters_per_day == 5_000
    assert result.requirements.transit_route_preference == "less_walking"
    assert result.assumptions
    assert not result.missing_fields


async def test_chinese_fallback_preserves_fewer_transfer_preference() -> None:
    result = await DeterministicRequirementExtractor().extract(
        "我从京都出发, 九月去东京一天, 想巡礼《孤独摇滚!》, 尽量少换乘。"
    )

    assert result.requirements.transit_route_preference == "fewer_transfers"


async def test_fixture_reviewer_obeys_deterministic_violations() -> None:
    result = await FixtureReviewer().review(
        ReviewerInput(
            context_snapshot_id="snapshot-1",
            deterministic_violations=("walking_limit",),
            revision_count=0,
        )
    )
    assert result.action == "revise"
    assert result.target_day == 2


async def test_openai_compatible_json_boundaries_validate_extraction_and_review() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        prompt = payload["messages"][1]["content"]
        content: dict[str, object]
        if "Review this bounded" in prompt:
            content = {"action": "accept", "target_day": None, "explanation": "valid"}
        else:
            content = {
                "requirements": {
                    "origin": "Kyoto",
                    "destination": "Tokyo",
                    "anime_query": "Bocchi the Rock",
                },
                "source": "llm",
                "assumptions": [],
                "missing_fields": [],
            }
        return httpx.Response(
            200,
            json={
                "id": "fixture-completion",
                "model": "fixture-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "reasoning_content": "provider-specific metadata",
                            "content": json.dumps(content),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = JsonChatClient(
        base_url="https://llm.example.test/v1",
        model="fixture-model",
        api_key="fixture",
        timeout_seconds=1,
        max_attempts=1,
    )
    await client.http.client.aclose()
    client.http.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    extracted = await LlmRequirementExtractor(client).extract(
        "我从京都出发\uff0c九月去东京三天\uff0c想巡礼《孤独摇滚\uff01》。"
    )
    reviewed = await LlmReviewer(client).review(
        ReviewerInput(
            context_snapshot_id="snapshot-2",
            deterministic_violations=(),
            revision_count=0,
        )
    )
    await client.close()

    assert extracted.source == "llm"
    assert extracted.requirements.destination == "Tokyo"
    assert extracted.requirements.start_date is not None
    assert extracted.requirements.end_date is not None
    assert (extracted.requirements.end_date - extracted.requirements.start_date).days == 2
    assert extracted.assumptions
    assert reviewed.action == "accept"


async def test_invalid_llm_output_uses_disclosed_deterministic_fallbacks() -> None:
    class FailingExtractor:
        async def extract(self, _text: str) -> RequirementExtraction:
            raise StructuredOutputError("fixture failure")

    class FailingReviewer:
        async def review(self, _request: ReviewerInput) -> ReviewerOutput:
            raise StructuredOutputError("fixture failure")

    extracted = await ResilientRequirementExtractor(FailingExtractor()).extract(
        "fixture request"
    )
    reviewed = await ResilientReviewer(FailingReviewer(), FixtureReviewer()).review(
        ReviewerInput(
            context_snapshot_id="snapshot-3",
            deterministic_violations=(),
            revision_count=0,
        )
    )

    assert extracted.source == "deterministic_fallback"
    assert "conservative parsing" in extracted.assumptions[-1]
    assert reviewed.action == "accept"
