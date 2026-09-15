from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.settings import ProviderMode, Settings


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str
    provider_mode: ProviderMode
    map_mode: Literal["mock", "baidu"]
    model_mode: Literal["mock", "real"]


def _adapter_modes(provider_mode: ProviderMode) -> tuple[Literal["mock", "baidu"], Literal["mock", "real"]]:
    if provider_mode == "fixture":
        return "mock", "mock"
    return "baidu", "real"


def create_health_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        map_mode, model_mode = _adapter_modes(settings.provider_mode)
        return HealthResponse(
            status="ok",
            service=settings.app_name,
            environment=settings.environment,
            provider_mode=settings.provider_mode,
            map_mode=map_mode,
            model_mode=model_mode,
        )

    return router
