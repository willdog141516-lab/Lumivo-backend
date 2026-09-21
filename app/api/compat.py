from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from app.ai_client import AiClientError, ChatClient
from app.domain.chat import ChatRequest, ChatResponse, TripPlanRequest
from app.planning_service import TripPlanner, TripPlannerError
from app.settings import Settings


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


class CompatRequestError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


async def _read_json(request: Request) -> object:
    try:
        return json.loads((await request.body()).decode("utf-8"))
    except UnicodeDecodeError:
        raise CompatRequestError(400, "INVALID_REQUEST", "请求体必须是有效 JSON") from None
    except json.JSONDecodeError:
        raise CompatRequestError(400, "INVALID_REQUEST", "请求体必须是有效 JSON") from None


def _validation_message(error: ValidationError) -> str:
    message = str(error.errors()[0].get("msg", "请求参数无效"))
    return message.removeprefix("Value error, ")


async def _parse(request: Request, model: type[ChatRequest]) -> ChatRequest:
    try:
        return model.model_validate(await _read_json(request))
    except CompatRequestError:
        raise
    except ValidationError as error:
        raise CompatRequestError(400, "INVALID_REQUEST", _validation_message(error)) from None


def _provider_message(code: str) -> str:
    messages = {
        "AI_NOT_CONFIGURED": "AI 服务尚未配置",
        "AI_PROVIDER_TIMEOUT": "AI 服务响应超时，请稍后重试",
        "AI_PROVIDER_ERROR": "AI 服务暂时不可用，请稍后重试",
    }
    return messages.get(code, "服务器内部错误")


def _provider_failure(error: AiClientError) -> JSONResponse:
    status = 503 if error.code != "INTERNAL_ERROR" else 500
    return _error(status, error.code, _provider_message(error.code))


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _wants_stream(request: Request) -> bool:
    return request.query_params.get("stream") == "true" or "text/event-stream" in request.headers.get("accept", "")


def _planner_failure(error: TripPlannerError) -> JSONResponse:
    messages = {
        "UNSUPPORTED_REGION": "暂不支持该地区，等待后续开发",
        "PLAN_NOT_AVAILABLE": "当前目的地的可播放行程尚未接入",
        "POI_NOT_FOUND": "未找到可用的真实地点",
        "ROUTE_UNAVAILABLE": "未找到可用的真实路线",
        "MAP_PROVIDER_TIMEOUT": "百度地图服务响应超时，请稍后重试",
        "MAP_PROVIDER_ERROR": "百度地图服务暂时不可用，请检查地图配置后重试",
        "MODEL_OUTPUT_INVALID": "AI 返回的行程选择无法通过校验",
        "PLAN_INPUT_REQUIRED": "请补充目的地和旅行天数",
    }
    status = 503 if error.code in {
        "MODEL_OUTPUT_INVALID",
        "MAP_PROVIDER_TIMEOUT",
        "MAP_PROVIDER_ERROR",
    } else 422
    return _error(status, error.code, messages.get(error.code, "服务器内部错误"))


def create_compat_router(
    settings: Settings,
    chat_client: ChatClient,
    planner: TripPlanner,
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "model": settings.ai_model}

    @router.post("/api/chat")
    async def chat(request: Request) -> Response:
        try:
            parsed = await _parse(request, ChatRequest)
            if _wants_stream(request):
                async def events():
                    try:
                        async for content in chat_client.stream(parsed):
                            yield _sse("delta", {"content": content})
                        yield _sse("done", {})
                    except AiClientError as error:
                        yield _sse(
                            "error",
                            {"error": {"code": error.code, "message": _provider_message(error.code)}},
                        )
                    except Exception:
                        yield _sse(
                            "error",
                            {"error": {"code": "INTERNAL_ERROR", "message": "服务器内部错误"}},
                        )

                return StreamingResponse(
                    events(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            response = await chat_client.complete(parsed)
            return JSONResponse(content=ChatResponse.model_validate(response).model_dump(mode="json"))
        except CompatRequestError as error:
            return _error(error.status, error.code, error.message)
        except AiClientError as error:
            return _provider_failure(error)
        except Exception:
            return _error(500, "INTERNAL_ERROR", "服务器内部错误")

    @router.post("/api/trips/plan")
    async def plan(request: Request) -> JSONResponse:
        try:
            parsed = await _parse(request, TripPlanRequest)
            result = await planner.plan(parsed)  # type: ignore[arg-type]
            return JSONResponse(
                content=result.model_dump(mode="json", by_alias=True, exclude_none=True)
            )
        except CompatRequestError as error:
            return _error(error.status, error.code, error.message)
        except TripPlannerError as error:
            return _planner_failure(error)
        except AiClientError as error:
            return _provider_failure(error)
        except Exception:
            return _error(500, "INTERNAL_ERROR", "服务器内部错误")

    return router
