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


def validate_revision(
    original: TripPlan,
    revised: TripPlan,
    target_day: int,
    target_candidate_uids: set[str],
) -> TripPlan:
    if (
        original.id != revised.id
        or revised.version != original.version + 1
        or original.destination != revised.destination
        or len(original.days) != len(revised.days)
        or target_day < 1
        or target_day > len(original.days)
        or [day.day_index for day in revised.days]
        != list(range(1, len(revised.days) + 1))
    ):
        raise _invalid_plan()

    target_index = target_day - 1
    for index, (original_day, revised_day) in enumerate(
        zip(original.days, revised.days)
    ):
        if index != target_index and original_day != revised_day:
            raise _invalid_plan()

    target_uids = [stop.poi.uid for stop in revised.days[target_index].stops]
    if not target_uids or any(uid not in target_candidate_uids for uid in target_uids):
        raise _invalid_plan()

    all_uids = [
        stop.poi.uid
        for day in revised.days
        for stop in day.stops
    ]
    if len(all_uids) != len(set(all_uids)):
        raise _invalid_plan()

    return validate_plan(revised)
