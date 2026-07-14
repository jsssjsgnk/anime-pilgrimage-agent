"""Server-side configuration with value-safe validation messages."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Secret values are never serialized."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
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
    provider_timeout_seconds: float = 10.0
    provider_max_attempts: int = 3
    provider_mode: Literal["fixture", "live"] = "fixture"
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
            "bangumi": bool(self.bangumi_access_token and self.bangumi_user_agent),
            "anitabi": True,
            "ors": bool(self.ors_api_key),
            "searchapi": bool(self.searchapi_api_key),
            "weather": True,
        }


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""

    return Settings()
