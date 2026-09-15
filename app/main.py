from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai_client import ChatClient, OpenAICompatibleChatClient
from app.api.compat import create_compat_router
from app.api.health import create_health_router
from app.baidu_map import BaiduMapAdapter
from app.model_provider import OpenAIModelAdapter
from app.planning_service import FixtureTripPlanner, TripPlanner
from app.real_planning_service import RealTripPlanner
from app.settings import Settings, get_settings


MAX_BODY_BYTES = 64 * 1024


def create_app(
    settings: Settings | None = None,
    chat_client: ChatClient | None = None,
    planner: FixtureTripPlanner | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_chat_client = chat_client or OpenAICompatibleChatClient(resolved_settings)
    if planner is not None:
        resolved_planner: TripPlanner = planner
    elif resolved_settings.provider_mode == "fixture":
        resolved_planner = FixtureTripPlanner(resolved_chat_client)
    else:
        resolved_planner = RealTripPlanner(
            BaiduMapAdapter(resolved_settings),
            OpenAIModelAdapter(resolved_chat_client),
        )
    application = FastAPI(title=resolved_settings.app_name, version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    @application.middleware("http")
    async def reject_oversized_bodies(request: Request, call_next):
        content_length = request.headers.get("content-length")
        try:
            oversized = content_length is not None and int(content_length) > MAX_BODY_BYTES
        except ValueError:
            oversized = False
        if oversized:
            return JSONResponse(
                status_code=413,
                content={"error": {"code": "INVALID_REQUEST", "message": "请求体不能超过 64 KiB"}},
            )
        return await call_next(request)

    application.include_router(create_compat_router(resolved_settings, resolved_chat_client, resolved_planner))
    application.include_router(create_health_router(resolved_settings), prefix="/api/v1")
    return application


app = create_app()
