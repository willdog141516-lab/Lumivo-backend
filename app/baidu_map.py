from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.domain.trips import GeoPoint, RouteLeg, TravelMode, VerifiedPoi
from app.map_provider import PoiSearchQuery, ResolvedDestination, RouteRequest
from app.settings import Settings


class MapProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_ROUTE_PATHS = {
    TravelMode.WALK: "walking",
    TravelMode.DRIVE: "driving",
    TravelMode.RIDE: "riding",
    TravelMode.TRANSIT: "transit",
}


def _number(value: object, field: str) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"invalid {field}") from None


def _point(value: object) -> GeoPoint:
    if not isinstance(value, dict):
        raise ValueError("invalid location")
    return GeoPoint(lng=_number(value.get("lng"), "longitude"), lat=_number(value.get("lat"), "latitude"))


def _status(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _path_points(value: object) -> list[GeoPoint]:
    if not isinstance(value, str):
        raise ValueError("invalid route path")
    points: list[GeoPoint] = []
    for pair in value.split(";"):
        if not pair:
            continue
        parts = pair.split(",")
        if len(parts) != 2:
            raise ValueError("invalid route path")
        point = GeoPoint(lng=_number(parts[0], "longitude"), lat=_number(parts[1], "latitude"))
        if not points or points[-1] != point:
            points.append(point)
    return points


class BaiduMapAdapter:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._http_client = http_client

    def _api_key(self) -> str:
        if not self._settings.baidu_map_ak:
            raise MapProviderError("MAP_PROVIDER_ERROR", "百度地图服务尚未配置 AK")
        return self._settings.baidu_map_ak

    async def _get(self, path: str, params: dict[str, object]) -> dict[str, object]:
        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(
            timeout=self._settings.map_timeout_ms / 1000
        )
        try:
            response = await client.get(
                f"{self._settings.map_base_url.rstrip('/')}{path}", params=params
            )
            if response.status_code >= 400:
                raise MapProviderError("MAP_PROVIDER_ERROR", "百度地图服务暂时不可用")
            try:
                payload = response.json()
            except (TypeError, ValueError):
                raise MapProviderError("MAP_PROVIDER_ERROR", "百度地图返回数据无效") from None
            if not isinstance(payload, dict):
                raise MapProviderError("MAP_PROVIDER_ERROR", "百度地图返回数据无效")
            return payload
        except MapProviderError:
            raise
        except httpx.TimeoutException:
            raise MapProviderError("MAP_PROVIDER_TIMEOUT", "百度地图服务响应超时") from None
        except httpx.RequestError:
            raise MapProviderError("MAP_PROVIDER_ERROR", "百度地图服务暂时不可用") from None
        finally:
            if owns_client:
                await client.aclose()

    async def resolve_destination(self, name: str) -> ResolvedDestination:
        payload = await self._get(
            "/geocoding/v3/",
            {
                "address": name,
                "output": "json",
                "ret_coordtype": "bd09ll",
                "ak": self._api_key(),
            },
        )
        if _status(payload.get("status")) != 0:
            raise MapProviderError("POI_NOT_FOUND", "未找到该目的地")
        try:
            result = payload["result"]
            point = _point(result["location"])  # type: ignore[index]
        except (KeyError, TypeError, ValueError):
            raise MapProviderError("POI_NOT_FOUND", "未找到该目的地") from None
        return ResolvedDestination(name=name, point=point)

    async def search_pois(self, query: PoiSearchQuery) -> list[VerifiedPoi]:
        results: dict[str, VerifiedPoi] = {}
        limit = max(1, min(query.limit, 20))
        for keyword in query.keywords:
            payload = await self._get(
                "/place/v2/search",
                {
                    "query": keyword,
                    "region": query.destination,
                    "city_limit": "true",
                    "scope": "2",
                    "page_size": limit,
                    "coord_type": 3,
                    "ret_coordtype": "bd09ll",
                    "output": "json",
                    "ak": self._api_key(),
                },
            )
            if _status(payload.get("status")) != 0:
                raise MapProviderError("MAP_PROVIDER_ERROR", "百度 POI 服务返回错误")
            raw_results = payload.get("results")
            if not isinstance(raw_results, list):
                continue
            for raw in raw_results:
                if not isinstance(raw, dict):
                    continue
                uid = raw.get("uid")
                name = raw.get("name")
                address = raw.get("address")
                try:
                    if not all(isinstance(item, str) and item.strip() for item in (uid, name, address)):
                        continue
                    point = _point(raw.get("location"))
                except ValueError:
                    continue
                detail_info = raw.get("detail_info")
                opening_hours = (
                    detail_info.get("shop_hours")
                    if isinstance(detail_info, dict)
                    else None
                )
                results[uid] = VerifiedPoi(
                    uid=uid,
                    name=name,
                    address=address,
                    point=point,
                    opening_hours=opening_hours if isinstance(opening_hours, str) else None,
                    recommended_stay_minutes=60,
                    source="baidu",
                    verified_at=datetime.now(timezone.utc),
                )
        if not results:
            raise MapProviderError("POI_NOT_FOUND", "该目的地没有可用 POI")
        return list(results.values())[:limit]

    async def route(self, request: RouteRequest) -> RouteLeg:
        mode_path = _ROUTE_PATHS[request.mode]
        payload = await self._get(
            f"/directionlite/v1/{mode_path}",
            {
                "origin": f"{request.from_poi.point.lat:.6f},{request.from_poi.point.lng:.6f}",
                "destination": f"{request.to_poi.point.lat:.6f},{request.to_poi.point.lng:.6f}",
                "origin_uid": request.from_poi.uid,
                "destination_uid": request.to_poi.uid,
                "coord_type": "bd09ll",
                "ret_coordtype": "bd09ll",
                "steps_info": 1,
                "ak": self._api_key(),
            },
        )
        if _status(payload.get("status")) != 0:
            raise MapProviderError("ROUTE_UNAVAILABLE", "百度路线服务返回错误")
        try:
            result = payload["result"]
            routes = result["routes"]  # type: ignore[index]
            route = routes[0]  # type: ignore[index]
            distance = int(float(route["distance"]))  # type: ignore[index]
            duration = int(float(route["duration"]))  # type: ignore[index]
            steps = route["steps"]  # type: ignore[index]
            if isinstance(steps, dict):
                steps = [steps]
            if not isinstance(steps, list):
                raise ValueError("invalid route steps")
            path_points: list[GeoPoint] = []
            for step in steps:
                if not isinstance(step, dict):
                    raise ValueError("invalid route step")
                for point in _path_points(step.get("path")):
                    if not path_points or path_points[-1] != point:
                        path_points.append(point)
            if distance <= 0 or duration <= 0 or not path_points:
                raise ValueError("route is not playable")
        except (KeyError, IndexError, TypeError, ValueError):
            raise MapProviderError("ROUTE_UNAVAILABLE", "百度没有返回可播放路线") from None

        geometry = [request.from_poi.point]
        for point in [*path_points, request.to_poi.point]:
            if geometry[-1] != point:
                geometry.append(point)

        return RouteLeg(
            id=f"baidu-route-{request.from_poi.uid}-{request.to_poi.uid}-{request.mode.value}",
            from_poi_uid=request.from_poi.uid,
            to_poi_uid=request.to_poi.uid,
            mode=request.mode,
            distance_meters=distance,
            duration_seconds=duration,
            geometry=geometry,
        )
