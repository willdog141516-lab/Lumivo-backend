import asyncio
from datetime import datetime, timezone
from hashlib import md5
from urllib.parse import quote, urlencode

import httpx
import pytest

from app.baidu_map import BaiduMapAdapter, MapProviderError
from app.domain.trips import GeoPoint, RouteLeg, TravelMode, VerifiedPoi
from app.map_provider import PoiSearchQuery, RouteRequest
from app.settings import Settings


def test_baidu_adapter_normalizes_geocode_poi_and_route_facts():
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/geocoding/v3/":
            return httpx.Response(
                200,
                json={
                    "status": 0,
                    "result": {"location": {"lng": 118.7969, "lat": 32.0603}},
                },
            )
        if request.url.path == "/place/v2/search":
            return httpx.Response(
                200,
                json={
                    "status": 0,
                    "results": [
                        {
                            "uid": "real-poi-1",
                            "name": "真实景点",
                            "address": "南京市真实地址",
                            "location": {"lng": 118.797, "lat": 32.061},
                            "detail_info": {"shop_hours": "09:00-18:00"},
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "status": 0,
                "result": {
                    "routes": [
                        {
                            "distance": 1200,
                            "duration": 600,
                            "steps": [
                                {"path": "118.797,32.061;118.798,32.062"},
                            ],
                        }
                    ]
                },
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = BaiduMapAdapter(Settings(baidu_map_ak="test-ak"), client)
            destination = await adapter.resolve_destination("南京")
            pois = await adapter.search_pois(PoiSearchQuery("南京", ("旅游景点",), 20))
            endpoint = VerifiedPoi(
                uid="real-poi-2",
                name="终点",
                address="地址",
                point=GeoPoint(lng=118.8, lat=32.063),
                recommended_stay_minutes=60,
                source="baidu",
                verified_at=datetime.now(timezone.utc),
            )
            leg = await adapter.route(RouteRequest(pois[0], endpoint))
            ride_leg = await adapter.route(
                RouteRequest(pois[0], endpoint, TravelMode.RIDE)
            )
            return destination, pois, leg, ride_leg

    destination, pois, leg, ride_leg = asyncio.run(run())

    assert destination.point.crs.value == "BD09"
    assert pois[0].uid == "real-poi-1"
    assert pois[0].opening_hours == "09:00-18:00"
    assert leg.distance_meters == 1200
    assert leg.duration_seconds == 600
    assert isinstance(leg, RouteLeg)
    assert leg.geometry[0] == pois[0].point
    assert leg.geometry[1].lng == 118.798
    assert leg.geometry[-1].lng == 118.8
    assert ride_leg.mode is TravelMode.RIDE
    assert paths == [
        "/geocoding/v3/",
        "/place/v2/search",
        "/directionlite/v1/walking",
        "/directionlite/v1/riding",
    ]


def test_baidu_adapter_parses_nested_transit_steps():
    start = VerifiedPoi(
        uid="transit-start",
        name="起点",
        address="地址",
        point=GeoPoint(lng=118.7, lat=32.0),
        recommended_stay_minutes=60,
        source="baidu",
        verified_at=datetime.now(timezone.utc),
    )
    end = start.model_copy(
        update={
            "uid": "transit-end",
            "name": "终点",
            "point": GeoPoint(lng=118.8, lat=32.06),
        }
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/directionlite/v1/transit"
        return httpx.Response(
            200,
            json={
                "status": 0,
                "message": "ok",
                "result": {
                    "origin": {"location": {"lng": 118.7, "lat": 32.0}},
                    "destination": {"location": {"lng": 118.8, "lat": 32.06}},
                    "routes": [
                        {
                            "distance": 22274,
                            "duration": 4143,
                            "line_price": 2,
                            "price": 2,
                            "traffic_condition": [],
                            "steps": [
                                [
                                    {
                                        "distance": 100,
                                        "duration": 60,
                                        "end_location": {"lng": 118.72, "lat": 32.01},
                                        "instruction": "步行",
                                        "path": "118.71,32.005;118.72,32.01",
                                        "start_location": {"lng": 118.7, "lat": 32.0},
                                        "type": 5,
                                        "vehicle": {},
                                    }
                                ],
                                [
                                    {
                                        "distance": 200,
                                        "duration": 120,
                                        "end_location": {"lng": 118.79, "lat": 32.05},
                                        "instruction": "乘坐公交",
                                        "path": "118.72,32.01;118.79,32.05",
                                        "start_location": {"lng": 118.72, "lat": 32.01},
                                        "type": 3,
                                        "vehicle": {"name": "公交"},
                                    }
                                ],
                            ],
                        }
                    ],
                    "taxi": {},
                },
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = BaiduMapAdapter(Settings(baidu_map_ak="test-ak", _env_file=None), client)
            return await adapter.route(RouteRequest(start, end, TravelMode.TRANSIT))

    leg = asyncio.run(run())

    assert leg.mode is TravelMode.TRANSIT
    assert leg.distance_meters == 22274
    assert leg.duration_seconds == 4143
    assert [point.lng for point in leg.geometry] == [118.7, 118.71, 118.72, 118.79, 118.8]


def test_baidu_adapter_adds_sn_signature_when_sk_is_configured():
    observed: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.update(dict(request.url.params.items()))
        return httpx.Response(
            200,
            json={"status": 0, "result": {"location": {"lng": 118.8, "lat": 32.0}}},
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = BaiduMapAdapter(
                Settings(baidu_map_ak="test-ak", baidu_map_sk="test-sk"), client
            )
            await adapter.resolve_destination("成都")

    asyncio.run(run())

    assert observed["ak"] == "test-ak"
    assert observed["timestamp"].isdigit()
    params = {
        "address": "成都",
        "output": "json",
        "ret_coordtype": "bd09ll",
        "ak": "test-ak",
        "timestamp": observed["timestamp"],
    }
    expected_sn = md5(
        quote("/geocoding/v3/?" + urlencode(params) + "test-sk", safe="").encode("utf-8")
    ).hexdigest()
    assert observed["sn"] == expected_sn


def test_baidu_adapter_requires_an_api_key():
    adapter = BaiduMapAdapter(Settings(_env_file=None))

    with pytest.raises(MapProviderError) as error:
        asyncio.run(adapter.resolve_destination("南京"))

    assert error.value.code == "MAP_PROVIDER_ERROR"


def test_baidu_adapter_maps_search_status_to_provider_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 2, "message": "invalid"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = BaiduMapAdapter(Settings(baidu_map_ak="test-ak"), client)
            await adapter.search_pois(PoiSearchQuery("南京", ("旅游景点",)))

    with pytest.raises(MapProviderError) as error:
        asyncio.run(run())

    assert error.value.code == "MAP_PROVIDER_ERROR"


def test_baidu_adapter_maps_empty_route_to_route_unavailable():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 0, "result": {"routes": []}})

    start = VerifiedPoi(
        uid="start",
        name="起点",
        address="地址",
        point=GeoPoint(lng=118.7, lat=32.0),
        recommended_stay_minutes=60,
        source="baidu",
        verified_at=datetime.now(timezone.utc),
    )
    end = start.model_copy(update={"uid": "end"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = BaiduMapAdapter(Settings(baidu_map_ak="test-ak"), client)
            await adapter.route(RouteRequest(start, end))

    with pytest.raises(MapProviderError) as error:
        asyncio.run(run())

    assert error.value.code == "ROUTE_UNAVAILABLE"


def test_baidu_adapter_maps_malformed_and_timeout_responses():
    async def malformed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async def run(handler):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = BaiduMapAdapter(Settings(baidu_map_ak="test-ak"), client)
            await adapter.resolve_destination("南京")

    with pytest.raises(MapProviderError) as malformed:
        asyncio.run(run(malformed_handler))
    with pytest.raises(MapProviderError) as timeout:
        asyncio.run(run(timeout_handler))

    assert malformed.value.code == "MAP_PROVIDER_ERROR"
    assert timeout.value.code == "MAP_PROVIDER_TIMEOUT"
