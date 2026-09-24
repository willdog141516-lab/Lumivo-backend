# Baidu Map Server Proxy Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Keep the existing Three.js route-story map while making all browser map requests go through Lumivo, with Baidu credentials used only by the backend.

**Architecture:** Add a narrow FastAPI map-resource proxy for vector tiles and the three static style scripts required by the installed @baidumap/mapv-three package. Switch the frontend provider to the package's offline mode and override its tile URL generator so the browser requests only Lumivo URLs containing validated tile coordinates.

**Tech Stack:** FastAPI, Pydantic Settings, httpx, Next.js 16, React, Three.js, @baidumap/mapv-three, Node node:test.

**Spec:** docs/superpowers/specs/2026-09-23-baidu-map-server-proxy-design.md

## Global Constraints

- The browser must not directly request a Baidu map host or send ak, sk, sn, or ApiAuthorization.
- The backend map proxy is an allowlist, never a general-purpose forward proxy.
- The backend injects LUMIVO_BAIDU_MAP_AK and never forwards client credentials.
- Reuse the installed mapv-three package; do not add a new map SDK or dependency.
- Keep TripPlan, StoryTimeline, route geometry, camera commands, and playback behavior unchanged.
- Preserve unrelated uncommitted work in both repositories and do not stage it.

## Review Focus

- M-prefixed and negative tile coordinates must survive browser URL construction and backend Baidu parameter encoding; Task 1 and Task 2 tests pin this.
- Client-supplied ak, sk, sn, and authorization-like parameters must not reach Baidu; Task 2 tests pin server-side credential injection.
- Missing AK, timeout, and non-success upstream responses must become structured 503 errors without leaking the upstream URL; Task 2 tests pin this.
- Unallowlisted or path-like style asset names must not become arbitrary proxy targets; Task 2 tests pin this.
- The frontend must work without a browser-key environment variable and must use BD-09-compatible proxy Provider settings; Task 3 tests pin this.

---

### Task 1: Backend tile request construction

**Files:**
- Modify: E:/code/Lumivo-AI/lumivo-backend/app/settings.py
- Create: E:/code/Lumivo-AI/lumivo-backend/app/map_proxy.py
- Test: E:/code/Lumivo-AI/lumivo-backend/tests/api/test_map_proxy.py

**Interfaces:**
- Consumes: existing Settings.baidu_vector_tile_ak and Settings.map_timeout_ms.
- Produces: encode_baidu_tile_descriptor(descriptor: str) -> str and build_baidu_vector_tile_params(x: str, y: str, z: int, ak: str) -> dict[str, str] for the router task.

- [ ] Step 1: Write the failing helper tests

Add the following focused assertions to the new test module:

~~~python
from app.map_proxy import build_baidu_vector_tile_params, encode_baidu_tile_descriptor


def test_baidu_tile_descriptor_matches_mapv_three_encoding():
    descriptor = "x=M1&y=-2&z=7&styles=pl&textimg=0&v=088&udt=20250110&json=0"

    assert encode_baidu_tile_descriptor(descriptor) == (
        "P3O;FJD>P;O7FK4>PCO8NE98O5K?CDI8A=B?BE9:K=J@CFHLKKO82E9>A;B92N4>O=6@BPE6>3D8FJ54>;B6KG98MM@9FJ2-467"
    )


def test_baidu_tile_params_keep_coordinates_and_use_server_ak():
    params = build_baidu_vector_tile_params("M1", "-2", 7, "server-ak")

    assert params["qt"] == "vtile"
    assert params["v"] == "three"
    assert params["ak"] == "server-ak"
    assert "client-ak" not in params["param"]
    assert params["param"] == encode_baidu_tile_descriptor(
        "x=M1&y=-2&z=7&styles=pl&textimg=0&v=088&udt=20250110&json=0"
    )
~~~

- [ ] Step 2: Run the helper tests and verify the expected failure

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_map_proxy.py -k "descriptor or tile_params" -q
~~~

Expected: FAIL because app.map_proxy and its helper functions do not exist yet.

- [ ] Step 3: Add the minimal settings and encoding helpers

Add two settings with safe Baidu defaults and aliases:

~~~python
baidu_vector_tile_base_url: str = Field(
    default="https://apimaponline0.bdimg.com",
    validation_alias=AliasChoices(
        "LUMIVO_BAIDU_VECTOR_TILE_BASE_URL", "BAIDU_VECTOR_TILE_BASE_URL"
    ),
)
baidu_map_static_base_url: str = Field(
    default="https://maponline0.bdimg.com",
    validation_alias=AliasChoices(
        "LUMIVO_BAIDU_MAP_STATIC_BASE_URL", "BAIDU_MAP_STATIC_BASE_URL"
    ),
)
~~~

In app/map_proxy.py, implement the mapv-three-compatible 8-bit/5-bit
encoding shown in the installed package, and build only these fixed tile
parameters: qt, v, ak, and param. Validate coordinates with one allowlist regex
accepting - prefixed digits or M prefixed digits and validate zoom in the router
boundary.

- [ ] Step 4: Run the helper tests and verify they pass

Run the same focused command. Expected: both tests PASS.

- [ ] Step 5: Record the task boundary without staging unrelated work

Run:

~~~powershell
git diff -- app/settings.py app/map_proxy.py tests/api/test_map_proxy.py
git status --short
~~~

Confirm only the intended hunks are part of this task; do not stage or commit
the existing unrelated worktree edits.

### Task 2: FastAPI map-resource proxy

**Files:**
- Modify: E:/code/Lumivo-AI/lumivo-backend/app/map_proxy.py
- Modify: E:/code/Lumivo-AI/lumivo-backend/app/main.py
- Modify: E:/code/Lumivo-AI/lumivo-backend/tests/api/test_map_proxy.py
- Modify: E:/code/Lumivo-AI/lumivo-backend/.env.example
- Modify: E:/code/Lumivo-AI/lumivo-backend/README.md
- Modify: E:/code/Lumivo-AI/lumivo-backend/CONTEXT.md
- Modify: E:/code/Lumivo-AI/lumivo-backend/docs/superpowers/specs/2026-08-18-lumivo-backend-design.md

**Interfaces:**
- Consumes: Task 1 settings and build_baidu_vector_tile_params helper.
- Produces: create_map_proxy_router(settings: Settings, http_client: httpx.AsyncClient | None = None) -> APIRouter, mounted under /api/v1/map.

- [ ] Step 1: Write failing endpoint tests using httpx.MockTransport

Extend tests/api/test_map_proxy.py with a small FastAPI test app that mounts
the router factory and injects an httpx.AsyncClient backed by a MockTransport.
Add tests with these behaviors:

~~~python
def test_vector_tile_proxy_injects_server_ak_and_returns_binary_content():
    observed = []

    async def upstream(request):
        observed.append(request)
        return httpx.Response(200, content=b"tile", headers={"content-type": "application/octet-stream"})

    response = test_client(transport=httpx.MockTransport(upstream), ak="server-ak").get(
        "/api/v1/map/baidu/pvd?z=7&x=M1&y=-2&ak=client-ak&sn=client-sn"
    )

    assert response.status_code == 200
    assert response.content == b"tile"
    assert observed[0].url.params["ak"] == "server-ak"
    assert "client-ak" not in str(observed[0].url)
    assert "client-sn" not in str(observed[0].url)


def test_static_proxy_allows_only_known_mapv_assets():
    async def upstream(request):
        return httpx.Response(
            200,
            content=b"window.iconSetInfo_high = {}",
            headers={"content-type": "application/javascript"},
        )

    client = test_client(transport=httpx.MockTransport(upstream), ak="server-ak")
    assert client.get("/api/v1/map/baidu/sty/icons_2x.js").status_code == 200
    assert client.get("/api/v1/map/baidu/sty/not-allowed.js").status_code == 404


def test_map_proxy_fails_closed_for_missing_key_and_upstream_timeout():
    missing_key = test_client(transport=httpx.MockTransport(lambda request: None), ak=None)
    assert missing_key.get("/api/v1/map/baidu/pvd?z=7&x=1&y=2").json()["error"]["code"] == "MAP_PROVIDER_ERROR"

    async def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    timed_out = test_client(transport=httpx.MockTransport(timeout), ak="server-ak")
    response = timed_out.get("/api/v1/map/baidu/pvd?z=7&x=1&y=2")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MAP_PROVIDER_TIMEOUT"
~~~

The test helper must close injected clients after each test. Do not use a live
network call in these tests.

- [ ] Step 2: Run the endpoint tests and verify the expected failure

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_map_proxy.py -q
~~~

Expected: FAIL because the router factory and endpoints are not implemented.

- [ ] Step 3: Implement the allowlisted proxy router

Implement create_map_proxy_router with:

~~~python
router = APIRouter(prefix="/api/v1/map")

@router.get("/baidu/pvd")
async def vector_tile(z: int, x: str, y: str): ...

@router.get("/baidu/sty/{asset_name}")
async def style_asset(asset_name: str): ...
~~~

Use Query(ge=0, le=21) for z, reject invalid x/y with a structured 400
response, and restrict assets to exactly icons_2x.js, fs.js, and indoor_fs.js.
Build upstream URLs from settings only. Ignore all unmodelled client query fields
so client credentials cannot be forwarded. Return the upstream content type and
body on success. Map missing AK, timeout, httpx.RequestError, and upstream status
>= 400 to JSON 503 responses with MAP_PROVIDER_ERROR or MAP_PROVIDER_TIMEOUT.

Include the router from create_app without changing planner assembly.

- [ ] Step 4: Run the endpoint tests and the backend API tests

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_map_proxy.py tests/api/test_health.py tests/api/test_canonical.py -q
~~~

Expected: all selected tests PASS.

- [ ] Step 5: Update backend configuration and documentation

Add the two safe proxy-host variables to .env.example. Replace the README
statement that the browser may directly use a Baidu key with the server-proxy
contract. Update CONTEXT.md and the backend design's HTTP, local configuration,
security, and acceptance sections to state that browser map resources use
/api/v1/map/baidu/* and credentials remain server-side.

### Task 3: Frontend proxy Provider integration

**Files:**
- Modify: E:/code/Lumivo-AI/lumivo-ai/components/map-stage/baidu-map-stage.tsx
- Modify: E:/code/Lumivo-AI/lumivo-ai/lib/map-stage/mapv-three.d.ts
- Test: E:/code/Lumivo-AI/lumivo-ai/components/map-stage/baidu-map-stage.test.mjs

**Interfaces:**
- Consumes: Task 2's /api/v1/map/baidu/pvd and /sty/* routes plus existing NEXT_PUBLIC_AI_BACKEND_URL.
- Produces: getBaiduMapProxyBaseUrl(backendUrl?: string) -> string and createBaiduVectorTileProxyUrl(baseUrl: string, z: number, x: string | number, y: string | number) -> string.

- [ ] Step 1: Write failing frontend URL and source-contract tests

Add tests before changing the component:

~~~js
test("builds a credential-free backend map proxy URL", () => {
  const base = baiduMapStageModule.getBaiduMapProxyBaseUrl("http://localhost:8000/");
  const url = baiduMapStageModule.createBaiduVectorTileProxyUrl(base, 7, "M1", "-2");

  assert.equal(url, "http://localhost:8000/api/v1/map/baidu/pvd?z=7&x=M1&y=-2");
  assert.doesNotMatch(url, /ak|sk|sn|authorization/i);
});

test("map stage no longer reads a browser Baidu key or assigns BaiduMapConfig.ak", () => {
  assert.doesNotMatch(source, /NEXT_PUBLIC_BAIDU_BROWSER_AK/);
  assert.doesNotMatch(source, /BaiduMapConfig\\.ak/);
});
~~~

- [ ] Step 2: Run the focused map-stage test and verify the expected failure

Run:

~~~powershell
node --import=tsx --test components/map-stage/baidu-map-stage.test.mjs
~~~

Expected: FAIL because the two URL helpers still do not exist and the source
still contains the browser-key integration.

- [ ] Step 3: Implement the credential-free Provider setup

Add the two pure URL helpers. Normalize the backend origin by trimming trailing
slashes, append /api/v1/map/baidu, and use URL.searchParams to add only z, x,
and y.

Replace the online Provider setup with:

~~~ts
const proxyBaseUrl = getBaiduMapProxyBaseUrl();
const tileProvider = new mapvthree.BaiduVectorTileProvider({
  isOffline: true,
  url: proxyBaseUrl,
  projection: "BD:MERCATOR",
  displayOptions: {
    base: true,
    building: theme !== "dark",
    link: true,
    poi: true,
  },
});

tileProvider.getTileURL = (zoom, x, y, tile) => {
  const baseZoom = tile.loaderConfig?.baseZ ?? zoom;
  const [level, tileX, tileY] = tile.grid.getRasterTileCoord(baseZoom, x, y);
  return createBaiduVectorTileProxyUrl(proxyBaseUrl, level, tileX, tileY);
};
~~~

Extend the local mapv-three declaration with isOffline, url, projection, and
the getTileURL/grid shape needed by this assignment. Remove the browser-key
read, the BaiduMapConfig.ak assignment, the unused dynamic Baidu style payload,
and the browser-key status branch. Keep Engine, R3F, theme clear color,
overlays, animation, and camera logic unchanged. Report the diagnostic bottom
map line as server-proxied Baidu vector tiles.

- [ ] Step 4: Run the focused map-stage test and the route-animation tests

Run:

~~~powershell
node --import=tsx --test components/map-stage/baidu-map-stage.test.mjs lib/map-stage/route-animation.test.mjs
~~~

Expected: all selected tests PASS.

### Task 4: Frontend configuration and cross-repo documentation

**Files:**
- Modify: E:/code/Lumivo-AI/lumivo-ai/.env.example
- Modify: E:/code/Lumivo-AI/lumivo-ai/README.md
- Modify: E:/code/Lumivo-AI/lumivo-ai/CONTEXT.md
- Modify: E:/code/Lumivo-AI/lumivo-ai/components/map-stage/baidu-map-stage.test.mjs

**Interfaces:**
- Consumes: Task 3's proxy-based MapStage behavior.
- Produces: no frontend Baidu credential configuration and documentation that points operators to the backend AK.

- [ ] Step 1: Remove stale browser-key configuration and update docs

Remove NEXT_PUBLIC_BAIDU_BROWSER_AK from the committed frontend example. Do
not print or copy any value from the ignored local environment file; if it still
contains the now-unused variable, leave unrelated variables intact and remove
only that variable through a targeted edit. Update the README and CONTEXT to
state that map resources are fetched from the backend proxy and the frontend
only needs NEXT_PUBLIC_AI_BACKEND_URL.

Update the existing source-contract test to assert the new proxy contract
instead of the old browser-key name, and remove assertions for the deleted
dynamic style helper.

- [ ] Step 2: Run frontend focused checks

Run:

~~~powershell
node --import=tsx --test components/map-stage/baidu-map-stage.test.mjs
npm run lint
npx tsc --noEmit
~~~

Expected: all commands exit 0.

### Task 5: Full verification and manual Network acceptance

**Files:**
- No new production files; inspect the complete diff in both repositories.

- [ ] Step 1: Run the complete backend suite

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest
~~~

Expected: 0 failures, with any existing warnings reported separately.

- [ ] Step 2: Run the complete frontend checks

Run from E:/code/Lumivo-AI/lumivo-ai:

~~~powershell
$tests = rg --files -g '*.test.mjs'
node --import=tsx --test $tests
npm run lint
npx tsc --noEmit
npm run build
~~~

Expected: all Node tests pass, lint/typecheck/build exit 0.

- [ ] Step 3: Scan for direct browser credential paths

Run from the frontend repository:

~~~powershell
rg -n --hidden --glob '!node_modules' --glob '!\\.next' "NEXT_PUBLIC_BAIDU|BaiduMapConfig\\.ak|api\\.map\\.baidu|apimaponline|maponline|ApiAuthorization" components lib app .env.example README.md CONTEXT.md
~~~

Expected: no production source or committed configuration match; any negative
test assertion must be intentional and documented.

- [ ] Step 4: Run manual local acceptance

Configure only LUMIVO_BAIDU_MAP_AK on the backend and
NEXT_PUBLIC_AI_BACKEND_URL=http://localhost:8000 on the frontend. Start both
servers, open the Story Map, and inspect Network. Confirm map requests target
the Lumivo backend, contain only z, x, and y or an allowlisted asset name, and
contain no ak, sk, sn, ApiAuthorization, or Baidu host. A 200 response from
the proxy without a rendered basemap is not sufficient; confirm the vector tile
layer and existing route overlays both render.

- [ ] Step 5: Report the boundary clearly

Report backend deterministic tests, frontend deterministic checks, build
status, and live browser/Provider smoke status separately. Do not claim live
Baidu success from local tests alone. Do not commit or push the implementation
files until the user explicitly asks for that integration step, because both
repositories contain unrelated pre-existing worktree changes.

