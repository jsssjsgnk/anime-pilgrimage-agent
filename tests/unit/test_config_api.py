from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch

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
        "bangumi": True,
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


def test_uppercase_provider_mode_selects_live_runtime(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "live")
    monkeypatch.setenv("BANGUMI_MODE", "live")
    monkeypatch.setenv("PILGRIMAGE_POINT_MODE", "anitabi")
    settings = Settings(_env_file=None)

    assert settings.provider_mode == "live"
    assert settings.bangumi_mode == "live"
    diagnostics = settings.provider_diagnostics()
    assert diagnostics["bangumi"].mode == "live"
    assert diagnostics["open_meteo"].mode == "live"
    assert diagnostics["ors"].mode == "fallback"
    assert diagnostics["ors"].fallback_mode == "haversine"
    assert diagnostics["anitabi"].mode == "live"


def test_runtime_diagnostics_expose_no_configuration_values() -> None:
    response = TestClient(app).get("/api/runtime/diagnostics")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"providers"}
    assert set(payload["providers"]["bangumi"]) == {
        "mode",
        "configured",
        "status",
        "fallback_mode",
    }
    serialized = response.text.lower()
    assert "authorization" not in serialized
    assert "api_key" not in serialized
