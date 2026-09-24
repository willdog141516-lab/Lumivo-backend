import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.map_proxy import create_map_proxy_router
from app.settings import Settings


def make_proxy_client(
    handler: httpx.AsyncBaseTransport | httpx.MockTransport,
    *,
    baidu_map_ak: str | None = "server-ak",
    baidu_vector_tile_ak: str | None = "vector-ak",
) -> TestClient:
    settings = Settings(
        _env_file=None,
        baidu_map_ak=baidu_map_ak,
        baidu_vector_tile_ak=baidu_vector_tile_ak,
        baidu_vector_tile_base_url="https://tiles.example",
        baidu_map_static_base_url="https://static.example",
    )
    app = FastAPI()
    http_client = httpx.AsyncClient(transport=handler)
    app.include_router(create_map_proxy_router(settings, http_client))
    return TestClient(app)


def test_vector_tile_proxy_uses_backend_only_vector_tile_ak() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"tile", headers={"content-type": "image/png"})

    with make_proxy_client(httpx.MockTransport(handler)) as client:
        response = client.get("/api/v1/map/baidu/pvd?z=7&x=M1&y=-2&ak=client-ak&sk=client-sk&sn=client-sn&ApiAuthorization=client-token")

    assert response.status_code == 200
    assert response.content == b"tile"
    assert response.headers["content-type"].startswith("image/png")
    assert len(requests) == 1
    assert str(requests[0].url).startswith("https://tiles.example/pvd/?")
    assert requests[0].url.params["ak"] == "vector-ak"
    assert "client-ak" not in str(requests[0].url)
    assert "client-token" not in str(requests[0].url)
    assert "client-ak" not in requests[0].url.params["param"]


def test_style_proxy_allows_known_static_asset() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://static.example/sty/icons_2x.js"
        return httpx.Response(
            200,
            content=b"style",
            headers={"content-type": "application/javascript"},
        )

    with make_proxy_client(httpx.MockTransport(handler)) as client:
        response = client.get("/api/v1/map/baidu/sty/icons_2x.js")

    assert response.status_code == 200
    assert response.content == b"style"


def test_style_proxy_allows_baidu_map_icon_assets() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert (
            str(request.url)
            == "https://static.example/sty/map_icons2x/MapRes/tiyu.png"
        )
        return httpx.Response(200, content=b"icon", headers={"content-type": "image/png"})

    with make_proxy_client(httpx.MockTransport(handler)) as client:
        response = client.get("/api/v1/map/baidu/sty/map_icons2x/MapRes/tiyu.png")

    assert response.status_code == 200
    assert response.content == b"icon"


def test_proxy_rejects_invalid_tile_coordinates_and_unknown_assets() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid requests must not reach Baidu")

    with make_proxy_client(httpx.MockTransport(handler)) as client:
        tile_response = client.get("/api/v1/map/baidu/pvd?z=7&x=1.5&y=2")
        asset_response = client.get("/api/v1/map/baidu/sty/not-allowed.js")

    assert tile_response.status_code == 400
    assert tile_response.json()["error"]["code"] == "INVALID_TILE_COORDINATE"
    assert asset_response.status_code == 404
    assert asset_response.json()["error"]["code"] == "MAP_STYLE_NOT_ALLOWED"


def test_proxy_requires_vector_tile_ak() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("missing credentials must not reach Baidu")

    with make_proxy_client(
        httpx.MockTransport(handler),
        baidu_vector_tile_ak=None,
    ) as client:
        response = client.get("/api/v1/map/baidu/pvd?z=7&x=1&y=2")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "BAIDU_MAP_NOT_CONFIGURED"

def test_proxy_maps_upstream_failure_to_structured_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with make_proxy_client(httpx.MockTransport(handler)) as client:
        response = client.get("/api/v1/map/baidu/pvd?z=7&x=1&y=2")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "BAIDU_MAP_UNAVAILABLE"


def test_proxy_maps_upstream_timeout_to_structured_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with make_proxy_client(httpx.MockTransport(handler)) as client:
        response = client.get("/api/v1/map/baidu/pvd?z=7&x=1&y=2")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "BAIDU_MAP_UNAVAILABLE"
