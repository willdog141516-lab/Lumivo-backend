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
    assert result.timeline.total_duration_ms == 49400


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


def test_compiler_uses_the_plan_day_count_in_the_intro_narration():
    result = nanjing_planning_result()
    one_day_plan = result.plan.model_copy(update={"days": result.plan.days[:1]})

    intro_text = compile_timeline(one_day_plan).chapters[0].commands[-1].payload["text"]

    assert intro_text == "南京一日行程，从夫子庙-秦淮风光带开始。"


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
