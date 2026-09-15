from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from app.ai_client import ChatClient
from app.domain.chat import ChatRequest
from app.domain.trips import VerifiedPoi


class ModelProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ScheduleCandidate:
    uid: str
    name: str
    address: str
    opening_hours: str | None


@dataclass(frozen=True, slots=True)
class ScheduleRequest:
    destination: str
    days: int
    message: str
    candidates: tuple[ScheduleCandidate, ...]


@dataclass(frozen=True, slots=True)
class PlannedDay:
    day_index: int
    poi_uids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProposedSchedule:
    days: tuple[PlannedDay, ...]


@dataclass(frozen=True, slots=True)
class NarrationRequest:
    destination: str
    pois: tuple[VerifiedPoi, ...]


@dataclass(frozen=True, slots=True)
class NarrationSet:
    by_poi_uid: dict[str, str]


class ModelProvider(Protocol):
    async def create_schedule(self, request: ScheduleRequest) -> ProposedSchedule: ...

    async def create_narration(self, request: NarrationRequest) -> NarrationSet: ...


INVALID_MODEL_OUTPUT = "AI 返回内容无法通过真实 POI 校验"


def _object(content: str) -> dict[str, object]:
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        raise ModelProviderError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT) from None
    if not isinstance(value, dict):
        raise ModelProviderError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT)
    return value


def _exact_keys(value: dict[str, object], keys: set[str]) -> bool:
    return set(value) == keys


def _invalid() -> ModelProviderError:
    return ModelProviderError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT)


def parse_schedule(content: str, request: ScheduleRequest) -> ProposedSchedule:
    value = _object(content)
    if not _exact_keys(value, {"days"}) or not isinstance(value["days"], list):
        raise _invalid()
    raw_days = value["days"]
    if len(raw_days) != request.days:
        raise _invalid()

    candidate_uids = {candidate.uid for candidate in request.candidates}
    seen_days: set[int] = set()
    seen_uids: set[str] = set()
    days: list[PlannedDay] = []
    for raw_day in raw_days:
        if not isinstance(raw_day, dict) or not _exact_keys(raw_day, {"day", "poiUids"}):
            raise _invalid()
        day = raw_day["day"]
        poi_uids = raw_day["poiUids"]
        if (
            not isinstance(day, int)
            or isinstance(day, bool)
            or day < 1
            or day > request.days
            or day in seen_days
            or not isinstance(poi_uids, list)
            or not poi_uids
            or any(not isinstance(uid, str) or not uid for uid in poi_uids)
        ):
            raise _invalid()
        uid_tuple = tuple(poi_uids)
        if any(uid not in candidate_uids or uid in seen_uids for uid in uid_tuple):
            raise _invalid()
        seen_days.add(day)
        seen_uids.update(uid_tuple)
        days.append(PlannedDay(day_index=day, poi_uids=uid_tuple))

    if seen_days != set(range(1, request.days + 1)):
        raise _invalid()
    return ProposedSchedule(days=tuple(sorted(days, key=lambda item: item.day_index)))


def parse_narration(content: str, request: NarrationRequest) -> NarrationSet:
    value = _object(content)
    if not _exact_keys(value, {"narration"}) or not isinstance(value["narration"], list):
        raise _invalid()

    expected_uids = {poi.uid for poi in request.pois}
    narrations: dict[str, str] = {}
    for raw_item in value["narration"]:
        if not isinstance(raw_item, dict) or not _exact_keys(raw_item, {"poiUid", "text"}):
            raise _invalid()
        uid = raw_item["poiUid"]
        text = raw_item["text"]
        if (
            not isinstance(uid, str)
            or uid not in expected_uids
            or uid in narrations
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise _invalid()
        narrations[uid] = text.strip()

    if set(narrations) != expected_uids:
        raise _invalid()
    return NarrationSet(by_poi_uid=narrations)


def _schedule_prompt(request: ScheduleRequest) -> str:
    candidates = [
        {
            "uid": candidate.uid,
            "name": candidate.name,
            "address": candidate.address,
            "openingHours": candidate.opening_hours,
        }
        for candidate in request.candidates
    ]
    return "\n".join(
        (
            "你负责为真实地图 POI 排列旅行日程。",
            f"目的地：{request.destination}",
            f"天数：{request.days}",
            f"用户需求：{request.message}",
            "只能使用候选列表中的 uid，每个 uid 最多使用一次；每天至少一个 POI。",
            "不要输出坐标、路线、距离、时长、营业时间或候选列表之外的事实。",
            f"候选列表：{json.dumps(candidates, ensure_ascii=False)}",
            '只返回严格 JSON：{"days":[{"day":1,"poiUids":["候选uid"]}]}',
        )
    )


def _narration_prompt(request: NarrationRequest) -> str:
    facts = [
        {
            "poiUid": poi.uid,
            "name": poi.name,
            "address": poi.address,
            "openingHours": poi.opening_hours,
        }
        for poi in request.pois
    ]
    return "\n".join(
        (
            "你负责为真实地图 POI 写简短旅行讲解。",
            f"目的地：{request.destination}",
            "只能根据给出的名称、地址和营业时间写作，不得补充未经提供的历史、数据或营业事实。",
            f"真实 POI 事实：{json.dumps(facts, ensure_ascii=False)}",
            '每个 POI 必须返回一条，且只返回严格 JSON：{"narration":[{"poiUid":"候选uid","text":"讲解"}]}',
        )
    )


class OpenAIModelAdapter:
    def __init__(self, chat_client: ChatClient) -> None:
        self._chat_client = chat_client

    async def create_schedule(self, request: ScheduleRequest) -> ProposedSchedule:
        response = await self._chat_client.complete(
            ChatRequest(
                message=_schedule_prompt(request),
                destination=request.destination,
                days=request.days,
            )
        )
        return parse_schedule(response.message.content, request)

    async def create_narration(self, request: NarrationRequest) -> NarrationSet:
        response = await self._chat_client.complete(
            ChatRequest(message=_narration_prompt(request), destination=request.destination)
        )
        return parse_narration(response.message.content, request)
