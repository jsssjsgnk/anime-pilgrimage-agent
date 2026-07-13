"""Server-side configuration with value-safe validation messages."""

from functools import lru_cache
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
    ors_api_key: SecretStr | None = Field(default=None, alias="ORS_API_KEY")
    searchapi_api_key: SecretStr | None = Field(default=None, alias="SEARCHAPI_API_KEY")
    provider_timeout_seconds: float = 10.0
    provider_max_attempts: int = 3

    def capability_status(self) -> dict[str, bool]:
        """Return presence flags only; values never leave the server."""

        return {
            "llm": bool(self.llm_api_key and self.llm_base_url and self.llm_model),
            "bangumi": bool(self.bangumi_access_token and self.bangumi_user_agent),
            "ors": bool(self.ors_api_key),
            "searchapi": bool(self.searchapi_api_key),
            "weather": True,
        }


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""

    return Settings()
