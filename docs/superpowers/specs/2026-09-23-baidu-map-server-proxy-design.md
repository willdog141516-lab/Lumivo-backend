# Baidu Map Server Proxy Design

Date: 2026-09-23

Status: Design approved in chat; implementation pending

## 1. Goal

Keep the current Three.js route-story experience while ensuring the browser
never sends a Baidu credential or directly requests a Baidu map host. The
server owns the Baidu AK and proxies only the vector-tile resources required by
the current `@baidumap/mapv-three` integration.

## 2. Non-goals

- Do not proxy arbitrary URLs or accept an upstream host from the browser.
- Do not move the existing POI and route provider calls into the frontend.
- Do not add authentication, persistence, a cache service, or a new map SDK.
- Do not promise that an exposed browser key can be made secret by encryption.
- Do not change the TripPlan, StoryTimeline, or route-animation contracts.

## 3. Design

The frontend keeps `@baidumap/mapv-three`, but creates its
`BaiduVectorTileProvider` in offline mode. The provider's tile URL is
overridden to point to the configured backend origin instead of using the
package's online mode, whose implementation hardcodes Baidu hosts and `ak`.
The provider uses the package's local style asset and the backend proxy for the
small static style scripts it needs.

The backend exposes a narrow map-resource boundary:

```text
Browser -> GET {NEXT_PUBLIC_AI_BACKEND_URL}/api/v1/map/baidu/pvd?z&x&y
        -> GET {server-configured Baidu vector host}/pvd/?...&ak=server AK

Browser -> GET {NEXT_PUBLIC_AI_BACKEND_URL}/api/v1/map/baidu/sty/{asset}
        -> GET {server-configured Baidu static host}/sty/{allowlisted asset}
```

The browser-facing requests contain only validated tile coordinates or an
allowlisted static asset name. The backend creates the Baidu vector-tile
parameter encoding itself and injects `LUMIVO_BAIDU_MAP_AK`; any client `ak`,
`sk`, `sn`, or authorization-like query values are ignored or rejected and are
never forwarded.

## 4. Backend interface

Add a router factory for map resources and include it from `create_app`:

- `GET /api/v1/map/baidu/pvd`
  - accepts `z` from 0 through 21;
  - accepts `x` and `y` as the SDK's non-negative, negative, or `M`-prefixed
    tile coordinate strings;
  - constructs the fixed Baidu vector-tile request;
  - returns the upstream binary body and content type;
  - returns a structured 503 map-provider error for missing AK, timeout, or
    upstream failure.
- `GET /api/v1/map/baidu/sty/{asset_name}`
  - permits only `icons_2x.js`, `fs.js`, and `indoor_fs.js`;
  - returns the upstream JavaScript body and content type;
  - never treats the path as a general proxy.

The proxy uses the existing `map_timeout_ms` and `baidu_map_ak` settings. The
two Baidu resource hosts are separate settings with safe Baidu defaults so
tests can point them at a controlled mock server without changing production
request construction. The proxy must not log complete upstream URLs or query
strings.

## 5. Frontend changes

- Remove the `NEXT_PUBLIC_BAIDU_BROWSER_AK` read and all assignments to
  `BaiduMapConfig.ak`.
- Build the proxy base from the existing `NEXT_PUBLIC_AI_BACKEND_URL` setting.
- Instantiate the provider with `isOffline: true`, the backend proxy base URL,
  and `projection: "BD:MERCATOR"` so BD-09 route coordinates keep the current
  projection boundary.
- Override only `getTileURL` to request the backend with `z`, `x`, and `y`,
  without `ApiAuthorization` or any credential parameter.
- Keep the existing Engine-owned renderer, R3F overlay, route geometry,
  camera commands, reduced-motion behavior, and playback controls.
- Update status copy and examples to describe the server-proxied basemap.

The current dynamic Baidu custom-style request is intentionally removed from
the first proxy version. The SDK's local default style remains available; a
separate style-conversion change can be considered only if visual acceptance
requires it.

## 6. Security and failure behavior

- The browser never receives `LUMIVO_BAIDU_MAP_AK` or any server-side signing
  secret.
- The proxy is an allowlist, not a general-purpose forward proxy.
- Client-supplied credential parameters cannot override server settings.
- Missing server AK fails closed with a structured error; it does not fall back
  to a browser key or direct Baidu access.
- Upstream timeout and non-success responses fail closed and do not return a
  playable map resource.
- CORS continues to use the existing configured frontend origin.

## 7. Verification

Backend tests cover:

- valid tile coordinate translation and server-side AK injection;
- rejection/ignoring of client credential parameters;
- static-asset allowlisting;
- missing AK, timeout, and upstream failure responses;
- existing complete backend suite.

Frontend tests cover:

- no browser AK environment variable or `BaiduMapConfig.ak` assignment;
- proxy URL construction contains only backend origin and tile coordinates;
- existing map-stage and route-animation suites, type-check, lint, and build.

Manual acceptance requires opening the story map with the backend running and
checking DevTools Network: map requests must target the Lumivo backend only and
must contain no `ak`, `sk`, `sn`, `ApiAuthorization`, or Baidu host. A live
basemap also requires the server AK to be authorized for the Baidu vector-tile
service; deterministic tests cannot prove that external permission.
