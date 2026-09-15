from __future__ import annotations

from uuid import uuid4

from app.baidu_map import MapProviderError
from app.domain.chat import TripPlanRequest
from app.domain.trips import PlanningResult, TripDay, TripPlan, TripStop, VerifiedPoi
from app.map_provider import MapProvider, PoiSearchQuery, RouteRequest
from app.model_provider import (
    ModelProvider,
    ModelProviderError,
    NarrationRequest,
    ScheduleCandidate,
    ScheduleRequest,
)
from app.planning_service import TripPlannerError
from app.planning_validator import PlanValidationError, validate_plan
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


class RealTripPlanner:
    def __init__(self, map_provider: MapProvider, model_provider: ModelProvider) -> None:
        self._map_provider = map_provider
        self._model_provider = model_provider

    async def plan(self, request: TripPlanRequest) -> PlanningResult:
        if any(marker in request.destination for marker in OVERSEAS_MARKERS):
            raise TripPlannerError("UNSUPPORTED_REGION", "暂不支持该地区，等待后续开发")

        try:
            await self._map_provider.resolve_destination(request.destination)
            candidates = await self._map_provider.search_pois(
                PoiSearchQuery(request.destination, ("旅游景点",), 20)
            )
            if len(candidates) < request.days:
                raise TripPlannerError("POI_NOT_FOUND", "该目的地没有足够的可用 POI")

            candidate_by_uid = {poi.uid: poi for poi in candidates}
            schedule = await self._model_provider.create_schedule(
                ScheduleRequest(
                    destination=request.destination,
                    days=request.days,
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
                )
            )
            self._validate_schedule(schedule.days, request.days, candidate_by_uid)

            days: list[TripDay] = []
            selected_pois: list[VerifiedPoi] = []
            for proposed_day in schedule.days:
                pois = [candidate_by_uid[uid] for uid in proposed_day.poi_uids]
                selected_pois.extend(pois)
                stops = [TripStop(poi=poi) for poi in pois]
                route_legs = [
                    await self._map_provider.route(RouteRequest(start, end))
                    for start, end in zip(pois, pois[1:])
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

            narrations = await self._model_provider.create_narration(
                NarrationRequest(destination=request.destination, pois=tuple(selected_pois))
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
                destination=request.destination,
                summary=f"根据百度地图真实地点与路线生成的{request.days}日行程。",
                days=days,
            )
            validate_plan(plan, set(candidate_by_uid))
        except TripPlannerError:
            raise
        except ModelProviderError as error:
            raise TripPlannerError(error.code, str(error)) from None
        except PlanValidationError as error:
            raise TripPlannerError("PLAN_INCOMPLETE", str(error)) from None
        except MapProviderError as error:
            raise TripPlannerError(error.code, str(error)) from None

        return PlanningResult(plan=plan, timeline=compile_timeline(plan))

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
