from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from app.domain.chat import TripPlanRequest, TripRevisionRequest
from app.domain.trips import PlanningResult
from app.planning_service import ProgressCallback, TripPlanner, TripPlannerError


Operation = Callable[[ProgressCallback], Awaitable[PlanningResult]]

PLANNER_MESSAGES = {
    "UNSUPPORTED_REGION": "暂不支持该地区，等待后续开发",
    "PLAN_NOT_AVAILABLE": "当前目的地的可播放行程尚未接入",
    "POI_NOT_FOUND": "未找到可用的真实地点",
    "ROUTE_UNAVAILABLE": "未找到可用的真实路线",
    "MAP_PROVIDER_TIMEOUT": "百度地图服务响应超时，请稍后重试",
    "MAP_PROVIDER_ERROR": "百度地图服务暂时不可用，请检查地图配置后重试",
    "MODEL_PROVIDER_TIMEOUT": "AI 服务响应超时，请稍后重试",
    "MODEL_OUTPUT_INVALID": "AI 返回的行程选择无法通过校验",
    "PLAN_INCOMPLETE": "行程不完整，无法播放",
}
RETRYABLE_CODES = {
    "MAP_PROVIDER_TIMEOUT",
    "MAP_PROVIDER_ERROR",
    "MODEL_PROVIDER_TIMEOUT",
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _validation_message(error: ValidationError) -> str:
    message = str(error.errors()[0].get("msg", "请求参数无效"))
    return message.removeprefix("Value error, ")


async def _parse(
    request: Request,
    model: type[BaseModel],
) -> BaseModel | JSONResponse:
    try:
        payload = await request.json()
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _error(400, "INVALID_REQUEST", "请求体必须是有效 JSON")
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        return _error(400, "INVALID_REQUEST", _validation_message(error))


def _safe_error(error: TripPlannerError | None) -> dict[str, object]:
    code = error.code if error is not None and error.code in PLANNER_MESSAGES else "INTERNAL_ERROR"
    message = PLANNER_MESSAGES.get(code, "服务器内部错误")
    return {
        "code": code,
        "message": message,
        "retryable": code in RETRYABLE_CODES,
        "details": {},
    }


def _line(
    event: str,
    request_id: str,
    sequence: int,
    *,
    data: object | None = None,
    error: dict[str, object] | None = None,
) -> str:
    payload: dict[str, object] = {
        "event": event,
        "requestId": request_id,
        "sequence": sequence,
    }
    if data is not None:
        payload["data"] = data
    if error is not None:
        payload["error"] = error
    return json.dumps(payload, ensure_ascii=False) + "\n"


async def _stream_events(
    request: Request,
    operation: Operation,
    request_id: str,
) -> AsyncIterator[str]:
    queue: asyncio.Queue[tuple[str, object | None]] = asyncio.Queue()

    async def progress(event: str, data: dict[str, object]) -> None:
        await queue.put(("progress", (event, data)))

    async def run() -> None:
        try:
            result = await operation(progress)
            await queue.put(("complete", result))
        except TripPlannerError as error:
            await queue.put(("error", error))
        except asyncio.CancelledError:
            raise
        except Exception:
            await queue.put(("error", None))
        finally:
            await queue.put(("finished", None))

    task = asyncio.create_task(run())
    sequence = 0
    try:
        yield _line("planning.started", request_id, sequence, data={})
        sequence += 1
        while True:
            if await request.is_disconnected():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue

            if kind == "progress":
                event, data = payload  # type: ignore[misc]
                yield _line(event, request_id, sequence, data=data)
                sequence += 1
            elif kind == "complete":
                result = payload
                assert isinstance(result, PlanningResult)
                serialized = result.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_none=True,
                )
                yield _line(
                    "planning.completed",
                    request_id,
                    sequence,
                    data=serialized,
                )
                sequence += 1
            elif kind == "error":
                error = payload if isinstance(payload, TripPlannerError) else None
                yield _line(
                    "planning.error",
                    request_id,
                    sequence,
                    error=_safe_error(error),
                )
                sequence += 1
            elif kind == "finished":
                return
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def create_canonical_router(planner: TripPlanner) -> APIRouter:
    router = APIRouter(prefix="/api/v1/trips")

    @router.post("/plan")
    async def plan(request: Request):
        parsed = await _parse(request, TripPlanRequest)
        if isinstance(parsed, JSONResponse):
            return parsed
        request_id = uuid4().hex
        return StreamingResponse(
            _stream_events(
                request,
                lambda progress: planner.plan(parsed, progress=progress),  # type: ignore[arg-type]
                request_id,
            ),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/revise")
    async def revise(request: Request):
        parsed = await _parse(request, TripRevisionRequest)
        if isinstance(parsed, JSONResponse):
            return parsed
        request_id = uuid4().hex
        return StreamingResponse(
            _stream_events(
                request,
                lambda progress: planner.revise(parsed, progress=progress),  # type: ignore[arg-type]
                request_id,
            ),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
