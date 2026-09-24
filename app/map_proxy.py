from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from app.settings import Settings


_TILE_COORDINATE_PATTERN = re.compile(r"^(?:-?\d+|M\d+)$")


def is_valid_tile_coordinate(value: str) -> bool:
    return bool(_TILE_COORDINATE_PATTERN.fullmatch(value))


def encode_baidu_tile_descriptor(descriptor: str) -> str:
    bits = "".join(f"{ord(character) << 1:08b}" for character in descriptor)
    padding = 5 - len(bits) % 5
    padded = "0" * padding + bits
    encoded = "".join(
        chr(int(padded[index : index + 5], 2) + 50)
        for index in range(0, len(padded), 5)
    )
    return f"{encoded}{padding}"


def build_baidu_vector_tile_params(
    x: str, y: str, z: int, ak: str
) -> dict[str, str | int]:
    descriptor = (
        f"x={x}&y={y}&z={z}&styles=pl&textimg=0&v=088&udt=20250110&json=0"
    )
    return {
        "qt": "vtile",
        "v": "three",
        "ak": ak,
        "param": encode_baidu_tile_descriptor(descriptor),
    }

_ALLOWED_STYLE_ASSETS = frozenset({"icons_2x.js", "fs.js", "indoor_fs.js"})
_MAP_ICON_ASSET_PATTERN = re.compile(r"^map_icons2x/MapRes/[A-Za-z0-9_-]+\.png$")


def _proxy_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def create_map_proxy_router(
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
) -> APIRouter:
    router = APIRouter()

    async def fetch_upstream(
        url: str, *, params: dict[str, str | int] | None = None
    ) -> httpx.Response:
        timeout_seconds = settings.map_timeout_ms / 1000
        if http_client is not None:
            return await http_client.get(url, params=params, timeout=timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            return await client.get(url, params=params)

    async def proxy_response(
        url: str, *, params: dict[str, str | int] | None = None
    ) -> Response:
        try:
            upstream = await fetch_upstream(url, params=params)
        except httpx.TimeoutException:
            return _proxy_error(503, "BAIDU_MAP_UNAVAILABLE", "地图服务暂时不可用")
        except httpx.RequestError:
            return _proxy_error(503, "BAIDU_MAP_UNAVAILABLE", "地图服务暂时不可用")
        if upstream.status_code >= 400:
            return _proxy_error(503, "BAIDU_MAP_UNAVAILABLE", "地图服务暂时不可用")
        return Response(
            content=upstream.content,
            media_type=upstream.headers.get("content-type", "application/octet-stream"),
        )

    @router.get("/api/v1/map/baidu/pvd")
    async def vector_tile(
        z: int = Query(ge=0, le=21),
        x: str = Query(min_length=1, max_length=32),
        y: str = Query(min_length=1, max_length=32),
    ) -> Response:
        if not is_valid_tile_coordinate(x) or not is_valid_tile_coordinate(y):
            return _proxy_error(400, "INVALID_TILE_COORDINATE", "地图瓦片坐标无效")
        ak = (settings.baidu_vector_tile_ak or "").strip()
        if not ak:
            return _proxy_error(503, "BAIDU_MAP_NOT_CONFIGURED", "地图服务未配置")
        url = f"{settings.baidu_vector_tile_base_url.rstrip('/')}/pvd/"
        return await proxy_response(url, params=build_baidu_vector_tile_params(x, y, z, ak))

    @router.get("/api/v1/map/baidu/sty/{asset_path:path}")
    async def style_asset(asset_path: str) -> Response:
        if (
            asset_path not in _ALLOWED_STYLE_ASSETS
            and not _MAP_ICON_ASSET_PATTERN.fullmatch(asset_path)
        ):
            return _proxy_error(404, "MAP_STYLE_NOT_ALLOWED", "地图样式资源不存在")
        url = f"{settings.baidu_map_static_base_url.rstrip('/')}/sty/{asset_path}"
        return await proxy_response(url)

    return router
