# Real-Data Story Planning Design

Date: 2026-09-14

Status: Implemented locally; live provider smoke pending

## Goal

Make the existing story-map planning flow use real Baidu POI, coordinate, and
route facts when `LUMIVO_PROVIDER_MODE=full-real`, while preserving the
frontend-compatible `POST /api/trips/plan` response containing `plan` and
`timeline`.

The current `fixture` mode remains available for deterministic offline tests.
No standalone story-only endpoint is added in this change.

## Scope

Included:

- Baidu geocoding for destination resolution.
- Baidu Place Search for verified POI candidates.
- Baidu DirectionLite routes for route geometry, distance, and duration.
- A model adapter that may select only returned Baidu POI UIDs and must ground
  narration in verified facts.
- Real-mode planner wiring, configuration, structured provider errors, and
  documentation.
- Unit and API contract tests using `httpx.MockTransport` and fake provider
  seams; live-provider smoke tests remain opt-in.

Excluded:

- Database, cache, login, queues, deployment, overseas planning, and revision.
- A frontend migration to the planned `/api/v1` NDJSON endpoint.
- POI photos, reviews, opening-status enrichment, traffic replay, or booking.

## Architecture

FastAPI continues to assemble dependencies and expose the compatibility route.
Pure planning code receives a `MapProvider` and `ModelProvider` Protocol, so
provider payloads never escape their adapters. `FixtureTripPlanner` remains the
offline implementation; `RealTripPlanner` resolves a destination, searches
Baidu candidates, asks the model for a UID-only schedule, calculates every
selected consecutive route through Baidu, asks the model for grounded
narration, validates the resulting `TripPlan`, and compiles its
`StoryTimeline`.

`full-real` and the existing `map-real` setting use the real planner so the
setting cannot silently return fixture data. Health metadata reports Baidu and
real-model modes for both. `fixture` remains the only mock mode.

## Provider contracts

`app/map_provider.py` defines:

```python
class MapProvider(Protocol):
    async def resolve_destination(self, name: str) -> ResolvedDestination: ...
    async def search_pois(self, query: PoiSearchQuery) -> list[VerifiedPoi]: ...
    async def route(self, request: RouteRequest) -> RouteLeg: ...
```

`BaiduMapAdapter` uses these official server endpoints:

- `geocoding/v3/` for destination coordinates, returning BD-09 longitude and
  latitude.
- `place/v2/search` for city-scoped POI candidates, requesting detailed
  information and BD-09 coordinates.
- `directionlite/v1/walking`, `driving`, `riding`, or `transit` for route
  facts. The first returned route is used. Each step's semicolon-separated
  `path` is flattened into geometry; the verified POI endpoints are retained
  as the first and last points so `PlanValidator` can enforce endpoint identity.

The adapter checks HTTP failures, malformed JSON, and non-zero Baidu status
codes. Timeouts become `MAP_PROVIDER_TIMEOUT`; no-result searches become
`POI_NOT_FOUND`; route failures become `ROUTE_UNAVAILABLE`.

`app/model_provider.py` defines schedule and narration Protocols. The real
adapter wraps the existing OpenAI-compatible client and parses strict JSON:

```json
{"days":[{"day":1,"poiUids":["baidu_uid_1","baidu_uid_2"]}]}
```

and:

```json
{"narration":[{"poiUid":"baidu_uid_1","text":"..."}]}
```

Unknown UIDs, duplicate selections, missing days, missing narration, extra
keys, invalid JSON, or non-positive content fail closed as
`MODEL_OUTPUT_INVALID`. The model never supplies coordinates, route facts, or
opening hours.

## Real planning flow

1. Reject the known overseas markers before any provider call.
2. Resolve the requested destination with Baidu geocoding.
3. Search up to 20 city-scoped tourist POIs, deduplicated by Baidu UID.
4. Ask the model to select at least one candidate per requested day using only
   candidate UIDs.
5. Build stops from the Baidu `VerifiedPoi` values. The provider's opening
   hours are preserved when available; the existing 60-minute presentation
   default is used only for the required recommendation field.
6. Call Baidu routing for each consecutive pair using walking as the default
   mode. Route geometry, distance, and duration come only from Baidu.
7. Ask the model for one grounded narration item per selected POI using only
   the POI name, address, and opening-hours facts.
8. Set the narration on the stops, validate the full plan, compile a timeline,
   and return the same camelCase `PlanningResult` shape.

Real plans use a new UUID and version `1` per request. No server-side state is
introduced.

## Configuration

Add these safe-default settings:

- `LUMIVO_BAIDU_MAP_AK`: required for real map calls, default empty.
- `LUMIVO_MAP_BASE_URL`: default `https://api.map.baidu.com`.
- `LUMIVO_MAP_TIMEOUT_MS`: default `10000`, bounded to 1000-120000.
- `LUMIVO_PROVIDER_MODE=full-real` to activate the real planner.

Keys remain in the ignored `.env`; `.env.example` contains no credentials.

## Error behavior

The compatibility route maps map/model failures to the existing `{error:{code,
message}}` envelope. A failed provider call or failed validation never returns
a partial or fabricated playable result. Existing fixture errors and response
shape remain unchanged.

## Verification

- Adapter tests assert exact Baidu query parameters, BD-09 normalization,
  route-path flattening, endpoint anchoring, and provider error mapping.
- Real planner tests use fake Protocol implementations and assert all selected
  POIs and route facts come from the map provider, UID grounding is enforced,
  and timeline identity matches the plan.
- Existing fixture/API/domain tests must remain green.
- `python -m pytest` is the required local suite. Live Baidu and live AI smoke
  checks are reported separately and only run when credentials are configured.

## Acceptance criteria

1. With `LUMIVO_PROVIDER_MODE=full-real`, a valid China destination produces a
   `plan` whose POI UIDs, coordinates, route geometry, distances, and durations
   originate from Baidu responses, plus a matching deterministic timeline.
2. With no map key, the service returns a structured configuration/provider
   error instead of fixture data or a fake success.
3. A model cannot introduce an unknown POI or any route/coordinate fact.
4. Fixture mode remains deterministic and offline.
5. The compatibility endpoint remains callable by the current frontend.

Official provider references:

- https://lbsyun.baidu.com/docs/webapi?title=geocoding/guide/webservice-geocoding-base
- https://lbsyun.baidu.com/docs/webapi?title=placev3/guide/webservice-placeapiV3/interfaceDocumentV2
- https://lbsyun.baidu.com/docs/webapi?title=directionlite/guide/webservice-lwrouteplanapi/walk
