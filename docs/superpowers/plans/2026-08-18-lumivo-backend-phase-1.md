# Lumivo Backend Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first runnable Lumivo FastAPI backend with environment settings, a health endpoint, canonical Pydantic contracts, structured errors, and deterministic tests.

**Architecture:** Use an application factory in `app/main.py` that assembles settings, CORS, and thin API routers. Keep domain models and errors in FastAPI-independent modules; provider adapters and trip-planning behavior remain out of scope for this phase. The default `fixture` mode is represented in settings and health output without making network calls.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pydantic-settings, Uvicorn, HTTPX, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-18-lumivo-backend-design.md`

## Global Constraints

- The MVP supports China-only itinerary planning and does not add authentication, a database, Redis, queues, cloud persistence, deployment, or real-time navigation.
- `TripPlan` is the canonical validated itinerary; `StoryTimeline` is derived from one exact `trip_id` and `trip_version`.
- Every coordinate crossing the future map-provider seam uses BD-09.
- Provider-specific payloads and planning logic do not enter this scaffold phase.
- Default tests must not require network access or provider credentials.
- Secrets stay in ignored `.env`; commit only safe mock defaults in `.env.example`.
- The current directory is not a Git repository, so do not initialize Git or create a commit during this phase.

## Planned File Structure

```text
app/
├─ __init__.py
├─ main.py
├─ settings.py
├─ api/
│  ├─ __init__.py
│  └─ health.py
└─ domain/
   ├─ __init__.py
   ├─ errors.py
   ├─ story.py
   └─ trips.py
tests/
├─ api/
│  ├─ __init__.py
│  └─ test_health.py
└─ domain/
   ├─ __init__.py
   ├─ test_story.py
   └─ test_trips.py
```

### Task 1: Package Configuration and Settings

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/settings.py`
- Create: `tests/__init__.py`
- Create: `tests/test_settings.py`

**Interfaces:**
- Produces `Settings`, `get_settings()`, and the `ProviderMode` literal type for `app.main` and the health router.
- `Settings` fields are `app_name: str`, `environment: str`, `provider_mode: Literal["fixture", "map-real", "full-real"]`, and `frontend_origin: str`.
- `get_settings() -> Settings` is an `lru_cache`-backed function that reads the `LUMIVO_` environment prefix once per process.

- [ ] **Step 1: Write the failing settings tests**

```python
from app.settings import Settings


def test_settings_use_fixture_defaults(monkeypatch):
    for name in (
        "LUMIVO_APP_NAME",
        "LUMIVO_ENVIRONMENT",
        "LUMIVO_PROVIDER_MODE",
        "LUMIVO_FRONTEND_ORIGIN",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.app_name == "Lumivo Backend"
    assert settings.environment == "development"
    assert settings.provider_mode == "fixture"
    assert settings.frontend_origin == "http://localhost:8989"


def test_settings_accept_environment_overrides(monkeypatch):
    monkeypatch.setenv("LUMIVO_APP_NAME", "Test Backend")
    monkeypatch.setenv("LUMIVO_ENVIRONMENT", "test")
    monkeypatch.setenv("LUMIVO_PROVIDER_MODE", "map-real")
    monkeypatch.setenv("LUMIVO_FRONTEND_ORIGIN", "http://localhost:3100")

    settings = Settings()

    assert settings.app_name == "Test Backend"
    assert settings.environment == "test"
    assert settings.provider_mode == "map-real"
    assert settings.frontend_origin == "http://localhost:3100"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest tests/test_settings.py -q`

Expected: collection fails because `app.settings` does not exist yet.

- [ ] **Step 3: Add the package metadata and settings implementation**

Create `pyproject.toml` with Python 3.12 support, runtime dependencies `fastapi>=0.115,<1`, `pydantic>=2.8,<3`, `pydantic-settings>=2.4,<3`, and `uvicorn[standard]>=0.30,<1`; add test dependencies `httpx>=0.27,<1` and `pytest>=8,<9`; configure pytest with `testpaths = ["tests"]`.

Implement `ProviderMode = Literal["fixture", "map-real", "full-real"]`. Implement `Settings(BaseSettings)` with the four fields and defaults from the tests, `SettingsConfigDict(env_prefix="LUMIVO_", env_file=".env", extra="ignore")`, and `get_settings()` decorated with `@lru_cache(maxsize=1)`.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `python -m pytest tests/test_settings.py -q`

Expected: 2 passed without network access.

### Task 2: Canonical Domain Contracts and Structured Errors

**Files:**
- Create: `app/domain/__init__.py`
- Create: `app/domain/errors.py`
- Create: `app/domain/trips.py`
- Create: `app/domain/story.py`
- Create: `tests/domain/__init__.py`
- Create: `tests/domain/test_trips.py`
- Create: `tests/domain/test_story.py`

**Interfaces:**
- Produces FastAPI-independent Pydantic models for future planning and playback code.
- `GeoPoint`, `TripRequest`, `VerifiedPoi`, `RouteLeg`, `TripStop`, `TripDay`, and `TripPlan` are defined in `app.domain.trips`.
- `StoryCommand`, `StoryChapter`, and `StoryTimeline` are defined in `app.domain.story`.
- `AppError` and `ErrorCode` are defined in `app.domain.errors`.

- [ ] **Step 1: Write contract tests for valid data and invariant-level field validation**

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.trips import (
    CoordinateSystem,
    GeoPoint,
    RouteLeg,
    TravelMode,
    TripDay,
    TripPlan,
    TripRequest,
    TripStop,
    VerifiedPoi,
)


def verified_poi(uid: str = "poi-1") -> VerifiedPoi:
    return VerifiedPoi(
        uid=uid,
        name="中山陵",
        address="南京市玄武区石象路7号",
        point=GeoPoint(lng=118.8567, lat=32.0584),
        recommended_stay_minutes=90,
        source="fixture:nanjing",
        verified_at=datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc),
    )


def test_trip_request_defaults_are_stable():
    request = TripRequest(destination="南京", days=3, message="安排历史文化景点")

    assert request.interests == []
    assert request.transport == []
    assert request.start_date is None


def test_trip_plan_accepts_verified_poi_and_route_contract():
    first = verified_poi()
    second = verified_poi("poi-2")
    leg = RouteLeg(
        id="leg-1",
        from_poi_uid=first.uid,
        to_poi_uid=second.uid,
        mode=TravelMode.TRANSIT,
        distance_meters=1200,
        duration_seconds=900,
        geometry=[first.point, second.point],
    )
    plan = TripPlan(
        id="trip-1",
        version=1,
        destination="南京",
        summary="南京三日游",
        days=[TripDay(day_index=1, stops=[TripStop(poi=first), TripStop(poi=second)], route_legs=[leg])],
    )

    assert plan.days[0].route_legs[0].from_poi_uid == "poi-1"
    assert plan.days[0].stops[1].poi.point.crs is CoordinateSystem.BD09


def test_invalid_coordinate_and_route_geometry_are_rejected():
    with pytest.raises(ValidationError):
        GeoPoint(lng=181, lat=32)

    with pytest.raises(ValidationError):
        RouteLeg(
            id="leg-1",
            from_poi_uid="poi-1",
            to_poi_uid="poi-2",
            mode=TravelMode.WALK,
            distance_meters=100,
            duration_seconds=60,
            geometry=[GeoPoint(lng=118.8, lat=32.0)],
        )


def test_verified_at_requires_timezone_aware_datetime():
    with pytest.raises(ValidationError):
        VerifiedPoi(
            uid="poi-1",
            name="中山陵",
            address="南京市玄武区石象路7号",
            point=GeoPoint(lng=118.8567, lat=32.0584),
            recommended_stay_minutes=90,
            source="fixture:nanjing",
            verified_at=datetime(2026, 8, 18, 9, 0),
        )
```

- [ ] **Step 2: Run the domain tests to verify they fail**

Run: `python -m pytest tests/domain -q`

Expected: collection fails because the domain modules do not exist yet.

- [ ] **Step 3: Implement trips and error models**

Define `CoordinateSystem(StrEnum)` with `BD09 = "BD09"` and `TravelMode(StrEnum)` with `WALK`, `TRANSIT`, `DRIVE`, and `RIDE` values matching the design. Define `GeoPoint` with longitude and latitude bounds and a default `crs=CoordinateSystem.BD09`.

Define `TripRequest` with `destination: str`, `days: int = Field(ge=1, le=14)`, `message: str`, optional `departure`, optional `start_date: date`, list defaults for `interests` and `transport`, and optional `pace` and `budget`.

Define `VerifiedPoi`, `RouteLeg`, `TripStop`, `TripDay`, and `TripPlan` with the field names from the design. Enforce positive stay, distance, and duration values; at least two route geometry points; at least one stop per day; and at least one day per plan. Add a reusable timezone-aware datetime validator for `VerifiedPoi.verified_at` and optional stop arrival/departure values.

Define `ErrorCode(StrEnum)` with all ten MVP codes from the design and `AppError(BaseModel)` with `code: ErrorCode`, `message: str`, `retryable: bool`, and optional `details: dict[str, object]`.

- [ ] **Step 4: Implement story contracts and their tests**

Add this test before implementation:

```python
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
```

Implement `StoryCommandType` with the semantic types needed by the design: `INTRODUCTION`, `PROJECTION`, `CAMERA_FLIGHT`, `POI_DISPLAY`, `ROUTE_DRAW`, `ROUTE_FOLLOW`, `NARRATION`, and `CLOSING`. Implement non-negative start times, positive command/chapter/timeline durations, non-empty chapter and command lists, stable IDs, and a payload default of an empty dictionary.

- [ ] **Step 5: Run all focused domain tests to verify they pass**

Run: `python -m pytest tests/domain -q`

Expected: all domain tests pass without network access.

### Task 3: Application Factory, Health API, and CORS

**Files:**
- Create: `app/api/__init__.py`
- Create: `app/api/health.py`
- Create: `app/main.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/test_health.py`

**Interfaces:**
- Produces `create_app(settings: Settings | None = None) -> FastAPI` and module-level `app: FastAPI`.
- Exposes `GET /api/v1/health` with `HealthResponse(status, service, environment, provider_mode, map_mode, model_mode)`.
- `fixture` maps to `mock` map/model adapters, `map-real` maps to `baidu`/`mock`, and `full-real` maps to `baidu`/`real`.

- [ ] **Step 1: Write the failing API tests**

```python
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_health_reports_fixture_modes():
    client = TestClient(create_app(Settings()))

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Lumivo Backend",
        "environment": "development",
        "provider_mode": "fixture",
        "map_mode": "mock",
        "model_mode": "mock",
    }


def test_health_reflects_full_real_configuration():
    settings = Settings(provider_mode="full-real", frontend_origin="http://localhost:8989")
    response = TestClient(create_app(settings)).get("/api/v1/health")

    assert response.json()["map_mode"] == "baidu"
    assert response.json()["model_mode"] == "real"


def test_cors_allows_the_configured_frontend_origin():
    settings = Settings(frontend_origin="http://localhost:3100")
    response = TestClient(create_app(settings)).get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3100"},
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:3100"
```

- [ ] **Step 2: Run the API tests to verify they fail**

Run: `python -m pytest tests/api/test_health.py -q`

Expected: collection fails because `app.main` does not exist yet.

- [ ] **Step 3: Implement the health router and application factory**

Create `HealthResponse` as a Pydantic model with the six response fields. Add a router with `@router.get("/health", response_model=HealthResponse)` that receives a `Settings` object through router closure or a small dependency and returns the adapter mode mapping without exposing credentials.

Implement `create_app(settings=None)` by selecting `settings or get_settings()`, creating a FastAPI instance with the configured title, adding `CORSMiddleware` with exactly `[settings.frontend_origin]`, and including the health router under `/api/v1`. Instantiate `app = create_app()` for Uvicorn and local imports.

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `python -m pytest tests/api/test_health.py -q`

Expected: all health and CORS tests pass.

### Task 4: Local Configuration, Documentation, and Complete Verification

**Files:**
- Create: `.env.example`
- Create: `.gitignore`
- Modify: `README.md`
- Modify: `CONTEXT.md`
- Modify: `docs/superpowers/specs/2026-08-18-lumivo-backend-design.md`

**Interfaces:**
- Produces a newcomer-readable local start path: install dependencies, run `uvicorn app.main:app --reload`, and call `/api/v1/health`.
- Documents that only Phase 1 is implemented and that planning endpoints/providers are still future phases.

- [ ] **Step 1: Add safe local environment and ignore rules**

Create `.env.example` with:

```dotenv
LUMIVO_APP_NAME=Lumivo Backend
LUMIVO_ENVIRONMENT=development
LUMIVO_PROVIDER_MODE=fixture
LUMIVO_FRONTEND_ORIGIN=http://localhost:8989
```

Create `.gitignore` covering `.env`, `.venv/`, `venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `*.py[cod]`, and local build directories.

- [ ] **Step 2: Update README and context with the actual Phase 1 state**

Update README to include PowerShell commands:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m uvicorn app.main:app --reload --port 8000
```

Document `GET http://localhost:8000/api/v1/health`, the fixture-mode response, and `python -m pytest`. State explicitly that `/trips/plan` and `/trips/revise` are not implemented yet.

Update `CONTEXT.md` so “Current implementation” says the Phase 1 scaffold, settings, health endpoint, domain contracts, and deterministic tests exist; update “Immediate build sequence” to make the next step the Nanjing fixture and Mock Adapter flow. Update the design status from awaiting written review to the approved Phase 1 implementation state without changing the later-phase acceptance criteria.

- [ ] **Step 3: Run the complete local suite**

Run: `python -m pytest`

Expected: every test passes, with no network access or provider credentials required.

- [ ] **Step 4: Run the local health smoke check**

Start the server with `python -m uvicorn app.main:app --port 8000`, then run:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health
```

Expected: HTTP 200 and a JSON object reporting `status = "ok"`, `provider_mode = "fixture"`, `map_mode = "mock"`, and `model_mode = "mock"`. Stop the local server after the check.

- [ ] **Step 5: Record repository limitation**

Run: `git status --short --branch`

Expected: the command reports that the current directory is not a Git repository; report that no commit was created rather than initializing Git without permission.

## Self-Review Checklist

- The plan covers the Phase 1 scope in the design: package/configuration, health route, canonical contracts, structured errors, deterministic tests, and newcomer documentation.
- It does not implement Baidu, AI, planning orchestration, NDJSON trip routes, revision, persistence, or deployment.
- All later consumers use exact names: `Settings`, `get_settings`, `create_app`, `TripPlan`, `StoryTimeline`, and `AppError`.
- Tests are specified before implementations and all default verification is local and deterministic.
- No Git commit is specified because the current workspace is not a Git repository.
