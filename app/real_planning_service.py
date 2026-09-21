from __future__ import annotations

import re
from uuid import uuid4

from app.baidu_map import MapProviderError
from app.domain.chat import TripPlanRequest, TripRevisionRequest
from app.domain.trips import PlanningResult, TravelMode, TripDay, TripPlan, TripStop, VerifiedPoi
from app.map_provider import MapProvider, PoiSearchQuery, RouteRequest
from app.model_provider import (
    ModelProvider,
    ModelProviderError,
    NarrationRequest,
    RevisionRequest,
    ScheduleCandidate,
    ScheduleRequest,
)
from app.planning_service import (
    ProgressCallback,
    TripPlannerError,
    emit_progress,
    resolve_trip_request,
)
from app.planning_validator import PlanValidationError, validate_plan, validate_revision
from app.story_compiler import compile_timeline


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

INVALID_MODEL_OUTPUT = "AI 返回内容无法通过真实 POI 校验"


_POI_REQUEST_MARKERS = (
    "想去",
    "要去",
    "去",
    "到",
    "游览",
    "参观",
    "逛",
    "安排",
    "换成",
    "改成",
    "加入",
    "添加",
    "增加",
)
_POI_REQUEST_SUFFIXES = ("游玩", "看看", "逛逛", "玩", "游览", "参观")
_POI_REJECTION_MARKERS = (
    "不想去",
    "不去",
    "不要去",
    "不要",
    "别去",
    "去掉",
    "删除",
    "移除",
    "取消",
)
_GENERIC_POI_TERMS = frozenset(
    {"景点", "地方", "路线", "交通", "方式", "博物馆", "公园", "餐厅", "酒店", "商场", "美食"}
)


def _extract_explicit_poi_terms(instruction: str) -> tuple[str, ...]:
    terms: list[str] = []
    for marker in sorted(_POI_REQUEST_MARKERS, key=len, reverse=True):
        match = re.search(
            rf"{re.escape(marker)}([\u4e00-\u9fffA-Za-z0-9·]{{2,20}})",
            instruction,
        )
        if not match:
            continue
        term = re.sub(r"^(?:一个|一处|一些)", "", match.group(1))
        for suffix in sorted(_POI_REQUEST_SUFFIXES, key=len, reverse=True):
            if term.endswith(suffix) and len(term) > len(suffix) + 1:
                term = term[: -len(suffix)]
                break
        if term and term not in terms:
            terms.append(term)
    return tuple(terms)


def _normalize_poi_text(value: str) -> str:
    return re.sub(r"[\s·—–-]+", "", value)


def _instruction_mentions_poi(instruction: str, name: str) -> bool:
    normalized_instruction = _normalize_poi_text(instruction)
    normalized_name = _normalize_poi_text(name)
    if normalized_name in normalized_instruction:
        return True
    return len(normalized_name) >= 3 and any(
        normalized_name[index : index + 3] in normalized_instruction
        for index in range(len(normalized_name) - 2)
    )


def _select_explicit_poi_uids(
    terms: tuple[str, ...], candidates: dict[str, VerifiedPoi]
) -> tuple[str, ...]:
    selected: list[str] = []
    for term in terms:
        normalized_term = _normalize_poi_text(term)
        if not normalized_term:
            continue
        matches: list[tuple[int, int, str]] = []
        for order, poi in enumerate(candidates.values()):
            normalized_name = _normalize_poi_text(poi.name)
            if normalized_term in normalized_name:
                matches.append(
                    (
                        0 if normalized_name == normalized_term else 1,
                        order,
                        poi.uid,
                    )
                )
        if matches:
            selected.append(min(matches)[2])
    return tuple(dict.fromkeys(selected))


def _instruction_rejects_poi(instruction: str, name: str) -> bool:
    # ponytail: local phrase heuristic; use structured revision intent for broader language coverage.
    normalized_instruction = _normalize_poi_text(instruction)
    normalized_name = _normalize_poi_text(name)
    name_index = normalized_instruction.find(normalized_name)
    if name_index < 0:
        return False
    context = normalized_instruction[
        max(0, name_index - 8) : name_index + len(normalized_name) + 8
    ]
    return any(marker in context for marker in _POI_REJECTION_MARKERS)


async def _route_leg(
    map_provider: MapProvider,
    start: VerifiedPoi,
    end: VerifiedPoi,
    mode: TravelMode,
):
    try:
        return await map_provider.route(RouteRequest(start, end, mode))
    except MapProviderError as error:
        if error.code != "ROUTE_UNAVAILABLE" or mode is not TravelMode.TRANSIT:
            raise
        return await map_provider.route(RouteRequest(start, end, TravelMode.DRIVE))


class RealTripPlanner:
    def __init__(self, map_provider: MapProvider, model_provider: ModelProvider) -> None:
        self._map_provider = map_provider
        self._model_provider = model_provider

    async def plan(
        self,
        request: TripPlanRequest,
        *,
        progress: ProgressCallback | None = None,
    ) -> PlanningResult:
        try:
            destination, days = await resolve_trip_request(
                request,
                self._model_provider.extract_trip_intent,
            )
            if any(marker in destination for marker in OVERSEAS_MARKERS):
                raise TripPlannerError("UNSUPPORTED_REGION", "暂不支持该地区，等待后续开发")
            resolved_destination = await self._map_provider.resolve_destination(destination)
            await emit_progress(
                progress,
                "destination.validated",
                {"destination": resolved_destination.name},
            )
            candidates = await self._map_provider.search_pois(
                PoiSearchQuery(destination, ("旅游景点",), 20)
            )
            if len(candidates) < days:
                raise TripPlannerError("POI_NOT_FOUND", "该目的地没有足够的可用 POI")
            await emit_progress(progress, "pois.found", {"count": len(candidates)})

            candidate_by_uid = {poi.uid: poi for poi in candidates}
            schedule = await self._model_provider.create_schedule(
                ScheduleRequest(
                    destination=destination,
                    days=days,
                    message=request.message,
                    candidates=tuple(
                        ScheduleCandidate(
                            uid=poi.uid,
                            name=poi.name,
                            address=poi.address,
                            opening_hours=poi.opening_hours,
                        )
                        for poi in candidates
                    ),
                    history=tuple(request.history),
                )
            )
            self._validate_schedule(schedule.days, days, candidate_by_uid)

            days: list[TripDay] = []
            selected_pois: list[VerifiedPoi] = []
            for proposed_day in schedule.days:
                pois = [candidate_by_uid[uid] for uid in proposed_day.poi_uids]
                selected_pois.extend(pois)
                stops = [TripStop(poi=poi) for poi in pois]
                route_modes = proposed_day.transport_modes or (
                    TravelMode.WALK,
                ) * (len(pois) - 1)
                if len(route_modes) != len(pois) - 1:
                    raise TripPlannerError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT)
                route_legs = [
                    await _route_leg(self._map_provider, start, end, mode)
                    for (start, end), mode in zip(
                        zip(pois, pois[1:]),
                        route_modes,
                    )
                ]
                days.append(
                    TripDay(
                        day_index=proposed_day.day_index,
                        title=f"第{proposed_day.day_index}天：{pois[0].name}",
                        summary=f"围绕{pois[0].name}安排的真实地点路线。",
                        stops=stops,
                        route_legs=route_legs,
                    )
                )

            await emit_progress(progress, "routes.calculated", {"count": sum(len(day.route_legs) for day in days)})
            narrations = await self._model_provider.create_narration(
                NarrationRequest(destination=destination, pois=tuple(selected_pois))
            )
            selected_uids = {poi.uid for poi in selected_pois}
            if set(narrations.by_poi_uid) != selected_uids:
                raise ModelProviderError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT)
            days = [
                day.model_copy(
                    update={
                        "stops": [
                            stop.model_copy(
                                update={"narration": narrations.by_poi_uid[stop.poi.uid]}
                            )
                            for stop in day.stops
                        ]
                    }
                )
                for day in days
            ]
            plan = TripPlan(
                id=f"trip-{uuid4().hex}",
                version=1,
                destination=destination,
                summary=f"根据百度地图真实地点与路线生成的{len(days)}日行程。",
                days=days,
            )
            validate_plan(plan, set(candidate_by_uid))
            await emit_progress(progress, "plan.validated", {})
        except TripPlannerError:
            raise
        except ModelProviderError as error:
            raise TripPlannerError(error.code, str(error)) from None
        except PlanValidationError as error:
            raise TripPlannerError("PLAN_INCOMPLETE", str(error)) from None
        except MapProviderError as error:
            raise TripPlannerError(error.code, str(error)) from None

        result = PlanningResult(plan=plan, timeline=compile_timeline(plan))
        await emit_progress(progress, "timeline.ready", {})
        return result

    async def revise(
        self,
        request: TripRevisionRequest,
        *,
        progress: ProgressCallback | None = None,
    ) -> PlanningResult:
        original = request.plan
        target_index = request.day - 1
        try:
            validate_plan(original)
            resolved_destination = await self._map_provider.resolve_destination(
                original.destination
            )
            await emit_progress(
                progress,
                "destination.validated",
                {"destination": resolved_destination.name},
            )
            explicit_poi_terms = _extract_explicit_poi_terms(request.instruction)
            search_keywords = (*explicit_poi_terms, request.instruction, "旅游景点")
            candidates = await self._map_provider.search_pois(
                PoiSearchQuery(original.destination, search_keywords, 20)
            )
            untouched_uids = {
                stop.poi.uid
                for index, day in enumerate(original.days)
                if index != target_index
                for stop in day.stops
            }
            candidate_by_uid = {
                poi.uid: poi for poi in candidates if poi.uid not in untouched_uids
            }
            for stop in original.days[target_index].stops:
                if stop.poi.uid not in candidate_by_uid:
                    candidate_by_uid[stop.poi.uid] = stop.poi
            rejected_poi_uids = {
                uid
                for uid, poi in candidate_by_uid.items()
                if _instruction_rejects_poi(request.instruction, poi.name)
            }
            candidate_by_uid = {
                uid: poi
                for uid, poi in candidate_by_uid.items()
                if uid not in rejected_poi_uids
            }
            requested_poi_uids = (
                _select_explicit_poi_uids(explicit_poi_terms, candidate_by_uid)
                if explicit_poi_terms
                else tuple(
                    poi.uid
                    for poi in candidate_by_uid.values()
                    if _instruction_mentions_poi(request.instruction, poi.name)
                )
            )
            named_poi_terms = tuple(
                term
                for term in explicit_poi_terms
                if term not in _GENERIC_POI_TERMS
                and not _instruction_rejects_poi(request.instruction, term)
            )
            if named_poi_terms and not requested_poi_uids:
                raise TripPlannerError(
                    "POI_NOT_FOUND",
                    "当前目的地未找到用户指定的地点",
                )
            if requested_poi_uids:
                target_day_uids = {
                    stop.poi.uid for stop in original.days[target_index].stops
                }
                allowed_uids = target_day_uids | set(requested_poi_uids)
                candidate_by_uid = {
                    uid: poi
                    for uid, poi in candidate_by_uid.items()
                    if uid in allowed_uids
                }
            if not candidate_by_uid:
                raise TripPlannerError("POI_NOT_FOUND", "该目的地没有可用的候选 POI")
            await emit_progress(
                progress,
                "pois.found",
                {"count": len(candidate_by_uid)},
            )

            revision = await self._model_provider.revise_day(
                RevisionRequest(
                    destination=original.destination,
                    day_index=request.day,
                    instruction=request.instruction,
                    current_poi_uids=tuple(
                        stop.poi.uid for stop in original.days[target_index].stops
                    ),
                    candidates=tuple(
                        ScheduleCandidate(
                            uid=poi.uid,
                            name=poi.name,
                            address=poi.address,
                            opening_hours=poi.opening_hours,
                        )
                        for poi in candidate_by_uid.values()
                    ),
                )
            )
            if (
                revision.day_index != request.day
                or not revision.poi_uids
                or len(set(revision.poi_uids)) != len(revision.poi_uids)
                or any(uid not in candidate_by_uid for uid in revision.poi_uids)
            ):
                raise TripPlannerError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT)

            original_day = original.days[target_index]
            selected_poi_uids = list(revision.poi_uids)
            for uid in requested_poi_uids:
                if uid not in selected_poi_uids:
                    selected_poi_uids.append(uid)

            pois = [candidate_by_uid[uid] for uid in selected_poi_uids]
            route_modes = list(revision.transport_modes)
            if not route_modes:
                route_modes = [TravelMode.WALK] * (len(revision.poi_uids) - 1)
            route_modes.extend(
                [TravelMode.WALK] * (len(selected_poi_uids) - len(revision.poi_uids))
            )
            if len(route_modes) != len(pois) - 1:
                raise TripPlannerError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT)
            if (
                tuple(selected_poi_uids) == tuple(stop.poi.uid for stop in original_day.stops)
                and tuple(route_modes) == tuple(leg.mode for leg in original_day.route_legs)
            ):
                raise TripPlannerError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT)
            route_legs = [
                await _route_leg(self._map_provider, start, end, mode)
                for (start, end), mode in zip(
                    zip(pois, pois[1:]),
                    route_modes,
                )
            ]

            await emit_progress(
                progress,
                "routes.calculated",
                {"count": len(route_legs)},
            )
            narrations = await self._model_provider.create_narration(
                NarrationRequest(destination=original.destination, pois=tuple(pois))
            )
            if set(narrations.by_poi_uid) != set(selected_poi_uids):
                raise ModelProviderError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT)
            revised_stops = [
                TripStop(
                    poi=poi,
                    narration=narrations.by_poi_uid[poi.uid],
                )
                for poi in pois
            ]
            previous_day = original_day
            revised_day = TripDay(
                day_index=previous_day.day_index,
                title=f"第{previous_day.day_index}天：{pois[0].name}",
                date=previous_day.date,
                summary=f"围绕{pois[0].name}安排的真实地点路线。",
                stops=revised_stops,
                route_legs=route_legs,
            )
            revised_days = list(original.days)
            revised_days[target_index] = revised_day
            revised_plan = original.model_copy(
                update={
                    "version": original.version + 1,
                    "days": revised_days,
                }
            )
            validate_revision(
                original,
                revised_plan,
                request.day,
                set(candidate_by_uid),
            )
            await emit_progress(progress, "plan.validated", {})
        except TripPlannerError:
            raise
        except ModelProviderError as error:
            raise TripPlannerError(error.code, str(error)) from None
        except PlanValidationError as error:
            raise TripPlannerError("PLAN_INCOMPLETE", str(error)) from None
        except MapProviderError as error:
            raise TripPlannerError(error.code, str(error)) from None

        result = PlanningResult(plan=revised_plan, timeline=compile_timeline(revised_plan))
        await emit_progress(progress, "timeline.ready", {})
        return result

    @staticmethod
    def _validate_schedule(days, requested_days: int, candidates: dict[str, VerifiedPoi]) -> None:
        if len(days) != requested_days:
            raise TripPlannerError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT)
        expected_days = list(range(1, requested_days + 1))
        if [day.day_index for day in days] != expected_days:
            raise TripPlannerError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT)
        seen: set[str] = set()
        for day in days:
            if not day.poi_uids or any(uid not in candidates or uid in seen for uid in day.poi_uids):
                raise TripPlannerError("MODEL_OUTPUT_INVALID", INVALID_MODEL_OUTPUT)
            seen.update(day.poi_uids)
