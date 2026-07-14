from fastapi.testclient import TestClient
from pydantic import SecretStr

from pilgrimage_agent.api.main import app
from pilgrimage_agent.config import Settings


def test_capabilities_expose_presence_only() -> None:
    settings = Settings(
        _env_file=None,
        LLM_API_KEY=SecretStr("secret-value"),
        LLM_BASE_URL="https://llm.example.test/v1",
        LLM_MODEL="model-id",
        BANGUMI_ACCESS_TOKEN=None,
        BANGUMI_USER_AGENT="fixture-agent",
        ORS_API_KEY=None,
        SEARCHAPI_API_KEY=None,
    )
    assert settings.capability_status() == {
        "llm": True,
        "bangumi": False,
        "anitabi": True,
        "ors": False,
        "searchapi": False,
        "weather": True,
    }
    assert "secret-value" not in repr(settings)


def test_health_does_not_require_external_services() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api",
        "version": "0.1.0",
        "database": "not_checked",
    }


def test_capability_endpoint_never_returns_values() -> None:
    response = TestClient(app).get("/api/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"capabilities"}
    assert all(isinstance(value, bool) for value in payload["capabilities"].values())
