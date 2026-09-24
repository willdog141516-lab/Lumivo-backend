import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.baidu_map import MapProviderError
from app.ai_client import AiClientError
from app.domain.chat import (
    ChatMessage,
    TripPlanRequest,
    TripRerouteRequest,
    TripRevisionRequest,
)
from app.domain.trips import GeoPoint, RouteLeg, TravelMode, VerifiedPoi
from app.map_provider import PoiSearchQuery, ResolvedDestination, RouteRequest
from app.model_provider import (
    NarrationRequest,
    NarrationSet,
    PlannedDay,
    ProposedRevision,
    ProposedSchedule,
    RevisionRequest,
    ScheduleRequest,
)
from app.planning_service import TripPlannerError
from app.real_planning_service import RealTripPlanner


class FakeMapProvider:
    def __init__(self) -> None:
        verified_at = datetime.now(timezone.utc)
        self.first = VerifiedPoi(
            uid="p1",
            name="真实起点",
            address="真实地址1",
            point=GeoPoint(lng=118.7, lat=32.0),
            recommended_stay_minutes=60,
            source="baidu",
            verified_at=verified_at,
        )
        self.second = self.first.model_copy(
            update={
                "uid": "p2",
                "name": "真实终点",
                "point": GeoPoint(lng=118.9, lat=32.1),
            }
        )
        self.third = self.first.model_copy(
            update={
                "uid": "p3",
                "name": "真实新景点",
                "point": GeoPoint(lng=119.0, lat=32.2),
            }
        )
        self.oriental_pearl = self.first.model_copy(
            update={
                "uid": "p4",
                "name": "东方明珠广播电视塔",
                "point": GeoPoint(lng=121.4997, lat=31.2397),
            }
        )
        self.search_queries: list[PoiSearchQuery] = []
        self.route_calls = 0
        self.route_modes = []
        self.fail_on_route_call = None

    async def resolve_destination(self, name: str) -> ResolvedDestination:
        return ResolvedDestination(name=name, point=self.first.point)

    async def search_pois(self, query: PoiSearchQuery) -> list[VerifiedPoi]:
        self.search_queries.append(query)
        return [self.first, self.second, self.third, self.oriental_pearl]

    async def route(self, request: RouteRequest) -> RouteLeg:
        self.route_calls += 1
        self.route_modes.append(request.mode)
        if self.route_calls == self.fail_on_route_call:
            raise MapProviderError("ROUTE_UNAVAILABLE", "route unavailable")
        return RouteLeg(
            id=f"real-route-{request.from_poi.uid}-{request.to_poi.uid}",
            from_poi_uid=request.from_poi.uid,
            to_poi_uid=request.to_poi.uid,
            mode=request.mode,
            distance_meters=1234,
            duration_seconds=600,
            geometry=[
                request.from_poi.point,
                GeoPoint(lng=118.8, lat=32.05),
                request.to_poi.point,
            ],
        )


class FakeModelProvider:
    def __init__(self, intent: SimpleNamespace | None = None) -> None:
        self.intent = intent
        self.schedule_requests: list[ScheduleRequest] = []

    async def extract_trip_intent(self, request: TripPlanRequest) -> SimpleNamespace:
        assert self.intent is not None
        return self.intent

    async def create_schedule(self, request: ScheduleRequest) -> ProposedSchedule:
        self.schedule_requests.append(request)
        return ProposedSchedule(days=(PlannedDay(1, ("p1", "p2")),))

    async def create_narration(self, request: NarrationRequest) -> NarrationSet:
        return NarrationSet({poi.uid: f"讲解{poi.name}" for poi in request.pois})

    async def revise_day(self, request: RevisionRequest) -> ProposedRevision:
        return ProposedRevision(day_index=request.day_index, poi_uids=("p1", "p3"))


class ThreeStopFakeModelProvider(FakeModelProvider):
    async def create_schedule(self, request: ScheduleRequest) -> ProposedSchedule:
        return ProposedSchedule(days=(PlannedDay(1, ("p1", "p2", "p3")),))


class TwoDayFakeModelProvider(FakeModelProvider):
    async def create_schedule(self, request: ScheduleRequest) -> ProposedSchedule:
        self.schedule_requests.append(request)
        return ProposedSchedule(
            days=(
                PlannedDay(1, ("p1",)),
                PlannedDay(2, ("p2",)),
            )
        )

    async def revise_day(self, request: RevisionRequest) -> ProposedRevision:
        return ProposedRevision(day_index=request.day_index, poi_uids=("p2", "p4"))


class NoNamedPoiMapProvider(FakeMapProvider):
    async def search_pois(self, query: PoiSearchQuery) -> list[VerifiedPoi]:
        self.search_queries.append(query)
        return [self.first, self.second, self.third]


class UnknownUidModelProvider(FakeModelProvider):
    async def create_schedule(self, request: ScheduleRequest) -> ProposedSchedule:
        return ProposedSchedule(days=(PlannedDay(1, ("unknown",)),))


class UnknownRevisionUidModelProvider(FakeModelProvider):
    async def revise_day(self, request: RevisionRequest) -> ProposedRevision:
        return ProposedRevision(day_index=request.day_index, poi_uids=("unknown",))


class NoopRevisionModelProvider(FakeModelProvider):
    async def revise_day(self, request: RevisionRequest) -> ProposedRevision:
        return ProposedRevision(
            day_index=request.day_index,
            poi_uids=request.current_poi_uids,
        )


class OverselectingRevisionModelProvider(FakeModelProvider):
    async def revise_day(self, request: RevisionRequest) -> ProposedRevision:
        return ProposedRevision(
            day_index=request.day_index,
            poi_uids=tuple(candidate.uid for candidate in request.candidates),
        )


class IntentFailureModelProvider(FakeModelProvider):
    async def extract_trip_intent(self, request: TripPlanRequest):
        raise AiClientError("AI_PROVIDER_ERROR", "provider unavailable")


class ExplicitPoiVariantsMapProvider(FakeMapProvider):
    def __init__(self) -> None:
        super().__init__()
        self.exact_landmark = self.first.model_copy(
            update={"uid": "p5", "name": "东方明珠"}
        )
        self.related_landmark = self.first.model_copy(
            update={"uid": "p6", "name": "东方明珠公园"}
        )

    async def search_pois(self, query: PoiSearchQuery) -> list[VerifiedPoi]:
        self.search_queries.append(query)
        return [
            self.first,
            self.second,
            self.third,
            self.oriental_pearl,
            self.exact_landmark,
            self.related_landmark,
        ]


def test_real_planner_builds_timeline_from_provider_facts():
    map_provider = FakeMapProvider()
    result = asyncio.run(
        RealTripPlanner(map_provider, FakeModelProvider()).plan(
            TripPlanRequest(message="成都一日游", destination="成都", days=1)
        )
    )

    assert result.plan.id.startswith("trip-")
    assert result.plan.destination == "成都"
    assert result.plan.days[0].stops[0].poi.source == "baidu"
    assert result.plan.days[0].route_legs[0].distance_meters == 1234
    assert result.plan.days[0].route_legs[0].geometry[1].lng == 118.8
    assert result.timeline.trip_id == result.plan.id
    assert result.timeline.trip_version == result.plan.version


def test_real_planner_reroutes_every_leg_and_rebuilds_the_timeline():
    map_provider = FakeMapProvider()
    planner = RealTripPlanner(map_provider, ThreeStopFakeModelProvider())
    original = asyncio.run(
        planner.plan(
            TripPlanRequest(message="成都一日游", destination="成都", days=1)
        )
    )
    route_snapshot = SimpleNamespace(
        id=original.plan.id,
        version=original.plan.version,
        destination=original.plan.destination,
        summary=original.plan.summary,
        warnings=original.plan.warnings,
        days=[
            SimpleNamespace(
                day_index=day.day_index,
                title=day.title,
                date=day.date,
                summary=day.summary,
                stops=day.stops,
            )
            for day in original.plan.days
        ],
    )

    rerouted = asyncio.run(
        planner.reroute(
            SimpleNamespace(plan=route_snapshot, transport=TravelMode.RIDE)
        )
    )

    assert map_provider.route_modes == [
        TravelMode.WALK,
        TravelMode.WALK,
        TravelMode.RIDE,
        TravelMode.RIDE,
    ]
    assert rerouted.plan.version == original.plan.version + 1
    assert [leg.mode for leg in rerouted.plan.days[0].route_legs] == [
        TravelMode.RIDE,
        TravelMode.RIDE,
    ]
    assert [stop.poi.uid for stop in rerouted.plan.days[0].stops] == [
        stop.poi.uid for stop in original.plan.days[0].stops
    ]
    assert rerouted.timeline.trip_id == original.plan.id
    assert rerouted.timeline.trip_version == rerouted.plan.version


def test_real_planner_does_not_return_a_partial_reroute_when_a_leg_fails():
    map_provider = FakeMapProvider()
    planner = RealTripPlanner(map_provider, ThreeStopFakeModelProvider())
    original = asyncio.run(
        planner.plan(
            TripPlanRequest(message="成都一日游", destination="成都", days=1)
        )
    )
    route_snapshot = original.plan.model_dump(
        mode="json",
        by_alias=True,
        exclude={"days": {"__all__": {"routeLegs"}}},
    )
    request = TripRerouteRequest.model_validate(
        {"plan": route_snapshot, "transport": "ride"}
    )
    map_provider.fail_on_route_call = map_provider.route_calls + 2
    progress_events = []

    async def on_progress(event, _data):
        progress_events.append(event)

    with pytest.raises(TripPlannerError) as error:
        asyncio.run(planner.reroute(request, progress=on_progress))

    assert error.value.code == "ROUTE_UNAVAILABLE"
    assert progress_events == []


def test_real_planner_translates_intent_provider_failure_to_structured_error():
    with pytest.raises(TripPlannerError) as error:
        asyncio.run(
            RealTripPlanner(FakeMapProvider(), IntentFailureModelProvider()).plan(
                TripPlanRequest(message="我想去上海玩两天")
            )
        )

    assert error.value.code == "AI_PROVIDER_ERROR"


def test_real_planner_uses_dialogue_intent_and_history_when_fields_are_missing():
    model_provider = FakeModelProvider(SimpleNamespace(destination="成都", days=1))
    result = asyncio.run(
        RealTripPlanner(FakeMapProvider(), model_provider).plan(
            TripPlanRequest(
                message="请把上面的聊天生成成故事地图",
                history=(
                    ChatMessage(role="user", content="我想去成都玩一天，重点看老街"),
                    ChatMessage(role="assistant", content="可以安排慢一点。"),
                ),
            )
        )
    )

    assert result.plan.destination == "成都"
    assert model_provider.schedule_requests[0].history[-1].content == "可以安排慢一点。"
    assert "1日" in result.plan.summary

def test_real_planner_does_not_guess_when_dialogue_lacks_trip_details():
    planner = RealTripPlanner(
        FakeMapProvider(),
        FakeModelProvider(SimpleNamespace(destination=None, days=None)),
    )

    with pytest.raises(TripPlannerError) as error:
        asyncio.run(planner.plan(TripPlanRequest(message="帮我做成故事地图")))

    assert error.value.code == "PLAN_INPUT_REQUIRED"

def test_real_planner_reports_progress_in_order():
    events: list[str] = []

    async def progress(event: str, data: dict[str, object]) -> None:
        events.append(event)

    asyncio.run(
        RealTripPlanner(FakeMapProvider(), FakeModelProvider()).plan(
            TripPlanRequest(message="成都一日游", destination="成都", days=1),
            progress=progress,
        )
    )

    assert events == [
        "destination.validated",
        "pois.found",
        "routes.calculated",
        "plan.validated",
        "timeline.ready",
    ]


def test_real_planner_revises_one_day_with_a_provider_candidate():
    map_provider = FakeMapProvider()
    planner = RealTripPlanner(map_provider, FakeModelProvider())
    original = asyncio.run(
        planner.plan(TripPlanRequest(message="成都一日游", destination="成都", days=1))
    )

    revised = asyncio.run(
        planner.revise(
            TripRevisionRequest(
                plan=original.plan,
                day=1,
                instruction="换一个景点",
            )
        )
    )

    assert revised.plan.id == original.plan.id
    assert revised.plan.version == original.plan.version + 1
    assert [stop.poi.uid for stop in revised.plan.days[0].stops] == ["p1", "p3"]
    assert revised.timeline.trip_id == revised.plan.id
    assert revised.timeline.trip_version == revised.plan.version


def test_real_planner_keeps_an_explicit_poi_request_in_the_target_day():
    map_provider = FakeMapProvider()
    planner = RealTripPlanner(map_provider, TwoDayFakeModelProvider())
    original = asyncio.run(
        planner.plan(TripPlanRequest(message="成都二日游", destination="成都", days=2))
    )

    revised = asyncio.run(
        planner.revise(
            TripRevisionRequest(
                plan=original.plan,
                day=2,
                instruction="第二天我想去东方明珠玩",
            )
        )
    )

    assert [stop.poi.uid for stop in revised.plan.days[1].stops] == ["p2", "p4"]
    assert map_provider.search_queries[-1].keywords[0] == "东方明珠"


def test_real_planner_limits_positive_poi_revision_to_named_and_current_pois():
    planner = RealTripPlanner(
        FakeMapProvider(),
        OverselectingRevisionModelProvider(),
    )
    original = asyncio.run(
        planner.plan(TripPlanRequest(message="成都一日游", destination="成都", days=1))
    )

    revised = asyncio.run(
        planner.revise(
            TripRevisionRequest(
                plan=original.plan,
                day=1,
                instruction="我想去东方明珠看看",
            )
        )
    )

    assert [stop.poi.uid for stop in revised.plan.days[0].stops] == ["p1", "p2", "p4"]


def test_real_planner_chooses_one_canonical_candidate_for_named_poi():
    planner = RealTripPlanner(
        ExplicitPoiVariantsMapProvider(), OverselectingRevisionModelProvider()
    )
    original = asyncio.run(
        planner.plan(TripPlanRequest(message="成都一日游", destination="成都", days=1))
    )

    revised = asyncio.run(
        planner.revise(
            TripRevisionRequest(
                plan=original.plan,
                day=1,
                instruction="我想去东方明珠看看",
            )
        )
    )

    assert [stop.poi.uid for stop in revised.plan.days[0].stops] == ["p1", "p2", "p5"]


@pytest.mark.parametrize("instruction", ["真实终点我不想去", "我不想去真实终点"])
def test_real_planner_removes_a_poi_when_the_instruction_rejects_it(instruction: str):
    planner = RealTripPlanner(FakeMapProvider(), FakeModelProvider())
    original = asyncio.run(
        planner.plan(TripPlanRequest(message="成都一日游", destination="成都", days=1))
    )

    revised = asyncio.run(
        planner.revise(
            TripRevisionRequest(
                plan=original.plan,
                day=1,
                instruction=instruction,
            )
        )
    )

    assert [stop.poi.uid for stop in revised.plan.days[0].stops] == ["p1", "p3"]


def test_real_planner_does_not_randomize_when_named_poi_is_outside_destination():
    map_provider = NoNamedPoiMapProvider()
    planner = RealTripPlanner(map_provider, TwoDayFakeModelProvider())
    original = asyncio.run(
        planner.plan(TripPlanRequest(message="成都二日游", destination="成都", days=2))
    )
    route_calls_after_plan = map_provider.route_calls

    with pytest.raises(TripPlannerError) as error:
        asyncio.run(
            planner.revise(
                TripRevisionRequest(
                    plan=original.plan,
                    day=2,
                    instruction="第二天我想去东方明珠玩",
                )
            )
        )

    assert error.value.code == "POI_NOT_FOUND"
    assert map_provider.route_calls == route_calls_after_plan


def test_real_planner_rejects_unknown_uid_before_route_lookup():
    map_provider = FakeMapProvider()

    with pytest.raises(TripPlannerError) as error:
        asyncio.run(
            RealTripPlanner(map_provider, UnknownUidModelProvider()).plan(
                TripPlanRequest(message="南京一日游", destination="南京", days=1)
            )
        )

    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert map_provider.route_calls == 0


def test_real_planner_rejects_unknown_revision_uid_before_route_lookup():
    map_provider = FakeMapProvider()
    planner = RealTripPlanner(map_provider, FakeModelProvider())
    original = asyncio.run(
        planner.plan(TripPlanRequest(message="成都一日游", destination="成都", days=1))
    )
    route_calls_after_plan = map_provider.route_calls

    with pytest.raises(TripPlannerError) as error:
        asyncio.run(
            RealTripPlanner(map_provider, UnknownRevisionUidModelProvider()).revise(
                TripRevisionRequest(
                    plan=original.plan,
                    day=1,
                    instruction="换一个景点",
                )
            )
        )

    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert map_provider.route_calls == route_calls_after_plan

def test_real_planner_rejects_revision_that_keeps_the_same_route():
    map_provider = FakeMapProvider()
    planner = RealTripPlanner(map_provider, NoopRevisionModelProvider())
    original = asyncio.run(
        planner.plan(TripPlanRequest(message="成都一日游", destination="成都", days=1))
    )
    route_calls_after_plan = map_provider.route_calls

    with pytest.raises(TripPlannerError) as error:
        asyncio.run(
            planner.revise(
                TripRevisionRequest(
                    plan=original.plan,
                    day=1,
                    instruction="换一个景点",
                )
            )
        )

    assert error.value.code == "MODEL_OUTPUT_INVALID"
    assert map_provider.route_calls == route_calls_after_plan


class TransitModelProvider(FakeModelProvider):
    async def create_schedule(self, request: ScheduleRequest) -> ProposedSchedule:
        return ProposedSchedule(
            days=(PlannedDay(1, ("p1", "p2"), (TravelMode.TRANSIT,)),)
        )


class MixedModeModelProvider(FakeModelProvider):
    async def create_schedule(self, request: ScheduleRequest) -> ProposedSchedule:
        return ProposedSchedule(
            days=(
                PlannedDay(
                    1,
                    ("p1", "p2", "p3"),
                    (TravelMode.WALK, TravelMode.TRANSIT),
                ),
            )
        )


def test_real_planner_routes_each_leg_with_the_ai_selected_transport_mode():
    map_provider = FakeMapProvider()
    result = asyncio.run(
        RealTripPlanner(map_provider, TransitModelProvider()).plan(
            TripPlanRequest(message="成都一日游", destination="成都", days=1)
        )
    )

    assert map_provider.route_modes == [TravelMode.TRANSIT]
    assert result.plan.days[0].route_legs[0].mode is TravelMode.TRANSIT


def test_real_planner_prioritizes_the_requested_transport_for_every_route_leg():
    map_provider = FakeMapProvider()
    result = asyncio.run(
        RealTripPlanner(map_provider, MixedModeModelProvider()).plan(
            TripPlanRequest(
                message="成都一日游",
                destination="成都",
                days=1,
                transport="drive",
            )
        )
    )

    assert map_provider.route_modes == [TravelMode.DRIVE, TravelMode.DRIVE]
    assert [leg.mode for leg in result.plan.days[0].route_legs] == [
        TravelMode.DRIVE,
        TravelMode.DRIVE,
    ]
