from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.errors import AppError, ErrorCode
from app.domain.trips import (
    CoordinateSystem,
    GeoPoint,
    RouteLeg,
    TravelMode,
    TripDay,
    TripPlan,
    TripRequest,
    TripStop,
    VerifiedPoi,
)


def verified_poi(uid: str = "poi-1") -> VerifiedPoi:
    return VerifiedPoi(
        uid=uid,
        name="中山陵",
        address="南京市玄武区石象路7号",
        point=GeoPoint(lng=118.8567, lat=32.0584),
        recommended_stay_minutes=90,
        source="fixture:nanjing",
        verified_at=datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc),
    )


def test_trip_request_defaults_are_stable():
    request = TripRequest(destination="南京", days=3, message="安排历史文化景点")

    assert request.interests == []
    assert request.transport == []
    assert request.start_date is None


def test_trip_plan_accepts_verified_poi_and_route_contract():
    first = verified_poi()
    second = verified_poi("poi-2")
    leg = RouteLeg(
        id="leg-1",
        from_poi_uid=first.uid,
        to_poi_uid=second.uid,
        mode=TravelMode.TRANSIT,
        distance_meters=1200,
        duration_seconds=900,
        geometry=[first.point, second.point],
    )
    plan = TripPlan(
        id="trip-1",
        version=1,
        destination="南京",
        summary="南京三日游",
        days=[
            TripDay(
                day_index=1,
                stops=[TripStop(poi=first), TripStop(poi=second)],
                route_legs=[leg],
            )
        ],
    )

    assert plan.days[0].route_legs[0].from_poi_uid == "poi-1"
    assert plan.days[0].stops[1].poi.point.crs is CoordinateSystem.BD09


def test_invalid_coordinate_and_route_geometry_are_rejected():
    with pytest.raises(ValidationError):
        GeoPoint(lng=181, lat=32)

    with pytest.raises(ValidationError):
        RouteLeg(
            id="leg-1",
            from_poi_uid="poi-1",
            to_poi_uid="poi-2",
            mode=TravelMode.WALK,
            distance_meters=100,
            duration_seconds=60,
            geometry=[GeoPoint(lng=118.8, lat=32.0)],
        )


def test_verified_at_requires_timezone_aware_datetime():
    with pytest.raises(ValidationError):
        VerifiedPoi(
            uid="poi-1",
            name="中山陵",
            address="南京市玄武区石象路7号",
            point=GeoPoint(lng=118.8567, lat=32.0584),
            recommended_stay_minutes=90,
            source="fixture:nanjing",
            verified_at=datetime(2026, 8, 18, 9, 0),
        )


def test_app_error_has_a_structured_retry_contract():
    error = AppError(
        code=ErrorCode.ROUTE_UNAVAILABLE,
        message="路线暂不可用",
        retryable=True,
        details={"from": "poi-1", "to": "poi-2"},
    )

    assert error.code is ErrorCode.ROUTE_UNAVAILABLE
    assert error.retryable is True
    assert error.details == {"from": "poi-1", "to": "poi-2"}
