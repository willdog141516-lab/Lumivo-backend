from app.domain.errors import AppError, ErrorCode
from app.domain.trips import TripPlan


class PlanValidationError(Exception):
    def __init__(self, error: AppError) -> None:
        super().__init__(error.message)
        self.error = error


def _invalid_plan(message: str = "行程不完整，无法播放") -> PlanValidationError:
    return PlanValidationError(
        AppError(code=ErrorCode.PLAN_INCOMPLETE, message=message, retryable=False)
    )


def validate_plan(plan: TripPlan, candidate_uids: set[str] | None = None) -> TripPlan:
    if not plan.days or [day.day_index for day in plan.days] != list(range(1, len(plan.days) + 1)):
        raise _invalid_plan()

    for day in plan.days:
        if not day.stops or len(day.route_legs) != len(day.stops) - 1:
            raise _invalid_plan()

        for stop in day.stops:
            if stop.poi.point.crs.value != "BD09" or (
                candidate_uids is not None and stop.poi.uid not in candidate_uids
            ):
                raise _invalid_plan()

        for index, leg in enumerate(day.route_legs):
            start = day.stops[index].poi
            end = day.stops[index + 1].poi
            if leg.from_poi_uid != start.uid or leg.to_poi_uid != end.uid:
                raise _invalid_plan()
            if leg.geometry[0] != start.point or leg.geometry[-1] != end.point:
                raise _invalid_plan()

    return plan
