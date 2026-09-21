import asyncio

import pytest

from app.domain.chat import TripRevisionRequest
from app.domain.errors import ErrorCode
from app.fixtures_nanjing import nanjing_planning_result
from app.planning_service import FixtureTripPlanner, TripPlannerError
from app.planning_validator import PlanValidationError, validate_plan
from app.story_compiler import compile_timeline


def test_fixture_plan_is_valid_and_timeline_identity_matches():
    result = nanjing_planning_result()

    validate_plan(result.plan)
    assert result.timeline.trip_id == result.plan.id
    assert result.timeline.trip_version == result.plan.version
    assert result.timeline.chapters[0].duration_ms == 1_000
    assert [chapter.duration_ms for chapter in result.timeline.chapters[1:-1]] == [
        8_000,
        8_000,
        8_000,
    ]
    assert result.timeline.chapters[-1].duration_ms == 2_000
    assert result.timeline.total_duration_ms == 27_000


def test_compiler_keeps_commands_inside_their_chapter_windows():
    result = nanjing_planning_result()

    for chapter in result.timeline.chapters:
        chapter_end = chapter.start_ms + chapter.duration_ms
        assert all(
            command.start_ms + command.duration_ms <= chapter_end
            for command in chapter.commands
        )


def test_compiler_emits_playable_route_commands_for_fixture():
    result = nanjing_planning_result()

    timeline = compile_timeline(result.plan)
    commands = [command for chapter in timeline.chapters for command in chapter.commands]

    assert commands[0].type.value == "stage.clear"
    route_commands = [command for command in commands if command.type.value == "route.draw"]
    assert len(route_commands) == 6
    assert {command.payload["routeLegId"] for command in route_commands} == {
        route.id for day in result.plan.days for route in day.route_legs
    }


def test_compiler_scales_intro_animation_to_its_chapter_window():
    result = nanjing_planning_result()
    timeline = compile_timeline(result.plan)
    intro = timeline.chapters[0]

    assert intro.id == "chapter-intro"
    assert intro.duration_ms == 1_000
    assert [command.type.value for command in intro.commands] == [
        "stage.clear",
        "globe.focus",
        "projection.toFlat",
        "camera.flyTo",
        "narration.show",
    ]
    assert intro.commands[-1].payload["text"] == "南京三日行程，从夫子庙-秦淮风光带开始。"
    assert timeline.chapters[1].start_ms == 1_000


def test_validator_rejects_route_endpoint_mismatch():
    result = nanjing_planning_result()
    day = result.plan.days[0]
    broken_leg = day.route_legs[0].model_copy(update={"to_poi_uid": "unknown-poi"})
    broken_day = day.model_copy(update={"route_legs": [broken_leg, *day.route_legs[1:]]})
    broken_plan = result.plan.model_copy(update={"days": [broken_day, *result.plan.days[1:]]})

    with pytest.raises(PlanValidationError) as error:
        validate_plan(broken_plan)

    assert error.value.error.code is ErrorCode.PLAN_INCOMPLETE


def test_fixture_revision_fails_closed():
    result = nanjing_planning_result()

    with pytest.raises(TripPlannerError) as error:
        asyncio.run(
            FixtureTripPlanner(None).revise(
                TripRevisionRequest(
                    plan=result.plan,
                    day=1,
                    instruction="换一个景点",
                )
            )
        )

    assert error.value.code == "PLAN_NOT_AVAILABLE"
