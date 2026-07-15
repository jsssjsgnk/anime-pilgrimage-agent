"""Server-side configuration with value-safe validation messages."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderRuntimeDiagnostic(BaseModel):
    """Value-safe provider state exposed by runtime diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["live", "fixture", "fallback", "imported", "unverified"]
    configured: bool
    status: Literal["available", "unavailable", "unverified"]
    fallback_mode: Literal[
        "imported",
        "haversine",
        "detail_then_imported",
    ] | None = None


class Settings(BaseSettings):
    """Application settings. Secret values are never serialized."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    app_env: Literal["development", "test", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    database_url: SecretStr = Field(
        default=SecretStr(
            "postgresql+asyncpg://pilgrimage:pilgrimage@localhost:5432/pilgrimage"
        ),
        alias="DATABASE_URL",
    )
    llm_api_key: SecretStr | None = Field(default=None, alias="LLM_API_KEY")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")
    bangumi_access_token: SecretStr | None = Field(default=None, alias="BANGUMI_ACCESS_TOKEN")
    bangumi_user_agent: str = Field(
        default="anime-pilgrimage-agent/0.1 (contact: local-development)",
        alias="BANGUMI_USER_AGENT",
    )
    anitabi_base_url: str = Field(
        default="https://api.anitabi.cn",
        alias="ANITABI_BASE_URL",
        pattern=r"^https://api\.anitabi\.cn/?$",
    )
    anitabi_static_base_url: str = Field(
        default="https://www.anitabi.cn/d",
        alias="ANITABI_STATIC_BASE_URL",
        pattern=r"^https://www\.anitabi\.cn/d/?$",
    )
    anitabi_static_fallback_url: str = Field(
        default="https://anitabi.cn/d",
        alias="ANITABI_STATIC_FALLBACK_URL",
        pattern=r"^https://anitabi\.cn/d/?$",
    )
    anitabi_static_cache_ttl_seconds: int = Field(
        default=21_600,
        alias="ANITABI_STATIC_CACHE_TTL_SECONDS",
        ge=60,
        le=86_400,
    )
    anitabi_user_agent: str = Field(
        default="anime-pilgrimage-agent/0.1 (read-only; local-development)",
        alias="ANITABI_USER_AGENT",
    )
    pilgrimage_points_import_path: Path = Field(
        default=Path("fixtures/providers/points.geojson"),
        alias="PILGRIMAGE_POINTS_IMPORT_PATH",
    )
    ors_api_key: SecretStr | None = Field(default=None, alias="ORS_API_KEY")
    searchapi_api_key: SecretStr | None = Field(default=None, alias="SEARCHAPI_API_KEY")
    searchapi_live_smoke: bool = Field(default=False, alias="SEARCHAPI_LIVE_SMOKE")
    provider_timeout_seconds: float = Field(
        default=10.0, gt=0, le=120, alias="PROVIDER_TIMEOUT_SECONDS"
    )
    provider_max_attempts: int = Field(
        default=3, ge=1, le=5, alias="PROVIDER_MAX_ATTEMPTS"
    )
    provider_mode: Literal["fixture", "live"] = Field(
        default="fixture", alias="PROVIDER_MODE"
    )
    bangumi_mode: Literal["fixture", "live"] = Field(
        default="fixture", alias="BANGUMI_MODE"
    )
    pilgrimage_point_mode: Literal["anitabi", "imported", "fixture"] = Field(
        default="fixture", alias="PILGRIMAGE_POINT_MODE"
    )
    mcp_tools_url: str = Field(
        default="http://127.0.0.1:8001/mcp",
        alias="MCP_TOOLS_URL",
        pattern=r"^http://(?:127\.0\.0\.1|localhost|mcp-tools):8001/mcp$",
    )
    rag_bm25_index_dir: Path = Field(
        default=Path(".cache/rag-bm25"), alias="RAG_BM25_INDEX_DIR"
    )
    rag_embedding_mode: Literal["fixture", "real"] = Field(
        default="fixture", alias="RAG_EMBEDDING_MODE"
    )

    def capability_status(self) -> dict[str, bool]:
        """Return presence flags only; values never leave the server."""

        return {
            "llm": bool(self.llm_api_key and self.llm_base_url and self.llm_model),
            "bangumi": bool(self.bangumi_user_agent),
            "anitabi": True,
            "ors": bool(self.ors_api_key),
            "searchapi": bool(self.searchapi_api_key),
            "weather": True,
        }

    def provider_diagnostics(self) -> dict[str, ProviderRuntimeDiagnostic]:
        """Describe actual provider selection without returning configuration values."""

        if self.provider_mode == "fixture":
            diagnostics = {
                name: ProviderRuntimeDiagnostic(
                    mode="fixture", configured=True, status="available"
                )
                for name in ("ors", "open_meteo", "searchapi")
            }
        else:
            diagnostics = {
                "ors": ProviderRuntimeDiagnostic(
                    mode="live" if self.ors_api_key else "fallback",
                    configured=bool(self.ors_api_key),
                    status="available",
                    fallback_mode=None if self.ors_api_key else "haversine",
                ),
                "open_meteo": ProviderRuntimeDiagnostic(
                    mode="live", configured=True, status="available"
                ),
                "searchapi": ProviderRuntimeDiagnostic(
                    mode="live" if self.searchapi_api_key else "unverified",
                    configured=bool(self.searchapi_api_key),
                    status=(
                        "available"
                        if self.searchapi_api_key and self.searchapi_live_smoke
                        else "unverified"
                    ),
                ),
            }
        diagnostics["bangumi"] = ProviderRuntimeDiagnostic(
            mode=self.bangumi_mode,
            configured=True if self.bangumi_mode == "fixture" else bool(self.bangumi_user_agent),
            status=(
                "available"
                if self.bangumi_mode == "fixture" or self.bangumi_user_agent
                else "unavailable"
            ),
        )
        if self.pilgrimage_point_mode == "fixture":
            points = ProviderRuntimeDiagnostic(
                mode="fixture", configured=True, status="available"
            )
        elif self.pilgrimage_point_mode == "imported":
            points = ProviderRuntimeDiagnostic(
                mode="imported",
                configured=self.pilgrimage_points_import_path.exists(),
                status=(
                    "available"
                    if self.pilgrimage_points_import_path.exists()
                    else "unavailable"
                ),
            )
        else:
            points = ProviderRuntimeDiagnostic(
                mode="live",
                configured=True,
                status="available",
                fallback_mode="detail_then_imported",
            )
        return {**diagnostics, "anitabi": points}


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""

    return Settings()
