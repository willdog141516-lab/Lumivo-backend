# Lumivo Backend

Lumivo Backend 是 Lumivo AI 的本地 Python FastAPI 后端。它负责把旅行需求转换成经过地图事实校验、可以驱动前端动画的行程。

前端位于 `E:\code\Lumivo-AI\lumivo-ai`，默认运行在 `http://localhost:8989`；后端默认运行在 `http://localhost:8000`。两个项目独立安装依赖和启动，通过 HTTP 通信。

## 当前状态

Python 兼容后端已接管前端当前使用的本地接口：

- Python 3.12+ 项目配置和环境变量读取
- FastAPI 应用工厂
- `GET /health`：兼容现有前端 Node 后端健康检查
- `POST /api/chat`：OpenAI-compatible Chat Completions 代理，支持 SSE 流式回复
- `POST /api/trips/plan`：fixture 或真实百度数据规划，严格校验 AI 返回的 POI UID
- `GET /api/v1/health`：Python 规范健康检查
- `GET /api/v1/map/baidu/pvd`：后端注入瓦片 AK 的矢量瓦片代理
- `GET /api/v1/map/baidu/sty/{asset_name}`：严格白名单的地图样式资源代理
- `TripPlan`、`StoryTimeline` 的前端 camelCase JSON 契约
- 默认不联网的 Pytest 测试

当前默认是 `fixture` 模式。设置 `LUMIVO_PROVIDER_MODE=full-real` 后，规划会读取百度真实 POI、BD-09 坐标和路线，并让 AI 只从已验证 POI 中排程。规范接口 `/api/v1/trips/plan` 和 `/api/v1/trips/revise` 已通过 NDJSON 输出进度、终态结果或结构化错误；修订不依赖服务端会话，沿用同一行程 ID 并递增版本。数据库和部署仍不在 MVP 范围内。

### 规范规划流

- `POST /api/v1/trips/plan`：接受消息与完整聊天记录；目的地和天数可显式传入，或只从对话中明确提到的信息提取，缺失时返回 `PLAN_INPUT_REQUIRED`。返回逐行 NDJSON 进度和最终 `PlanningResult`。
- `POST /api/v1/trips/revise`：接受当前完整 `TripPlan`、目标天数和修订指令；用户明确点名的候选 POI 会被纳入目标日，当前目的地找不到时返回 `POI_NOT_FOUND`，不会随机替换。
- 前端 `TripClient` 已消费这两个接口；旧的 `/api/chat` 和 `/api/trips/plan` 保留为兼容接口。

## 本地启动

PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m uvicorn app.main:app --reload --port 8000
```

然后访问：

```text
http://localhost:8000/health
http://localhost:8000/api/v1/health
```

默认响应会报告：

```json
{
  "status": "ok",
  "service": "Lumivo Backend",
  "environment": "development",
  "provider_mode": "fixture",
  "map_mode": "mock",
  "model_mode": "mock"
}
```

## 测试

```powershell
python -m pytest
```

浏览器底图不再直连百度：前端只请求本服务的地图资源代理，服务端再访问固定的百度瓦片和样式 host。浏览器 Network 中不会出现百度 AK、SK 或百度 host；实时底图需要后端配置 `LUMIVO_BAIDU_VECTOR_TILE_AK`（百度浏览器端 AK，仅存后端）；路线和地理编码仍使用服务端 `LUMIVO_BAIDU_MAP_AK`。

默认 fixture 测试不需要百度密钥、AI 密钥或网络连接。

## 前端兼容接口

前端 `E:\code\Lumivo-AI\lumivo-ai` 默认请求 `http://localhost:8000`，因此启动本服务后无需修改前端请求地址。

`POST /api/chat` 接受 `message`、可选 `history`、`destination` 和 `days`。请求带 `Accept: text/event-stream` 或 `?stream=true` 时返回 SSE：`delta` 事件携带增量文本，最后是 `done` 事件；不带流式标记时仍返回原 JSON 契约。`POST /api/trips/plan` 接受 `message`、可选 `history`、`destination` 和 `days`；缺失的目的地或天数仅从对话中明确提到的信息提取，否则返回 `PLAN_INPUT_REQUIRED`。`fixture` 模式返回南京三日 fixture，`full-real` 模式调用百度真实 POI/路线并返回相同的 `plan` 与 `timeline`。无百度 AK、无可用 POI、无可用路线或模型输出不符合 UID 约束时返回结构化错误，不会回退为假数据。

## 真实数据模式

复制 `.env.example` 为 `.env`，填入百度服务端 AK；如果百度控制台启用了 SN 校验，再填入 SK；同时填入 AI 服务密钥，然后设置：

```dotenv
LUMIVO_PROVIDER_MODE=full-real
LUMIVO_BAIDU_MAP_AK=你的百度服务端AK
LUMIVO_BAIDU_MAP_SK=你的百度服务端SK（启用SN校验时填写）
LUMIVO_BAIDU_VECTOR_TILE_AK=后端保存的百度浏览器端AK（仅地图瓦片）
AI_API_KEY=你的AI服务密钥
```

真实模式当前默认使用步行路线；百度 POI 名称、地址、坐标、路线几何、距离和耗时来自服务端响应。实时百度/AI 凭据、配额和前端播放需要单独 smoke 验证。

百度服务端 AK/SK 只在后端配置，业务接口不接受 `ak`、`sk` 或其他 Provider 凭据字段；后端调用百度时才把服务端 AK 加入 Provider 请求。生产环境应使用 Secret Manager 等运行时密钥管理服务，不要把真实值写入源码、`.env.example` 或日志。

## 配置

复制 `.env.example` 为 `.env` 后，可以配置：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LUMIVO_APP_NAME` | `Lumivo Backend` | 应用名称 |
| `LUMIVO_ENVIRONMENT` | `development` | 运行环境名称 |
| `LUMIVO_PROVIDER_MODE` | `fixture` | `fixture`、`map-real` 或 `full-real` |
| `LUMIVO_FRONTEND_ORIGIN` | `http://localhost:8989` | CORS 允许的前端地址 |
| `LUMIVO_BAIDU_MAP_AK` | 空 | 百度地图服务端 AK；真实模式必填 |
| `LUMIVO_BAIDU_MAP_SK` | 空 | 百度地图服务端 SK；启用 SN 校验时填写 |
| `LUMIVO_BAIDU_VECTOR_TILE_AK` | 空 | 后端使用的百度浏览器端 AK；只用于矢量瓦片，不发送给浏览器 |
| `LUMIVO_MAP_BASE_URL` | `https://api.map.baidu.com` | 百度地图服务地址 |
| `LUMIVO_BAIDU_VECTOR_TILE_BASE_URL` | `https://apimaponline0.bdimg.com` | 百度矢量瓦片上游 host；仅后端使用 |
| `LUMIVO_BAIDU_MAP_STATIC_BASE_URL` | `https://maponline0.bdimg.com` | 百度地图静态样式上游 host；仅后端使用 |
| `LUMIVO_MAP_TIMEOUT_MS` | `10000` | 百度地图请求超时毫秒数 |
| `AI_BASE_URL` | `https://api.deepseek.com` | OpenAI-compatible 服务地址 |
| `AI_API_KEY` | 空 | AI 服务密钥；也兼容 `DEEPSEEK_API_KEY` |
| `AI_MODEL` | `deepseek-chat` | 模型名称 |
| `AI_TIMEOUT_MS` | `30000` | AI 请求超时毫秒数 |

## 设计与开发规则

- [CONTEXT.md](./CONTEXT.md)：当前范围、决策和开发顺序
- [AGENTS.md](./AGENTS.md)：后端开发规则
- [后端架构设计](./docs/superpowers/specs/2026-08-18-lumivo-backend-design.md)：模块、接口、数据流、错误和测试设计
