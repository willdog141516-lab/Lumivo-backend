# Python Backend Compatibility Implementation Plan

**Goal:** Replace the current TypeScript backend behavior with a Python FastAPI service in this project while keeping the existing frontend HTTP contract.

**Architecture:** FastAPI owns transport and dependency assembly. A small OpenAI-compatible client handles `/api/chat`; a fixture planner validates AI-selected UIDs against deterministic Nanjing facts and returns the existing `TripPlan`/`StoryTimeline` JSON shape. Domain models serialize with the frontend's camelCase contract.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, pydantic-settings, httpx, pytest.

**Scope:** `/health`, `/api/chat`, `/api/trips/plan`, CORS, request limits, structured errors, Nanjing fixture planning, and documentation. Baidu adapters, nationwide planning, revision, persistence, and deployment remain out of scope.

### Task 1: Write compatibility and fixture tests

**Files:**
- Create: `tests/api/test_compat.py`
- Create: `tests/planning/test_fixture.py`
- Create: `tests/providers/test_ai.py`

- [x] Add tests for legacy health, chat validation/injection, fixture planning, unsupported destinations, invalid model selections, camelCase output, and provider response parsing.
- [x] Run the focused tests and confirm collection failed because the new modules/routes did not exist.

### Task 2: Implement domain serialization, fixture, validation, and compiler

**Files:**
- Modify: `app/domain/trips.py`
- Modify: `app/domain/story.py`
- Modify: `app/domain/errors.py`
- Create: `app/fixtures_nanjing.py`
- Create: `app/planning_validator.py`
- Create: `app/story_compiler.py`

- [x] Match the frontend's `day`, `durationMs`, `tripId`, `tripVersion`, `routeLegs`, and related aliases.
- [x] Port the deterministic Nanjing POIs/routes/plan and compile the same playable command sequence.
- [x] Reject unknown POIs, wrong coordinate systems, missing route legs, and endpoint mismatches.

### Task 3: Implement AI client and HTTP compatibility routes

**Files:**
- Modify: `app/settings.py`
- Modify: `app/main.py`
- Create: `app/ai_client.py`
- Create: `app/planning/service.py`
- Create: `app/api/compat.py`
- Modify: `pyproject.toml`

- [x] Port OpenAI-compatible chat requests, timeout/error mapping, CORS, 64 KiB request protection, and legacy response envelopes.
- [x] Port the strict Nanjing fixture selection prompt and fail-closed planning endpoint.
- [x] Keep `/api/v1/health` available for the existing Python contract while adding legacy `/health`.

### Task 4: Verify and document

**Files:**
- Modify: `README.md`
- Modify: `CONTEXT.md`
- Modify: `.env.example`

- [x] Run focused tests and the complete Python suite with the installed interpreter.
- [x] Run a local HTTP smoke test for health, chat validation, and unsupported destinations; the deterministic Nanjing success path is covered by the injected-provider API test.
- [x] Record environment limitations separately from code results.
