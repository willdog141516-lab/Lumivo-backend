from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from app.ai_client import ChatClient
from app.domain.chat import ChatRequest, TripPlanRequest
from app.domain.trips import PlanningResult, TripPlan
from app.fixtures_nanjing import nanjing_planning_result, nanjing_trip_plan
from app.planning_validator import validate_plan


class TripPlannerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TripPlanner(Protocol):
    async def plan(self, request: TripPlanRequest) -> PlanningResult: ...


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

    async def plan(self, request: TripPlanRequest) -> PlanningResult:
        if any(marker in request.destination for marker in OVERSEAS_MARKERS):
            raise TripPlannerError("UNSUPPORTED_REGION", "暂不支持该地区，等待后续开发")

        destination = request.destination.removesuffix("市")
        if destination != "南京" or request.days != 3:
            raise TripPlannerError("PLAN_NOT_AVAILABLE", "当前目的地的可播放行程尚未接入")

        prompt = build_fixture_selection_prompt(request)
        response = await self._chat_client.complete(
            ChatRequest(
                message=prompt,
                destination=request.destination,
                days=request.days,
            )
        )
        plan = nanjing_trip_plan()
        try:
            selection = parse_fixture_selection(response.message.content)
            if not _has_exact_fixture_selection(selection, plan):
                raise ValueError(INVALID_SELECTION_MESSAGE)
            result = nanjing_planning_result()
            validate_plan(result.plan, {stop.poi.uid for day in plan.days for stop in day.stops})
            return result
        except (ValueError, TypeError, KeyError):
            raise TripPlannerError("MODEL_OUTPUT_INVALID", INVALID_SELECTION_MESSAGE) from None
