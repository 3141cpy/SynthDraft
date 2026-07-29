# SynthDraft Backend

FastAPI 后端服务 + Celery Worker，提供智能审图与智能生成的 API 入口与异步任务执行。

## 目录结构

```
backend/
├── app/
│   ├── api/
│   │   ├── deps.py                 # 依赖注入（settings/db/logger/user）
│   │   └── v1/
│   │       ├── router.py           # v1 路由聚合
│   │       └── endpoints/
│   │           ├── health.py       # /healthz + /readyz
│   │           ├── reviews.py      # 审图任务提交
│   │           ├── generations.py  # 生成任务提交
│   │           ├── tasks.py        # 任务状态查询/取消
│   │           └── ws.py           # WebSocket 进度推送
│   ├── celery/
│   │   ├── base.py                 # BaseTask（统一日志/异常处理）
│   │   └── tasks/
│   │       ├── reviews.py          # 审图任务（P0 占位）
│   │       └── generations.py      # 生成任务（P0 占位）
│   ├── schemas/
│   │   ├── health.py
│   │   ├── review.py
│   │   ├── generation.py
│   │   └── task.py
│   ├── services/
│   │   └── redis_probe.py          # Redis 探活
│   ├── models/                     # ORM 模型（Task 2+）
│   ├── config.py                   # pydantic-settings 配置
│   ├── database.py                 # SQLAlchemy 异步引擎
│   ├── logging.py                  # structlog 配置
│   ├── security.py                 # JWT + bcrypt
│   ├── tracing.py                  # OpenTelemetry 配置
│   ├── celery_app.py               # Celery 实例
│   ├── main.py                     # FastAPI 入口
│   └── __main__.py                 # python -m app.main
├── Dockerfile
└── requirements.txt
```

## 本地开发

### 1. 创建虚拟环境

```bash
cd backend
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
# 从 infra/.env.example 拷贝并在 backend/ 下创建 .env
# 或直接设置环境变量指向本地服务
```

所需环境变量见 `infra/.env.example`。本地开发时需将 host 从容器名改为 `localhost`。

### 4. 启动依赖服务

```bash
cd ../infra
cp .env.example .env
docker compose --env-file .env up -d postgres redis qdrant minio ollama
```

### 5. 启动 FastAPI

```bash
cd ../backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

或：

```bash
python -m app.main
```

### 6. 启动 Celery Worker（另一终端）

```bash
cd backend
celery -A app.celery_app worker --loglevel=info --concurrency=2 -Q reviews,generations,default
```

## API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 服务信息 |
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc |
| GET | `/openapi.json` | OpenAPI schema |
| GET | `/api/v1/healthz` | 存活探针 |
| GET | `/api/v1/readyz` | 就绪探针（PG/Redis） |
| POST | `/api/v1/reviews` | 提交审图任务 |
| POST | `/api/v1/generations` | 提交生成任务 |
| GET | `/api/v1/tasks/{task_id}` | 查询任务状态 |
| POST | `/api/v1/tasks/{task_id}/cancel` | 取消任务 |
| WS | `/api/v1/ws/tasks/{task_id}` | 任务进度推送 |

## 配置项

所有配置通过环境变量加载，详见 `infra/.env.example`。关键项：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_ENV` | development | 环境 |
| `DATABASE_URL` | postgresql+asyncpg://... | 数据库连接串 |
| `REDIS_URL` | redis://redis:6379/0 | Redis 连接 |
| `CELERY_BROKER_URL` | redis://redis:6379/1 | Celery broker |
| `OTEL_ENABLED` | false | 是否启用 tracing |
| `CORS_ORIGINS` | http://localhost:3000,... | CORS 允许来源 |

## Docker 部署

```bash
cd infra
docker compose --env-file .env up -d backend celery_worker
```

镜像构建：`docker build -t synthdraft-backend ./backend`

## 测试

```bash
cd backend
pytest
```

测试框架：pytest + pytest-asyncio + asgi-lifespan。
