import asyncio
from datetime import datetime, timezone

import pytest

from app.domain.chat import TripPlanRequest
from app.domain.trips import GeoPoint, RouteLeg, VerifiedPoi
from app.map_provider import PoiSearchQuery, ResolvedDestination, RouteRequest
from app.model_provider import (
    NarrationRequest,
    NarrationSet,
    PlannedDay,
    ProposedSchedule,
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
        self.route_calls = 0

    async def resolve_destination(self, name: str) -> ResolvedDestination:
        return ResolvedDestination(name=name, point=self.first.point)

    async def search_pois(self, query: PoiSearchQuery) -> list[VerifiedPoi]:
        return [self.first, self.second]

    async def route(self, request: RouteRequest) -> RouteLeg:
        self.route_calls += 1
        return RouteLeg(
            id="real-route-1",
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
    async def create_schedule(self, request: ScheduleRequest) -> ProposedSchedule:
        return ProposedSchedule(days=(PlannedDay(1, ("p1", "p2")),))

    async def create_narration(self, request: NarrationRequest) -> NarrationSet:
        return NarrationSet({poi.uid: f"讲解{poi.name}" for poi in request.pois})


class UnknownUidModelProvider(FakeModelProvider):
    async def create_schedule(self, request: ScheduleRequest) -> ProposedSchedule:
        return ProposedSchedule(days=(PlannedDay(1, ("unknown",)),))


def test_real_planner_builds_timeline_from_provider_facts():
    map_provider = FakeMapProvider()
    result = asyncio.run(
        RealTripPlanner(map_provider, FakeModelProvider()).plan(
            TripPlanRequest(message="南京一日游", destination="南京", days=1)
        )
    )

    assert result.plan.id.startswith("trip-")
    assert result.plan.days[0].stops[0].poi.source == "baidu"
    assert result.plan.days[0].route_legs[0].distance_meters == 1234
    assert result.plan.days[0].route_legs[0].geometry[1].lng == 118.8
    assert result.timeline.trip_id == result.plan.id
    assert result.timeline.trip_version == result.plan.version


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
