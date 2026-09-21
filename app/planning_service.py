from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from app.ai_client import AiClientError, ChatClient
from app.domain.chat import ChatRequest, TripPlanRequest, TripRevisionRequest
from app.domain.trips import PlanningResult, TripPlan
from app.fixtures_nanjing import nanjing_planning_result, nanjing_trip_plan
from app.model_provider import ModelProviderError, TripIntent, extract_trip_intent_from_chat
from app.planning_validator import validate_plan


class TripPlannerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


ProgressCallback = Callable[[str, dict[str, object]], Awaitable[None]]


async def emit_progress(
    progress: ProgressCallback | None,
    event: str,
    data: dict[str, object] | None = None,
) -> None:
    if progress is not None:
        await progress(event, data or {})


TripIntentExtractor = Callable[[TripPlanRequest], Awaitable[TripIntent]]


async def resolve_trip_request(
    request: TripPlanRequest,
    extract_intent: TripIntentExtractor,
) -> tuple[str, int]:
    if request.destination is not None and request.days is not None:
        return request.destination, request.days

    try:
        intent = await extract_intent(request)
    except (AiClientError, ModelProviderError) as error:
        raise TripPlannerError(error.code, str(error)) from None

    destination = request.destination or intent.destination
    days = request.days if request.days is not None else intent.days
    missing = [
        label
        for label, value in (("目的地", destination), ("旅行天数", days))
        if value is None
    ]
    if missing:
        raise TripPlannerError(
            "PLAN_INPUT_REQUIRED",
            f"请在对话中补充{'、'.join(missing)}",
        )
    return destination, days


class TripPlanner(Protocol):
    async def plan(
        self,
        request: TripPlanRequest,
        *,
        progress: ProgressCallback | None = None,
    ) -> PlanningResult: ...

    async def revise(
        self,
        request: TripRevisionRequest,
        *,
        progress: ProgressCallback | None = None,
    ) -> PlanningResult: ...


@dataclass(frozen=True)
class FixtureSelection:
    days: list[dict[str, object]]


OVERSEAS_MARKERS = (
    "巴黎",
    "东京",
    "纽约",
    "伦敦",
    "首尔",
    "新加坡",
    "悉尼",
    "日本",
    "美国",
    "英国",
    "法国",
    "韩国",
    "欧洲",
    "澳大利亚",
)

INVALID_SELECTION_MESSAGE = "AI 返回的行程选择无法通过校验"


def _is_exact_keys(value: dict[str, object], keys: set[str]) -> bool:
    return set(value) == keys


def parse_fixture_selection(content: str) -> FixtureSelection:
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError) as error:
        raise ValueError(INVALID_SELECTION_MESSAGE) from error

    if not isinstance(parsed, dict) or not _is_exact_keys(parsed, {"days"}):
        raise ValueError(INVALID_SELECTION_MESSAGE)
    days_value = parsed["days"]
    if not isinstance(days_value, list):
        raise ValueError(INVALID_SELECTION_MESSAGE)

    days: list[dict[str, object]] = []
    for value in days_value:
        if not isinstance(value, dict) or not _is_exact_keys(value, {"day", "poiUids"}):
            raise ValueError(INVALID_SELECTION_MESSAGE)
        day = value["day"]
        poi_uids = value["poiUids"]
        if (
            not isinstance(day, int)
            or isinstance(day, bool)
            or not isinstance(poi_uids, list)
            or any(not isinstance(uid, str) or not uid for uid in poi_uids)
        ):
            raise ValueError(INVALID_SELECTION_MESSAGE)
        days.append({"day": day, "poiUids": poi_uids})
    return FixtureSelection(days=days)


def build_fixture_selection_prompt(request: TripPlanRequest) -> str:
    plan = nanjing_trip_plan()
    candidates = [
        {
            "day": day.day_index,
            "pois": [{"uid": stop.poi.uid, "name": stop.poi.name} for stop in day.stops],
        }
        for day in plan.days
    ]
    return "\n".join(
        (
            "你只负责确认已验证的南京三日 fixture 选择。",
            f"目的地：{request.destination}",
            f"天数：{request.days}",
            "只能从以下候选 POI 中返回原有三日顺序，不得新增或改写任何 UID：",
            json.dumps(candidates, ensure_ascii=False, indent=2),
            '只返回严格 JSON：{"days":[{"day":1,"poiUids":["fixture-nanjing-fuzimiao"]}]}',
            "不要返回坐标、路线、距离、时长、营业时间或解释文字。",
        )
    )


def _has_exact_fixture_selection(selection: FixtureSelection, plan: TripPlan) -> bool:
    expected = [
        {"day": day.day_index, "poiUids": [stop.poi.uid for stop in day.stops]}
        for day in plan.days
    ]
    return selection.days == expected


class FixtureTripPlanner:
    def __init__(self, chat_client: ChatClient) -> None:
        self._chat_client = chat_client

    async def plan(
        self,
        request: TripPlanRequest,
        *,
        progress: ProgressCallback | None = None,
    ) -> PlanningResult:
        async def extract_intent(plan_request: TripPlanRequest) -> TripIntent:
            return await extract_trip_intent_from_chat(self._chat_client, plan_request)

        resolved_destination, days = await resolve_trip_request(request, extract_intent)
        resolved_request = request.model_copy(
            update={"destination": resolved_destination, "days": days}
        )
        if any(marker in resolved_destination for marker in OVERSEAS_MARKERS):
            raise TripPlannerError("UNSUPPORTED_REGION", "暂不支持该地区，等待后续开发")

        destination = resolved_destination.removesuffix("市")
        if destination != "南京" or days != 3:
            raise TripPlannerError("PLAN_NOT_AVAILABLE", "当前目的地的可播放行程尚未接入")

        await emit_progress(
            progress,
            "destination.validated",
            {"destination": resolved_request.destination},
        )
        prompt = build_fixture_selection_prompt(resolved_request)
        response = await self._chat_client.complete(
            ChatRequest(
                message=prompt,
                destination=resolved_request.destination,
                days=resolved_request.days,
            )
        )
        plan = nanjing_trip_plan()
        try:
            selection = parse_fixture_selection(response.message.content)
            if not _has_exact_fixture_selection(selection, plan):
                raise ValueError(INVALID_SELECTION_MESSAGE)
            result = nanjing_planning_result()
            await emit_progress(progress, "pois.found", {"count": 9})
            await emit_progress(progress, "routes.calculated", {"count": 6})
            validate_plan(result.plan, {stop.poi.uid for day in plan.days for stop in day.stops})
            await emit_progress(progress, "plan.validated", {})
            await emit_progress(progress, "timeline.ready", {})
            return result
        except (ValueError, TypeError, KeyError):
            raise TripPlannerError("MODEL_OUTPUT_INVALID", INVALID_SELECTION_MESSAGE) from None

    async def revise(
        self,
        request: TripRevisionRequest,
        *,
        progress: ProgressCallback | None = None,
    ) -> PlanningResult:
        raise TripPlannerError("PLAN_NOT_AVAILABLE", "当前目的地的可播放行程尚未接入")
