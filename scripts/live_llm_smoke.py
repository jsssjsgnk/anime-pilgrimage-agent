"""One value-safe, read-only structured-output smoke against the configured LLM."""

from __future__ import annotations

import json

import httpx

from pilgrimage_agent.agent.schemas import ReviewerOutput
from pilgrimage_agent.config import get_settings


def main() -> int:
    settings = get_settings()
    if not settings.capability_status()["llm"]:
        print("FAIL: real LLM smoke is required but its server-side configuration is incomplete.")
        return 1
    assert settings.llm_api_key is not None
    assert settings.llm_base_url is not None
    assert settings.llm_model is not None
    endpoint = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.llm_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return only JSON matching: action accept|revise, optional target_day, "
                    "and a short explanation. Do not call tools."
                ),
            },
            {
                "role": "user",
                "content": "No deterministic violations remain. Review this fixture plan.",
            },
        ],
    }
    try:
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}"},
            json=payload,
            timeout=30,
        )
    except httpx.HTTPError:
        print("FAIL: configured LLM endpoint was unavailable; no configuration was logged.")
        return 1
    if response.status_code >= 400:
        print(f"FAIL: configured LLM returned HTTP {response.status_code}; body omitted.")
        return 1
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        ReviewerOutput.model_validate(json.loads(content))
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        print("FAIL: configured LLM did not return the required structured output; body omitted.")
        return 1
    print("PASS: one real LLM response satisfied the strict Reviewer schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
