# Real-Data Story Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `full-real` planning path that builds the existing `plan` and `timeline` response from Baidu POI/route facts and grounded model output, while keeping fixture mode unchanged.

**Architecture:** Add small `MapProvider` and `ModelProvider` Protocol seams. `BaiduMapAdapter` normalizes Baidu geocoding, Place Search, and DirectionLite responses into domain values; `OpenAIModelAdapter` parses UID-only schedule and fact-grounded narration JSON; `RealTripPlanner` composes, validates, and compiles the result. FastAPI selects the real planner for `full-real` and the existing `map-real` alias without changing the frontend compatibility route.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, httpx, pytest, stdlib dataclasses/uuid/json.

**Spec:** `docs/superpowers/specs/2026-09-14-real-data-story-planning-design.md`

## Global Constraints

- Keep `TripPlan` as the canonical validated itinerary and `StoryTimeline` derived from the exact plan ID/version.
- Every map coordinate crossing the adapter boundary is BD-09.
- The model may select only verified POI UIDs and may not provide coordinates, route geometry, distance, duration, or opening hours.
- Provider failures return structured errors; never fabricate a successful playable plan.
- Keep fixture mode deterministic and offline.
- Do not add a database, ORM, cache, queue, authentication, deployment configuration, or new dependency.
- Run focused tests while changing a module, then run `python -m pytest` or the installed Python 3.12 equivalent.

---

### Task 1: Add the Baidu map provider seam and adapter

**Files:**
- Create: `app/map_provider.py`
- Create: `app/baidu_map.py`
- Modify: `app/settings.py`
- Test: `tests/providers/test_baidu_map.py`

**Interfaces:**
- Produces `ResolvedDestination`, `PoiSearchQuery`, `RouteRequest`, and `MapProvider` from `app/map_provider.py`.
- Produces `BaiduMapAdapter(settings: Settings, http_client: httpx.AsyncClient | None = None)` implementing `MapProvider`.
- `MapProvider.resolve_destination(name: str) -> ResolvedDestination`.
- `MapProvider.search_pois(query: PoiSearchQuery) -> list[VerifiedPoi]`.
- `MapProvider.route(request: RouteRequest) -> RouteLeg`.
- `MapProviderError(code: str, message: str)` uses `MAP_PROVIDER_TIMEOUT`, `POI_NOT_FOUND`, `ROUTE_UNAVAILABLE`, or `MAP_PROVIDER_ERROR`.

- [x] **Step 1: Write the failing adapter contract test**

```python
def test_baidu_adapter_normalizes_geocode_poi_and_route_facts():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/geocoding/v3/":
            return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 118.7969, "lat": 32.0603}}})
        if request.url.path == "/place/v2/search":
            return httpx.Response(200, json={"status": 0, "results": [{
                "uid": "real-poi-1", "name": "真实景点", "address": "南京市真实地址",
                "location": {"lng": 118.797, "lat": 32.061},
                "detail_info": {"shop_hours": "09:00-18:00"},
            }]})
        return httpx.Response(200, json={"status": 0, "result": {"routes": [{
            "distance": 1200, "duration": 600,
            "steps": [{"path": "118.797,32.061;118.798,32.062"}],
        }]}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = BaiduMapAdapter(Settings(baidu_map_ak="test-ak"), client)
            destination = await adapter.resolve_destination("南京")
            pois = await adapter.search_pois(PoiSearchQuery("南京", ("旅游景点",), 20))
            leg = await adapter.route(RouteRequest(pois[0], VerifiedPoi(
                uid="real-poi-2", name="终点", address="地址", point=GeoPoint(lng=118.8, lat=32.063),
                recommended_stay_minutes=60, source="baidu",
                verified_at=datetime.now(timezone.utc),
            )))
            return destination, pois, leg

    destination, pois, leg = asyncio.run(run())
    assert destination.point.crs.value == "BD09"
    assert pois[0].uid == "real-poi-1"
    assert pois[0].opening_hours == "09:00-18:00"
    assert leg.distance_meters == 1200
    assert leg.duration_seconds == 600
    assert leg.geometry[0] == pois[0].point
    assert leg.geometry[-1].lng == 118.8
```

- [x] **Step 2: Run the focused test and confirm it fails for the missing provider module**

Run: `python -m pytest tests/providers/test_baidu_map.py -q`

Expected: collection fails with `ModuleNotFoundError` for `app.baidu_map` or `app.map_provider`.

- [x] **Step 3: Add map settings and provider contracts**

Add to `Settings`:

```python
baidu_map_ak: str | None = Field(default=None, validation_alias=AliasChoices("LUMIVO_BAIDU_MAP_AK", "BAIDU_MAP_AK"))
map_base_url: str = Field(default="https://api.map.baidu.com", validation_alias=AliasChoices("LUMIVO_MAP_BASE_URL", "MAP_BASE_URL"))
map_timeout_ms: int = Field(default=10_000, ge=1_000, le=120_000, validation_alias=AliasChoices("LUMIVO_MAP_TIMEOUT_MS", "MAP_TIMEOUT_MS"))
```

Define frozen dataclasses for the destination, POI search query, and route request. The route request defaults to `TravelMode.WALK` and contains `from_poi` and `to_poi`.

Use these exact fields:

```python
@dataclass(frozen=True)
class ResolvedDestination:
    name: str
    point: GeoPoint


@dataclass(frozen=True)
class PoiSearchQuery:
    destination: str
    keywords: tuple[str, ...]
    limit: int = 20


@dataclass(frozen=True)
class RouteRequest:
    from_poi: VerifiedPoi
    to_poi: VerifiedPoi
    mode: TravelMode = TravelMode.WALK
```

- [x] **Step 4: Implement the minimal Baidu adapter**

Use `httpx.AsyncClient.get` with these paths and parameters:

```python
"/geocoding/v3/": {"address": name, "output": "json", "ret_coordtype": "bd09ll", "ak": ak}
"/place/v2/search": {"query": keyword, "region": query.destination, "city_limit": "true", "scope": "2", "page_size": query.limit, "coord_type": 3, "ret_coordtype": "bd09ll", "output": "json", "ak": ak}
f"/directionlite/v1/{mode_path}": {"origin": "lat,lng", "destination": "lat,lng", "origin_uid": ..., "destination_uid": ..., "coord_type": "bd09ll", "ret_coordtype": "bd09ll", "steps_info": 1, "ak": ak}
```

Parse Baidu `status == 0`, `location`, `results`, `routes[0]`, `distance`, `duration`, and each step's semicolon-separated `path`. Deduplicate adjacent geometry points and force the verified POI points as the first and last geometry values. Set `source="baidu"`, `verified_at=datetime.now(timezone.utc)`, and `recommended_stay_minutes=60` for the required presentation field. Never log the AK or complete request URL.

- [x] **Step 5: Add adapter error tests and run them**

Cover missing AK, non-zero search status, empty routes, malformed JSON, and `httpx.TimeoutException`. Assert the corresponding `MapProviderError.code` values.

Run: `python -m pytest tests/providers/test_baidu_map.py -q`

Expected: PASS.

### Task 2: Add strict real-model schedule and narration adapter

**Files:**
- Create: `app/model_provider.py`
- Test: `tests/providers/test_model_provider.py`

**Interfaces:**
- Produces `ScheduleCandidate`, `ScheduleRequest`, `PlannedDay`, `ProposedSchedule`, `NarrationRequest`, `NarrationSet`, and `ModelProvider`.
- `ModelProvider.create_schedule(request: ScheduleRequest) -> ProposedSchedule`.
- `ModelProvider.create_narration(request: NarrationRequest) -> NarrationSet`.
- Produces `OpenAIModelAdapter(chat_client: ChatClient)`.

Use these exact provider-side values:

```python
@dataclass(frozen=True)
class ScheduleCandidate:
    uid: str
    name: str
    address: str
    opening_hours: str | None


@dataclass(frozen=True)
class ScheduleRequest:
    destination: str
    days: int
    message: str
    candidates: tuple[ScheduleCandidate, ...]


@dataclass(frozen=True)
class PlannedDay:
    day_index: int
    poi_uids: tuple[str, ...]


@dataclass(frozen=True)
class ProposedSchedule:
    days: tuple[PlannedDay, ...]


@dataclass(frozen=True)
class NarrationRequest:
    destination: str
    pois: tuple[VerifiedPoi, ...]


@dataclass(frozen=True)
class NarrationSet:
    by_poi_uid: dict[str, str]
```

- [x] **Step 1: Write the failing strict-parser tests**

Use these test-only helpers so the examples exercise real adapter behavior
without hiding setup in an implicit fixture:

```python
class FakeChatClient:
    def __init__(self, contents: list[str]):
        self.contents = iter(contents)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(message={"role": "assistant", "content": next(self.contents)})


def verified_poi(uid: str) -> VerifiedPoi:
    return VerifiedPoi(
        uid=uid,
        name="景点",
        address="南京市地址",
        point=GeoPoint(lng=118.8, lat=32.06),
        recommended_stay_minutes=60,
        source="baidu",
        verified_at=datetime.now(timezone.utc),
    )


def valid_schedule_request() -> ScheduleRequest:
    return ScheduleRequest(
        destination="南京",
        days=1,
        message="南京一日游",
        candidates=(ScheduleCandidate("p1", "景点", "地址", None),),
    )
```

```python
def test_real_model_adapter_accepts_only_candidate_uids():
    client = FakeChatClient([
        '{"days":[{"day":1,"poiUids":["p1"]}]}',
        '{"narration":[{"poiUid":"p1","text":"基于真实地址的讲解"}]}',
    ])
    adapter = OpenAIModelAdapter(client)
    schedule = asyncio.run(adapter.create_schedule(ScheduleRequest(
        destination="南京", days=1, message="南京一日游",
        candidates=(ScheduleCandidate("p1", "景点", "地址", "09:00-18:00"),),
    )))
    narration = asyncio.run(adapter.create_narration(NarrationRequest(
        destination="南京", pois=(verified_poi("p1"),),
    )))
    assert schedule.days[0].poi_uids == ("p1",)
    assert narration.by_poi_uid["p1"] == "基于真实地址的讲解"


def test_real_model_adapter_rejects_unknown_uid():
    adapter = OpenAIModelAdapter(FakeChatClient(['{"days":[{"day":1,"poiUids":["not-real"]}]}']))
    with pytest.raises(ModelProviderError, match="校验"):
        asyncio.run(adapter.create_schedule(valid_schedule_request()))
```

- [x] **Step 2: Run the focused model tests and confirm the missing-module failure**

Run: `python -m pytest tests/providers/test_model_provider.py -q`

Expected: collection fails with `ModuleNotFoundError` for `app.model_provider`.

- [x] **Step 3: Implement strict JSON parsing and prompts**

The schedule prompt must include only destination, days, user message, and candidate UID/name/address/opening-hours facts and must require exactly `{"days":[...]}`. The narration prompt must include only selected verified POI facts and require exactly `{"narration":[...]}`. Parse with `json.loads`, reject code fences and extra keys, require every requested day exactly once, reject duplicate/unknown UIDs, and require narration UIDs to equal the selected UID set. Let existing `AiClientError` pass through unchanged; convert malformed or invalid model content to `ModelProviderError("MODEL_OUTPUT_INVALID", ...)`.

- [x] **Step 4: Run the focused model tests**

Run: `python -m pytest tests/providers/test_model_provider.py -q`

Expected: PASS.

### Task 3: Compose the real planner and wire the compatibility API

**Files:**
- Create: `app/real_planning_service.py`
- Modify: `app/planning_service.py`
- Modify: `app/main.py`
- Modify: `app/api/compat.py`
- Modify: `app/api/health.py`
- Test: `tests/planning/test_real.py`
- Test: `tests/api/test_compat.py`
- Test: `tests/api/test_health.py`

**Interfaces:**
- `RealTripPlanner(map_provider: MapProvider, model_provider: ModelProvider)` implements the existing `plan(request: TripPlanRequest) -> PlanningResult` shape.
- `TripPlanner` Protocol in `app/planning_service.py` exposes `async plan(request: TripPlanRequest) -> PlanningResult` for both planners and route typing.
- `create_app` uses the injected planner when provided; otherwise it selects `FixtureTripPlanner` for `fixture` and `RealTripPlanner(BaiduMapAdapter(...), OpenAIModelAdapter(...))` for `full-real` and `map-real`.

- [x] **Step 1: Write the failing real-planner test**

Use these test-only fakes, whose route data is deliberately distinguishable
from any fixture value:

```python
class FakeMapProvider:
    def __init__(self):
        self.route_calls = 0
        self.first = VerifiedPoi(
            uid="p1", name="真实起点", address="真实地址1",
            point=GeoPoint(lng=118.7, lat=32.0), recommended_stay_minutes=60,
            source="baidu", verified_at=datetime.now(timezone.utc),
        )
        self.second = self.first.model_copy(update={
            "uid": "p2", "name": "真实终点",
            "point": GeoPoint(lng=118.9, lat=32.1),
        })

    async def resolve_destination(self, name: str) -> ResolvedDestination:
        return ResolvedDestination(name=name, point=self.first.point)

    async def search_pois(self, query: PoiSearchQuery) -> list[VerifiedPoi]:
        return [self.first, self.second]

    async def route(self, request: RouteRequest) -> RouteLeg:
        self.route_calls += 1
        return RouteLeg(
            id="real-route-1", from_poi_uid=request.from_poi.uid,
            to_poi_uid=request.to_poi.uid, mode=request.mode,
            distance_meters=1234, duration_seconds=600,
            geometry=[request.from_poi.point, GeoPoint(lng=118.8, lat=32.05), request.to_poi.point],
        )


class FakeModelProvider:
    async def create_schedule(self, request: ScheduleRequest) -> ProposedSchedule:
        return ProposedSchedule(days=(PlannedDay(1, ("p1", "p2")),))

    async def create_narration(self, request: NarrationRequest) -> NarrationSet:
        return NarrationSet({poi.uid: f"讲解{poi.name}" for poi in request.pois})
```

```python
def test_real_planner_builds_timeline_from_provider_facts():
    map_provider = FakeMapProvider()
    model_provider = FakeModelProvider()
    result = asyncio.run(RealTripPlanner(map_provider, model_provider).plan(
        TripPlanRequest(message="南京一日游", destination="南京", days=1)
    ))
    assert result.plan.days[0].stops[0].poi.source == "baidu"
    assert result.plan.days[0].route_legs[0].distance_meters == 1234
    assert result.plan.days[0].route_legs[0].geometry[1].lng == 118.8
    assert result.timeline.trip_id == result.plan.id
    assert result.timeline.trip_version == result.plan.version
```

Add a second fake-model test that returns an unknown UID and assert
`TripPlannerError.code == "MODEL_OUTPUT_INVALID"` without any route call.

- [x] **Step 2: Run the focused planner tests and confirm the missing-module failure**

Run: `python -m pytest tests/planning/test_real.py -q`

Expected: collection fails with `ModuleNotFoundError` for `app.real_planning_service`.

- [x] **Step 3: Implement the real planner**

Reject known overseas markers before provider calls. Resolve the destination, search up to 20 tourist candidates, require at least one candidate per requested day, ask the model for a UID-only schedule, build stops only from the candidate map, request one walking route for every consecutive pair, ask for grounded narration, then create:

```python
TripPlan(
    id=f"trip-{uuid4().hex}",
    version=1,
    destination=request.destination,
    summary=f"根据百度地图真实地点与路线生成的{request.days}日行程。",
    days=days,
)
```

Call `validate_plan(plan, candidate_uids)` and return `PlanningResult(plan=plan, timeline=compile_timeline(plan))`. Translate `MapProviderError` and `ModelProviderError` into `TripPlannerError` while allowing existing `AiClientError` to reach the HTTP mapping. Translate validation failure to `PLAN_INCOMPLETE`.

- [x] **Step 4: Run the focused planner tests**

Run: `python -m pytest tests/planning/test_real.py -q`

Expected: PASS.

- [x] **Step 5: Wire mode selection and error messages**

Update `create_app` to instantiate the real planner for both non-fixture modes. Update compatibility route typing and `_planner_failure` messages/statuses for `POI_NOT_FOUND`, `ROUTE_UNAVAILABLE`, `MAP_PROVIDER_TIMEOUT`, and `MAP_PROVIDER_ERROR`. Keep the JSON response from `/api/trips/plan` unchanged.

- [x] **Step 6: Add API mode and response tests**

Use an injected fake real planner in `create_app(Settings(provider_mode="full-real"), planner=fake_planner)` and assert `/api/trips/plan` returns `plan` and `timeline`. Assert `/api/v1/health` reports `map_mode="baidu"` and `model_mode="real"` for `full-real` and `map-real`, while fixture reports mock modes.

Run: `python -m pytest tests/api/test_compat.py tests/api/test_health.py -q`

Expected: PASS.

### Task 4: Document configuration and verify the complete suite

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `CONTEXT.md`
- Modify: `docs/superpowers/specs/2026-09-14-real-data-story-planning-design.md`

- [x] **Step 1: Document safe real-mode configuration**

Add these credential-free examples to `.env.example`:

```dotenv
LUMIVO_PROVIDER_MODE=fixture
LUMIVO_BAIDU_MAP_AK=
LUMIVO_MAP_BASE_URL=https://api.map.baidu.com
LUMIVO_MAP_TIMEOUT_MS=10000
```

Document that real data requires `LUMIVO_PROVIDER_MODE=full-real`, a Baidu server AK, and the existing AI API key; explain that fixture mode is the only offline mode and provider failures do not fall back to fixture data.

- [x] **Step 2: Update context and mark the implemented scope**

Update `CONTEXT.md` and the design status to state that Baidu and full-real code paths are implemented locally, while live credentials, quotas, and frontend playback remain separately unverified.

- [x] **Step 3: Run the complete local suite**

Run: `python -m pytest`

Expected: all tests pass; if the `python` shim lacks a configured interpreter, use the installed Python 3.12 executable and report that environment issue separately.

- [x] **Step 4: Run a no-credential smoke check**

Construct `Settings(provider_mode="full-real", baidu_map_ak=None, ai_api_key=None)`, call the API with a valid request, and assert a structured non-200 error rather than fixture data. Do not call a live provider without credentials.

- [x] **Step 5: Review the final diff and report evidence separately**

Run `git diff --check` if Git metadata becomes available; otherwise inspect the changed files directly. Report focused tests, complete suite, no-credential behavior, and live Baidu/AI/browser verification as separate evidence categories.
