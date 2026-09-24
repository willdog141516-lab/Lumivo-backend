# Lumivo Backend Context

Last updated: 2026-09-23

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
- Integration order: deterministic fixture and local HTTP flow are complete; real Baidu map data, constrained real AI, canonical NDJSON planning, stateless day revision, and Story Map route-preference rerouting are implemented locally; live credentials, browser acceptance, and hardening remain.
- No login, database, Redis, queue, server deployment, or overseas planning in the MVP.

## Current implementation

Initial planning still accepts an optional transport preference for API clients; omitted preferences preserve AI-selected modes, with the existing transit-to-driving fallback. On the Story Map, users can reroute all real-plan legs as public transport, driving, walking, or cycling. The new reroute path requests the selected mode exactly and fails the whole operation if any route is unavailable. Fixture route geometry is fixed: its UI controls are disabled with an explanation, and the backend rejects rerouting.

Python 兼容后端已经接管前端当前使用的本地接口：GET /health、POST /api/chat 和 POST /api/trips/plan。聊天接口通过 OpenAI-compatible Chat Completions 调用 AI，并支持 SSE 增量输出；规范规划、修订和交通方式重算接口 POST /api/v1/trips/plan、POST /api/v1/trips/revise 与 POST /api/v1/trips/reroute 以 NDJSON 输出进度和终态结果，规划结果仅允许已验证 UID、完整有效路线与匹配版本的 StoryTimeline。重算请求只携带行程元数据及站点，不携带旧路线几何；成功时保留行程 ID、递增版本，并返回与新路线匹配的 StoryTimeline。当前 StoryTimeline 为 1000ms 开场、每天 8000ms、2000ms 结尾。GET /api/v1/health 保留为 Python 规范健康检查。

规范规划会把完整聊天记录交给模型提取明确提到的目的地与旅行天数；缺失时返回 `PLAN_INPUT_REQUIRED`，不会猜测。修订会优先检索并保留用户明确点名的 POI；当前目的地找不到该地点时返回 `POI_NOT_FOUND`，不会随机替换。修订成功还要求目标日的 POI 顺序或交通方式实际变化，避免无变化结果被前端当作新路线。`fixture` 仍只提供南京三日离线样例，全国真实地图规划须使用 `full-real`。
默认 Adapter 模式仍为 fixture。真实模式需要 LUMIVO_BAIDU_MAP_AK 和 AI Key；百度控制台启用 SN 校验时还需要服务端 LUMIVO_BAIDU_MAP_SK；浏览器底图代理还需要后端保存的 LUMIVO_BAIDU_VECTOR_TILE_AK。NDJSON 规划、无状态修订和路线重算已在本地实现；实时凭据/配额验证、浏览器验收、全国更丰富的检索、数据库和外部持久化仍未完成。
公开规划、修订、重算和地图资源代理请求都不接受 Provider 凭据字段；服务端 Adapter 从运行时配置读取百度服务端 AK/SK，地图代理单独读取后端保存的矢量瓦片 AK。浏览器地图使用离线模式的 mapv-three provider，瓦片和样式资源统一经后端白名单代理，浏览器不再持有或发送百度 Key。

## Immediate build sequence

1. Verify live Baidu POIs/routes, live vector tiles, and live AI with configured credentials.
2. Complete browser Network acceptance, cancellation/retry hardening, and performance evidence.
3. Keep database, cloud persistence, deployment, and authentication outside the MVP.

## Core evidence rule

Report deterministic tests, live Baidu checks, live model checks, and browser integration as separate evidence. A passing Pytest suite does not prove provider credentials, provider quotas, or frontend playback.
