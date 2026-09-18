import pytest
from pydantic import ValidationError

from app.domain.chat import TripRevisionRequest
from app.fixtures_nanjing import nanjing_trip_plan


def test_revision_day_must_exist_in_the_current_plan():
    with pytest.raises(ValidationError, match="day"):
        TripRevisionRequest(
            plan=nanjing_trip_plan(),
            day=4,
            instruction="换一个景点",
        )


def test_revision_instruction_is_trimmed():
    request = TripRevisionRequest(
        plan=nanjing_trip_plan(),
        day=2,
        instruction="  增加一个博物馆  ",
    )
    assert request.instruction == "增加一个博物馆"
