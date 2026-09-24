from datetime import datetime

from app.domain.trips import (
    GeoPoint,
    PlanningResult,
    RouteLeg,
    TravelMode,
    TripDay,
    TripPlan,
    TripStop,
    VerifiedPoi,
)
from app.story_compiler import compile_timeline


FIXTURE_VERIFIED_AT = datetime.fromisoformat("2026-08-18T00:00:00+08:00")


def _point(lng: float, lat: float) -> GeoPoint:
    return GeoPoint(lng=lng, lat=lat)


def _poi(
    uid: str,
    name: str,
    address: str,
    point: GeoPoint,
    opening_hours: str,
    recommended_stay_minutes: int,
) -> VerifiedPoi:
    return VerifiedPoi(
        uid=uid,
        name=name,
        address=address,
        point=point,
        opening_hours=opening_hours,
        recommended_stay_minutes=recommended_stay_minutes,
        source="fixture",
        verified_at=FIXTURE_VERIFIED_AT,
    )


def _stop(poi: VerifiedPoi, narration: str) -> TripStop:
    return TripStop(poi=poi, narration=narration)


def _route(
    route_id: str,
    start: VerifiedPoi,
    end: VerifiedPoi,
    mode: TravelMode,
    distance_meters: int,
    duration_seconds: int,
    waypoints: list[GeoPoint],
) -> RouteLeg:
    return RouteLeg(
        id=route_id,
        from_poi_uid=start.uid,
        to_poi_uid=end.uid,
        mode=mode,
        distance_meters=distance_meters,
        duration_seconds=duration_seconds,
        geometry=[start.point, *waypoints, end.point],
    )


def nanjing_trip_plan() -> TripPlan:
    fuzimiao = _poi(
        "fixture-nanjing-fuzimiao", "夫子庙-秦淮风光带", "南京市秦淮区夫子庙秦淮河景区", _point(118.7945, 32.0232), "全天开放，具体场馆以现场公告为准", 120
    )
    zhonghuamen = _poi(
        "fixture-nanjing-zhonghuamen", "中华门", "南京市秦淮区中华门城堡", _point(118.7815, 32.0134), "08:30-21:00", 90
    )
    laomendong = _poi(
        "fixture-nanjing-laomendong", "老门东历史文化街区", "南京市秦淮区箍桶巷与剪子巷一带", _point(118.7904, 32.0116), "全天开放，商户营业时间各异", 120
    )
    presidential_palace = _poi(
        "fixture-nanjing-presidential-palace", "南京总统府", "南京市玄武区长江路292号", _point(118.7986, 32.0436), "08:30-18:00，周一闭馆", 120
    )
    six_dynasties_museum = _poi(
        "fixture-nanjing-six-dynasties-museum", "六朝博物馆", "南京市玄武区长江路302号", _point(118.8032, 32.0455), "09:00-18:00，周一闭馆", 90
    )
    nanjing_museum = _poi(
        "fixture-nanjing-museum", "南京博物院", "南京市玄武区中山东路321号", _point(118.8438, 32.0416), "09:00-17:00，周一闭馆", 150
    )
    xuanwu_lake = _poi(
        "fixture-nanjing-xuanwu-lake", "玄武湖", "南京市玄武区玄武巷1号", _point(118.799, 32.0722), "06:00-21:00", 120
    )
    jiming_temple = _poi(
        "fixture-nanjing-jiming-temple", "鸡鸣寺", "南京市玄武区鸡鸣寺路1号", _point(118.8155, 32.0605), "07:30-17:30", 90
    )
    taicheng = _poi(
        "fixture-nanjing-taicheng", "明城墙台城段", "南京市玄武区解放门至神策门一带", _point(118.814, 32.0671), "08:30-21:00", 90
    )

    return TripPlan(
        id="fixture-nanjing-3d",
        version=1,
        destination="南京",
        summary="用三天时间串联秦淮风光、民国城市记忆与玄武湖畔的南京城市故事。",
        days=[
            TripDay(
                day_index=1,
                title="秦淮灯影与城南旧事",
                summary="从夫子庙沿秦淮河走到中华门，再在老门东收束第一天。",
                stops=[
                    _stop(fuzimiao, "从夫子庙开始认识南京：秦淮河、牌坊与市井烟火在这里交汇。"),
                    _stop(zhonghuamen, "中华门是南京城墙的重要南门，可以从城门结构俯瞰城南街巷。"),
                    _stop(laomendong, "老门东把传统街巷、手作店铺和夜间小吃连成一段适合慢慢散步的收尾路线。"),
                ],
                route_legs=[
                    _route("fixture-route-day-1-fuzimiao-zhonghuamen", fuzimiao, zhonghuamen, TravelMode.RIDE, 3400, 960, [_point(118.789, 32.018)]),
                    _route("fixture-route-day-1-zhonghuamen-laomendong", zhonghuamen, laomendong, TravelMode.WALK, 1500, 480, [_point(118.7866, 32.011)]),
                ],
            ),
            TripDay(
                day_index=2,
                title="长江路上的近代南京",
                summary="沿长江路理解南京的近代城市脉络，再用南京博物院补足历史纵深。",
                stops=[
                    _stop(presidential_palace, "总统府保留了多重历史时期的建筑与空间，是理解近代南京的一处入口。"),
                    _stop(six_dynasties_museum, "六朝博物馆用考古遗存和城市文脉，串起南京作为六朝古都的早期记忆。"),
                    _stop(nanjing_museum, "南京博物院适合用较完整的一段时间浏览，从地方文明看到更大的中国历史。"),
                ],
                route_legs=[
                    _route("fixture-route-day-2-presidential-six-dynasties", presidential_palace, six_dynasties_museum, TravelMode.WALK, 1100, 480, [_point(118.8005, 32.0447)]),
                    _route("fixture-route-day-2-six-dynasties-nanjing-museum", six_dynasties_museum, nanjing_museum, TravelMode.RIDE, 4200, 1200, [_point(118.818, 32.0438)]),
                ],
            ),
            TripDay(
                day_index=3,
                title="玄武湖畔的城墙与晨光",
                summary="以玄武湖的开阔水面开始，在鸡鸣寺和台城段城墙结束南京三日行程。",
                stops=[
                    _stop(xuanwu_lake, "玄武湖给最后一天留出舒展的节奏，湖面与城墙共同构成南京的城市天际线。"),
                    _stop(jiming_temple, "鸡鸣寺临湖而建，短暂停留可以感受古寺、山门和城市之间的距离。"),
                    _stop(taicheng, "从台城段城墙回望玄武湖，把自然水面、古都城防和现代城市放进同一幅画面。"),
                ],
                route_legs=[
                    _route("fixture-route-day-3-xuanwu-jiming", xuanwu_lake, jiming_temple, TravelMode.WALK, 2200, 720, [_point(118.8084, 32.0674)]),
                    _route("fixture-route-day-3-jiming-taicheng", jiming_temple, taicheng, TravelMode.WALK, 800, 300, [_point(118.8144, 32.0638)]),
                ],
            ),
        ],
        warnings=[],
    )


def nanjing_planning_result(transport: TravelMode | None = None) -> PlanningResult:
    plan = nanjing_trip_plan()
    if transport is not None:
        # ponytail: fixture modes reuse fixed route facts; live mode-specific routes require full-real.
        plan = plan.model_copy(
            update={
                "days": [
                    day.model_copy(
                        update={
                            "route_legs": [
                                leg.model_copy(update={"mode": transport})
                                for leg in day.route_legs
                            ]
                        }
                    )
                    for day in plan.days
                ]
            }
        )
    return PlanningResult(plan=plan, timeline=compile_timeline(plan))
