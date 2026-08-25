# TravelAgent V1

TravelAgent V1 是一个旅行路线规划 Agent。它面向已经有目的地、酒店、景点或交通意向的用户，逐步整合旅行信息，并基于真实地图事实生成、展示和调整可执行路线。

当前仓库处于 **Stage 0：后端工程骨架 + 数据持久化地基**。现有代码提供 FastAPI 服务、PostgreSQL 开发/测试数据库、Alembic 迁移、Trip 最小 API 和自动测试；尚未接入前端、高德地图、LLM 或生产部署。

## 当前能力

- `GET /health`：服务存活检查。
- `POST /trips`：创建并持久化一趟旅行。
- `GET /trips/{trip_id}`：读取指定旅行。
- `PATCH /trips/{trip_id}`：修改旅行名称或日期。
- 校验旅行名称、日期范围、地点坐标和车辆基础数据。
- 使用独立的 PostgreSQL 开发库与测试库。
- 使用 Alembic 管理数据库表结构版本。
- 使用 pytest 覆盖配置、模型、API、数据库连接、迁移和真实持久化流程。

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
