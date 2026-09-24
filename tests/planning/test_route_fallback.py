import asyncio

from app.baidu_map import MapProviderError
from app.domain.chat import TripPlanRequest, TripRerouteRequest
from app.domain.trips import RouteLeg, TravelMode
from app.map_provider import RouteRequest
from app.planning_service import TripPlannerError
from app.fixtures_nanjing import nanjing_trip_plan
from app.real_planning_service import RealTripPlanner
from tests.planning.test_real import FakeMapProvider, TransitModelProvider


class TransitUnavailableMapProvider(FakeMapProvider):
    async def route(self, request: RouteRequest) -> RouteLeg:
        if request.mode is TravelMode.TRANSIT:
            self.route_calls += 1
            self.route_modes.append(request.mode)
            raise MapProviderError("ROUTE_UNAVAILABLE", "公交路线不可用")
        return await super().route(request)


def test_real_planner_keeps_initial_transit_fallback():
    map_provider = TransitUnavailableMapProvider()

    result = asyncio.run(
        RealTripPlanner(map_provider, TransitModelProvider()).plan(
            TripPlanRequest(message="成都一日游", destination="成都", days=1)
        )
    )

    assert result.plan.days[0].route_legs[0].mode is TravelMode.DRIVE
    assert map_provider.route_modes == [TravelMode.TRANSIT, TravelMode.DRIVE]


def test_real_planner_does_not_fallback_during_reroute():
    map_provider = TransitUnavailableMapProvider()
    plan = nanjing_trip_plan()
    route_snapshot = plan.model_dump(mode="json", exclude={"days": {i: {"route_legs"} for i in range(len(plan.days))}})

    try:
        asyncio.run(
            RealTripPlanner(map_provider, TransitModelProvider()).reroute(
                TripRerouteRequest.model_validate(
                    {"plan": route_snapshot, "transport": TravelMode.TRANSIT}
                )
            )
        )
    except TripPlannerError as error:
        assert error.code == "ROUTE_UNAVAILABLE"
    else:
        raise AssertionError("reroute transit failure must not silently become driving")

    assert map_provider.route_modes == [TravelMode.TRANSIT]
