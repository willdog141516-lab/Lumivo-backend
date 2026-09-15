# Lumivo Backend Agent Rules

## Read first

Before changing this project, read `CONTEXT.md` and `docs/superpowers/specs/2026-08-18-lumivo-backend-design.md`. Inspect the worktree and preserve unrelated or user-authored changes.

## Product scope

This project is the Python FastAPI backend for Lumivo AI. The MVP supports China-only itinerary planning, verified map facts, and StoryTimeline generation for route playback. It does not include authentication, a database, Redis, queues, cloud persistence, production deployment, or real-time navigation.

## Domain invariants

- `TripPlan` is the canonical validated itinerary.
- `StoryTimeline` is derived from one exact `tripId` and `version`.
- Every coordinate crossing the map seam uses BD-09.
- AI never invents POI identity, coordinates, route geometry, distance, or duration.
- Full-real plans use Baidu-verified POIs and routes. Fixture mode uses stable fixture IDs and geometry.
- A plan with unknown POIs, missing route legs, mismatched endpoints, or invalid coordinates is not playable.
- Revisions are stateless in the MVP: the caller sends the current full plan and receives a new version.
- Provider failures return structured errors; never fabricate a successful plan.

## Architecture rules

- Design deep modules with small interfaces and test them through those interfaces.
- Keep map-provider and model-provider details behind Protocol seams with mock and real Adapters.
- Keep Pydantic domain models independent of FastAPI request objects and provider response objects.
- Keep PlanValidator and StoryCompiler pure and deterministic.
- Route handlers translate HTTP to application calls; they do not contain planning logic.
- Provider-specific payloads do not escape their Adapter.
- Do not add a repository, ORM, authentication abstraction, queue, or deployment configuration before that capability enters scope.

## Python rules

- Target Python 3.12 and declare dependencies in `pyproject.toml`.
- Use type hints for public functions and Protocol interfaces.
- Use `async` only for network and streaming work; keep pure domain logic synchronous.
- Use explicit units in names such as `distance_meters`, `duration_seconds`, and `start_ms`.
- Use timezone-aware ISO 8601 values when dates or times are present.
- Keep secrets in an ignored `.env`; commit only `.env.example` with safe mock defaults.
- Log request IDs, event types, durations, and provider status without logging credentials or complete free-form user messages.

## Required verification

Run focused tests while changing a module, then run the complete local suite:

```powershell
python -m pytest
```

When formatting, linting, or type-checking tools are added to `pyproject.toml`, run their declared project commands before claiming completion. Unit tests do not prove live Baidu or live AI behavior; report those smoke tests separately.

## Documentation discipline

- Update `CONTEXT.md` when scope, provider mode, current implementation, or immediate priority changes.
- Update the backend design when an interface, invariant, endpoint, or acceptance criterion changes.
- Keep `README.md` newcomer-oriented and accurate about what is actually implemented.
