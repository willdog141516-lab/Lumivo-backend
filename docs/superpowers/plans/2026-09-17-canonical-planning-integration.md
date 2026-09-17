# Canonical Planning Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Connect /ai to the Python planner, stream verified planning progress, and support stateless one-day revisions with provider-returned POIs.

**Architecture:** Keep the existing compatibility JSON/SSE routes. Add a FastAPI canonical router around the existing planner seam, extend the real planner with validated day revision, and expose both operations through a browser TripClient. The /trip page saves complete results and provides a native revision form.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, Next.js 16.3.1, React 19, TypeScript, native fetch, ReadableStream, and node:test. No new dependency.

**Spec:** docs/superpowers/specs/2026-09-17-canonical-planning-integration-design.md

## Global Constraints

- TripPlan is canonical; StoryTimeline is derived from its exact tripId and version.
- Every map coordinate remains BD-09.
- AI selects provider-verified UIDs and writes grounded narration; it never invents map facts.
- New real-mode POIs must be returned by the current map-provider candidate search.
- Revisions are stateless and receive the complete current TripPlan.
- Keep /api/chat, /api/trips/plan, /health, and /api/v1/health compatible.
- Do not add authentication, persistence, Redis, queues, jobs, deployment configuration, or dependencies.
- Keep Chinese UI copy and existing map/story controls.
- Read node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md before changing Next.js code.
- Preserve unrelated dirty changes in both repositories.

## File Map

| Repository | Files | Responsibility |
| --- | --- | --- |
| lumivo-backend | app/domain/chat.py | TripRevisionRequest validation. |
| lumivo-backend | app/model_provider.py | UID-only revision model contract, parser, and grounded narration. |
| lumivo-backend | app/planning_service.py | Progress callback and revision-capable planner protocol. |
| lumivo-backend | app/real_planning_service.py | Real provider revision and progress points. |
| lumivo-backend | app/planning_validator.py | Pure revision invariants. |
| lumivo-backend | app/api/canonical.py, app/main.py | NDJSON endpoints and app wiring. |
| lumivo-backend | tests/domain/test_chat.py, tests/providers/test_model_provider.py | Contract tests. |
| lumivo-backend | tests/planning/test_real.py, tests/planning/test_fixture.py | Planner tests. |
| lumivo-backend | tests/api/test_canonical.py | Stream, error, and cancellation tests. |
| lumivo-ai | lib/trip/client.ts | Browser NDJSON client. |
| lumivo-ai | lib/trip/client.test.mjs | Client stream/error/abort tests. |
| lumivo-ai | components/ai-chat.tsx, package.json | Planning migration and Python startup. |
| lumivo-ai | components/trip-revision-panel.tsx, components/trip-story-home.tsx | Usable revision control and live result state. |
| lumivo-ai | components/story-player-panel.tsx | Dynamic day-count label. |
| lumivo-ai | component tests, local-trip-store.test.mjs | UI and revised-result regressions. |
| both repositories | CONTEXT.md, README.md, architecture spec | Current-state documentation after implementation. |

---

### Task 1: Add the revision request and model-provider contracts

**Files:**
- Modify: app/domain/chat.py
- Modify: app/model_provider.py
- Create: tests/domain/test_chat.py
- Modify: tests/providers/test_model_provider.py

**Interfaces:**
- TripRevisionRequest(plan: TripPlan, day: int, instruction: str).
- RevisionRequest(destination: str, day_index: int, instruction: str, current_poi_uids: tuple[str, ...], candidates: tuple[ScheduleCandidate, ...]).
- ProposedRevision(day_index: int, poi_uids: tuple[str, ...]).
- ModelProvider.revise_day(request: RevisionRequest) -> ProposedRevision.

- [ ] **Step 1: Write failing tests**

Create tests/domain/test_chat.py:

~~~python
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
~~~

Add provider tests for valid JSON {"day": 2, "poiUids": ["p1", "p2"]}, an unknown UID, a duplicate UID, and narration without a three-character POI-name anchor. Use the existing FakeChatClient, verified_poi, OpenAIModelAdapter, ModelProviderError, and asyncio helpers in tests/providers/test_model_provider.py.

- [ ] **Step 2: Run the focused tests and verify failure**

Run from E:\code\Lumivo-AI\lumivo-backend:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q tests/domain/test_chat.py tests/providers/test_model_provider.py
~~~

Expected: FAIL because the revision classes, method, and parser do not exist.

- [ ] **Step 3: Implement the minimum contracts**

Add TripRevisionRequest with a stripped nonblank instruction of at most 4000 characters and a model validator requiring 1 <= day <= len(plan.days). Add the two frozen revision dataclasses and the protocol method in app/model_provider.py.

Implement parse_revision with exact keys {"day", "poiUids"}, matching day, non-empty UID list, no duplicates, and candidate membership. Implement OpenAIModelAdapter.revise_day with a strict UID-only prompt containing destination, target day, instruction, current target UIDs, and candidate facts.

Extend parse_narration and its prompt to require the full POI name or a three-character consecutive name anchor after removing whitespace and ·—–-. Keep provider facts in the adapter boundary.

- [ ] **Step 4: Run the focused tests and verify success**

Run the same pytest command from Step 2. Expected: all focused tests PASS.

- [ ] **Step 5: Commit only this contract slice**

~~~powershell
git add -- app/domain/chat.py app/model_provider.py tests/domain/test_chat.py tests/providers/test_model_provider.py
git diff --cached --check
git commit -m "feat: add validated trip revision selection"
~~~

### Task 2: Add planner progress and real day revision

**Files:**
- Modify: app/planning_service.py
- Modify: app/real_planning_service.py
- Modify: app/planning_validator.py
- Modify: tests/planning/test_real.py
- Modify: tests/planning/test_fixture.py

**Interfaces:**
- ProgressCallback = Callable[[str, dict[str, object]], Awaitable[None]].
- plan(request, *, progress: ProgressCallback | None = None) -> PlanningResult.
- revise(request: TripRevisionRequest, *, progress: ProgressCallback | None = None) -> PlanningResult.
- validate_revision(original, revised, target_day, target_candidate_uids) -> TripPlan.

- [ ] **Step 1: Write failing tests**

Capture progress from RealTripPlanner.plan and assert this order:

~~~python
[
    "destination.validated",
    "pois.found",
    "routes.calculated",
    "plan.validated",
    "timeline.ready",
]
~~~

Extend the existing fake map provider with provider POI p3 and endpoint-specific route IDs. Add a fake model revise_day returning ProposedRevision(1, ("p1", "p3")). Plan one day with p1/p2, revise day 1, and assert the same trip ID, version plus one, p3 in the result, and matching timeline identity. Add an unknown-UID case that makes no target route call. Add a fixture revision test expecting structured PLAN_NOT_AVAILABLE instead of fabricated data.

- [ ] **Step 2: Run the focused planner tests and verify failure**

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q tests/planning/test_real.py tests/planning/test_fixture.py
~~~

Expected: FAIL because progress, revise_day, revise, and revision validation are absent.

- [ ] **Step 3: Implement progress and revision**

In app/planning_service.py, add:

~~~python
ProgressCallback = Callable[[str, dict[str, object]], Awaitable[None]]


async def emit_progress(
    progress: ProgressCallback | None,
    event: str,
    data: dict[str, object] | None = None,
) -> None:
    if progress is not None:
        await progress(event, data or {})
~~~

Emit progress after destination resolution, POI search, route creation, plan validation, and timeline compilation. In RealTripPlanner.revise, validate the submitted plan, refresh map candidates, exclude UIDs from untouched days, merge current target-day POIs only when absent from fresh results, call revise_day, rebuild only the target day, copy other days, increment version, validate, and compile a new timeline. Map ModelProviderError, MapProviderError, and PlanValidationError to TripPlannerError; let asyncio.CancelledError propagate.

Implement validate_revision so it checks same ID, version plus one, destination/day count/order, exact equality for untouched days, target UIDs in the allowed provider set, no cross-day duplicate UIDs, and validate_plan(revised). FixtureTripPlanner.revise fails closed with PLAN_NOT_AVAILABLE.

- [ ] **Step 4: Run planner tests and verify success**

Run the Step 2 command. Expected: all planner tests PASS.

- [ ] **Step 5: Commit only the planner slice**

~~~powershell
git add -- app/planning_service.py app/real_planning_service.py app/planning_validator.py tests/planning/test_real.py tests/planning/test_fixture.py
git diff --cached --check
git commit -m "feat: support progress and stateless day revisions"
~~~

### Task 3: Add canonical FastAPI NDJSON routes

**Files:**
- Create: app/api/canonical.py
- Modify: app/main.py
- Create: tests/api/test_canonical.py

**Interfaces:**
- create_canonical_router(planner: TripPlanner) -> APIRouter.
- POST /api/v1/trips/plan and POST /api/v1/trips/revise.
- Envelope fields: event, requestId, sequence, and data or error.

- [ ] **Step 1: Write failing API tests**

Use a fake planner with plan and revise methods accepting the optional progress callback. Assert a successful plan response has content type application/x-ndjson and events:

~~~python
[
    "planning.started",
    "destination.validated",
    "timeline.ready",
    "planning.completed",
]
~~~

Assert the completed data has plan and timeline. Add a provider-error fake that yields one progress event then raises TripPlannerError("MAP_PROVIDER_ERROR", "provider secret"); assert the last event is planning.error, the safe message excludes provider secret, and no completed event exists. Add invalid-input, revision-request, and disconnect-cancellation tests.

- [ ] **Step 2: Run the API test and verify failure**

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q tests/api/test_canonical.py
~~~

Expected: FAIL because the router and endpoints do not exist.

- [ ] **Step 3: Implement the stream**

Parse TripPlanRequest and TripRevisionRequest before creating StreamingResponse. Generate uuid4().hex request IDs. Emit each record as json.dumps(payload, ensure_ascii=False) plus a newline, with sequence owned by the route and starting at zero.

Run the planner in an asyncio task and use an asyncio.Queue for progress callbacks. Poll request.is_disconnected() between queue reads and cancel the task on disconnect:

~~~python
# ponytail: poll between progress events; use an ASGI disconnect hook if jobs enter scope.
if await request.is_disconnected():
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return
~~~

Emit planning.started, forward planner events, serialize completion with model_dump(mode="json", by_alias=True, exclude_none=True), and emit planning.completed with data containing the serialized plan and timeline. Convert planner failures to safe existing error codes with retryable and details fields; emit one terminal planning.error. Never include exception text or a completed event after failure. Set media type application/x-ndjson, Cache-Control no-cache, and X-Accel-Buffering no.

Wire create_canonical_router(resolved_planner) in app/main.py and widen the injectable planner type to TripPlanner | None. Do not change compat route behavior.

- [ ] **Step 4: Run canonical and compatibility tests**

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q tests/api/test_canonical.py tests/api/test_compat.py tests/api/test_health.py
~~~

Expected: all selected tests PASS.

- [ ] **Step 5: Commit only the API slice**

~~~powershell
git add -- app/api/canonical.py app/main.py tests/api/test_canonical.py
git diff --cached --check
git commit -m "feat: expose canonical planning streams"
~~~

### Task 4: Build the frontend TripClient

**Files:**
- Create: E:\code\Lumivo-AI\lumivo-ai\lib/trip/client.ts
- Create: E:\code\Lumivo-AI\lumivo-ai\lib/trip/client.test.mjs

**Interfaces:**
- TripClient.planTrip(input: PlanInput, options?: StreamOptions): Promise<PlanningResult>.
- TripClient.reviseTrip(input: RevisionInput, options?: StreamOptions): Promise<PlanningResult>.
- StreamOptions has signal?: AbortSignal and onProgress?: (event: PlanningEvent) => void.
- TripClientError has code, retryable, and optional details.

- [ ] **Step 1: Write failing client tests**

Use an injected fetcher returning a Response whose ReadableStream splits one NDJSON record across two chunks. Assert planTrip returns the fixture result and calls onProgress. Add a planning.error test that rejects with TripClientError("MAP_PROVIDER_ERROR"). Add an AbortController test asserting the exact signal is passed to fetch.

- [ ] **Step 2: Run the client test and verify failure**

~~~powershell
cd E:\code\Lumivo-AI\lumivo-ai
node --import=tsx --test lib/trip/client.test.mjs
~~~

Expected: FAIL because lib/trip/client.ts does not exist.

- [ ] **Step 3: Implement the parser**

Define PlanInput, RevisionInput, PlanningEvent, and StreamOptions. TripClient trims baseUrl, sends JSON with Accept application/x-ndjson, buffers arbitrary UTF-8 chunks until newline, rejects malformed records, checks one request ID and increasing sequence, invokes onProgress for non-completion events, parses terminal errors, and returns only complete data with plan and timeline. It never imports localStorage.

- [ ] **Step 4: Run the client test and verify success**

~~~powershell
node --import=tsx --test lib/trip/client.test.mjs
~~~

Expected: all client tests PASS.

- [ ] **Step 5: Commit only the client slice**

~~~powershell
git -C E:\code\Lumivo-AI\lumivo-ai add -- lib/trip/client.ts lib/trip/client.test.mjs
git -C E:\code\Lumivo-AI\lumivo-ai diff --cached --check
git -C E:\code\Lumivo-AI\lumivo-ai commit -m "feat: add streamed trip client"
~~~

### Task 5: Migrate /ai and default startup

**Files:**
- Modify: E:\code\Lumivo-AI\lumivo-ai\components/ai-chat.tsx
- Modify: E:\code\Lumivo-AI\lumivo-ai\package.json
- Create: E:\code\Lumivo-AI\lumivo-ai\components/ai-chat.test.mjs

**Interfaces:**
- Chat keeps the existing /api/chat SSE flow.
- Playable planning calls TripClient.planTrip and saveActiveTrip.
- backend:dev and backend:start launch Python; backend:legacy:dev and backend:legacy:start retain the old Node server explicitly.

- [ ] **Step 1: Read Next.js guidance and write the migration test**

~~~powershell
cd E:\code\Lumivo-AI\lumivo-ai
Get-Content -Raw node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md
~~~

Create components/ai-chat.test.mjs. Read ai-chat.tsx and assert it contains TripClient, planTrip, planningStatus, and onProgress, and does not contain the direct legacy planning URL.

- [ ] **Step 2: Run the migration test and verify failure**

~~~powershell
node --import=tsx --test components/ai-chat.test.mjs
~~~

Expected: FAIL because AiChat directly fetches /api/trips/plan and has no progress state.

- [ ] **Step 3: Migrate the handler and scripts**

Replace only createPlayablePlan’s direct fetch with TripClient.planTrip and an onProgress callback. Save the complete result and navigate to /trip. Map TripClientError codes to current Chinese messages, reset status in finally, and abort the active plan request on unmount. Keep chat SSE code unchanged.

Set package.json scripts to:

~~~json
"backend:dev": "cd ../lumivo-backend && python -m uvicorn app.main:app --reload --port 8000",
"backend:start": "cd ../lumivo-backend && python -m uvicorn app.main:app --port 8000",
"backend:legacy:dev": "node --watch --env-file=backend/.env --import=tsx backend/start.ts",
"backend:legacy:start": "node --env-file=backend/.env --import=tsx backend/start.ts"
~~~

- [ ] **Step 4: Run focused frontend checks**

~~~powershell
node --import=tsx --test components/ai-chat.test.mjs lib/trip/client.test.mjs
npx tsc --noEmit --incremental false
~~~

Expected: tests and typecheck PASS.

- [ ] **Step 5: Commit only the migration slice**

~~~powershell
git -C E:\code\Lumivo-AI\lumivo-ai add -- components/ai-chat.tsx package.json components/ai-chat.test.mjs
git -C E:\code\Lumivo-AI\lumivo-ai diff --cached --check
git -C E:\code\Lumivo-AI\lumivo-ai commit -m "feat: route playable planning through FastAPI"
~~~

### Task 6: Add /trip revision UI and dynamic day labels

**Files:**
- Create: E:\code\Lumivo-AI\lumivo-ai\components/trip-revision-panel.tsx
- Create: E:\code\Lumivo-AI\lumivo-ai\components/trip-revision-panel.test.mjs
- Modify: E:\code\Lumivo-AI\lumivo-ai\components/trip-story-home.tsx
- Modify: E:\code\Lumivo-AI\lumivo-ai\components/story-player-panel.tsx
- Modify: E:\code\Lumivo-AI\lumivo-ai\components/story-player-panel.test.mjs
- Modify: E:\code\Lumivo-AI\lumivo-ai\lib/trip/local-trip-store.test.mjs

**Interfaces:**
- TripRevisionPanelProps = { result: PlanningResult; onRevised: (result: PlanningResult) => void }.
- The panel calls TripClient.reviseTrip, saveActiveTrip, then onRevised.
- TripStoryHome renders the updated plan/timeline without navigation.

- [ ] **Step 1: Write failing UI and persistence tests**

Create a source regression asserting the new component contains a native details element, trip-revision-day, trip-revision-instruction, reviseTrip, and saveActiveTrip. Assert story-player-panel uses plan.days.length and no longer contains 三日路线故事. Add a store round-trip using fixture version 2 for both plan and timeline.

- [ ] **Step 2: Run focused tests and verify failure**

~~~powershell
cd E:\code\Lumivo-AI\lumivo-ai
node --import=tsx --test components/trip-revision-panel.test.mjs components/story-player-panel.test.mjs lib/trip/local-trip-store.test.mjs
~~~

Expected: FAIL because the panel is absent and the playback title is fixed.

- [ ] **Step 3: Implement the smallest usable control**

Create a use client component with a native details disclosure, a select containing result.plan.days, a textarea for Chinese instructions, a submit button, disabled/loading/error states, and aria-live progress. On success persist the result and notify the parent; on failure keep the old result.

Change trip-story-home.tsx to retain useSyncExternalStore fallback plus local current-result state, wrap the existing full-height experience, and render the panel beside it. Change story-player-panel.tsx to:

~~~tsx
{plan.destination} · {plan.days.length}日路线故事
~~~

- [ ] **Step 4: Run focused UI tests and typecheck**

~~~powershell
node --import=tsx --test components/trip-revision-panel.test.mjs components/story-player-panel.test.mjs lib/trip/local-trip-store.test.mjs app/trip/page.test.mjs
npx tsc --noEmit --incremental false
~~~

Expected: all selected tests and typecheck PASS.

- [ ] **Step 5: Commit only the /trip slice**

~~~powershell
git -C E:\code\Lumivo-AI\lumivo-ai add -- components/trip-revision-panel.tsx components/trip-revision-panel.test.mjs components/trip-story-home.tsx components/story-player-panel.tsx components/story-player-panel.test.mjs lib/trip/local-trip-store.test.mjs
git -C E:\code\Lumivo-AI\lumivo-ai diff --cached --check
git -C E:\code\Lumivo-AI\lumivo-ai commit -m "feat: add trip day revision control"
~~~

### Task 7: Update documentation and verify the full slice

**Files:**
- Modify: E:\code\Lumivo-AI\lumivo-backend\CONTEXT.md
- Modify: E:\code\Lumivo-AI\lumivo-backend\README.md
- Modify: E:\code\Lumivo-AI\lumivo-backend\docs/superpowers/specs/2026-08-18-lumivo-backend-design.md
- Modify: E:\code\Lumivo-AI\lumivo-ai\CONTEXT.md

**Interfaces:**
- Docs state Python FastAPI is the default backend.
- Docs list canonical planning/revision routes as implemented locally.
- Docs distinguish fake-provider tests from live Baidu/AI smoke evidence.

- [ ] **Step 1: Update current-state documentation**

Replace stale TypeScript-default and fixture-only claims with:

~~~text
Python FastAPI is the default backend. POST /api/v1/trips/plan streams
application/x-ndjson and POST /api/v1/trips/revise performs a stateless
one-day revision. Legacy JSON/SSE routes remain for compatibility. Local
tests use fake provider seams; live Baidu and live AI require separate smoke
verification.
~~~

Add the backend virtual-environment activation and uvicorn command. Link the existing architecture spec to the approved 2026-09-17 design without deleting historical compatibility details.

- [ ] **Step 2: Run complete verification**

Backend:

~~~powershell
cd E:\code\Lumivo-AI\lumivo-backend
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
~~~

Frontend:

~~~powershell
cd E:\code\Lumivo-AI\lumivo-ai
npm run lint
npx tsc --noEmit --incremental false
npm run build
npm run backend:test
npm run backend:typecheck
~~~

Expected: tests, lint, typecheck, and build pass. Report .next or .pytest_cache permission warnings separately; a blocked build is not a pass. Do not claim live-provider behavior from local tests.

- [ ] **Step 3: Review and commit only documentation**

Run status and diff checks in both repositories. Stage only the four listed documentation files, then commit backend and frontend documentation separately with:

~~~powershell
git -C E:\code\Lumivo-AI\lumivo-backend commit -m "docs: record canonical planning integration"
git -C E:\code\Lumivo-AI\lumivo-ai commit -m "docs: record Python planning backend"
~~~

The final status must retain only unrelated pre-existing worktree changes.

## Spec Coverage Self-Review

- NDJSON contract, terminal errors, and cancellation: Task 3.
- Real-mode revision, new provider POIs, untouched-day preservation, and version identity: Tasks 1 and 2.
- Frontend parser and abort handling: Task 4.
- /ai migration and Python startup: Task 5.
- Usable /trip revision form and dynamic day labels: Task 6.
- Compatibility, docs, and verification boundaries: Tasks 3 and 7.
- Authentication, persistence, queues, sharing, and real-time navigation remain excluded.
