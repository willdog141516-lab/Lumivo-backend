from app.domain.story import StoryChapter, StoryCommand, StoryCommandType, StoryTimeline
from app.domain.trips import TripDay, TripPlan


INTRO_DURATION_MS = 5_200
DAY_DURATION_MS = 13_800
CLOSING_DURATION_MS = 2_800


def _ordinal(day: int) -> str:
    return {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}.get(day, str(day))


def _command(
    chapter_id: str,
    index: int,
    command_type: StoryCommandType,
    start_ms: int,
    duration_ms: int,
    payload: dict[str, object] | None = None,
    easing: str = "linear",
) -> StoryCommand:
    return StoryCommand(
        id=f"command-{chapter_id}-{index}",
        chapter_id=chapter_id,
        type=command_type,
        start_ms=start_ms,
        duration_ms=duration_ms,
        easing=easing,
        payload=payload or {},
    )


def _day_chapter(plan: TripPlan, day: TripDay, start_ms: int) -> StoryChapter:
    chapter_id = f"chapter-day-{day.day_index}"
    commands: list[StoryCommand] = []
    first = day.stops[0]
    commands.append(
        _command(
            chapter_id,
            len(commands),
            StoryCommandType.POI_SHOW,
            start_ms,
            300,
            {"poiUid": first.poi.uid},
        )
    )
    commands.append(
        _command(
            chapter_id,
            len(commands),
            StoryCommandType.NARRATION_SHOW,
            start_ms + 300,
            1_800,
            {"text": first.narration or "", "poiUid": first.poi.uid},
        )
    )

    for index, leg in enumerate(day.route_legs):
        offset = index * 4_700
        destination = day.stops[index + 1]
        commands.append(
            _command(
                chapter_id,
                len(commands),
                StoryCommandType.ROUTE_DRAW,
                start_ms + 2_100 + offset,
                800,
                {"routeLegId": leg.id},
            )
        )
        commands.append(
            _command(
                chapter_id,
                len(commands),
                StoryCommandType.ROUTE_FOLLOW,
                start_ms + 2_900 + offset,
                1_700 if index == 0 else 1_600,
                {"routeLegId": leg.id},
                "easeInOut",
            )
        )
        commands.append(
            _command(
                chapter_id,
                len(commands),
                StoryCommandType.POI_SHOW,
                start_ms + 4_600 + offset,
                300,
                {"poiUid": destination.poi.uid},
            )
        )
        commands.append(
            _command(
                chapter_id,
                len(commands),
                StoryCommandType.NARRATION_SHOW,
                start_ms + 4_900 + offset,
                2_500 if index == len(day.route_legs) - 1 else 1_900,
                {"text": destination.narration or "", "poiUid": destination.poi.uid},
            )
        )

    commands.append(
        _command(
            chapter_id,
            len(commands),
            StoryCommandType.CHAPTER_PAUSE,
            start_ms + 12_000,
            1_800,
        )
    )
    return StoryChapter(
        id=chapter_id,
        title=f"第{_ordinal(day.day_index)}天：{day.title or plan.destination}",
        start_ms=start_ms,
        duration_ms=DAY_DURATION_MS,
        commands=commands,
    )


def compile_timeline(plan: TripPlan) -> StoryTimeline:
    first_stop = plan.days[0].stops[0]
    chapters = [
        StoryChapter(
            id="chapter-intro",
            title=f"从全景进入{plan.destination}",
            start_ms=0,
            duration_ms=INTRO_DURATION_MS,
            commands=[
                _command("chapter-intro", 0, StoryCommandType.STAGE_CLEAR, 0, 300),
                _command(
                    "chapter-intro",
                    1,
                    StoryCommandType.GLOBE_FOCUS,
                    0,
                    1_800,
                    {"target": first_stop.poi.point.model_dump(mode="json")},
                    "easeInOut",
                ),
                _command(
                    "chapter-intro",
                    2,
                    StoryCommandType.PROJECTION_TO_FLAT,
                    1_800,
                    1_000,
                    easing="easeInOut",
                ),
                _command(
                    "chapter-intro",
                    3,
                    StoryCommandType.CAMERA_FLY_TO,
                    2_800,
                    1_800,
                    {"target": first_stop.poi.point.model_dump(mode="json"), "zoom": 14},
                    "easeInOut",
                ),
                _command(
                    "chapter-intro",
                    4,
                    StoryCommandType.NARRATION_SHOW,
                    3_900,
                    1_200,
                    {"text": f"{plan.destination}{_ordinal(len(plan.days))}日行程，从{first_stop.poi.name}开始。"},
                ),
            ],
        )
    ]

    for index, day in enumerate(plan.days):
        chapters.append(_day_chapter(plan, day, INTRO_DURATION_MS + index * DAY_DURATION_MS))

    closing_start = INTRO_DURATION_MS + len(plan.days) * DAY_DURATION_MS
    chapters.append(
        StoryChapter(
            id="chapter-closing",
            title=f"{plan.destination}行程结束",
            start_ms=closing_start,
            duration_ms=CLOSING_DURATION_MS,
            commands=[
                _command(
                    "chapter-closing",
                    0,
                    StoryCommandType.NARRATION_SHOW,
                    closing_start,
                    1_800,
                    {"text": f"这段{plan.destination}行程，从城市故事开始，也在城市故事中闭合。"},
                ),
                _command(
                    "chapter-closing",
                    1,
                    StoryCommandType.CHAPTER_PAUSE,
                    closing_start + 1_800,
                    1_000,
                ),
            ],
        )
    )

    return StoryTimeline(
        trip_id=plan.id,
        trip_version=plan.version,
        total_duration_ms=closing_start + CLOSING_DURATION_MS,
        chapters=chapters,
    )
