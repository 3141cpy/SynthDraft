# SynthDraft

AI 驱动工程设计辅助系统 —— 提供智能审图与智能生成两大核心能力，面向机械工程设计领域，支持私有化部署。

## 项目状态

**当前阶段：P0（MVP 基础管线打通）**
**已完成：Task 1（项目骨架与基础设施搭建）**

> ⚠️ 阶段门控铁律：P0 阶段全部任务完成后，须经自检 + 全面深入测试 + 阶段审核报告 + 用户书面批准，方可进入 P1。详见 `.trae/specs/ai-engineering-design-assistant/tasks.md`。

## 目录结构

```
SynthDraft/
├── backend/              # FastAPI 后端 + Celery Worker
│   ├── app/
│   │   ├── api/v1/endpoints/  # REST 端点（health/reviews/generations/tasks/ws）
│   │   ├── celery/            # Celery 任务（base/reviews/generations）
│   │   ├── schemas/           # Pydantic 模型
│   │   ├── services/          # 业务服务
│   │   ├── models/            # ORM 模型（Task 2+）
│   │   ├── config.py          # 配置加载
│   │   ├── database.py        # SQLAlchemy 异步引擎
│   │   ├── logging.py         # structlog 配置
│   │   ├── security.py        # JWT 与密码哈希
│   │   ├── tracing.py         # OpenTelemetry 配置
│   │   ├── celery_app.py      # Celery 实例
│   │   └── main.py            # FastAPI 入口
│   ├── Dockerfile
│   └── requirements.txt
├── ai/                   # 多模态理解、LLM 推理、RAG（Task 3+）
├── kb/                   # 工程规范知识库构建工具（Task 3+）
├── frontend/             # React Web 控制台（Task 6+，待创建）
├── solidworks_addin/     # SolidWorks 插件（P1，可选）
├── infra/                # 基础设施配置
│   ├── docker-compose.yml
│   ├── .env.example
│   ├── init.sql
│   └── otel-collector-config.yaml
├── docs/                 # 项目文档
└── .trae/specs/          # Spec 文档（spec.md / tasks.md / checklist.md）
```

## 技术栈

| 层 | 选型 | 版本（已查询确认） |
|---|---|---|
| Web 框架 | FastAPI | 0.140.0 |
| ASGI 服务器 | Uvicorn | 0.51.0 |
| 任务队列 | Celery | 5.6.3 |
| 数据库 | PostgreSQL | 16 |
| 缓存/队列 | Redis | 7 |
| 向量库 | Qdrant | v1.18.3 |
| 对象存储 | MinIO | RELEASE.2025-09-07T16-13-09Z |
| 本地 LLM | Ollama | 0.30.6 |
| 高性能推理 | vLLM | v0.25.0（可选） |
| 可观测性 | OpenTelemetry + structlog | 1.44.0 / 26.1.0 |

## 快速开始

### 前置要求

- Docker Desktop 4.30+（含 Docker Compose v2）
- Python 3.11+（本地非容器开发时需要）
- Git

### 一键启动（Docker Compose）

**Windows PowerShell：**
```powershell
.\start-dev.ps1
```

**Linux / macOS：**
```bash
./start-dev.sh
```

脚本会自动：
1. 检查 `.env` 是否存在，不存在则从 `.env.example` 拷贝
2. 启动所有基础设施服务（PostgreSQL / Redis / Qdrant / MinIO / Ollama）
3. 构建并启动 backend 与 celery_worker
4. 输出各服务访问地址

### 手动启动

```bash
cd infra
cp .env.example .env
docker compose --env-file .env up -d
```

### 验证服务

| 服务 | 地址 | 说明 |
|---|---|---|
| FastAPI 文档 | http://localhost:8000/docs | Swagger UI |
| 健康检查 | http://localhost:8000/api/v1/healthz | 存活探针 |
| 就绪检查 | http://localhost:8000/api/v1/readyz | 依赖探针 |
| MinIO 控制台 | http://localhost:9001 | 用户名/密码见 .env |
| Qdrant 控制台 | http://localhost:6333/dashboard | 向量库 |
| Redis | localhost:6379 | redis-cli 可直连 |

## 本地开发（非容器）

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\Activate.ps1
# Linux
source .venv/bin/activate

pip install -r requirements.txt
# 需要先启动 PostgreSQL/Redis 等依赖（可仅 docker compose up postgres redis qdrant minio ollama）
uvicorn app.main:app --reload
```

## 关键端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 服务信息 |
| GET | `/api/v1/healthz` | 存活探针 |
| GET | `/api/v1/readyz` | 就绪探针（探测 PG/Redis） |
| POST | `/api/v1/reviews` | 提交审图任务 |
| POST | `/api/v1/generations` | 提交生成任务 |
| GET | `/api/v1/tasks/{task_id}` | 查询任务状态 |
| POST | `/api/v1/tasks/{task_id}/cancel` | 取消任务 |
| WS | `/api/v1/ws/tasks/{task_id}` | 订阅任务进度 |

## Spec 与任务

详见 `.trae/specs/ai-engineering-design-assistant/`：
- `spec.md`：项目规格说明
- `tasks.md`：任务清单（P0/P1/P2 分阶段）
- `checklist.md`：验收检查清单

## 八荣八耻原则

本项目严格遵守以下原则（详见 checklist.md）：
- 以瞎猜接口为耻，以认真查询为荣
- 以模糊执行为耻，以寻求确认为荣
- 以臆想业务为耻，以人类确认为荣
- 以创造接口为耻，以复用现有为荣
- 以跳过验证为耻，以主动测试为荣
- 以破坏架构为耻，以遵循规范为荣
- 以假装理解为耻，以诚实无知为荣
- 以盲目修改为耻，以谨慎重构为荣
