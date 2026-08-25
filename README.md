# TravelAgent V1

TravelAgent V1 是一个旅行路线规划 Agent。它面向已经有目的地、酒店、景点或交通意向的用户，逐步整合旅行信息，并基于真实地图事实生成、展示和调整可执行路线。

当前已完成 **Stage 1：高德地图事实层工程化**。项目在 Stage 0 的 FastAPI、PostgreSQL、Alembic 和 Trip 最小 API 地基之上，增加了可测试、可替换的高德 Web API 地图事实服务；尚未接入 LLM、行程编排、正式前端地图或生产部署。

## 当前能力

- `GET /health`：服务存活检查。
- `POST /trips`：创建并持久化一趟旅行。
- `GET /trips/{trip_id}`：读取指定旅行。
- `PATCH /trips/{trip_id}`：修改旅行名称或日期。
- 校验旅行名称、日期范围、地点坐标和车辆基础数据。
- 使用独立的 PostgreSQL 开发库与测试库。
- 使用 Alembic 管理数据库表结构版本。
- 使用 pytest 覆盖配置、模型、API、数据库连接、迁移和真实持久化流程。
- 通过 `AmapApiService` 提供统一的地图事实入口：POI 搜索、标准地点确认、周边 POI、加油站、充电站、驾车路线和同城市内公共交通路线。
- 将高德 V5 原始响应转换为项目内部 `PoiCandidate`、`ResolvedLocation`、`Route`、`RouteSegment` 与 `Polyline` 模型。
- 将 Key 缺失、超时、HTTP `429` 或高德配额/限流 `infocode`、上游异常、无结果等情况转换为可预测的项目内部错误；不会记录 API Key 或原始响应正文。
- 支持驾车、步行、公交、地铁、铁路分段及其可用的 Polyline；不对路线做业务决策。

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

集成测试会连接 `.env` 中的开发库和测试库，执行 Alembic 迁移，并验证 Trip 的创建、读取、更新和 PostgreSQL 真实持久化。

高德真实 Smoke Test 默认不会运行，以避免意外消耗配额。设置 `AMAP_WEB_API_KEY` 后可显式执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts="" -m amap_smoke
```

该测试会用少量真实 V5 请求验证 POI 搜索、地点确认、驾车路线和市内公共交通路线。无 Key 时跳过；不会输出 Key 或响应正文。

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
