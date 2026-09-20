from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ProviderMode = Literal["fixture", "map-real", "full-real"]


class Settings(BaseSettings):
    """Process-wide configuration loaded from safe defaults and the environment."""

    app_name: str = "Lumivo Backend"
    environment: str = "development"
    provider_mode: ProviderMode = "fixture"
    frontend_origin: str = Field(
        default="http://localhost:8989",
        validation_alias=AliasChoices("LUMIVO_FRONTEND_ORIGIN", "CORS_ORIGIN"),
    )
    ai_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices("LUMIVO_AI_BASE_URL", "AI_BASE_URL"),
    )
    ai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LUMIVO_AI_API_KEY",
            "AI_API_KEY",
            "DEEPSEEK_API_KEY",
        ),
    )
    ai_model: str = Field(
        default="deepseek-chat",
        validation_alias=AliasChoices("LUMIVO_AI_MODEL", "AI_MODEL"),
    )
    ai_timeout_ms: int = Field(
        default=30_000,
        ge=1_000,
        le=120_000,
        validation_alias=AliasChoices("LUMIVO_AI_TIMEOUT_MS", "AI_TIMEOUT_MS"),
    )
    baidu_map_ak: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LUMIVO_BAIDU_MAP_AK", "BAIDU_MAP_AK"),
    )
    baidu_map_sk: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LUMIVO_BAIDU_MAP_SK", "BAIDU_MAP_SK"),
    )
    map_base_url: str = Field(
        default="https://api.map.baidu.com",
        validation_alias=AliasChoices("LUMIVO_MAP_BASE_URL", "MAP_BASE_URL"),
    )
    map_timeout_ms: int = Field(
        default=10_000,
        ge=1_000,
        le=120_000,
        validation_alias=AliasChoices("LUMIVO_MAP_TIMEOUT_MS", "MAP_TIMEOUT_MS"),
    )

    model_config = SettingsConfigDict(
        env_prefix="LUMIVO_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process settings used by the application factory."""

    return Settings()
