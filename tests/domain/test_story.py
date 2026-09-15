import pytest
from pydantic import ValidationError

from app.domain.story import StoryChapter, StoryCommand, StoryCommandType, StoryTimeline


def test_story_timeline_keeps_trip_identity_and_command_order():
    timeline = StoryTimeline(
        trip_id="trip-1",
        trip_version=2,
        total_duration_ms=5000,
        chapters=[
            StoryChapter(
                id="chapter-1",
                title="开场",
                start_ms=0,
                duration_ms=5000,
                commands=[
                    StoryCommand(
                        id="command-1",
                        chapter_id="chapter-1",
                        type=StoryCommandType.INTRODUCTION,
                        start_ms=0,
                        duration_ms=5000,
                    )
                ],
            )
        ],
    )

    assert timeline.trip_id == "trip-1"
    assert timeline.trip_version == 2
    assert timeline.chapters[0].commands[0].chapter_id == "chapter-1"


def test_story_durations_must_be_positive():
    with pytest.raises(ValidationError):
        StoryCommand(
            id="command-1",
            chapter_id="chapter-1",
            type=StoryCommandType.CLOSING,
            start_ms=0,
            duration_ms=0,
        )
