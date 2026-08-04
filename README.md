# SynthDraft

AI 驱动工程设计辅助系统 —— 提供智能审图与智能生成两大核心能力，面向机械工程设计领域，支持私有化部署。

## 项目状态

**当前阶段：P0-P2 全部完成 + 多轮质量优化（V2-V4 验证、LLM 幻觉优化、前端 polish、CodeRabbit 全方位审查 0 issues）+ 全文件类型支持（7 种格式端到端验证通过）+ AI Provider 统一配置 + 知识库检索验证（bge-m3 + sentence-transformers 双模型）**

> 阶段门控铁律：每个阶段（P0/P1/P2）完成后均经自检 + 全面深入测试 + 阶段审核报告 + 用户书面批准。详见 `.trae/specs/ai-engineering-design-assistant/` 下各阶段 GATE 报告。

## 核心功能

- **智能审图**：支持 7 种文件类型端到端审图（PDF / DWG / image / STEP / IGES / SLDPRT / SLDASM），AI 自动审查是否符合国标规范，输出合规性评分、缺陷列表、定位标注与修改建议。
- **智能生成**：根据自然语言描述或手绘草图，生成可编辑的 CadQuery 参数化建模代码，并产出 DXF / STEP / IGES / STL / SLDPRT 等文件。
- **知识库检索**：基于国标 GB/T 标准的 RAG 检索（bge-m3 嵌入 + Qdrant 向量库），关键结论强制引用规范原文条款编号，杜绝 LLM 幻觉。
- **SolidWorks 集成**：Windows 端 SolidWorks 插件（C# Add-in），支持在 SolidWorks 内直接触发审图/生成，并产出 SLDPRT/SLDASM 原生文件。
- **多模态理解**：图纸图像 OCR + VLM 理解（YOLOv11 区域检测 + PaddleOCR 区域受限 OCR + VLM 语义解析），覆盖"感知 → 语义 → 工程语义"四层认知框架。
- **审图-生成协同闭环**：审图缺陷一键转生成 prompt → 生成修订图纸 → 自动复审 → 缺陷 diff 报告。
- **AI Provider 统一配置**：所有 AI provider（本地 Ollama / OpenAI 兼容 / Anthropic）使用统一 5 字段配置模型，通过前端 `/settings` 页面即可完成全部配置与运行时热切换，API key 加密存储，无需编辑 `.env`。

## 技术栈

| 层 | 选型 | 版本（已查询确认） |
|---|---|---|
| **后端 Web 框架** | FastAPI | 0.140.0 |
| ASGI 服务器 | Uvicorn | 0.51.0 |
| 任务队列 | Celery | 5.6.3 |
| 数据校验 | Pydantic | 2.13.4 |
| 关系数据库 | PostgreSQL | 16-alpine |
| 缓存 / 队列 | Redis | 7-alpine |
| 向量库 | Qdrant | v1.18.3 |
| 对象存储 | MinIO | RELEASE.2025-09-07T16-13-09Z |
| 高性能推理 | vLLM | v0.25.0（可选，profile=gpu） |
| 可观测性 | OpenTelemetry + structlog | 1.44.0 / 26.1.0 |
| **前端框架** | Next.js | 14.2.35 |
| UI 库 | React + TypeScript | 18 / 5.x |
| 样式 | Tailwind CSS | 3.4.1 |
| 组件库 | shadcn/ui（Radix UI）+ lucide-react + sonner | - |
| **SolidWorks Add-in** | C# .NET Framework | 4.8 |
| **AI / ML** | CadQuery | 2.8.0 |
| 目标检测 | YOLOv11（ultralytics） | 8.4.108 |
| OCR | PaddleOCR | 3.7.0 |
| Embedding | bge-m3（FlagEmbedding）+ sentence-transformers（回退） | 1.3.3 / 5.6.0 |
| CAD 解析 | ezdxf + ODA File Converter + pythonOCC + FreeCAD | 1.4.4 |

## 架构说明

系统采用 **Linux AI 服务 + Windows SolidWorks Worker** 的跨平台解耦架构，两端通过 Redis / Celery 消息队列通信：

- **Linux 端**：AI 服务（FastAPI 后端 + Celery Worker）+ 基础设施（PostgreSQL / Redis / Qdrant / MinIO）。无状态、可水平扩展。LLM/VLM 通过 OpenAI 兼容 API（DeepSeek / 通义千问 / 智谱 GLM 等）接入，无需本地 Ollama。
- **Windows 端**：SolidWorks Worker（win32com COM 自动化，单并发）+ SolidWorks Add-in 插件（C# .NET 4.8）。有状态，受许可证限制。

```
┌───────────────────────────── Linux 节点 ─────────────────────────────┐
│                                                                       │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐   │
│   │  Next.js Web │◄──►│   FastAPI    │───►│   Celery Worker      │   │
│   │  (frontend)  │ WS │  后端 (API)  │    │ reviews/generations/ │   │
│   └──────────────┘    └──────┬───────┘    │ sketch/assembly/coll │   │
│                              │            └──────────┬───────────┘   │
│                              │                       │               │
│   ┌────────────┐  ┌──────────┴────┐  ┌──────────────┴──────────┐    │
│   │ PostgreSQL │  │     Redis     │  │  Qdrant │ MinIO          │    │
│   │     16     │  │ 7 (broker)    │  │ 向量库  │ 存储           │    │
│   └────────────┘  └──────┬────────┘  └─────────────────────────┘    │
│                          │ broker                                    │
└──────────────────────────┼──────────────────────────────────────────┘
                           │ Celery 队列（solidworks）
                           ▼
┌──────────────────────── Windows 节点 ───────────────────────────────┐
│   ┌─────────────────────┐    ┌──────────────────────────────────┐   │
│   │ SolidWorks Worker   │───►│  SolidWorks 实例（win32com COM） │   │
│   │ -Q solidworks -c 1  │    │  读/写 SLDPRT / SLDASM           │   │
│   └─────────────────────┘    └──────────────────────────────────┘   │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │  SolidWorks Add-in（C# .NET 4.8）— 工程师在 SolidWorks 内触发 │  │
│   └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## 目录结构

```
SynthDraft/
├── backend/              # FastAPI 后端 + Celery Worker（已实现）
│   ├── app/
│   │   ├── api/v1/endpoints/  # REST 端点（11 个文件，27 条路径）
│   │   ├── celery/            # Celery 任务（reviews/generations/solidworks/sketch/assembly/collaboration）
│   │   ├── schemas/           # Pydantic 模型
│   │   ├── services/          # 8 大业务服务（review/generation/solidworks/assembly/collaboration/kb/cad/ai）
│   │   ├── observability/     # tracing / queue_monitor / llm_metrics / alerts
│   │   ├── config.py          # 配置加载
│   │   ├── database.py        # SQLAlchemy 异步引擎
│   │   ├── logging.py         # structlog 配置
│   │   ├── tracing.py         # OpenTelemetry 配置
│   │   ├── celery_app.py      # Celery 实例 + 6 条队列路由
│   │   └── main.py            # FastAPI 入口
│   ├── tests/                 # 集成与验证脚本
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/             # Next.js Web 控制台（已实现）
│   ├── src/
│   │   ├── app/               # App Router 页面（/ /review /generate /kb /settings）
│   │   ├── components/        # 业务组件 + shadcn/ui 组件
│   │   └── lib/               # api / ws / utils / types
│   ├── package.json
│   └── tailwind.config.ts
├── solidworks_addin/     # SolidWorks C# 插件（已实现）
│   ├── SynthDraftAddIn.csproj # .NET Framework 4.8
│   ├── SynthDraftAddIn.cs     # 插件主入口
│   ├── BackendClient.cs       # 后端 API 客户端
│   ├── install.ps1 / uninstall.ps1 / build.ps1
│   └── version.json
├── kb/                   # 国标知识库与构建工具（已实现）
│   ├── standards/             # GB/T 国标 Markdown 条文（1182/4457.4/17450/1804/131/18229）
│   └── tools/                 # 条文抽取工具（extract_clauses.py）
├── infra/                # 基础设施配置（已实现）
│   ├── docker-compose.yml     # 9 个服务编排
│   ├── .env.example
│   ├── init.sql
│   ├── otel-collector-config.yaml
│   ├── observability/         # Grafana / Prometheus / Tempo
│   └── offline_install/       # 离线部署包构建工具
├── docs/                 # 项目文档（已实现）
│   ├── architecture.md        # 架构设计文档
│   ├── api.md / deployment.md / operations.md / user_manual.md
└── .trae/specs/          # 项目规格文档
    └── ai-engineering-design-assistant/  # spec.md / tasks.md / checklist.md / 各阶段 GATE 报告
```

## 快速开始

### 前置要求

- Docker Desktop 4.30+（含 Docker Compose v2）
- Python 3.11+（本地非容器开发时需要，推荐 3.13）
- Node.js 18+（前端开发时需要）
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
2. 启动所有基础设施服务（PostgreSQL / Redis / Qdrant / MinIO）
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

## 关键端点

### 后端 API（33 条路径）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 服务信息 |
| GET | `/api/v1/healthz` | 存活探针 |
| GET | `/api/v1/readyz` | 就绪探针（探测 PG/Redis） |
| GET, POST | `/api/v1/uploads` | 文件上传 |
| POST | `/api/v1/reviews` | 提交审图任务 |
| GET | `/api/v1/reviews/{task_id}/report` | 获取审图报告 |
| GET | `/api/v1/reviews/{task_id}/result` | 获取审图结果 |
| POST | `/api/v1/generations` | 提交生成任务 |
| POST | `/api/v1/generations/execute` | 同步执行生成 |
| GET | `/api/v1/generations/files/{file_path}` | 下载生成产物 |
| GET | `/api/v1/generations/{task_id}/result` | 获取生成结果 |
| POST | `/api/v1/sketches` | 草图转 CAD |
| POST | `/api/v1/sketches/calibrate` | 草图校准 |
| GET | `/api/v1/sketches/{task_id}/result` | 获取草图任务结果 |
| POST | `/api/v1/collaboration/optimize-from-review` | 审图缺陷一键转生成 |
| GET | `/api/v1/collaboration/optimize-result/{task_id}` | 获取协同优化结果 |
| GET | `/api/v1/collaboration/diff-report/{old}/{new}` | 缺陷 diff 报告 |
| POST | `/api/v1/collaboration/feedback` | 提交反馈（误报/采纳） |
| GET | `/api/v1/kb/clauses` | 知识库条文检索 |
| GET | `/api/v1/kb/standards` | 已索引规范列表 |
| POST | `/api/v1/kb/reindex` | 重建知识库索引 |
| GET | `/api/v1/ai/config` | 获取 AI 配置列表（api_key 脱敏） |
| POST | `/api/v1/ai/config` | 新增 AI 配置（api_key 加密存储） |
| PUT | `/api/v1/ai/config/{id}` | 更新 AI 配置 |
| DELETE | `/api/v1/ai/config/{id}` | 删除 AI 配置 |
| POST | `/api/v1/ai/config/{id}/activate` | 激活 AI 配置（运行时热切换） |
| POST | `/api/v1/ai/config/{id}/test` | 测试 AI 配置连接（文本+视觉模型） |
| GET | `/api/v1/tasks/{task_id}` | 查询任务状态 |
| POST | `/api/v1/tasks/{task_id}/cancel` | 取消任务 |
| WS | `/api/v1/ws/tasks/{task_id}` | 订阅任务进度 |

### 前端页面（Next.js App Router）

| 路径 | 说明 |
|---|---|
| `/` | 首页（项目概览与导航） |
| `/review` | 智能审图工作台（上传图纸 / 查看评分 / 缺陷列表 / 报告） |
| `/generate` | 智能生成工作台（自然语言 → CadQuery 代码 → 产物下载） |
| `/kb` | 知识库检索（国标条文搜索 + 规范列表） |
| `/settings` | AI Provider 配置管理（新增/编辑/测试/激活配置，运行时热切换） |

## AI Provider 配置

系统采用统一的 AI Provider 配置模型，所有 provider（本地或远程）使用相同的 5 字段结构：`provider_type` / `base_url` / `api_key` / `model` / `vlm_model`。

**推荐配置方式**：通过前端 `/settings` 页面（http://localhost:3000/settings）完成全部配置，支持新增/编辑/测试连接/激活，激活后运行时热切换生效，无需重启服务。API key 经 Fernet 加密存储于数据库，接口返回时脱敏。

**首次启动自动迁移**：应用首次启动且数据库无 provider 配置时，会自动从 `.env` 的 `LLM_PROVIDER` / `OPENAI_*` / `ANTHROPIC_*` / `OLLAMA_*` 字段迁移为一条数据库记录。后续配置变更以数据库为准，修改 `.env` 不影响已迁移的运行时配置。

**支持的 provider 类型**：

| provider_type | 适用场景 | base_url 示例 |
|---|---|---|
| `ollama` | 本地 Ollama 推理（需自行安装 Ollama，api_key 留空） | `http://localhost:11434` |
| `openai_compatible` | OpenAI 官方 / DeepSeek / 通义千问 / 智谱 / vLLM 等 OpenAI 兼容 API（**推荐**） | `https://api.openai.com/v1`、`https://api.deepseek.com/v1` |
| `anthropic` | Anthropic Claude | `https://api.anthropic.com` |

> **注**：默认不再捆绑 Ollama Docker 服务。如需本地推理，请自行安装 [Ollama](https://ollama.com/) 并通过 `/settings` 页面配置。推荐使用 OpenAI 兼容 API（如通义千问 / DeepSeek）以获得更稳定的推理质量。

> 配置 API 亦可通过 `GET/POST/PUT/DELETE /api/v1/ai/config` 及 `POST /api/v1/ai/config/{id}/activate`、`POST /api/v1/ai/config/{id}/test` 端点编程访问。

## 本地开发（非容器）

### 后端

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\Activate.ps1
# Linux
source .venv/bin/activate

pip install -r requirements.txt
# 需要先启动 PostgreSQL/Redis 等依赖（可仅 docker compose up postgres redis qdrant minio）
uvicorn app.main:app --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 http://localhost:3000，通过 `NEXT_PUBLIC_API_BASE_URL` 环境变量指向后端（默认 http://localhost:8000）。

### SolidWorks Worker（仅 Windows + 已装 SolidWorks）

```powershell
cd backend
celery -A app.celery_app worker --loglevel=info --concurrency=1 -Q solidworks --without-gossip
```

## Spec 与任务

> **注**：`.trae/specs/` 目录仅保留在本地，不入库 GitHub。如需查看 spec 文档，请在本地项目目录下阅读。

详见 `.trae/specs/ai-engineering-design-assistant/`：
- `spec.md`：项目规格说明
- `tasks.md`：任务清单（P0/P1/P2 分阶段）
- `checklist.md`：验收检查清单
- `P0_GATE_*` / `P1_GATE_REPORT.md` / `P2_GATE_*.md`：各阶段门控审核报告

其他迭代规格位于 `.trae/specs/` 下（V2-V4 验证、LLM 幻觉优化、前端 polish、CodeRabbit 全方位审查、全文件类型支持、AI Provider 统一配置等）。

## 许可证

本项目采用 MIT 许可证，详见 [LICENSE](LICENSE)。

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
