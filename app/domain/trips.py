from __future__ import annotations

from datetime import date as Date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.story import StoryTimeline


class CoordinateSystem(StrEnum):
    BD09 = "BD09"


class GeoPoint(BaseModel):
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    crs: CoordinateSystem = CoordinateSystem.BD09


class TravelMode(StrEnum):
    WALK = "walk"
    TRANSIT = "transit"
    DRIVE = "drive"
    RIDE = "ride"


class TripRequest(BaseModel):
    destination: str
    days: int = Field(ge=1, le=14)
    message: str
    departure: str | None = None
    start_date: Date | None = None
    interests: list[str] = Field(default_factory=list)
    pace: str | None = None
    budget: str | None = None
    transport: list[TravelMode] = Field(default_factory=list)


def _require_timezone_aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("datetime must include timezone information")
    return value


class VerifiedPoi(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uid: str
    name: str
    address: str
    point: GeoPoint
    opening_hours: str | None = Field(default=None, alias="openingHours")
    recommended_stay_minutes: int = Field(gt=0, alias="recommendedStayMinutes")
    source: str
    verified_at: datetime = Field(alias="verifiedAt")

    @field_validator("verified_at")
    @classmethod
    def verified_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _require_timezone_aware(value)  # type: ignore[return-value]


class RouteLeg(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    from_poi_uid: str = Field(alias="fromPoiUid")
    to_poi_uid: str = Field(alias="toPoiUid")
    mode: TravelMode
    distance_meters: int = Field(gt=0, alias="distanceMeters")
    duration_seconds: int = Field(gt=0, alias="durationSeconds")
    geometry: list[GeoPoint] = Field(min_length=2)


class TripStop(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    poi: VerifiedPoi
    arrival_at: datetime | None = Field(default=None, alias="arrivalTime")
    departure_at: datetime | None = Field(default=None, alias="departureTime")
    stay_minutes: int | None = Field(default=None, gt=0, alias="stayMinutes")
    narration: str | None = None

    _arrival_at_must_be_timezone_aware = field_validator("arrival_at", "departure_at")(
        _require_timezone_aware
    )

    @model_validator(mode="after")
    def departure_must_not_precede_arrival(self) -> "TripStop":
        if (
            self.arrival_at is not None
            and self.departure_at is not None
            and self.departure_at < self.arrival_at
        ):
            raise ValueError("departure_at must not precede arrival_at")
        return self


class TripDay(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    day_index: int = Field(ge=1, alias="day")
    title: str | None = None
    date: Date | None = None
    summary: str | None = None
    stops: list[TripStop] = Field(min_length=1)
    route_legs: list[RouteLeg] = Field(default_factory=list, alias="routeLegs")


class TripPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    version: int = Field(ge=1)
    destination: str
    summary: str
    days: list[TripDay] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class TripRerouteDay(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    day_index: int = Field(ge=1, alias="day")
    title: str | None = None
    date: Date | None = None
    summary: str | None = None
    stops: list[TripStop] = Field(min_length=1)


class TripReroutePlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    version: int = Field(ge=1)
    destination: str
    summary: str
    days: list[TripRerouteDay] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class PlanningResult(BaseModel):
    plan: TripPlan
    timeline: StoryTimeline
