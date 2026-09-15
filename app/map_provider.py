from dataclasses import dataclass
from typing import Protocol

from app.domain.trips import GeoPoint, RouteLeg, TravelMode, VerifiedPoi


@dataclass(frozen=True, slots=True)
class ResolvedDestination:
    name: str
    point: GeoPoint


@dataclass(frozen=True, slots=True)
class PoiSearchQuery:
    destination: str
    keywords: tuple[str, ...]
    limit: int = 20


@dataclass(frozen=True, slots=True)
class RouteRequest:
    from_poi: VerifiedPoi
    to_poi: VerifiedPoi
    mode: TravelMode = TravelMode.WALK


class MapProvider(Protocol):
    async def resolve_destination(self, name: str) -> ResolvedDestination: ...

    async def search_pois(self, query: PoiSearchQuery) -> list[VerifiedPoi]: ...

    async def route(self, request: RouteRequest) -> RouteLeg: ...
