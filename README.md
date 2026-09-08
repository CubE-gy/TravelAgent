# TravelAgent V1

TravelAgent V1 是一个旅行路线规划 Agent。它面向已经有目的地、酒店、景点或交通意向的用户，逐步整合旅行信息，并基于真实地图事实生成、展示和调整可执行路线。

当前已完成 **Stage 3：门到门公共交通完整闭环**，正在开发 **Stage 4：地图旅行工作台**。Stage 4 以本次确认的地图工作台范围为准：通过连续对话整理地点，在真实地图上建立空间认知；不自动分天、分组、排序或推荐路线。本小步完成不代表 Stage 4 已通过阶段验收。

## 当前能力

- `GET /health`：服务存活检查。
- `POST /trips`：创建并持久化一趟旅行。
- `GET /trips`：读取全部已保存旅行，最近更新的排在前面。
- `GET /trips/{trip_id}`：读取指定旅行。
- `GET /trips/{trip_id}/workspace`：读取地图工作台所需的 Trip、TripState 与已保存公共交通计划。
- `PATCH /trips/{trip_id}`：修改旅行名称或日期。
- `POST /trips/conversations`：通过首条自然语言消息创建 Trip 与 `TripState`。
- `POST /trips/{trip_id}/messages`：向既有 Trip 发送一条自然语言补充或修改消息。
- `POST /trips/{trip_id}/locations/confirm`：确认此前返回的一个歧义地点候选。
- `POST /trips/{trip_id}/public-transport-plan`：生成并保存一份完整的门到门公共交通计划。
- `GET /trips/{trip_id}/public-transport-plan`：读取已保存的公共交通计划，不重新查询路线。
- 校验旅行名称、日期范围、地点坐标和车辆基础数据。
- 使用独立的 PostgreSQL 开发库与测试库。
- 使用 Alembic 管理数据库表结构版本。
- 使用 pytest 覆盖配置、模型、API、数据库连接、迁移和真实持久化流程。
- 通过 `AmapApiService` 提供统一的地图事实入口：POI 搜索、标准地点确认、周边 POI、加油站、充电站、驾车路线和同城市内公共交通路线。
- 将高德 V5 原始响应转换为项目内部 `PoiCandidate`、`ResolvedLocation`、`Route`、`RouteSegment` 与 `Polyline` 模型。
- 将 Key 缺失、超时、HTTP `429` 或高德配额/限流 `infocode`、上游异常、无结果等情况转换为可预测的项目内部错误；不会记录 API Key 或原始响应正文。
- 支持驾车、步行、公交、地铁、铁路分段及其可用的 Polyline；不对路线做业务决策。
- 使用 LLM 将每条自然语言消息提取为显式的 `TripState` 增量，并只修改用户本轮明确提及的字段。
- 持久化出发地、目的地、返程地、日期、住宿、景点、城际/市内交通和车辆等 `TripState` 信息；未提及字段会继续保留。
- 对城市使用高德行政区域查询，独立保存 `resolved_city`（名称、行政区编码、城市编码、中心点）；城市中心只用于地图视野，不能作为具体车站、酒店或门到门路线端点。
- 对具体地点按已确定的目的地城市搜索高德 POI，结合名称、类型和景点主体匹配自动选点，并通过 POI 详情确认真实坐标；同名门店或弱匹配保留待补充状态，通过对话询问线索。查询失败保留用户输入，不生成虚构标记。
- 由 Python 确定缺失字段与地点确认需求，再由 LLM 生成简洁中文补问；LLM 的补问结果与需求不一致会被拒绝。
- 一次对话的状态更新、日期投影与补问生成以同一事务处理；补问或上游调用失败时回滚，避免出现失败响应却已保存状态的情况。
- `TripState` 是规划日期的唯一事实来源；`Trip.start_date/end_date` 是兼容 Stage 0 API 的镜像字段，日期 PATCH 会在同一事务中同步两者。
- LLM 配置缺失返回安全的 `503 Service Unavailable` 响应，不向客户端泄露 Key、模型名或上游配置细节。
- 公共交通计划要求 `TripState` 的出发地、目的地、返程目的地、住宿、每日景点和日期均已确认；每日 `day_number` 必须落在出发日至返程日的范围内，但可保留没有景点的休息日。
- 城际车站或机场请求只接收高德 `poi_id`，后端会通过 Stage 1 重新标准化地点；会校验出发地、目标城市、住宿、景点和返程节点的城市一致性。
- 城际车次、时长等信息是用户确认的事实；本阶段不做实时查票、票价比较或交通方式推荐。任何一段市内路线没有结果时，不会保存半截计划。

## Agent 上下文入口

决策与工具后回复共用 `agent_context_builder.py`：稳定规则、应用事实快照、
按原始角色排列的近期对话、最后一条当前请求分别传入模型。历史按连续的完整可用轮次
保留，上限为 10 条消息和 8000 字符（这是字符限制，不是精确 token 限制）。
前端不会把发送失败的消息作为已完成对话再次传入。

提取服务不再按“酒店、去、住”等关键词触发重试。仅当模型返回既没有操作、
也没有有效回复的空状态决策时，保留原上下文进行一次结构性重试。
直接回复必须包含正文；推荐工具调用允许没有预先编写的回复，实际回复在查询后生成。
模型决策失败时明确说明尚未理解、本次未修改，不再用住宿等缺失字段补问冒充当前请求的回答。

真实上下文决策测试（显式调用已配置模型，不调用地图、不写数据库）：

```powershell
.\.venv\Scripts\python.exe -B -m pytest -o addopts= -q tests/services/test_agent_context_real_smoke.py
```

这些场景检查推荐省略表达、修改、取消和话题切换，不代表整套地图对话已验收。
本步未变更地图工具与持久化流程。

本步验证：默认后端测试 372 项通过，前端 33 项通过且构建成功。
真实模型 8 个决策场景均获得通过结果，其中 1 项因读取超时单独重试后通过。
这是决策层 Smoke Test，不是完整地图业务或模型稳定性验收；本轮未执行数据库集成测试。

## 技术栈

- Python 3.12+
- FastAPI + Uvicorn
- Pydantic Settings
- PostgreSQL 16
- SQLAlchemy 2.x + Psycopg 3
- Alembic
- pytest + HTTPX
- Docker Compose（仅用于本地 PostgreSQL）

## 本地启动

以下命令以 Windows PowerShell 为例。

### 1. 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### 2. 配置环境变量

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，为开发库和测试库设置密码。`TRAVEL_AGENT_DEV_DB_PASSWORD`、`TRAVEL_AGENT_TEST_DB_PASSWORD` 必须分别与 `DATABASE_URL`、`TEST_DATABASE_URL` 中的密码保持一致。

如需调用真实高德服务或运行地图 Smoke Test，再设置 `AMAP_WEB_API_KEY`。该 Key 必须在高德控制台创建为“Web服务”类型。

`.env` 包含本地密钥和密码，已被 `.gitignore` 排除，不要提交到 Git。

### 3. 启动 PostgreSQL

```powershell
docker compose up -d postgres-dev postgres-test
docker compose ps
```

开发库监听 `127.0.0.1:5434`，测试库监听 `127.0.0.1:5435`。

### 4. 执行数据库迁移

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

### 5. 启动 API

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

服务默认地址为 `http://127.0.0.1:8000`，交互式 API 文档位于 `http://127.0.0.1:8000/docs`。

## API 示例

### 健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

预期结果：

```json
{"status":"ok"}
```

### 创建、读取和更新 Trip

```powershell
$trip = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/trips `
  -ContentType "application/json" `
  -Body '{"name":"北京五日游","start_date":"2026-10-01","end_date":"2026-10-05"}'

$trip
Invoke-RestMethod "http://127.0.0.1:8000/trips/$($trip.id)"

Invoke-RestMethod `
  -Method Patch `
  -Uri "http://127.0.0.1:8000/trips/$($trip.id)" `
  -ContentType "application/json" `
  -Body '{"name":"更新后的北京五日游","end_date":"2026-10-06"}'
```

`POST /trips` 成功时返回 `201 Created`。不存在的 Trip 返回 `404`；空名称、空更新或无效日期范围返回 `422`。

### 读取地图工作台

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/trips/<trip_id>/workspace"
```

响应一次返回 `trip`、`state` 和 `public_transport_plan`。尚未创建 `TripState` 或尚未生成公共交通计划时，相应字段为 `null`；仅在 Trip 不存在时返回 `404`。公共交通计划存在时附带 `stale`，表示它是否基于当前 `TripState` revision。

### 通过对话创建和更新 TripState

```powershell
$conversation = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/trips/conversations `
  -ContentType "application/json" `
  -Body '{"message":"2026年10月1日从南京去北京，3日回南京，住王府井附近，想去故宫，坐高铁。"}'

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/trips/$($conversation.trip.id)/messages" `
  -ContentType "application/json" `
  -Body '{"message":"酒店改到国贸附近，城际改坐飞机，景点只保留故宫。"}'
```

响应包含当前 `state`、地点解析失败信息、完整性 `assessment` 与下一轮 `clarification`。地图工作台不要求先填齐日期、交通方式等规划信息。明确的城市和可可靠匹配的 POI 自动确认；仍有歧义时通过对话补充线索。原 `POST /trips/{trip_id}/locations/confirm` 接口继续支持显式候选确认，但工作台不默认展示候选选择题。

## Stage 4 对话地图工作台

前端位于 `web/`，使用 React、TypeScript、Vite、Tailwind CSS 和现有 shadcn/ui Button。桌面端左半为连续对话与输入框，右半为高德 JS API 2.0 地图和可展开的地点清单；窄屏上下排列。

在 `web/.env.local` 配置 `VITE_API_BASE_URL`、`VITE_AMAP_JS_API_KEY` 和 `VITE_AMAP_SECURITY_JS_CODE`（参考 `web/.env.example`）。前端使用 JS API Key，后端使用 Web 服务 Key。

```powershell
cd web
npm install
npm run dev
```

打开 `http://localhost:5173` 可查看已保存的旅行；点击任一旅行继续它的对话地图工作台，或点击“新旅行”开始新的对话。后端默认允许此来源；如果改用 `127.0.0.1` 或其他端口，需要在 `FRONTEND_ORIGINS` 中配置对应的完整来源地址。

验收路径：先输入“我想去南京”，应定位南京城市范围；再输入“我还想去中山陵”，应自动显示景点主体标记。若输入“我从北京坐高铁去，在市内乘公共交通游玩”，系统会为北京和南京分别查询高铁站：单一结果自动标记，多站结果在地点清单中展示候选按钮，点击后确认并更新地图。继续添加明确的酒店和车站，展开清单点击地点检查地图联动，再通过对话删除或纠正地点。每轮成功响应直接更新地图；失败时保留原地点和输入，状态冲突时读取最新状态并提示重试。

TripState 持久化在 PostgreSQL；对话气泡保存在当前浏览器标签页的 `sessionStorage`，同标签页刷新可恢复，未提供跨设备对话历史。刷新时仍从后端读取最新地点，不能以缓存消息替代地图事实。普通提问、状态询问和景点推荐请求由 LLM 直接回复，不修改地图事实；当前推荐不接知识库，不会自动添加地点。

```powershell
# 在 web/ 下运行
npm run test
npm run build

# 在项目根目录运行（真实服务测试会消耗少量调用配额）
.\.venv\Scripts\python.exe -m pytest -o addopts="" tests/services/test_workspace_smoke.py
```

### 创建公共交通计划

在 `TripState` 已完整且所有地点均已确认后，提交城际车站/机场的真实高德 POI ID、用户确认的城际事实，以及每天的已确认景点 POI ID：

```powershell
$plan = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/trips/<trip_id>/public-transport-plan" `
  -ContentType "application/json" `
  -Body '{
    "trip_id":"<trip_id>",
    "outbound_intercity":{
      "travel_mode":"high_speed_rail",
      "departure_poi_id":"<outbound_departure_poi_id>",
      "arrival_poi_id":"<outbound_arrival_poi_id>",
      "fact":{"service_identifier":"<user_confirmed_service>","duration_seconds":7200}
    },
    "return_intercity":{
      "travel_mode":"high_speed_rail",
      "departure_poi_id":"<return_departure_poi_id>",
      "arrival_poi_id":"<return_arrival_poi_id>",
      "fact":{"service_identifier":"<user_confirmed_service>","duration_seconds":7200}
    },
    "daily_places":[{"day_number":1,"place_poi_ids":["<TripState_place_poi_id>"]}]
  }'

Invoke-RestMethod "http://127.0.0.1:8000/trips/<trip_id>/public-transport-plan"
```

成功时返回 `201 Created`。路径和 body 中的 `trip_id` 必须一致；城际 POI 会由后端重新解析，且所有市内路段必须能取得真实高德公共交通路线。违反日期、Day、城市一致性或地点确认要求时返回 `422`；Trip 或 TripState 不存在时分别返回 `404`、`409`。

## 地图事实服务

Stage 1 不新增地图 FastAPI 路由。上层 Python 业务通过 `AmapApiService` 取得已经标准化的地图事实，而不读取高德原始 JSON：

```python
from app.core.config import Settings
from app.services import AmapApiService

map_service = AmapApiService(Settings().amap_web_api_key)
candidates = map_service.search_pois("天安门", region="北京")
origin = map_service.resolve_location(candidates[0].poi_id)

destination_candidates = map_service.search_pois("故宫博物院", region="北京")
destination = map_service.resolve_location(destination_candidates[0].poi_id)

driving_route = map_service.get_driving_route(origin, destination)
public_transport_route = map_service.get_local_public_transport_route(
    origin, destination
)
```

市内公共交通要求起点和终点都有相同的高德 `city_code`。这只用于确认请求属于同一城市，并不替代后续阶段的城际/市内业务决策。

## 自动测试

默认命令运行不依赖 PostgreSQL 的测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

启动两个 PostgreSQL 容器后，可以运行数据库集成测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts="" -m integration
```

运行包含集成测试在内的完整测试集：

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts=""
```

集成测试会连接 `.env` 中的开发库和测试库，执行 Alembic 迁移，并验证 Trip 与 TripState 的创建、读取、日期同步、事务回滚、地点确认和 PostgreSQL 真实持久化。

高德真实 Smoke Test 默认不会运行，以避免意外消耗配额。设置 `AMAP_WEB_API_KEY` 后可显式执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts="" -m amap_smoke
```

该测试会用少量真实 V5 请求验证 POI 搜索、地点确认、驾车路线和市内公共交通路线。无 Key 时跳过；不会输出 Key 或响应正文。

该命令还包含 Stage 3 的真实门到门公共交通 Smoke Test：它会检索和标准化真实 POI、生成完整路线骨架，并验证六段市内高德公共交通路线及两段用户确认的城际事实能够正确装配；不会查询实时票务或保存计划。

真实 LLM 验收同样是显式执行的：在 `.env` 设置 `LLM_PROVIDER=real`、`LLM_API_KEY`、`LLM_MODEL`（可选修改 `LLM_BASE_URL`）后运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts="" -m llm_smoke
```

该 Smoke Test 会把真实中文旅行描述交给已配置的 OpenAI-compatible Provider，并验证首次结构化提取，以及对已有状态的组合纠正（更换酒店、改城际交通、删除景点且保留未提及字段）。未设置真实 Provider 凭据时会跳过，且不会输出密钥。

## 项目结构

```text
TravelAgent/
├── app/
│   ├── api/             # FastAPI 路由
│   ├── core/            # 配置管理
│   ├── db/              # SQLAlchemy 引擎与 Session
│   ├── models/          # 数据库模型与枚举
│   ├── repositories/    # 数据访问操作
│   ├── schemas/         # Pydantic 输入/输出模型
│   ├── services/        # 地图事实服务与高德 Web API 封装
│   └── main.py          # FastAPI 应用入口
├── migrations/          # Alembic 迁移脚本
├── tests/               # 单元测试与 PostgreSQL 集成测试
├── .env.example         # 环境变量示例
├── alembic.ini          # Alembic 配置
├── compose.yaml         # 本地开发/测试数据库
└── pyproject.toml       # 项目信息、依赖与 pytest 配置
```

## V1 Stage 路线

| Stage | 业务闭环 |
|---|---|
| 0 | 后端工程骨架 + 数据持久化地基 |
| 1 | 高德地图事实层工程化 |
| 2 | 多轮需求理解 + Trip State Agent |
| 3 | 门到门公共交通完整闭环 |
| 4 | 地图旅行工作台 |
| 5 | 自驾 + 油车/电车补能规划 |
| 6 | 用户修改 + 动态重规划 |
| 7 | 完整产品交互 + 前后端联调 |
| 8 | 系统级质量验证 + 生产加固 |
| 9 | Railway 真实生产上线 |

各 Stage 严格按顺序推进。详细协作方式、边界和交接格式见 [`AGENTS.md`](AGENTS.md)。
