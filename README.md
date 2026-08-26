# TravelAgent V1

TravelAgent V1 是一个旅行路线规划 Agent。它面向已经有目的地、酒店、景点或交通意向的用户，逐步整合旅行信息，并基于真实地图事实生成、展示和调整可执行路线。

当前已完成 **Stage 2：多轮需求理解 + Trip State Agent**。项目在 Stage 0 的 FastAPI、PostgreSQL、Alembic 和 Trip 最小 API 地基，以及 Stage 1 的高德地图事实服务之上，支持将自然语言需求持续合并为可持久化的 `TripState`，并对缺失信息生成补问；尚未进入门到门公共交通路线、多日规划、补能规划、正式前端地图或生产部署。

## 当前能力

- `GET /health`：服务存活检查。
- `POST /trips`：创建并持久化一趟旅行。
- `GET /trips/{trip_id}`：读取指定旅行。
- `PATCH /trips/{trip_id}`：修改旅行名称或日期。
- `POST /trips/conversations`：通过首条自然语言消息创建 Trip 与 `TripState`。
- `POST /trips/{trip_id}/messages`：向既有 Trip 发送一条自然语言补充或修改消息。
- `POST /trips/{trip_id}/locations/confirm`：确认此前返回的一个歧义地点候选。
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
- 对地点执行高德标准化：成功时保存确认地点，歧义时返回候选项供用户确认，地图查询失败时保留原始输入并返回可理解的失败信息。
- 由 Python 确定缺失字段与地点确认需求，再由 LLM 生成简洁中文补问；LLM 的补问结果与需求不一致会被拒绝。
- 一次对话的状态更新、日期投影与补问生成以同一事务处理；补问或上游调用失败时回滚，避免出现失败响应却已保存状态的情况。
- `TripState` 是规划日期的唯一事实来源；`Trip.start_date/end_date` 是兼容 Stage 0 API 的镜像字段，日期 PATCH 会在同一事务中同步两者。
- LLM 配置缺失返回安全的 `503 Service Unavailable` 响应，不向客户端泄露 Key、模型名或上游配置细节。

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

响应包含当前 `state`、地点解析失败信息、完整性 `assessment` 与下一轮 `clarification`。当地点存在多个候选项时，使用 `POST /trips/{trip_id}/locations/confirm` 提交候选 `poi_id`，而不是让系统重新猜测地点。

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
| 4 | 多日地点规划引擎 |
| 5 | 自驾 + 油车/电车补能规划 |
| 6 | 用户修改 + 动态重规划 |
| 7 | 完整产品交互 + 前后端联调 |
| 8 | 系统级质量验证 + 生产加固 |
| 9 | Railway 真实生产上线 |

各 Stage 严格按顺序推进。详细协作方式、边界和交接格式见 [`AGENTS.md`](AGENTS.md)。
