"""Context minimization and structured Reviewer boundary tests."""

import json

import pytest

from pilgrimage_agent.agent.context import ContextBuilder
from pilgrimage_agent.agent.review import StructuredOutputError, parse_reviewer_output
from pilgrimage_agent.agent.schemas import ReviewerInput, ReviewerOutput, RunMetric


def test_context_snapshot_contains_minimal_safe_projection() -> None:
    snapshot = ContextBuilder().build(
        node="reviewer",
        owner_user_id="user-a",
        thread_id="thread-a",
        trip_id="trip-a",
        facts=("walking limit is 5 km",),
        route_a_point_ids=("point-1",),
        relevant_knowledge_ids=("knowledge-1",),
    )
    payload = json.dumps(ContextBuilder.safe_projection(snapshot))
    for forbidden in ("prior private message", "credential-value", "Bearer secret"):
        assert forbidden not in payload
    assert snapshot.estimated_tokens < 100
    assert snapshot.state_ids == ("user-a", "thread-a", "trip-a")


def test_invalid_llm_json_retries_with_a_hard_limit() -> None:
    calls = 0

    def invalid_then_valid(_request: ReviewerInput) -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            return "not-json"
        return '{"action":"accept","explanation":"validated"}'

    result = parse_reviewer_output(
        invalid_then_valid,
        ReviewerInput(
            context_snapshot_id="snapshot-1",
            deterministic_violations=(),
            revision_count=0,
        ),
    )
    assert result == ReviewerOutput(action="accept", explanation="validated")
    assert calls == 3


def test_persistently_invalid_llm_json_is_structured_error() -> None:
    with pytest.raises(StructuredOutputError, match="invalid structured output"):
        parse_reviewer_output(
            lambda _request: "{}",
            ReviewerInput(
                context_snapshot_id="snapshot-1",
                deterministic_violations=(),
                revision_count=0,
            ),
            max_attempts=2,
        )


def test_metrics_schema_has_no_prompt_or_content_fields() -> None:
    metric = RunMetric(node="reviewer", duration_ms=12, retry_count=1, outcome="ok")
    assert set(metric.model_dump()) == {"run_id", "node", "duration_ms", "retry_count", "outcome"}
