# Canonical Planning Integration Design

Date: 2026-09-17

Status: Approved design; implementation pending

## Problem

The Python backend already owns verified map-backed planning, but the frontend still calls the legacy JSON compatibility route and its local Node backend remains fixture-only. The next slice should make one usable vertical path: streamed planning, stateless day-level revision, and a minimal revision control in `/trip`.

## Goals

- Make `POST /api/v1/trips/plan` the canonical streamed planning API.
- Move the frontend's planning call and default startup path to the Python backend.
- Add `POST /api/v1/trips/revise` for a stateless partial revision of one day.
- Allow newly discovered provider POIs during real-mode revision while keeping AI output UID-only.
- Preserve the existing compatibility routes and local storage contract.

## Non-goals

Authentication, persistence, sharing, Redis/queues, background jobs, real-time navigation, and live-provider reliability guarantees remain out of scope. Fixture mode remains closed-world and may only select fixture POIs.

## Contracts

### Streamed planning

`POST /api/v1/trips/plan` accepts the existing `TripPlanRequest` JSON shape and returns `application/x-ndjson`. Every line is a JSON envelope:

```json
{"event":"planning.started","requestId":"...","sequence":0,"data":{}}
```

The sequence is monotonic per request and starts at zero. The normal event order is:

```text
planning.started
destination.validated
pois.found
routes.calculated
plan.validated
timeline.ready
planning.completed
```

The completed event is the only event carrying a playable result:

```json
{"event":"planning.completed","requestId":"...","sequence":6,"data":{"plan":{},"timeline":{}}}
```

Malformed input is rejected before streaming with the existing structured HTTP error body. Once streaming has started, provider, model, validation, and cancellation failures produce one terminal `planning.error` envelope and never a completed event:

```json
{"event":"planning.error","requestId":"...","sequence":3,"error":{"code":"MAP_PROVIDER_ERROR","message":"地图服务暂时不可用","retryable":true,"details":{}}}
```

The route owns request IDs and sequence numbers. The planner emits optional progress callbacks; compatibility callers omit the callback and keep receiving the existing `{plan, timeline}` JSON response.

### Stateless revision

`POST /api/v1/trips/revise` accepts the complete current plan, a one-based target day, and an instruction:

```json
{
  "plan": {},
  "day": 2,
  "instruction": "把博物馆换成更适合慢游的景点，并增加一个新景点"
}
```

The response uses the same NDJSON envelope and completed payload as planning. Revision rules:

1. Only the requested day may change; other days are copied unchanged.
2. Real mode refreshes the verified candidate POI pool before model selection.
3. Candidates already used by untouched days are excluded.
4. The model returns an ordered list of candidate UIDs only. Unknown UIDs, duplicate UIDs, empty days, and cross-day collisions fail validation.
5. New POIs are valid only when returned by the map provider in the refreshed candidate pool; the model cannot invent POI facts.
6. Only the target day's route legs and narration are recalculated.
7. `tripId` is preserved, `version` increments by one, and a new Timeline is compiled from the resulting plan.

Revision errors use the existing `AppError` codes and the same terminal error envelope. A request that cannot be satisfied returns a structured `PLAN_NOT_AVAILABLE` or validation error rather than silently keeping the requested change.

## Backend design

- Add the canonical router beside `app/api/compat.py`; keep HTTP translation out of planning logic.
- Add the smallest optional async progress callback to the planner seam. The handler emits `planning.started`, forwards planner events, emits the completed event, and propagates task cancellation when the client disconnects.
- Add a narrow model-provider operation for day revision that accepts verified candidate POIs and returns candidate UIDs. Its parser enforces the target day, candidate membership, non-empty selection, and uniqueness.
- Implement revision in `RealTripPlanner` by reusing the existing map search, route, validator, and story compiler seams. It constructs a new plan from copied untouched days and a rebuilt target day.
- Keep `FixtureTripPlanner` deterministic. Its revision candidates come only from fixture data; it does not call live providers.
- Keep provider payloads, AI prompts, and raw user instructions inside their existing adapters/services. Do not add a repository, cache, queue, or persistence layer.

## Frontend design

- Add `lib/trip/client.ts` with `planTrip` and `reviseTrip` methods. It owns fetch, NDJSON line buffering across arbitrary chunks, terminal error parsing, and `AbortController` cancellation.
- Migrate `components/ai-chat.tsx` from direct fetch calls to `TripClient`; keep the current `PlanningResult` storage and `/trip` navigation.
- Change the default `backend:dev` and `backend:start` path to the sibling Python FastAPI service. Keep the old TypeScript fixture backend available only as an explicit legacy path during migration.
- Add a minimal `/trip` revision control: target-day select, instruction input, submit state, error text, and save-and-render of the returned `PlanningResult`. Reuse the existing story/map components; no new editor framework.
- Surface streamed progress as the existing planning loading state. Do not persist in-progress events.

## Validation and tests

Backend tests must cover:

- exact NDJSON event order and final `{plan, timeline}` payload;
- terminal provider/model errors with no completed event;
- cancellation propagation on client disconnect;
- revision preserving untouched days, incrementing version, and preserving `tripId`;
- acceptance of a provider-returned new POI and rejection of an unknown UID;
- route endpoint/geometry and Timeline consistency;
- unchanged compatibility route behavior.

Frontend tests must cover:

- NDJSON parsing when records split across fetch chunks;
- completed and error envelopes;
- abort behavior;
- saving and reloading a revised result with its new version.

Verification remains separate by boundary:

```text
Backend: .venv\Scripts\python.exe -m pytest -q
Frontend: npm run lint; npx tsc --noEmit; npm run build
Live Baidu/AI: explicit smoke test only, not implied by local tests
```

## Acceptance criteria

1. A real-mode request from `/ai` reaches Python `/api/v1/trips/plan`, displays progress, and opens the playable result in `/trip`.
2. A user can revise one day in `/trip`, including adding a newly returned real POI, without changing other days.
3. The revised result has the same `tripId`, the next version, valid route facts, and a matching Timeline.
4. A provider/model failure is visible as a structured error and never becomes a fake successful itinerary.
5. Existing `/api/chat` and `/api/trips/plan` callers continue to work.
