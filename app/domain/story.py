from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StoryCommandType(StrEnum):
    STAGE_CLEAR = "stage.clear"
    GLOBE_FOCUS = "globe.focus"
    PROJECTION_TO_FLAT = "projection.toFlat"
    CAMERA_FLY_TO = "camera.flyTo"
    POI_SHOW = "poi.show"
    ROUTE_DRAW = "route.draw"
    ROUTE_FOLLOW = "route.follow"
    NARRATION_SHOW = "narration.show"
    CHAPTER_PAUSE = "chapter.pause"
    INTRODUCTION = "introduction"
    LEGACY_PROJECTION = "projection"
    LEGACY_CAMERA_FLIGHT = "camera_flight"
    LEGACY_POI_DISPLAY = "poi_display"
    LEGACY_ROUTE_DRAW = "route_draw"
    LEGACY_ROUTE_FOLLOW = "route_follow"
    LEGACY_NARRATION = "narration"
    CLOSING = "closing"


class StoryCommand(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    chapter_id: str = Field(alias="chapterId")
    type: StoryCommandType
    start_ms: int = Field(ge=0, alias="startMs")
    duration_ms: int = Field(gt=0, alias="durationMs")
    easing: str = "linear"
    payload: dict[str, object] = Field(default_factory=dict)


class StoryChapter(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    start_ms: int = Field(ge=0, alias="startMs")
    duration_ms: int = Field(gt=0, alias="durationMs")
    commands: list[StoryCommand] = Field(min_length=1)


class StoryTimeline(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    trip_id: str = Field(alias="tripId")
    trip_version: int = Field(ge=1, alias="tripVersion")
    total_duration_ms: int = Field(gt=0, alias="durationMs")
    chapters: list[StoryChapter] = Field(min_length=1)
