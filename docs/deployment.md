# AI 驱动工程设计辅助系统 — 部署手册

> 文档版本：v1.0
> 编写日期：2026-07-27
> 适用阶段：阶段三（P2）Task 18.3 部署交付
> 信息来源：实际代码与配置文件（见末尾"信息来源"），所有端口、镜像 tag、命令均基于实际文件读取

---

## 0. 部署模式选型

| 维度 | A. 私有化部署（默认推荐） | B. 云部署（轻量试用） |
|---|---|---|
| 数据出域 | 否（全部本地） | 是（数据库/对象存储上云） |
| SolidWorks Worker | Windows 节点内网部署 | Windows 节点内网部署（不可上云） |
| LLM 推理 | Ollama / vLLM 本地 | 商业 API（OpenAI/Anthropic）或 vLLM GPU 实例 |
| 离线安装 | 支持（tar 包 + wheels） | 不支持（依赖公网） |
| 适用场景 | 涉密图纸、合规要求高 | 快速 POC、试用评估 |

**架构总览**（来源：`docs/architecture.md` §2.2）：

```
┌─────────────────────┐       ┌──────────────────────────────────────────┐
│  用户浏览器          │       │  Linux AI 服务节点（Docker Compose）       │
│  Next.js 14 Web UI  │◀─────▶│  ┌────────┐ ┌────────┐ ┌──────────┐      │
└─────────────────────┘ HTTPS │  │FastAPI │ │Celery  │ │Celery Beat│      │
                            │  │ :8000  │ │Worker  │ │ (可选)    │      │
                            │  └───┬────┘ └───┬────┘ └────┬─────┘      │
                            │      │          │           │            │
                            │  ┌───▼──────────▼───────────▼───┐        │
                            │  │ Redis 7 (broker/backend/pubsub)│        │
                            │  └──────────────────────────────┘        │
                            │  ┌────────────┐ ┌────────┐ ┌──────────┐  │
                            │  │PostgreSQL16│ │Qdrant  │ │ MinIO    │  │
                            │  │ :5433      │ │ :6333  │ │ :9000    │  │
                            │  └────────────┘ └────────┘ └──────────┘  │
                            │  ┌────────────┐ ┌────────┐               │
                            │  │Ollama      │ │vLLM    │ (GPU, 可选)   │
                            │  │ :11434     │ │ :8001  │               │
                            │  └────────────┘ └────────┘               │
                            └──────────────┬───────────────────────────┘
                                           │ Redis broker (跨网)
                                           ▼
                            ┌──────────────────────────────────────────┐
                            │ Windows SolidWorks Worker 节点             │
                            │ celery -A app.celery_app worker           │
                            │   -Q solidworks -c 1 --without-gossip    │
                            │ pywin32 + SolidWorks (COM Dispatch)       │
                            └──────────────────────────────────────────┘
```

**端口规划**（均来源：`infra/docker-compose.yml` + `infra/observability/docker-compose.observability.yml`）：

| 服务 | 宿主端口 | 容器端口 | 用途 |
|---|---|---|---|
| PostgreSQL 16 | 5433 | 5432 | 结构化业务数据（宿主 5433 避免冲突） |
| Redis 7 | 6379 | 6379 | broker（DB1）+ result backend（DB2）+ 缓存（DB0）+ pubsub |
| Qdrant v1.18.3 | 6333 / 6334 | 6333 / 6334 | REST API / gRPC（向量检索） |
| MinIO | 9000 / 9001 | 9000 / 9001 | S3 API / Web Console |
| Ollama 0.30.6 | 11434 | 11434 | 本地 LLM/VLM 推理 |
| vLLM v0.25.0 | 8001 | 8000 | GPU 高性能推理（profile: gpu） |
| Backend FastAPI | 8000 | 8000 | API 网关 |
| OTEL Collector | 4317 / 4318 | 4317 / 4318 | OTLP gRPC / HTTP（profile: observability） |
| Grafana 12.2.0 | 3001 | 3000 | 可视化仪表盘 |
| Tempo 2.8.1 | 4318 / 3200 | 4318 / 3200 | OTLP HTTP / Tempo API（注意与 collector 4318 二选一） |
| Prometheus v3.4.0 | 9090 | 9090 | metrics 抓取 |
| Flower 2.0.1 | 5555 | 5555 | Celery 任务监控 UI |
| Frontend Next.js | 3000 | 3000 | Web 控制台（dev/start） |

---

## A. 私有化部署模式（默认推荐）

### A.1 环境要求

#### A.1.1 Linux AI 服务节点

| 项 | 要求 | 来源 |
|---|---|---|
| 操作系统 | Ubuntu 22.04+ / CentOS 8+ | 任务规格 |
| Python | 3.11+ 最低（Dockerfile 基线 `python:3.11-slim`）/ 3.13+ 推荐（`requirements.txt` 注释） | `backend/Dockerfile` L1 + `backend/requirements.txt` L3 |
| Docker | 24+ | 任务规格 |
| Docker Compose | v2（`docker compose` 子命令） | `infra/docker-compose.yml` 语法 |
| GPU（可选） | NVIDIA GPU + CUDA 11.8+ + NVIDIA Container Toolkit | vLLM 启用前置 |
| 内存 | ≥ 16 GB（Ollama CPU 模式 + bge-m3 加载约 4 GB） | 实测估算 |
| 磁盘 | ≥ 100 GB（Docker 镜像 + 模型权重 + MinIO 对象） | 实测估算 |

#### A.1.2 Windows SolidWorks Worker 节点

| 项 | 要求 | 来源 |
|---|---|---|
| 操作系统 | Windows 10/11 或 Windows Server 2022 | 任务规格 |
| SolidWorks | 2022 / 2023 / 2024 / 2025（任一，需激活许可证） | `backend/app/services/solidworks/sw_session.py` 注释（API Help 2025） |
| .NET | 6.0+（SolidWorks 安装通常自带更高版本） | 任务规格 |
| Python | 3.11+ / 3.13+ 推荐（与 Linux 节点对齐，pywin32 cp313 wheel 可用） | `backend/requirements.txt` L91 |
| pywin32 | ≥ 308（`pywin32>=308; sys_platform == "win32"`） | `backend/requirements.txt` L91 |
| 内存 | ≥ 8 GB（SolidWorks 实例 + Worker 进程） | 实测估算 |
| 网络 | 可访问 Redis broker（默认 6379） | 跨网通信前置 |

#### A.1.3 网络隔离部署要求

私有化部署支持**完全离线**运行，无任何外网调用：

- **LLM 推理**：使用本地 Ollama（`LLM_PROVIDER=ollama`），不调用 OpenAI/Anthropic
- **模型权重**：预下载到本地（见 A.7 离线安装包制作）
- **Docker 镜像**：导出为 tar 包离线加载（见 A.7）
- **Python 依赖**：打包为 wheels 离线安装（见 A.7）
- **HuggingFace 镜像**：默认 `HF_ENDPOINT=https://hf-mirror.com`（来源：`backend/app/config.py` L73），离线场景需在预下载阶段完成，运行时不再访问

**网络策略建议**：
- Linux 节点 ↔ Windows 节点：仅放通 Redis 端口（6379）+ MinIO 端口（9000，用于产物回传）
- 用户浏览器 ↔ Linux 节点：放通 HTTPS（443）或 HTTP（8000/3000）
- Linux 节点禁止出站公网

---

### A.2 依赖服务部署

依赖服务通过 `infra/docker-compose.yml` 一键编排（来源：`infra/docker-compose.yml` 全文）。

#### A.2.1 准备环境变量

```bash
cd /opt/synthdraft/infra
cp .env.example .env
```

编辑 `.env`，**生产环境必须修改**以下字段（来源：`infra/.env.example` + `backend/app/config.py`）：

```dotenv
# ===== [SECURE] 生产必须替换 =====
POSTGRES_PASSWORD=<强随机密码>
MINIO_ACCESS_KEY=<强随机用户名>
MINIO_SECRET_KEY=<强随机密码，至少 8 位>
JWT_SECRET_KEY=<openssl rand -hex 32 生成>

# ===== 应用配置 =====
APP_ENV=production
APP_DEBUG=false
LOG_LEVEL=INFO

# ===== 网络（按实际节点 IP 调整）=====
# Windows Worker 需通过此地址访问 Redis
# 若 Windows Worker 与 Redis 不在同一主机，将 host 改为 Linux 节点 IP
REDIS_HOST=<linux-node-ip>
CELERY_BROKER_URL=redis://<linux-node-ip>:6379/1
CELERY_RESULT_BACKEND=redis://<linux-node-ip>:6379/2

# ===== CORS（按前端域名调整）=====
CORS_ORIGINS=https://synthdraft.internal,http://<linux-node-ip>:3000
```

#### A.2.2 启动基础依赖服务

```bash
cd /opt/synthdraft/infra

# 启动基础依赖（不含 backend/celery，后者见 A.3）
docker compose --env-file .env up -d postgres redis qdrant minio ollama
```

启动后验证（来源：`infra/docker-compose.yml` healthcheck 配置）：

```bash
# PostgreSQL（容器内端口 5432，宿主映射 5433）
docker exec synthdraft-postgres pg_isready -U synthdraft -d synthdraft

# Redis
docker exec synthdraft-redis redis-cli ping
# 期望返回：PONG

# Qdrant
curl http://localhost:6333/healthz
# 期望返回：{"title":"Qdrant","status":"ok"}

# MinIO
curl http://localhost:9000/minio/health/live
# 期望返回：200 OK

# Ollama
curl http://localhost:11434/api/tags
# 首次为空，需拉模型（见 A.2.3）
```

#### A.2.3 Ollama 模型下载

来源：`backend/app/config.py` L67-69（默认模型配置）。

```bash
# 进入 Ollama 容器拉取模型
docker exec -it synthdraft-ollama ollama pull qwen2.5-coder:7b
docker exec -it synthdraft-ollama ollama pull qwen2.5:7b
docker exec -it synthdraft-ollama ollama pull nomic-embed-text

# VLM 模型（视觉，审图 OCR 增强用）
docker exec -it synthdraft-ollama ollama pull qwen2.5-vl:7b
```

**说明**：
- `qwen2.5-coder:7b`：默认 LLM 文本模型（`LLM_MODEL`）
- `qwen2.5:7b`：通用文本模型（备选）
- `nomic-embed-text`：Ollama 内置 embedding 备选
- `qwen2.5-vl:7b`：默认 VLM 视觉模型（`VLM_MODEL`）
- `bge-m3`：默认 embedding 模型（`EMBEDDING_MODEL`），**不走 Ollama**，由 `FlagEmbedding==1.3.3` 从 HuggingFace 下载（约 2 GB），首次启动自动拉取，见 A.2.4

#### A.2.4 bge-m3 嵌入模型预下载

来源：`backend/requirements.txt` L41 + `backend/app/config.py` L71-75。

```bash
# 在 Linux 节点（含网络或预下载阶段）执行
# 默认 HF_ENDPOINT=https://hf-mirror.com（中国境内加速）
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DOWNLOAD_TIMEOUT=60

# 进入 backend 虚拟环境（或临时容器）
cd /opt/synthdraft/backend
python -c "from FlagEmbedding import BGEM3Inferencer; m = BGEM3Inferencer(); print('bge-m3 loaded ok')"

# 权重缓存路径：~/.cache/huggingface/hub/
# 离线部署时将此目录打包随安装包分发（见 A.7）
```

#### A.2.5 可选：vLLM GPU 推理加速

来源：`infra/docker-compose.yml` L102-125。

vLLM 通过 `--profile gpu` 启用，需先安装 NVIDIA Container Toolkit：

```bash
# Ubuntu 22.04 安装 nvidia-container-toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/libnvidia-container/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

编辑 `infra/docker-compose.yml`，取消 vLLM 服务的 GPU 配置注释（L110-118）：

```yaml
  vllm:
    image: vllm/vllm-openai:v0.25.0
    runtime: nvidia
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    command: --model Qwen/Qwen2.5-Coder-7B-Instruct --trust-remote-code
```

启动 vLLM：

```bash
docker compose --env-file .env --profile gpu up -d vllm
```

切换 `LLM_PROVIDER`：

```dotenv
# 在 .env 中追加（覆盖默认 ollama）
LLM_PROVIDER=openai
OPENAI_API_KEY=dummy  # vLLM 兼容 OpenAI 协议，但鉴权可空
OPENAI_BASE_URL=http://vllm:8000/v1
OPENAI_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct
```

---

### A.3 后端服务部署

#### A.3.1 FastAPI 后端启动

**方式 A：Docker Compose（推荐，生产）**

来源：`infra/docker-compose.yml` L140-170。

```bash
cd /opt/synthdraft/infra

# 构建镜像（首次或依赖变更时）
docker compose --env-file .env build backend

# 启动 backend（依赖 postgres/redis/qdrant/minio 健康检查通过后自动启动）
docker compose --env-file .env up -d backend
```

容器内启动命令（开发模式带 `--reload`，生产应移除）：

```
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**生产环境建议**：编辑 `infra/docker-compose.yml` 的 `backend.command`，改用 gunicorn + uvicorn worker：

```yaml
  backend:
    command: >
      gunicorn app.main:app
      --bind 0.0.0.0:8000
      --workers 4
      --worker-class uvicorn.workers.UvicornWorker
      --timeout 120
      --graceful-timeout 30
      --access-logfile -
      --error-logfile -
```

注：`gunicorn` 需在 `backend/requirements.txt` 中追加（当前未包含，部署时 `pip install gunicorn==23.0.0` 即可，不修改项目文件）。

**方式 B：裸机部署（无 Docker）**

```bash
cd /opt/synthdraft/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install gunicorn==23.0.0  # 生产推荐

# 配置环境变量（从 backend/.env 读取，或导出到 shell）
cp .env.example .env
# 编辑 .env，将各 host 改为 localhost 或实际 IP

# 数据库迁移（Alembic，需 Task 2+ schema 就绪）
alembic upgrade head

# 启动
gunicorn app.main:app \
  --bind 0.0.0.0:8000 \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --timeout 120
```

#### A.3.2 Celery Worker 启动（按队列分离）

来源：`backend/app/celery_app.py` L43-50（队列路由）+ `infra/docker-compose.yml` L196。

Celery 共 6 个业务队列 + 1 个默认队列：

| 队列 | 消费节点 | 路由匹配 | 推荐并发 |
|---|---|---|---|
| `reviews` | Linux | `app.celery.tasks.reviews.*` | 2-4 |
| `generations` | Linux | `app.celery.tasks.generations.*` | 2-4 |
| `sketch` | Linux | `app.celery.tasks.sketch.*` | 2 |
| `assembly` | Linux | `app.celery.tasks.assembly.*` | 2 |
| `collaboration` | Linux | `app.celery.tasks.collaboration.*` | 1-2 |
| `solidworks` | **Windows** | `app.celery.tasks.solidworks.*` | 1（许可证限制） |
| `default` | Linux | 兜底 | 1 |

**生产推荐：按队列分离启动多个 Worker 进程**（避免长任务饿死后继）：

```bash
cd /opt/synthdraft/backend
source .venv/bin/activate

# Worker 1：审图任务
celery -A app.celery_app worker --loglevel=info --concurrency=4 \
  -Q reviews --name=worker-reviews@%h

# Worker 2：生成任务
celery -A app.celery_app worker --loglevel=info --concurrency=4 \
  -Q generations --name=worker-generations@%h

# Worker 3：草图转 CAD
celery -A app.celery_app worker --loglevel=info --concurrency=2 \
  -Q sketch --name=worker-sketch@%h

# Worker 4：装配体生成
celery -A app.celery_app worker --loglevel=info --concurrency=2 \
  -Q assembly --name=worker-assembly@%h

# Worker 5：协同闭环
celery -A app.celery_app worker --loglevel=info --concurrency=2 \
  -Q collaboration --name=worker-collab@%h

# Worker 6：默认队列（兜底）
celery -A app.celery_app worker --loglevel=info --concurrency=1 \
  -Q default --name=worker-default@%h
```

**关键配置**（来源：`backend/app/celery_app.py` L52-61）：
- `worker_prefetch_multiplier=1`：长任务预取 1 条，避免饿死
- `broker_visibility_timeout=3600`：可见性超时 1 小时（长任务需更长）
- `result_expires=604800`：结果 7 天过期
- `timezone=Asia/Shanghai`、`enable_utc=True`

**推荐 systemd unit 管理**（示例 `synthdraft-celery-reviews.service`）：

```ini
[Unit]
Description=SynthDraft Celery Worker (reviews)
After=network.target redis-server.service

[Service]
Type=simple
User=synthdraft
WorkingDirectory=/opt/synthdraft/backend
EnvironmentFile=/opt/synthdraft/backend/.env
ExecStart=/opt/synthdraft/backend/.venv/bin/celery -A app.celery_app worker \
  --loglevel=info --concurrency=4 -Q reviews --name=worker-reviews@%h
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### A.3.3 Celery Beat 启动（定时任务）

来源：`infra/docker-compose.yml` L198-216（profile: scheduler）。

```bash
# Docker 方式
docker compose --env-file .env --profile scheduler up -d celery_beat

# 裸机方式
cd /opt/synthdraft/backend
source .venv/bin/activate
celery -A app.celery_app beat --loglevel=info
```

**注意**：Beat 进程全局唯一，禁止多实例（会导致任务重复调度）。

---

### A.4 SolidWorks Worker 部署（Windows 节点）

来源：`backend/app/celery/tasks/solidworks.py` L29-32 + `backend/app/services/solidworks/sw_session.py` + `backend/app/services/solidworks/license.py`。

#### A.4.1 环境准备

1. **安装 SolidWorks**（2022-2025 任一版本），激活许可证
2. **安装 Python 3.11+ / 3.13+ 推荐**（[python.org](https://www.python.org/downloads/)）
3. **安装 Visual C++ Redistributable**（pywin32 运行依赖）

#### A.4.2 拉取代码并安装依赖

```powershell
# 假设代码已同步到 D:\SynthDraft（通过内网 git 或离线拷贝）
cd D:\SynthDraft\backend

# 创建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 安装依赖（pywin32 仅 Windows 安装，Linux 跳过）
pip install -r requirements.txt

# 验证 pywin32 安装
python -c "import win32com.client; print('pywin32 ok')"
# 若失败，执行：python .venv\Scripts\pywin32_postinstall.py -install
```

#### A.4.3 配置环境变量

```powershell
# 在 D:\SynthDraft\backend\.env 中配置（指向 Linux 节点的 Redis）
CELERY_BROKER_URL=redis://<linux-node-ip>:6379/1
CELERY_RESULT_BACKEND=redis://<linux-node-ip>:6379/2

# MinIO（用于产物回传到 Linux 节点）
MINIO_ENDPOINT=<linux-node-ip>:9000
MINIO_ACCESS_KEY=<同 A.2.1>
MINIO_SECRET_KEY=<同 A.2.1>
MINIO_BUCKET=synthdraft-files
MINIO_SECURE=false

# SolidWorks 预热（生产建议 1，避免首次任务 ~10s Dispatch 开销）
SOLIDWORKS_PREWARM_COUNT=1

# 日志
LOG_LEVEL=INFO
APP_ENV=production
```

来源：`backend/app/config.py` L121-122（`SOLIDWORKS_PREWARM_COUNT` 默认 0，生产建议 1-2）。

#### A.4.4 SolidWorks 许可证激活验证

来源：`backend/app/services/solidworks/license.py` L129-215（`get_status` 探测逻辑）。

```powershell
cd D:\SynthDraft\backend
.\.venv\Scripts\Activate.ps1

# 探测许可证（耗时约 10s，会 Dispatch 一次 SolidWorks 并立即 ExitApp）
python -c "from app.services.solidworks.license import get_license_manager; m = get_license_manager(); print(m.get_status())"
```

期望输出：`LicenseStatus.AVAILABLE` 或 `LicenseStatus.IN_USE`。
- 若返回 `EXHAUSTED`：许可证并发已满或服务器拒绝
- 若返回 `UNKNOWN`：pywin32 未装 / SolidWorks 未安装 / COM Dispatch 异常

#### A.4.5 启动 SolidWorks Worker

来源：`backend/app/celery/tasks/solidworks.py` L30（启动命令）。

```powershell
cd D:\SynthDraft\backend
.\.venv\Scripts\Activate.ps1

# -c 1：单并发（SolidWorks COM 是 STA，许可证通常限单实例）
# --without-gossip：降低 broker 压力
celery -A app.celery_app worker -Q solidworks -c 1 --without-gossip --loglevel=info
```

**生产推荐：用 NSSM 注册为 Windows 服务**

```powershell
# 下载 NSSM: https://nssm.cc/download
nssm install SynthDraft-SolidWorks-Worker ^
  "D:\SynthDraft\backend\.venv\Scripts\celery.exe" ^
  "-A app.celery_app worker -Q solidworks -c 1 --without-gossip --loglevel=info"

nssm set SynthDraft-SolidWorks-Worker AppDirectory "D:\SynthDraft\backend"
nssm set SynthDraft-SolidWorks-Worker AppEnvironmentExtra "PYTHONUNBUFFERED=1"
nssm set SynthDraft-SolidWorks-Worker Start SERVICE_AUTO_START
nssm start SynthDraft-SolidWorks-Worker
```

#### A.4.6 跨网通信验证

```powershell
# 在 Windows 节点验证 Redis 连通性
python -c "import redis; r = redis.Redis(host='<linux-node-ip>', port=6379, db=1); print(r.ping())"
# 期望：True

# 验证 Worker 已注册到 broker
celery -A app.celery_app inspect ping -d celery@<windows-hostname>
```

---

### A.5 前端部署

来源：`frontend/package.json` L5-9（scripts）。

#### A.5.1 构建前端

```bash
cd /opt/synthdraft/frontend

# 安装依赖（首次或 package.json 变更时）
npm ci

# 配置后端 API 地址
# 创建 .env.local（或 .env.production）
echo "NEXT_PUBLIC_API_BASE_URL=https://synthdraft.internal/api/v1" > .env.local
echo "NEXT_PUBLIC_WS_BASE_URL=wss://synthdraft.internal/api/v1/ws" >> .env.local

# 生产构建
npm run build

# 启动（默认监听 3000）
npm run start
# 或指定端口：PORT=3100 npm run start
```

#### A.5.2 Nginx 反向代理配置

```nginx
# /etc/nginx/conf.d/synthdraft.conf
upstream synthdraft_backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

upstream synthdraft_frontend {
    server 127.0.0.1:3000;
    keepalive 16;
}

server {
    listen 443 ssl http2;
    server_name synthdraft.internal;

    # SSL（生产必须，证书路径按实际）
    ssl_certificate     /etc/nginx/ssl/synthdraft.crt;
    ssl_certificate_key /etc/nginx/ssl/synthdraft.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    # 上传文件大小限制（图纸/PDF 可能较大）
    client_max_body_size 100m;

    # API 反向代理
    location /api/ {
        proxy_pass http://synthdraft_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;  # 长任务同步等待
    }

    # WebSocket 反向代理（任务进度推送）
    location /api/v1/ws/ {
        proxy_pass http://synthdraft_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;  # WS 长连接
    }

    # 前端
    location / {
        proxy_pass http://synthdraft_frontend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}

# HTTP → HTTPS 跳转
server {
    listen 80;
    server_name synthdraft.internal;
    return 301 https://$host$request_uri;
}
```

启动 Nginx：

```bash
sudo nginx -t  # 配置校验
sudo systemctl reload nginx
```

---

### A.6 可观测性栈部署

来源：`infra/observability/docker-compose.observability.yml` 全文 + `infra/otel-collector-config.yaml` + `infra/observability/prometheus.yml` + `infra/observability/tempo.yaml`。

#### A.6.1 启用 OpenTelemetry 导出

在 `infra/.env` 中配置：

```dotenv
OTEL_ENABLED=true
OTEL_SERVICE_NAME=synthdraft-backend
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

来源：`backend/app/config.py` L94-97。

#### A.6.2 启动可观测性栈

```bash
cd /opt/synthdraft/infra

# 步骤 1：先启动主 compose 的 otel-collector（与 backend 同网络）
docker compose --env-file .env --profile observability up -d otel-collector

# 步骤 2：启动观测后端（Grafana + Tempo + Prometheus + Flower）
cd /opt/synthdraft/infra/observability
docker compose -f docker-compose.observability.yml --profile observability up -d
```

**注意**（来源：`infra/observability/docker-compose.observability.yml` L10-13 + L45 注释）：
- 观测栈 compose 文件声明 `synthdraft_default` 网络为 `external: true`，必须先启动主 compose 创建该网络
- Tempo 的 4318 端口与 otel-collector 的 4318 冲突，二选一：
  - 方案 A（推荐）：otel-collector 接收 → 转发到 Tempo（注释 Tempo 的 4318 端口映射）
  - 方案 B：直接让应用推送到 Tempo（注释 otel-collector 服务，`OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4318`）

#### A.6.3 配置 Tempo 为 otel-collector 的导出后端

编辑 `infra/otel-collector-config.yaml`，将 `debug` exporter 替换为 `otlp`：

```yaml
exporters:
  otlp:
    endpoint: tempo:4317
    tls:
      insecure: true
```

#### A.6.4 访问入口

| 服务 | URL | 默认账号 |
|---|---|---|
| Grafana | http://<linux-node-ip>:3001 | admin / admin（首次登录强制改密） |
| Prometheus | http://<linux-node-ip>:9090 | 无鉴权 |
| Tempo API | http://<linux-node-ip>:3200 | 无鉴权 |
| Flower | http://<linux-node-ip>:5555 | 无鉴权 |

Grafana 数据源已通过 `grafana-dashboard.json` 预配置（来源：`infra/observability/docker-compose.observability.yml` L31）。

#### A.6.5 验证 tracing 链路

```bash
# 触发一次审图请求
curl -X POST http://localhost:8000/api/v1/reviews \
  -H "Content-Type: application/json" \
  -d '{"file_url":"...","spec_id":"..."}'

# 在 Grafana → Explore → Tempo 中查询 service.name=synthdraft-backend 的 trace
```

---

### A.7 离线安装包制作

适用于完全无外网的私有化部署场景。

#### A.7.1 模型权重预下载

在有网络的预备机上执行：

```bash
# 1. Ollama 模型权重（容器内拉取后打包）
docker exec synthdraft-ollama ollama pull qwen2.5-coder:7b
docker exec synthdraft-ollama ollama pull qwen2.5:7b
docker exec synthdraft-ollama ollama pull qwen2.5-vl:7b
docker exec synthdraft-ollama ollama pull nomic-embed-text

# 导出 Ollama 数据卷
docker run --rm -v synthdraft_ollama_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/ollama_models.tar.gz -C /data .

# 2. bge-m3 权重（HuggingFace 缓存）
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DOWNLOAD_TIMEOUT=60
python -c "from FlagEmbedding import BGEM3Inferencer; BGEM3Inferencer()"

# 打包 HF 缓存
tar czf hf_cache_bge_m3.tar.gz -C ~/.cache/huggingface/hub/ models--BAAI--bge-m3
```

在目标离线节点恢复：

```bash
# Ollama 模型
docker volume create synthdraft_ollama_data
docker run --rm -v synthdraft_ollama_data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/ollama_models.tar.gz -C /data

# bge-m3 权重
mkdir -p ~/.cache/huggingface/hub
tar xzf hf_cache_bge_m3.tar.gz -C ~/.cache/huggingface/hub/
```

#### A.7.2 Docker 镜像 tar 包导出

```bash
# 在有网络的预备机上拉取并导出所有镜像
mkdir -p synthdraft_images

docker pull postgres:16-alpine
docker pull redis:7-alpine
docker pull qdrant/qdrant:v1.18.3
docker pull minio/minio:RELEASE.2025-09-07T16-13-09Z
docker pull ollama/ollama:0.30.6
docker pull vllm/vllm-openai:v0.25.0
docker pull otel/opentelemetry-collector-contrib:0.129.1
docker pull grafana/grafana:12.2.0
docker pull grafana/tempo:2.8.1
docker pull prom/prometheus:v3.4.0
docker pull mher/flower:2.0.1

# 构建项目镜像
cd /opt/synthdraft/infra
docker compose --env-file .env build backend

# 导出为 tar
docker save -o synthdraft_images/postgres.tar postgres:16-alpine
docker save -o synthdraft_images/redis.tar redis:7-alpine
docker save -o synthdraft_images/qdrant.tar qdrant/qdrant:v1.18.3
docker save -o synthdraft_images/minio.tar minio/minio:RELEASE.2025-09-07T16-13-09Z
docker save -o synthdraft_images/ollama.tar ollama/ollama:0.30.6
docker save -o synthdraft_images/vllm.tar vllm/vllm-openai:v0.25.0
docker save -o synthdraft_images/otel-collector.tar otel/opentelemetry-collector-contrib:0.129.1
docker save -o synthdraft_images/grafana.tar grafana/grafana:12.2.0
docker save -o synthdraft_images/tempo.tar grafana/tempo:2.8.1
docker save -o synthdraft_images/prometheus.tar prom/prometheus:v3.4.0
docker save -o synthdraft_images/flower.tar mher/flower:2.0.1
docker save -o synthdraft_images/synthdraft-backend.tar synthdraft-backend:latest
```

在离线节点加载：

```bash
for img in synthdraft_images/*.tar; do
  docker load -i "$img"
done
```

#### A.7.3 Python wheels 离线安装

适用于 Windows SolidWorks Worker 节点（无法 Docker 化）。

```bash
# 在有网络且与目标节点同架构的机器上下载 wheels
mkdir -p synthdraft_wheels
cd /opt/synthdraft/backend
pip download -r requirements.txt -d ../synthdraft_wheels

# 额外下载 gunicorn（Linux 后端用）
pip download gunicorn==23.0.0 -d ../synthdraft_wheels

# 打包
tar czf synthdraft_wheels.tar.gz synthdraft_wheels/
```

在离线 Windows 节点安装：

```powershell
cd D:\SynthDraft\backend
.\.venv\Scripts\Activate.ps1
pip install --no-index --find-links=D:\synthdraft_wheels -r requirements.txt
```

---

## B. 云部署模式（轻量试用）

适用于快速 POC、内部试用评估。**注意**：SolidWorks Worker 仍须部署在企业内网 Windows 机器上，不可上云。

### B.1 云服务器选型

| 云厂商 | 推荐实例 | 配置 | 适用规模 |
|---|---|---|---|
| AWS | `t3.xlarge` / `m6i.xlarge` | 4 vCPU / 16 GB | ≤ 10 并发 |
| Azure | `Standard_D4s_v5` | 4 vCPU / 16 GB | ≤ 10 并发 |
| 阿里云 | `ecs.g7.xlarge` | 4 vCPU / 16 GB | ≤ 10 并发 |
| AWS（GPU） | `g5.xlarge` | 1× A10G / 4 vCPU / 16 GB | vLLM 推理 |
| 阿里云（GPU） | `ecs.gn7i-c8g1.2xlarge` | 1× T4 / 8 vCPU / 32 GB | vLLM 推理 |

**操作系统**：Ubuntu Server 22.04 LTS（与私有化 Linux 节点一致）。

### B.2 GPU 实例配置（如使用 vLLM）

1. 选择 GPU 实例后，安装 NVIDIA 驱动 + Container Toolkit（步骤同 A.2.5）
2. 配置 `HUGGING_FACE_HUB_TOKEN`（来源：`infra/docker-compose.yml` L120）以拉取门控模型
3. 启用 vLLM profile：`docker compose --env-file .env --profile gpu up -d vllm`
4. 切换 `LLM_PROVIDER=openai` + `OPENAI_BASE_URL=http://vllm:8000/v1`

### B.3 对象存储替换（MinIO → S3/OSS）

后端通过 `minio==7.2.20` SDK 访问，兼容 S3 协议，可直接切换至云厂商对象存储。

来源：`backend/app/config.py` L54-59。

```dotenv
# AWS S3
MINIO_ENDPOINT=s3.<region>.amazonaws.com:443
MINIO_ACCESS_KEY=<AWS_ACCESS_KEY_ID>
MINIO_SECRET_KEY=<AWS_SECRET_ACCESS_KEY>
MINIO_BUCKET=synthdraft-prod
MINIO_SECURE=true

# 阿里云 OSS（需启用 S3 兼容端点）
MINIO_ENDPOINT=<bucket>.<region>.aliyuncs.com:443
MINIO_ACCESS_KEY=<OSS_ACCESS_KEY_ID>
MINIO_SECRET_KEY=<OSS_ACCESS_KEY_SECRET>
MINIO_BUCKET=synthdraft-prod
MINIO_SECURE=true
```

**注意**：替换后 `infra/docker-compose.yml` 中的 `minio` 服务可停止，但需保留 `MINIO_BUCKET` 已创建。

### B.4 数据库托管服务

#### B.4.1 PostgreSQL（RDS / 云数据库）

```dotenv
# 替换 DATABASE_URL 与 POSTGRES_*
POSTGRES_HOST=<rds-endpoint>.rds.amazonaws.com
POSTGRES_PORT=5432
POSTGRES_USER=synthdraft
POSTGRES_PASSWORD=<强随机密码>
POSTGRES_DB=synthdraft
DATABASE_URL=postgresql+asyncpg://synthdraft:<pwd>@<rds-endpoint>:5432/synthdraft
```

**注意**：
- RDS 默认端口 5432（与容器内一致，宿主 5433 仅开发用）
- 安全组需放通 5432 给后端实例
- 首次需手动执行 `infra/init.sql`（来源：`infra/init.sql`，当前为占位）

#### B.4.2 Redis（ElastiCache / 云 Redis）

```dotenv
REDIS_HOST=<elasticache-endpoint>.cache.amazonaws.com
REDIS_PORT=6379
REDIS_URL=redis://<elasticache-endpoint>:6379/0
CELERY_BROKER_URL=redis://<elasticache-endpoint>:6379/1
CELERY_RESULT_BACKEND=redis://<elasticache-endpoint>:6379/2
```

**注意**：ElastiCache 默认禁用 `appendonly`，与 `infra/docker-compose.yml` L36 的 `--appendonly yes` 不同，生产可接受（broker 数据可重建）。

### B.5 商业 API 增强模式（OpenAI/Anthropic）

来源：`backend/app/config.py` L77-87 + `backend/.env.example` L78-96。

适用于试用阶段无需本地 GPU、直接调用商业 LLM API 的场景。

```dotenv
# 切换 LLM provider 为 OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-<your-key>
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_VLM_MODEL=gpt-4o

# 或切换为 Anthropic Claude
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-<your-key>
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
ANTHROPIC_VLM_MODEL=claude-3-5-sonnet-latest
```

**国内云厂商兼容端点**（OpenAI 协议）：
- DeepSeek：`OPENAI_BASE_URL=https://api.deepseek.com/v1`，`OPENAI_MODEL=deepseek-coder`
- 通义千问：`OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- 智谱 GLM：`OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4`

**注意**：商业 API 模式下 Ollama/vLLM 服务可不启动，但 `bge-m3` embedding 仍需本地运行（向量检索不依赖商业 API）。

### B.6 CDN 与 SSL 配置

#### B.6.1 SSL 证书

| 云厂商 | 服务 | 推荐方式 |
|---|---|---|
| AWS | ACM (Certificate Manager) | 免费托管证书，绑定 ALB |
| 阿里云 | SSL 证书服务 | 免费版 DV 证书，绑定 SLB |
| Cloudflare | 边缘证书 | 全程 SSL，回源用自签 |

#### B.6.2 CDN 加速

仅对前端静态资源启用 CDN（API 与 WebSocket 不走 CDN）：

```
前端域名 synthdraft.example.com → CDN → 源站（Nginx :3000）
API 域名  api.synthdraft.example.com → 直连源站（Nginx :8000）
```

#### B.6.3 负载均衡（ALB/SLB）

- 前端：HTTP/HTTPS，监听 443 → 转发 3000
- API：HTTP/HTTPS，监听 443 → 转发 8000
- WebSocket：监听 443 → 转发 8000，启用 sticky session
- 健康检查：`GET /api/v1/healthz`，期望 200

---

## C. 通用章节

### C.1 部署验证

#### C.1.1 健康检查

来源：`backend/app/api/v1/endpoints/health.py`（`/healthz` + `/readyz`）。

```bash
# 存活探针（轻量，不探测依赖）
curl http://localhost:8000/api/v1/healthz
# 期望：{"status":"healthy",...}

# 就绪探针（探测 PostgreSQL / Redis / LLM provider）
curl http://localhost:8000/api/v1/readyz
# 期望：overall=true，各组件 status=ok
```

#### C.1.2 依赖服务健康检查

```bash
# PostgreSQL
docker exec synthdraft-postgres pg_isready -U synthdraft

# Redis
docker exec synthdraft-redis redis-cli ping

# Qdrant
curl -s http://localhost:6333/healthz | grep -q '"status":"ok"'

# MinIO
curl -s -o /dev/null -w "%{http_code}" http://localhost:9000/minio/health/live
# 期望：200

# Ollama
curl -s http://localhost:11434/api/tags | grep -q "qwen2.5-coder"

# SolidWorks Worker（从 Linux 节点发起）
celery -A app.celery_app inspect ping -d celery@<windows-hostname>
# 期望：{"pong":"pong"}
```

#### C.1.3 Smoke Test（端到端冒烟）

```bash
# 1. 获取 JWT Token（若启用鉴权）
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<pwd>"}' | jq -r .access_token)

# 2. 上传一份测试图纸
TASK_ID=$(curl -s -X POST http://localhost:8000/api/v1/reviews \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"file_url":"<minio-file-url>","spec_id":"gb-t-1182"}' | jq -r .task_id)

# 3. 轮询任务状态
curl http://localhost:8000/api/v1/tasks/$TASK_ID \
  -H "Authorization: Bearer $TOKEN"

# 4. WebSocket 进度推送验证（wscat 工具）
wscat -c "ws://localhost:8000/api/v1/ws/tasks/$TASK_ID" \
  -H "Authorization: Bearer $TOKEN"
```

#### C.1.4 SolidWorks Worker 端到端验证

来源：`backend/app/celery/tasks/solidworks.py`（`license_status_task` 任务）。

```bash
# 从 Linux 节点投递许可证探测任务
celery -A app.celery_app call app.celery.tasks.solidworks.license_status_task
# 在 Windows Worker 日志中观察返回：{"status":"available",...}
```

---

### C.2 升级流程

#### C.2.1 蓝绿部署（推荐，无停机）

适用于后端 FastAPI 与 Celery Worker 的版本升级。

```
当前版本（蓝）           新版本（绿）
┌──────────────┐        ┌──────────────┐
│ backend:8000 │        │ backend:8001 │
│ celery       │        │ celery (新)  │
└──────────────┘        └──────────────┘
       ↑ Nginx 流量
```

步骤：

```bash
# 1. 部署绿环境（新版本，端口 8001）
cd /opt/synthdraft-new/infra
docker compose --env-file .env -p synthdraft-green up -d backend celery_worker

# 2. 绿环境 Smoke Test 通过后，切换 Nginx upstream
sudo sed -i 's/127.0.0.1:8000/127.0.0.1:8001/' /etc/nginx/conf.d/synthdraft.conf
sudo nginx -s reload

# 3. 观察绿环境 30 分钟无异常后，销毁蓝环境
cd /opt/synthdraft/infra
docker compose -p synthdraft down

# 4. 下次升级前，将绿环境重命名为蓝（端口回 8000）
```

**注意**：
- 数据库迁移（Alembic）须向后兼容，先迁移再切流量
- SolidWorks Worker 升级须停机（COM 单例，无法蓝绿），见 C.2.2

#### C.2.2 滚动更新（Celery Worker）

```bash
# 逐个重启 Celery Worker（避免任务中断）
cd /opt/synthdraft/backend

# 对每个 worker：
systemctl stop synthdraft-celery-reviews
# 等待当前任务完成（最长 broker_visibility_timeout=3600s）
systemctl start synthdraft-celery-reviews
```

#### C.2.3 SolidWorks Worker 升级

```powershell
# 1. 在 Linux 节点暂停投递 solidworks 队列任务（或排空队列）
celery -A app.celery_app purge -Q solidworks

# 2. Windows 节点停止 Worker
nssm stop SynthDraft-SolidWorks-Worker

# 3. 等待当前任务完成（最长任务超时 5 分钟，见 solidworks.py L60）

# 4. 拉取新代码 + 依赖
cd D:\SynthDraft
git pull
cd backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt --upgrade

# 5. 重启 Worker
nssm start SynthDraft-SolidWorks-Worker
```

---

### C.3 回滚流程

#### C.3.1 应用层回滚

```bash
# 1. Nginx 切回旧版本（蓝绿部署场景）
sudo sed -i 's/127.0.0.1:8001/127.0.0.1:8000/' /etc/nginx/conf.d/synthdraft.conf
sudo nginx -s reload

# 2. 数据库回滚（如有破坏性迁移）
cd /opt/synthdraft/backend
alembic downgrade -1

# 3. 镜像回滚（Docker 场景）
docker compose --env-file .env down backend
docker tag synthdraft-backend:previous synthdraft-backend:latest
docker compose --env-file .env up -d backend
```

#### C.3.2 依赖服务回滚

```bash
# PostgreSQL（基于 volume 快照恢复）
docker compose --env-file .env stop postgres
# 恢复 postgres_data volume 快照
docker compose --env-file .env start postgres

# Redis（broker 数据丢失可接受，重启即可）
docker compose --env-file .env restart redis

# Qdrant（基于 volume 快照恢复）
docker compose --env-file .env stop qdrant
# 恢复 qdrant_data volume 快照
docker compose --env-file .env start qdrant
```

---

### C.4 常见部署问题排查（FAQ）

#### Q1: Backend 启动报 `asyncpg.exceptions.InvalidPasswordError`

**原因**：PostgreSQL 密码与 `.env` 不一致。

**排查**：
```bash
docker exec synthdraft-postgres psql -U synthdraft -c "\du"
# 确认用户存在且密码已设置
```

**解决**：
```bash
# 重置密码
docker exec synthdraft-postgres psql -U synthdraft -c \
  "ALTER USER synthdraft PASSWORD '<new-pwd>';"
# 同步更新 .env 的 POSTGRES_PASSWORD 与 DATABASE_URL
```

---

#### Q2: Celery Worker 启动后无任务消费

**原因**：队列名与路由不匹配，或 broker 网络不通。

**排查**：
```bash
# 1. 检查 Redis broker 中的待处理任务
docker exec synthdraft-redis redis-cli -n 1 LLEN reviews
docker exec synthdraft-redis redis-cli -n 1 LLEN solidworks

# 2. 检查 Worker 注册的队列
celery -A app.celery_app inspect active_queues

# 3. 检查 Worker 是否就绪
celery -A app.celery_app inspect ping
```

**解决**：
- 确认 Worker 启动参数 `-Q` 与 `backend/app/celery_app.py` L43-50 的 `task_routes` 一致
- 确认 `CELERY_BROKER_URL` 指向同一 Redis DB（默认 DB 1）

---

#### Q3: SolidWorks Worker 报 `SolidWorksNotAvailableError: pywin32 not installed`

**原因**：pywin32 未正确安装或 postinstall 脚本未执行。

**解决**：
```powershell
cd D:\SynthDraft\backend
.\.venv\Scripts\Activate.ps1
python .\.venv\Scripts\pywin32_postinstall.py -install
python -c "import win32com.client; print('ok')"
```

---

#### Q4: SolidWorks Worker 报 `SolidWorksLicenseError: 许可证不可用或并发已满`

来源：`backend/app/services/solidworks/worker_pool.py` L370-374。

**原因**：
- SolidWorks 许可证未激活 / 已过期
- 并发实例数超过许可证上限（默认 `max_workers=1`）

**排查**：
```powershell
python -c "from app.services.solidworks.license import get_license_manager; print(get_license_manager().get_status())"
```

**解决**：
- 检查 SolidWorks 许可证服务器（SNL）是否可达
- 关闭其他正在运行的 SolidWorks 实例
- 确认 `SOLIDWORKS_PREWARM_COUNT` 不超过许可证并发上限

---

#### Q5: SolidWorks 任务超时（`SolidWorksTaskTimeout`）

来源：`backend/app/services/solidworks/worker_pool.py` L489-524。

**原因**：COM 调用卡死（STA 线程阻塞）。

**自动恢复**：Worker Pool 会自动 `_kill_solidworks_process` + `_restart_with_retry`（指数退避 3 次重试）。

**手动处理**：
```powershell
# 检查是否有残留 sldworks.exe 进程
tasklist | findstr sldworks
# 强制 kill
taskkill /F /IM sldworks.exe
# 重启 Worker
nssm restart SynthDraft-SolidWorks-Worker
```

---

#### Q6: bge-m3 加载失败 / 超时

**原因**：HuggingFace 下载超时或网络不通。

**解决**：
```bash
# 设置镜像（中国境内）
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DOWNLOAD_TIMEOUT=60

# 离线场景：从预备机拷贝缓存（见 A.7.1）
mkdir -p ~/.cache/huggingface/hub
tar xzf hf_cache_bge_m3.tar.gz -C ~/.cache/huggingface/hub/
```

来源：`backend/app/config.py` L71-75。

---

#### Q7: Qdrant 连接失败 / 向量检索 503

**排查**：
```bash
curl http://localhost:6333/healthz
docker logs synthdraft-qdrant --tail 50
```

**解决**：
- 确认 `QDRANT_URL=http://qdrant:6333`（容器内）或 `http://<linux-node-ip>:6333`（容器外）
- 若 volume 损坏：`docker volume rm synthdraft_qdrant_data` 后重启（需重新索引知识库）

---

#### Q8: Grafana 看不到 tracing 数据

**原因**：otel-collector exporter 未指向 Tempo，或 `OTEL_ENABLED=false`。

**排查**：
```bash
# 1. 确认 OTEL_ENABLED
docker exec synthdraft-backend env | grep OTEL_ENABLED
# 期望：OTEL_ENABLED=true

# 2. 确认 otel-collector 配置（见 A.6.3）
cat infra/otel-collector-config.yaml | grep -A2 otlp:

# 3. 确认 Tempo 接收到 spans
curl http://localhost:3200/metrics | grep tempo_distributor_spans_received
```

---

#### Q9: vLLM 启动失败 / GPU 不可见

**排查**：
```bash
# 容器内 GPU 可见性
docker exec synthdraft-vllm nvidia-smi
# 若失败：NVIDIA Container Toolkit 未正确安装或未重启 Docker

# vLLM 启动日志
docker logs synthdraft-vllm --tail 100
```

**解决**：
```bash
sudo systemctl restart docker
docker compose --env-file .env --profile gpu up -d vllm
```

---

#### Q10: 前端构建失败 `next build`

**原因**：Node.js 版本过低或依赖缺失。

**解决**：
```bash
# 确认 Node.js 版本（Next.js 14.2.35 需 18.17+）
node --version

# 清理缓存重新构建
rm -rf .next node_modules
npm ci
npm run build
```

---

## D. 附录

### D.1 环境变量速查表

来源：`backend/app/config.py` 全文 + `backend/.env.example` 全文 + `infra/.env.example` 全文。

| 变量 | 默认值 | 说明 | 来源 |
|---|---|---|---|
| `APP_ENV` | development | 运行环境（production 时 `is_production=True`） | config.py L27 |
| `APP_DEBUG` | true | 调试模式（生产须 false） | config.py L28 |
| `LOG_LEVEL` | DEBUG | 日志级别 | config.py L31 |
| `DATABASE_URL` | postgresql+asyncpg://... | SQLAlchemy 异步连接串 | config.py L40-42 |
| `REDIS_URL` | redis://redis:6379/0 | 应用缓存 | config.py L47 |
| `CELERY_BROKER_URL` | redis://redis:6379/1 | Celery broker | config.py L48 |
| `CELERY_RESULT_BACKEND` | redis://redis:6379/2 | Celery result backend | config.py L49 |
| `QDRANT_URL` | http://qdrant:6333 | 向量库 | config.py L52 |
| `MINIO_ENDPOINT` | minio:9000 | 对象存储 | config.py L55 |
| `MINIO_ACCESS_KEY` | synthdraft_minio | [SECURE] | config.py L56 |
| `MINIO_SECRET_KEY` | synthdraft_minio_secret | [SECURE] | config.py L57 |
| `MINIO_BUCKET` | synthdraft-files | 桶名 | config.py L58 |
| `MINIO_SECURE` | false | 是否 HTTPS | config.py L59 |
| `OLLAMA_HOST_URL` | http://ollama:11434 | Ollama | config.py L62 |
| `VLLM_BASE_URL` | http://vllm:8000/v1 | vLLM | config.py L63 |
| `LLM_PROVIDER` | ollama | ollama/openai/anthropic | config.py L66 |
| `LLM_MODEL` | qwen2.5-coder:7b | 文本模型 | config.py L67 |
| `VLM_MODEL` | qwen2.5-vl:7b | 视觉模型 | config.py L68 |
| `EMBEDDING_MODEL` | bge-m3 | 嵌入模型 | config.py L69 |
| `HF_ENDPOINT` | https://hf-mirror.com | HF 镜像（中国加速） | config.py L73 |
| `HF_HUB_DOWNLOAD_TIMEOUT` | 60 | 下载超时秒 | config.py L75 |
| `OPENAI_API_KEY` | （空） | OpenAI 兼容 key | config.py L78 |
| `OPENAI_BASE_URL` | https://api.openai.com/v1 | OpenAI 端点 | config.py L79 |
| `OPENAI_MODEL` | gpt-4o-mini | 文本模型 | config.py L80 |
| `OPENAI_VLM_MODEL` | gpt-4o | 视觉模型 | config.py L81 |
| `ANTHROPIC_API_KEY` | （空） | Anthropic key | config.py L84 |
| `ANTHROPIC_BASE_URL` | https://api.anthropic.com | Anthropic 端点 | config.py L85 |
| `ANTHROPIC_MODEL` | claude-3-5-sonnet-latest | 文本模型 | config.py L86 |
| `ANTHROPIC_VLM_MODEL` | claude-3-5-sonnet-latest | 视觉模型 | config.py L87 |
| `JWT_SECRET_KEY` | change-this-... | [SECURE] 生产必换 | config.py L90 |
| `JWT_ALGORITHM` | HS256 | | config.py L91 |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | 1440 | 24 小时 | config.py L92 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | （空） | OTLP 端点 | config.py L95 |
| `OTEL_SERVICE_NAME` | synthdraft-backend | | config.py L96 |
| `OTEL_ENABLED` | false | 是否启用 tracing | config.py L97 |
| `OBS_QUEUE_MONITOR_ENABLED` | true | 队列监控 | config.py L101 |
| `OBS_QUEUE_BACKLOG_ALERT` | 50 | 堆积告警阈值 | config.py L103 |
| `OBS_QUEUE_FAILURE_RATE_ALERT` | 10.0 | 失败率告警（%） | config.py L105 |
| `OBS_QUEUE_SCAN_INTERVAL_SEC` | 60 | 采集间隔 | config.py L107 |
| `OBS_ALERT_WEBHOOK_URL` | （空） | 告警 webhook | config.py L109 |
| `OBS_LLM_METRICS_PATH` | ./tmp_metrics/llm_metrics.jsonl | LLM 指标路径 | config.py L112 |
| `OBS_FEEDBACK_STORE_PATH` | ./tmp_metrics/feedback.jsonl | 反馈路径 | config.py L115 |
| `CORS_ORIGINS` | http://localhost:3000,... | CORS 允许来源 | config.py L118 |
| `SOLIDWORKS_PREWARM_COUNT` | 0 | Worker 预热数（生产 1-2） | config.py L122 |
| `CAD_CACHE_ENABLED` | true | CAD 解析缓存 | config.py L125 |
| `CAD_CACHE_TTL` | 86400 | CAD 缓存 TTL（秒） | config.py L126 |
| `RAG_CACHE_ENABLED` | true | RAG 检索缓存 | config.py L129 |
| `RAG_CACHE_TTL` | 3600 | RAG 缓存 TTL（秒） | config.py L130 |
| `LLM_STREAM_ENABLED` | true | LLM 流式输出 | config.py L133 |
| `LLM_STREAM_TIMEOUT` | 300 | 流式超时（秒） | config.py L134 |
| `PDF_BACKEND` | auto | PDF 后端（auto/weasyprint/wkhtmltopdf/playwright/xhtml2pdf） | config.py L146 |

### D.2 Celery 队列速查表

来源：`backend/app/celery_app.py` L43-50 + `backend/app/celery/tasks/solidworks.py` L30。

| 队列 | 路由匹配 | 消费节点 | 推荐并发 | 启动命令 |
|---|---|---|---|---|
| `reviews` | `app.celery.tasks.reviews.*` | Linux | 4 | `celery -A app.celery_app worker -Q reviews -c 4` |
| `generations` | `app.celery.tasks.generations.*` | Linux | 4 | `celery -A app.celery_app worker -Q generations -c 4` |
| `sketch` | `app.celery.tasks.sketch.*` | Linux | 2 | `celery -A app.celery_app worker -Q sketch -c 2` |
| `assembly` | `app.celery.tasks.assembly.*` | Linux | 2 | `celery -A app.celery_app worker -Q assembly -c 2` |
| `collaboration` | `app.celery.tasks.collaboration.*` | Linux | 2 | `celery -A app.celery_app worker -Q collaboration -c 2` |
| `solidworks` | `app.celery.tasks.solidworks.*` | **Windows** | 1 | `celery -A app.celery_app worker -Q solidworks -c 1 --without-gossip` |
| `default` | 兜底 | Linux | 1 | `celery -A app.celery_app worker -Q default -c 1` |

### D.3 信息来源

本文档所有具体数字、端口、镜像 tag、命令均来自以下实际文件：

| 文件 | 用途 |
|---|---|
| `infra/docker-compose.yml` | 主编排（PG/Redis/Qdrant/MinIO/Ollama/vLLM/OTEL/Backend/Celery） |
| `infra/observability/docker-compose.observability.yml` | 可观测性栈（Grafana/Tempo/Prometheus/Flower） |
| `infra/otel-collector-config.yaml` | OTEL Collector 配置 |
| `infra/observability/prometheus.yml` | Prometheus 抓取配置 |
| `infra/observability/tempo.yaml` | Tempo 配置 |
| `infra/.env.example` + `infra/.env` | 基础设施环境变量模板 |
| `infra/init.sql` | PostgreSQL 初始化（占位） |
| `backend/requirements.txt` | Python 依赖版本 |
| `backend/Dockerfile` | 后端镜像构建（python:3.11-slim） |
| `backend/.env.example` | 后端环境变量模板 |
| `backend/app/config.py` | Settings 类（全部配置项 + 默认值） |
| `backend/app/celery_app.py` | Celery 队列路由 + 配置 |
| `backend/app/api/v1/endpoints/health.py` | 健康检查端点 |
| `backend/app/services/solidworks/sw_session.py` | SolidWorks COM 会话 |
| `backend/app/services/solidworks/worker_pool.py` | Worker 池（预热/超时/重启/许可证） |
| `backend/app/services/solidworks/license.py` | 许可证管理 |
| `backend/app/celery/tasks/solidworks.py` | SolidWorks 队列任务 + Worker 启动命令 |
| `backend/app/services/cad/README.md` | CAD 外部依赖（ODA/FreeCAD/OCC） |
| `backend/README.md` | 后端本地开发指引 |
| `frontend/package.json` | 前端构建命令 |
| `docs/architecture.md` | 架构设计文档（Task 18.1） |

### D.4 外部依赖安装参考

来源：`backend/app/services/cad/README.md` + `backend/requirements.txt` 注释。

| 依赖 | 安装方式 | 必需性 | 说明 |
|---|---|---|---|
| ODA File Converter | 注册下载（[opendesign.com](https://www.opendesign.com/guestfiles/oda_file_converter)） | 可选 | DWG → DXF 转换；未装时 `dwg_to_dxf()` 抛 `ODANotAvailableError` |
| FreeCAD | 官网下载（[freecadweb.org](https://www.freecadweb.org/downloads.php)） | 可选（备用引擎） | 配置 PYTHONPATH；未装时 `freecad_engine` 降级 |
| GTK3（Windows） | MSYS2 `pacman -S mingw-w64-x86_64-gtk3` | 可选 | weasyprint PDF 后端依赖；未装时 PDF_BACKEND=auto 自动回退 |
| wkhtmltopdf | 官网下载（[wkhtmltopdf.org](https://wkhtmltopdf.org/downloads.html)） | 可选 | wkhtmltopdf PDF 后端依赖 |
| NVIDIA Container Toolkit | apt 安装（见 A.2.5） | vLLM 必需 | GPU 容器支持 |
| pywin32 | `pip install pywin32>=308`（仅 Windows） | SolidWorks Worker 必需 | 装后执行 `pywin32_postinstall.py -install` |
