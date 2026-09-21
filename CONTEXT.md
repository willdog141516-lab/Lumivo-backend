# Lumivo Backend Context

Last updated: 2026-09-21

## Relationship to the frontend

- Frontend: `E:\code\Lumivo-AI\lumivo-ai`
- Backend: `E:\code\Lumivo-AI\lumivo-backend`
- Frontend development URL: `http://localhost:8989`
- Backend development URL: `http://localhost:8000`

The projects are sibling directories. They have independent dependencies and processes. Their shared contract is the FastAPI OpenAPI document; frontend TypeScript types should be generated or mechanically derived from it.

## Confirmed MVP

The backend provides three capabilities for China-only travel:

1. Itinerary planning.
2. Verified street-map facts through Baidu services.
3. StoryTimeline compilation for frontend route animation.

Overseas destinations return `UNSUPPORTED_REGION` with “暂不支持该地区，等待后续开发”.

## Confirmed decisions

- Backend language: Python.
- Framework: FastAPI with Pydantic models.
- Map authority: Baidu POI and route services.
- Coordinate system at the map seam: BD-09.
- First fixture and acceptance scenario: Nanjing, three days.
- Initial delivery mode: fixture remains the offline default; `full-real` uses BaiduMap plus the OpenAI-compatible model adapter.
- Integration order: deterministic fixture and local HTTP flow are complete; real Baidu map data, constrained real AI, canonical NDJSON planning, and stateless day revision are implemented locally; live credentials, browser acceptance, and hardening remain.
- No login, database, Redis, queue, server deployment, or overseas planning in the MVP.

## Current implementation

Python 兼容后端已经接管前端当前使用的本地接口：`GET /health`、`POST /api/chat` 和 `POST /api/trips/plan`。聊天接口通过 OpenAI-compatible Chat Completions 调用 AI，并支持 SSE 增量输出；规范规划接口 `POST /api/v1/trips/plan` 与 `POST /api/v1/trips/revise` 以 NDJSON 输出进度和终态结果，规划结果只允许已验证 UID、有效路线和匹配的 StoryTimeline。当前 StoryTimeline 为 1000ms 开场、每天 8000ms、2000ms 结尾。`GET /api/v1/health` 保留为 Python 规范健康检查。

规范规划会把完整聊天记录交给模型提取明确提到的目的地与旅行天数；缺失时返回 `PLAN_INPUT_REQUIRED`，不会猜测。修订会优先检索并保留用户明确点名的 POI；当前目的地找不到该地点时返回 `POI_NOT_FOUND`，不会随机替换。修订成功还要求目标日的 POI 顺序或交通方式实际变化，避免无变化结果被前端当作新路线。`fixture` 仍只提供南京三日离线样例，全国真实地图规划须使用 `full-real`。
默认 Adapter 模式仍为 `fixture`。真实模式需要 `LUMIVO_BAIDU_MAP_AK` 和 AI Key；百度控制台启用 SN 校验时还需要服务端 `LUMIVO_BAIDU_MAP_SK`。NDJSON 规划和无状态修订已完成；实时凭据/配额验证、浏览器验收、全国更丰富的检索、数据库和外部持久化仍未完成。

## Immediate build sequence

1. Verify live Baidu POIs/routes and live AI with configured credentials.
2. Complete browser acceptance, cancellation/retry hardening, and performance evidence.
3. Keep database, cloud persistence, deployment, and authentication outside the MVP.

## Core evidence rule

Report deterministic tests, live Baidu checks, live model checks, and browser integration as separate evidence. A passing Pytest suite does not prove provider credentials, provider quotas, or frontend playback.
