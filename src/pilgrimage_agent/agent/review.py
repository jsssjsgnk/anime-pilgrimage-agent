"""Bounded structured-output validation for Reviewer responses."""

import json
from collections.abc import Callable

from pydantic import ValidationError

from pilgrimage_agent.agent.schemas import ReviewerInput, ReviewerOutput


class StructuredOutputError(RuntimeError):
    """The model failed to return valid bounded JSON after all attempts."""


def parse_reviewer_output(
    call: Callable[[ReviewerInput], str], request: ReviewerInput, *, max_attempts: int = 3
) -> ReviewerOutput:
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between one and three")
    for _attempt in range(max_attempts):
        try:
            raw = json.loads(call(request))
            return ReviewerOutput.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, TypeError):
            continue
    raise StructuredOutputError("reviewer returned invalid structured output")


class FixtureReviewer:
    """LLM mock that emits only the schema the real boundary accepts."""

    def __init__(self, *, always_revise: bool = False) -> None:
        self.always_revise = always_revise

    def review(self, request: ReviewerInput) -> ReviewerOutput:
        if self.always_revise or request.deterministic_violations:
            return ReviewerOutput(
                action="revise",
                target_day=2,
                explanation="Revise only the affected day while preserving stable days.",
            )
        return ReviewerOutput(action="accept", explanation="All deterministic checks passed.")
