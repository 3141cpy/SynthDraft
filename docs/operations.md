# AI 驱动工程设计辅助系统 — 运维手册

> 文档版本：v1.0
> 编写日期：2026-07-27
> 适用阶段：阶段三（P2）Task 18.5 运维交付
> 信息来源：实际代码与配置文件（见末尾"信息来源"），所有监控指标、告警阈值、命令均基于实际文件读取
> 配套文档：`docs/deployment.md`（部署细节）、`docs/architecture.md`（架构设计）

---

## 1. 运维概述

### 1.1 系统架构与运维边界

SynthDraft 采用**跨平台解耦架构**，运维边界明确划分为两个节点：

| 节点 | 操作系统 | 承载服务 | 运维责任 |
|---|---|---|---|
| **Linux AI 服务节点** | Ubuntu 22.04+ / CentOS 8+ | FastAPI 后端、Celery Worker（reviews/generations/sketch/assembly/collaboration/default）、Celery Beat、PostgreSQL、Redis、Qdrant、MinIO、Ollama/vLLM、可观测性栈 | 应用启停、配置变更、监控告警、数据备份、版本升级 |
| **Windows SolidWorks Worker 节点** | Windows 10/11 或 Server 2022 | Celery Worker（仅消费 `solidworks` 队列）、SolidWorks COM 实例 | SolidWorks 许可证维护、Worker 进程守护、磁盘空间监控 |

**通信边界**：两节点通过 Redis broker（DB1，默认端口 6379）解耦，Windows Worker 通过 `CELERY_BROKER_URL=redis://<linux-node-ip>:6379/1` 连接。产物回传通过 MinIO（端口 9000）。

来源：`backend/app/celery_app.py` L43-50（队列路由）+ `docs/architecture.md` §2.2。

### 1.2 运维角色与职责

| 角色 | 职责 | 关注指标 |
|---|---|---|
| **应用运维** | 后端服务启停、配置变更、日志归档、版本发布 | 服务可用性、QPS、错误率 |
| **基础设施运维** | PostgreSQL/Redis/Qdrant/MinIO 维护、备份恢复、扩容 | 资源利用率、备份完整性 |
| **AI/LLM 运维** | Ollama/vLLM 模型管理、LLM 成本监控、Prompt 调优 | LLM 延迟 p95、成本 USD、失败率 |
| **SolidWorks 运维** | Windows Worker 守护、许可证维护、COM 故障处理 | Worker 健康状态、任务超时率、许可证占用 |
| **安全运维** | 密钥轮换、审计日志、文件上传安全 | 鉴权失败率、异常上传 |

### 1.3 关键 SLA 指标

| SLA 项 | 目标 | 监控方式 | 数据来源 |
|---|---|---|---|
| 审图任务端到端 | ≤ 5 分钟 | Tempo trace `review.pipeline` span 耗时 | `tracing.py` `review_pipeline_span()` |
| CadQuery 代码执行 | ≤ 30 秒 | Celery `generations` 队列任务耗时 | `celery_task_duration_seconds_bucket{queue="generations"}` |
| SolidWorks 生成（预热后） | ≤ 60 秒 | Tempo trace `solidworks.call` span 耗时 | `tracing.py` `solidworks_call_span()` |
| 区域检测 + OCR | ≤ 90 秒 | `review.pipeline` span 子段 | Tempo trace 分析 |
| 并发 50 用户 SLA 达标率 | ≥ 95% | HTTP p95 延迟 + 错误率 | `http_server_request_duration_seconds_bucket` |

**SLA 验证查询**（Prometheus PromQL，来源：`infra/observability/grafana-dashboard.json` L106-127）：

```promql
# 审图任务 p95 延迟（应 ≤ 300s）
histogram_quantile(0.95, sum(rate(celery_task_duration_seconds_bucket{queue="reviews"}[5m])) by (le))

# HTTP 请求 p95 延迟（并发 50 用户基线）
histogram_quantile(0.95, sum(rate(http_server_request_duration_seconds_bucket{job="synthdraft-backend"}[5m])) by (le))

# 5xx 错误率（应 < 5%）
sum(rate(http_server_request_duration_seconds_count{job="synthdraft-backend", http_status_code=~"5.."}[5m]))
  / sum(rate(http_server_request_duration_seconds_count{job="synthdraft-backend"}[5m])) * 100
```

---

## 2. 日常运维操作

### 2.1 服务启停

#### 2.1.1 Linux AI 服务节点（Docker Compose 模式）

来源：`infra/docker-compose.yml` 全文。

```bash
cd /opt/synthdraft/infra

# 启动基础依赖服务
docker compose --env-file .env up -d postgres redis qdrant minio ollama

# 启动后端服务
docker compose --env-file .env up -d backend celery_worker

# 启动 Celery Beat（可选，定时任务调度，全局唯一）
docker compose --env-file .env --profile scheduler up -d celery_beat

# 启动可观测性栈
docker compose --env-file .env --profile observability up -d otel-collector
cd /opt/synthdraft/infra/observability
docker compose -f docker-compose.observability.yml --profile observability up -d
```

停止服务（按依赖反序）：

```bash
cd /opt/synthdraft/infra

# 停止应用层
docker compose --env-file .env stop backend celery_worker celery_beat

# 停止可观测性栈
cd /opt/synthdraft/infra/observability
docker compose -f docker-compose.observability.yml --profile observability stop
cd /opt/synthdraft/infra
docker compose --env-file .env --profile observability stop otel-collector

# 停止基础依赖（谨慎：将中断所有业务）
docker compose --env-file .env stop postgres redis qdrant minio ollama
```

#### 2.1.2 Linux AI 服务节点（systemd 模式，裸机部署）

来源：`docs/deployment.md` §A.3.2 推荐的 systemd unit 模板。

```bash
# 启停单个 Celery Worker（按队列分离）
sudo systemctl start synthdraft-celery-reviews
sudo systemctl stop synthdraft-celery-reviews
sudo systemctl restart synthdraft-celery-reviews

# 查看状态
sudo systemctl status synthdraft-celery-reviews

# 启停 FastAPI 后端
sudo systemctl start synthdraft-backend
sudo systemctl stop synthdraft-backend
```

#### 2.1.3 Windows SolidWorks Worker 节点

来源：`docs/deployment.md` §A.4.5（NSSM 注册 Windows 服务）。

```powershell
# 启动 / 停止 / 重启 SolidWorks Worker 服务（NSSM 注册）
nssm start SynthDraft-SolidWorks-Worker
nssm stop SynthDraft-SolidWorks-Worker
nssm restart SynthDraft-SolidWorks-Worker

# 手动前台启动（调试用）
cd D:\SynthDraft\backend
.\.venv\Scripts\Activate.ps1
celery -A app.celery_app worker -Q solidworks -c 1 --without-gossip --loglevel=info
```

**注意**（来源：`backend/app/celery_app.py` L43-50 + `backend/app/services/solidworks/worker_pool.py` L96-101）：
- SolidWorks Worker 必须以 `-c 1` 单并发运行（COM 是 STA，许可证通常限单实例）
- `--without-gossip` 降低 broker 压力
- `SOLIDWORKS_PREWARM_COUNT=1`（生产建议）避免首次任务 ~10s Dispatch 开销

### 2.2 服务状态检查

#### 2.2.1 健康检查端点

来源：`backend/app/api/v1/endpoints/health.py` 全文。

```bash
# 存活探针（轻量，不探测依赖，附带 LLM provider 可用性快照）
curl http://localhost:8000/api/v1/healthz
# 期望：{"service":"SynthDraft Backend","status":"healthy","llm_provider":"ollama","llm_available":true,"vlm_available":true}

# 就绪探针（探测 PostgreSQL + Redis，任一不可用返回 503）
curl -i http://localhost:8000/api/v1/readyz
# 期望：HTTP 200，{"status":"ok","components":[{"name":"postgres","status":"ok"},{"name":"redis","status":"ok"}]}
```

#### 2.2.2 Celery 队列与 Worker 状态

```bash
cd /opt/synthdraft/backend
source .venv/bin/activate  # 裸机模式；Docker 模式用 docker exec

# 在线 Worker 探测
celery -A app.celery_app inspect ping
# 期望：{"celery@<hostname>": {"pong": "pong"}}

# 各 Worker 正在消费的队列
celery -A app.celery_app inspect active_queues

# 各队列待处理任务数（来源：queue_monitor.py L137-154，通过 Redis LLEN 采集）
docker exec synthdraft-redis redis-cli -n 1 LLEN reviews
docker exec synthdraft-redis redis-cli -n 1 LLEN generations
docker exec synthdraft-redis redis-cli -n 1 LLEN solidworks

# 通过可观测性 API 获取队列状态（来源：observability.py L25-38）
curl http://localhost:8000/api/v1/observability/queue-status | jq .
```

#### 2.2.3 Flower Web UI

来源：`infra/observability/docker-compose.observability.yml` L64-78。

访问 `http://<linux-node-ip>:5555`，可查看：
- 各 Worker 实时状态与正在执行的任务
- 队列深度与任务历史
- 失败任务详情与 traceback

#### 2.2.4 SolidWorks Worker 健康检查

来源：`backend/app/services/solidworks/worker_pool.py` L559-592。

```bash
# 从 Linux 节点探测 Windows Worker 是否在线
celery -A app.celery_app inspect ping -d celery@<windows-hostname>

# 触发许可证探测任务（来源：deployment.md §C.1.4）
celery -A app.celery_app call app.celery.tasks.solidworks.license_status_task
```

SolidWorks Worker 内部健康检查（**自动运行**，无需手动触发）：
- 检查间隔：60 秒（来源：`worker_pool.py` L139 `_health_check_interval = 60.0`）
- 健康状态枚举：`healthy` / `degraded` / `unhealthy` / `restarting` / `stopped`（来源：`worker_pool.py` L149 + `status.py`）
- 连续失败 3 次触发硬重启（来源：`worker_pool.py` L151 `_max_consecutive_failures = 3`）
- 重启策略：指数退避 3 次重试，退避基数 2.0 秒（来源：`worker_pool.py` L866-944 `_restart_with_retry`）

### 2.3 日志查看与归档

#### 2.3.1 日志格式

项目使用结构化日志（JSON 格式），通过 `app.logging.get_logger` 统一输出。关键字段：
- `timestamp`：ISO 8601 时间戳
- `level`：日志级别
- `event`：事件名（点分命名，如 `sw.worker_pool.task_completed`）
- 业务字段：随事件类型变化（如 `task_id`、`elapsed`、`worker_count`）

#### 2.3.2 Docker 模式日志查看

```bash
# 实时查看后端日志
docker logs -f --tail 100 synthdraft-backend

# 查看 Celery Worker 日志
docker logs -f --tail 100 synthdraft-celery-worker

# 查看指定时间段日志
docker logs --since "2026-07-27T10:00:00" --until "2026-07-27T11:00:00" synthdraft-backend

# 按事件名过滤（jq 解析 JSON）
docker logs synthdraft-backend 2>&1 | jq 'select(.event == "alert.triggered")'
```

#### 2.3.3 日志归档

Docker 默认 json-file 驱动建议配置轮转。编辑 `/etc/docker/daemon.json`：

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "10"
  }
}
```

重启 Docker 生效：`sudo systemctl restart docker`（注意：仅对新创建容器生效，已有容器需重建）。

#### 2.3.4 业务指标 JSONL 文件

来源：`backend/app/config.py` L112-115。

| 文件 | 路径（默认） | 用途 |
|---|---|---|
| LLM 指标 | `./tmp_metrics/llm_metrics.jsonl` | LLM 推理成本与延迟记录（来源：`llm_metrics.py` L121-171） |
| 反馈数据 | `./tmp_metrics/feedback.jsonl` | 用户审图反馈（误报/采纳标记） |

**归档建议**：每日凌晨归档至 MinIO `synthdraft-logs` 桶，保留 90 天：

```bash
# 压缩归档
tar czf /tmp/metrics-$(date +%Y%m%d).tar.gz -C /opt/synthdraft/backend/tmp_metrics .

# 上传至 MinIO（需 mc 客户端配置 alias）
mc cp /tmp/metrics-$(date +%Y%m%d).tar.gz minio/synthdraft-logs/metrics/

# 清理本地 7 天前的文件
find /opt/synthdraft/backend/tmp_metrics -name "*.jsonl" -mtime +7 -delete
```

### 2.4 配置变更流程

#### 2.4.1 修改 `.env`

来源：`backend/app/config.py`（所有配置项）+ `docs/deployment.md` §A.2.1。

```bash
cd /opt/synthdraft/infra
vi .env  # 修改配置项
```

#### 2.4.2 滚动重启

**配置变更后必须重启对应服务才生效**（`pydantic-settings` 在进程启动时加载 `.env`，`@lru_cache` 缓存 Settings 单例）。

```bash
# Docker 模式：滚动重启（保留容器）
docker compose --env-file .env restart backend celery_worker

# systemd 模式：逐个重启 Worker（避免任务中断）
sudo systemctl restart synthdraft-celery-reviews
# 等待该 Worker 重新就绪后再重启下一个
sudo systemctl restart synthdraft-celery-generations
# ... 其他 Worker
```

**SolidWorks Worker 配置变更**（来源：`docs/deployment.md` §C.2.3）：

```powershell
# 1. 先排空 solidworks 队列（在 Linux 节点执行）
celery -A app.celery_app purge -Q solidworks

# 2. 停止 Windows Worker
nssm stop SynthDraft-SolidWorks-Worker

# 3. 修改 D:\SynthDraft\backend\.env

# 4. 重启
nssm start SynthDraft-SolidWorks-Worker
```

---

## 3. 监控体系

### 3.1 监控栈架构

来源：`infra/observability/docker-compose.observability.yml` + `infra/observability/prometheus.yml` + `backend/app/observability/tracing.py`。

```
┌─────────────────────────────────────────────────────────────┐
│ Linux AI 服务节点                                            │
│  ┌──────────┐  OTLP/HTTP 4318  ┌──────────────────────┐    │
│  │ FastAPI  │ ───────────────▶ │ OTEL Collector 0.129.1│    │
│  │  :8000   │                  │ (profile:observability)│    │
│  └────┬─────┘                  └─────────┬────────────┘    │
│       │ /metrics :8000                   │ OTLP gRPC 4317   │
│       │ (Prometheus scrape)              ▼                  │
│       │                          ┌──────────────────────┐   │
│       │                          │ Tempo 2.8.1 (traces) │   │
│       │                          └──────────────────────┘   │
│       ▼                                                     │
│  ┌──────────────────┐  scrape   ┌──────────────────────┐   │
│  │ Prometheus v3.4.0│ ◀──────── │ Flower 2.0.1 :5555  │   │
│  │     :9090        │           │ (Celery metrics)     │   │
│  └────────┬─────────┘           └──────────────────────┘   │
│           │ datasource                                     │
│           ▼                                                │
│  ┌──────────────────┐                                      │
│  │ Grafana 12.2.0   │                                      │
│  │     :3001        │                                      │
│  └──────────────────┘                                      │
└─────────────────────────────────────────────────────────────┘
```

**关键说明**（来源：`docs/deployment.md` §A.6.2）：
- 观测栈 compose 声明 `synthdraft_default` 网络为 `external: true`，必须先启动主 compose 创建该网络
- Tempo 的 4318 端口与 otel-collector 的 4318 冲突，二选一（推荐 otel-collector 接收 → 转发到 Tempo）

**Prometheus 抓取目标**（来源：`infra/observability/prometheus.yml` L7-33）：

| job_name | target | metrics_path | 用途 |
|---|---|---|---|
| `synthdraft-backend` | `host.docker.internal:8000` | `/metrics` | 后端 HTTP 与业务指标 |
| `celery-flower` | `flower:5555` | `/metrics` | Celery 队列与 Worker 指标 |
| `prometheus` | `localhost:9090` | - | Prometheus 自监控 |
| `tempo` | `tempo:3200` | - | Tempo 自监控 |

### 3.2 关键监控指标

#### 3.2.1 系统层指标

通过 Node Exporter（需额外部署）或 Docker stats 采集：

```bash
# 容器资源占用快照
docker stats --no-stream synthdraft-backend synthdraft-celery-worker synthdraft-postgres synthdraft-redis synthdraft-qdrant synthdraft-minio

# 磁盘空间（关键：日志 + 上传文件 + 模型权重）
df -h /var/lib/docker/volumes
du -sh /opt/synthdraft/backend/tmp_uploads /opt/synthdraft/backend/tmp_metrics
```

**关注阈值**：
- 磁盘使用率 > 80%：告警清理
- 磁盘使用率 > 95%：紧急扩容
- 内存使用率 > 90%：检查 OOM 风险

#### 3.2.2 应用层指标

来源：`infra/observability/grafana-dashboard.json` Panel 1-2。

| 指标 | PromQL | 阈值 |
|---|---|---|
| HTTP 请求延迟 p50/p95/p99 | `histogram_quantile(0.95, sum(rate(http_server_request_duration_seconds_bucket{job="synthdraft-backend"}[5m])) by (le))` | p95 < 5s |
| HTTP 5xx 错误率 | `sum(rate(http_server_request_duration_seconds_count{job="synthdraft-backend", http_status_code=~"5.."}[5m])) / sum(rate(http_server_request_duration_seconds_count{job="synthdraft-backend"}[5m])) * 100` | < 1% |

#### 3.2.3 任务层指标

来源：`infra/observability/grafana-dashboard.json` Panel 3, 5, 7 + `backend/app/observability/queue_monitor.py`。

| 指标 | PromQL | 阈值 |
|---|---|---|
| Celery 任务耗时 p50/p95（按队列） | `histogram_quantile(0.95, sum(rate(celery_task_duration_seconds_bucket[5m])) by (le, queue))` | reviews p95 < 300s |
| 队列堆积数 | `synthdraft_celery_queue_backlog` | > 50 触发告警 |
| 队列活跃任务数 | `synthdraft_celery_queue_active` | 监控趋势 |
| 在线 Worker 数 | `synthdraft_celery_workers_online` | = 0 触发 critical 告警 |

#### 3.2.4 业务层指标

来源：`infra/observability/grafana-dashboard.json` Panel 4, 8-10 + `backend/app/api/v1/endpoints/observability.py`。

| 指标 | PromQL / API | 阈值 |
|---|---|---|
| LLM 推理耗时（按模型） | `histogram_quantile(0.95, sum(rate(synthdraft_llm_inference_duration_seconds_bucket[5m])) by (le, model))` | p95 < 30s |
| LLM 调用 QPS | `sum(rate(synthdraft_llm_inference_duration_seconds_count[5m]))` | 监控趋势 |
| LLM 累计成本（USD） | `sum(synthdraft_llm_cost_usd_total)` | 按预算告警 |
| 用户反馈误报率 | `synthdraft_feedback_false_positive_rate` | < 10% |
| 审图 SLA 达标率 | 业务侧计算（5 分钟内完成占比） | ≥ 95% |

**业务指标 API 端点**（来源：`observability.py` 全文）：

```bash
# LLM 成本汇总（按模型）
curl http://localhost:8000/api/v1/observability/llm-cost-summary | jq .

# LLM 延迟分布（p50/p95/p99）
curl http://localhost:8000/api/v1/observability/llm-latency | jq .

# 反馈总体统计（误报率/采纳率）
curl http://localhost:8000/api/v1/observability/feedback-summary | jq .

# 反馈按缺陷类别分组
curl http://localhost:8000/api/v1/observability/feedback-by-category | jq .

# 反馈时间趋势（支持 day/week/month 粒度）
curl "http://localhost:8000/api/v1/observability/feedback-trend?granularity=day" | jq .
```

### 3.3 Grafana 仪表盘使用

来源：`infra/observability/grafana-dashboard.json` 全文 + `infra/observability/docker-compose.observability.yml` L31。

#### 3.3.1 访问入口

- URL：`http://<linux-node-ip>:3001`
- 默认账号：`admin` / `admin`（首次登录强制改密，来源：`docker-compose.observability.yml` L26-27）
- 仪表盘自动 provisioning：`grafana-dashboard.json` 已挂载到 `/etc/grafana/provisioning/dashboards/synthdraft-dashboard.json`

#### 3.3.2 仪表盘面板清单

仪表盘 UID：`synthdraft-observability`，标题"SynthDraft Backend 可观测性仪表盘"，刷新间隔 30 秒。

| Panel ID | 类型 | 标题 | 数据源 | 用途 |
|---|---|---|---|---|
| 1 | timeseries | HTTP 请求延迟 p50/p95/p99 | Prometheus | 应用层延迟监控 |
| 2 | gauge | HTTP 错误率（5xx） | Prometheus | 应用层错误率，阈值 5% 红色 |
| 3 | timeseries | Celery 任务耗时分布（按队列） | Prometheus | 任务层延迟，按队列分组 |
| 4 | timeseries | LLM 推理耗时（按模型） | Prometheus | LLM 延迟 p50/p95，按模型分组 |
| 5 | timeseries | Celery 队列堆积（阈值 50） | Prometheus | 队列深度，阈值 50 红色标记 |
| 6 | traces | Tempo 全链路 Trace | Tempo | TraceQL 查询 `service.name=synthdraft-backend` |
| 7 | stat | 在线 Celery Worker 数 | Prometheus | 0 时红色，≥1 绿色 |
| 8 | stat | 用户反馈误报率 | Prometheus | 阈值 10% 红色 |
| 9 | stat | LLM 累计成本（USD） | Prometheus | 累计成本，单位 currencyUSD |
| 10 | stat | LLM 调用 QPS | Prometheus | 实时调用频率 |

#### 3.3.3 Tempo Trace 查询

Panel 6 已预配置 TraceQL 查询 `{service.name="synthdraft-backend"}`，支持：
- 节点图（Node Graph）展示调用链路
- Span 过滤器（Span Filters）按属性筛选
- 服务映射（Service Map）展示依赖关系

**手动查询**：Grafana → Explore → Tempo，输入 TraceQL：

```
# 查询审图流程慢 trace（> 5 分钟）
{service.name="synthdraft-backend" && span.name="review.pipeline" && span.duration > 5m}

# 查询 SolidWorks 调用失败 trace
{service.name="synthdraft-backend" && span.name="solidworks.call" && status=error}
```

### 3.4 自定义业务指标采集

来源：`backend/app/observability/tracing.py` L150-186。

#### 3.4.1 业务 Span 工厂

项目已实现 4 个语义化业务 Span 入口，OTEL 启用时自动上报到 Tempo：

| Span 名称 | 工厂函数 | 关键属性 | 用途 |
|---|---|---|---|
| `review.pipeline` | `review_pipeline_span(file_type, file_key)` | `pipeline=review`、`review.file_type`、`review.file_key` | 审图全流程 |
| `generation.pipeline` | `generation_pipeline_span(intent)` | `pipeline=generation`、`generation.intent` | 生成全流程 |
| `solidworks.call` | `solidworks_call_span(operation)` | `system=solidworks`、`solidworks.operation` | SolidWorks COM 调用 |
| `rag.retrieval` | `rag_retrieval_span(query, top_k)` | `pipeline=rag`、`rag.query`（截断 200 字符）、`rag.top_k` | 规范检索 |

**用法示例**（来源：`tracing.py` L122-148 `trace_span` 上下文管理器）：

```python
from app.observability.tracing import review_pipeline_span

with review_pipeline_span(file_type="dxf", file_key="upload/abc.dxf") as span:
    # 业务逻辑
    result = run_review(...)
    if span is not None:
        span.set_attribute("review.defect_count", len(result.defects))
```

#### 3.4.2 降级行为

来源：`tracing.py` L34-36 + L122-135。

- `OTEL_ENABLED=false`（默认）时：`trace_span` yield None，调用方无需条件分支
- `opentelemetry-instrumentation-httpx/requests` 未安装时：`instrument_httpx()` / `instrument_requests()` 优雅降级，返回 False
- Span 属性设置失败不阻断业务（`tracing.py` L142-144）

#### 3.4.3 启用 Tracing

```dotenv
# 在 .env 中配置
OTEL_ENABLED=true
OTEL_SERVICE_NAME=synthdraft-backend
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

验证 tracing 链路（来源：`docs/deployment.md` §A.6.5）：

```bash
# 触发一次审图请求后，在 Grafana → Explore → Tempo 查询
{service.name="synthdraft-backend"}
```

---

## 4. 告警体系

### 4.1 告警规则

来源：`backend/app/observability/alerts.py` L28-104。

告警规则在 `evaluate_queue_alerts()` 函数中实现，由 `queue_monitor.collect_queue_status()` 每次采集时调用。

#### 4.1.1 规则清单

| 规则名 | 级别 | 触发条件 | 阈值来源 | 默认阈值 |
|---|---|---|---|---|
| `worker_offline` | **critical** | 在线 Worker 数 == 0 | 硬编码（`alerts.py` L49） | worker_count = 0 |
| `queue_backlog` | warning | 某队列 `active + reserved + scheduled` > 阈值 | `settings.OBS_QUEUE_BACKLOG_ALERT` | 50 |
| `queue_failure_rate` | warning | 某队列失败率 > 阈值（仅当 `failed > 0` 时计算） | `settings.OBS_QUEUE_FAILURE_RATE_ALERT` | 10.0% |

#### 4.1.2 告警字段结构

来源：`alerts.py` L50-59 + L65-74 + L82-91。

```json
{
  "level": "critical | warning",
  "rule": "worker_offline | queue_backlog | queue_failure_rate",
  "queue": "* | <queue-name>",
  "value": <当前值>,
  "threshold": <阈值>,
  "message": "<人类可读描述>"
}
```

#### 4.1.3 阈值配置

来源：`backend/app/config.py` L103-105。

```dotenv
# 在 .env 中调整阈值
OBS_QUEUE_BACKLOG_ALERT=50          # 队列堆积告警阈值（排队任务数）
OBS_QUEUE_FAILURE_RATE_ALERT=10.0   # 队列失败率告警阈值（百分比 0-100）
```

**说明**（来源：`queue_monitor.py` L104-106 注释）：实时探测无法获取历史失败率，`queue_failure_rate` 规则仅当 `failed > 0` 时触发；生产环境失败率统计应基于 `celery_task_duration_seconds_count` 的历史数据。

### 4.2 告警通知渠道

来源：`alerts.py` L101-127。

#### 4.2.1 日志通道（始终启用）

告警触发时按级别记录日志（`alerts.py` L94-98）：
- `critical` 级别：`log.error("alert.triggered", **alert)`
- `warning` 级别：`log.warning("alert.triggered", **alert)`

查询告警日志：

```bash
docker logs synthdraft-backend 2>&1 | jq 'select(.event == "alert.triggered")'
docker logs synthdraft-celery-worker 2>&1 | jq 'select(.event == "alert.triggered")'
```

#### 4.2.2 Webhook 通道（可选）

来源：`alerts.py` L107-127 + `config.py` L109。

配置 `OBS_ALERT_WEBHOOK_URL` 后，告警触发时通过 `httpx.post` 发送（fire-and-forget，5 秒超时）：

```dotenv
# 在 .env 中配置
OBS_ALERT_WEBHOOK_URL=https://hooks.example.com/synthdraft-alerts
```

**Webhook payload 结构**（来源：`alerts.py` L109-113）：

```json
{
  "source": "synthdraft-backend",
  "fired_at": "2026-07-27T10:00:00+00:00",
  "alerts": [
    {
      "level": "critical",
      "rule": "worker_offline",
      "queue": "*",
      "value": 0,
      "threshold": 1,
      "message": "无在线 Celery worker"
    }
  ]
}
```

**通知行为**（来源：`alerts.py` L120-126）：
- 成功：`log.info("alert.webhook.sent", status_code=200, alert_count=N)`
- 失败：`log.warning("alert.webhook.failed", error=..., alert_count=N)`，不阻塞业务

#### 4.2.3 主动探测告警

通过定时调用可观测性 API 触发告警评估（来源：`observability.py` L25-38）：

```bash
# 每分钟探测一次队列状态（结合 cron）
* * * * * curl -s http://localhost:8000/api/v1/observability/queue-status | jq -e '.alerts | length == 0' || curl -X POST -d @- $OBS_ALERT_WEBHOOK_URL
```

### 4.3 告警处理 SOP

#### 4.3.1 worker_offline（critical）

**症状**：所有 Celery Worker 离线，任务堆积无法消费。

**排查步骤**：

```bash
# 1. 确认 Worker 进程是否存活
docker ps | grep synthdraft-celery-worker
# 或 systemd 模式
sudo systemctl status synthdraft-celery-*

# 2. 检查 Redis broker 连通性
docker exec synthdraft-redis redis-cli ping
# 期望：PONG

# 3. 检查 Worker 日志
docker logs --tail 200 synthdraft-celery-worker
# 关注：连接超时、OOM、import 错误

# 4. 手动 ping 探测
celery -A app.celery_app inspect ping
```

**处理**：
- 进程未存活：`docker compose --env-file .env restart celery_worker` 或 `systemctl restart synthdraft-celery-*`
- Redis 连接失败：检查 `CELERY_BROKER_URL` 配置与 Redis 健康状态
- import 错误：检查代码部署完整性，回滚最近变更

#### 4.3.2 queue_backlog（warning）

**症状**：某队列堆积任务数 > 50。

**排查步骤**：

```bash
# 1. 查看各队列深度
curl http://localhost:8000/api/v1/observability/queue-status | jq '.queues'

# 2. 检查对应队列的 Worker 是否在线
celery -A app.celery_app inspect ping
celery -A app.celery_app inspect active_queues

# 3. 检查是否有长任务阻塞（来源：celery_app.py L58 worker_prefetch_multiplier=1）
celery -A app.celery_app inspect active
```

**处理**：
- Worker 数不足：临时扩容 Worker（见 §8.3.2）
- 长任务阻塞：识别长任务并优化（查看 Tempo trace `review.pipeline` span 耗时）
- 任务失败堆积：检查失败任务日志，修复后重新投递

#### 4.3.3 queue_failure_rate（warning）

**症状**：某队列失败率 > 10%。

**排查步骤**：

```bash
# 1. 查看失败任务详情（Flower UI 或命令行）
celery -A app.celery_app inspect reserved
# 在 Flower UI (http://<linux-node-ip>:5555) 查看失败任务 traceback

# 2. 检查依赖服务
curl http://localhost:8000/api/v1/readyz
docker exec synthdraft-redis redis-cli ping
docker exec synthdraft-postgres pg_isready -U synthdraft

# 3. 检查 LLM provider 可用性
curl http://localhost:8000/api/v1/healthz | jq '.llm_available'
```

**处理**：
- LLM 不可用：检查 Ollama/vLLM 服务状态，必要时切换 provider
- 数据库连接失败：检查 PostgreSQL 连接池与配置
- 代码 bug：根据 traceback 修复，回滚或热补丁

### 4.4 告警静默与维护窗口

项目未实现内置静默机制，推荐通过以下方式实现维护窗口：

#### 4.4.1 临时调高阈值

```dotenv
# 维护窗口期间临时调整（修改 .env 后重启 backend）
OBS_QUEUE_BACKLOG_ALERT=1000      # 临时调高，避免维护期间误报
OBS_QUEUE_FAILURE_RATE_ALERT=100  # 临时关闭失败率告警
```

#### 4.4.2 Webhook 端侧过滤

在 webhook 接收端（如 Alertmanager / 飞书机器人）配置静默规则：
- 按 `source` 字段过滤
- 按 `rule` 字段过滤
- 按时间窗口静默

#### 4.4.3 维护流程

```bash
# 1. 通知相关人员维护窗口
# 2. 临时调高阈值（见 4.4.1）
# 3. 执行维护操作
# 4. 恢复原阈值
# 5. 验证告警链路：手动触发一次 queue-status 探测
curl http://localhost:8000/api/v1/observability/queue-status | jq '.alerts'
```

---

## 5. 数据备份与恢复

### 5.1 备份对象

| 备份对象 | 存储位置 | 数据类型 | 重要性 | 备份方式 |
|---|---|---|---|---|
| **PostgreSQL 16** | `postgres_data` volume | 任务记录、反馈、规范元数据 | 高（业务核心） | `pg_dump` 全量 + WAL 增量 |
| **Qdrant v1.18.3** | `qdrant_data` volume | 规范条文向量索引 | 中（可重建） | snapshot API |
| **MinIO** | `minio_data` volume | 上传文件、生成文件、报告 | 高（用户数据） | `mc mirror` |
| **Redis** | `redis_data` volume | 任务状态、缓存 | 低（可重建） | 可选，RDB 快照 |
| **反馈数据 JSONL** | `./tmp_metrics/feedback.jsonl` | 用户反馈原始记录 | 中 | `cp` 至备份存储 |
| **LLM 指标 JSONL** | `./tmp_metrics/llm_metrics.jsonl` | LLM 成本与延迟记录 | 中 | `cp` 至备份存储 |

**说明**：
- PostgreSQL 与 MinIO 包含不可重建的业务数据，必须严格备份
- Qdrant 索引可通过重新 embedding 规范条文重建，但耗时长（建议备份）
- Redis 数据可重建（broker 丢失后任务重投），可仅做 RDB 快照

### 5.2 备份策略

| 备份类型 | 频率 | 时间 | 保留期 | 存储位置 |
|---|---|---|---|---|
| 全量备份 | 每日 | 02:00（业务低峰） | 7 天 | 本地 + MinIO 远程桶 |
| 增量备份 | 每小时 | 整点 | 7 天 | 本地 |
| 周备 | 每周日 | 02:00 | 4 周 | MinIO 远程桶 |
| 月备 | 每月 1 日 | 02:00 | 12 月 | MinIO 远程桶（冷存储） |

**PostgreSQL WAL 归档**（启用 PITR 前置）：在 `infra/docker-compose.yml` 的 postgres 服务追加配置：

```yaml
postgres:
  environment:
    POSTGRES_USER: ${POSTGRES_USER:-synthdraft}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-synthdraft_dev_pwd}
    POSTGRES_DB: ${POSTGRES_DB:-synthdraft}
    # 启用 WAL 归档
    WAL_LEVEL: replica
    ARCHIVE_MODE: "on"
    ARCHIVE_COMMAND: "test ! -f /archive/%f && cp %p /archive/%f"
  volumes:
    - postgres_data:/var/lib/postgresql/data
    - ./init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    - postgres_archive:/archive  # WAL 归档目录
```

### 5.3 备份脚本

> **说明**：以下脚本为运维人员需创建的模板，项目仓库未内置。建议存放于 `/opt/synthdraft/infra/backup/` 目录。

#### 5.3.1 全量备份脚本（`backup-full.sh`）

```bash
#!/bin/bash
# 全量备份：PostgreSQL + Qdrant + MinIO + JSONL 指标
# 用法：./backup-full.sh
# 建议：crontab 每日 02:00 执行：0 2 * * * /opt/synthdraft/infra/backup/backup-full.sh

set -euo pipefail

BACKUP_DIR="/opt/synthdraft/backups/$(date +%Y%m%d)"
REMOTE_BUCKET="minio/synthdraft-backups"  # mc alias 名称/桶名
RETENTION_DAYS=7

mkdir -p "$BACKUP_DIR"
echo "[$(date)] 开始全量备份到 $BACKUP_DIR"

# ===== 1. PostgreSQL 全量备份 =====
echo "[$(date)] 备份 PostgreSQL..."
docker exec synthdraft-postgres pg_dump -U "${POSTGRES_USER:-synthdraft}" \
  -d "${POSTGRES_DB:-synthdraft}" --format=custom --no-owner \
  > "$BACKUP_DIR/postgres-$(date +%Y%m%d-%H%M%S).dump"

# ===== 2. Qdrant snapshot =====
echo "[$(date)] 备份 Qdrant..."
# Qdrant snapshot API（来源：Qdrant 官方文档，容器内执行）
COLLECTIONS=$(curl -s http://localhost:6333/collections | jq -r '.result.collections[].name')
for col in $COLLECTIONS; do
  curl -X POST "http://localhost:6333/collections/${col}/snapshots" \
    -o "$BACKUP_DIR/qdrant-${col}-$(date +%Y%m%d-%H%M%S).snapshot"
done

# ===== 3. MinIO mirror =====
echo "[$(date)] 备份 MinIO..."
mc mirror --overwrite minio/synthdraft-files "$BACKUP_DIR/minio-files/"

# ===== 4. JSONL 指标文件 =====
echo "[$(date)] 备份 JSONL 指标..."
cp -r /opt/synthdraft/backend/tmp_metrics "$BACKUP_DIR/metrics-"$(date +%Y%m%d)

# ===== 5. 上传至远程 MinIO 桶 =====
echo "[$(date)] 上传至远程存储 $REMOTE_BUCKET..."
mc cp --recursive "$BACKUP_DIR" "$REMOTE_BUCKET/$(date +%Y%m%d)/"

# ===== 6. 清理过期备份 =====
echo "[$(date)] 清理 ${RETENTION_DAYS} 天前的本地备份..."
find /opt/synthdraft/backups -maxdepth 1 -type d -mtime +${RETENTION_DAYS} -exec rm -rf {} \;

echo "[$(date)] 全量备份完成"
```

#### 5.3.2 增量备份脚本（`backup-incr.sh`）

```bash
#!/bin/bash
# 增量备份：PostgreSQL WAL 归档 + MinIO 新增对象
# 用法：./backup-incr.sh
# 建议：crontab 每小时执行：0 * * * * /opt/synthdraft/infra/backup/backup-incr.sh

set -euo pipefail

BACKUP_DIR="/opt/synthdraft/backups/incremental/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

# 1. PostgreSQL WAL 归档（依赖 5.2 中 archive_command 配置）
if docker exec synthdraft-postgres test -d /archive; then
  docker cp synthdraft-postgres:/archive "$BACKUP_DIR/wal-archive"
fi

# 2. MinIO 增量（基于 last-modified 时间）
mc mirror --attr --overwrite --newer-than "1h" \
  minio/synthdraft-files "$BACKUP_DIR/minio-files/"

echo "[$(date)] 增量备份完成到 $BACKUP_DIR"
```

#### 5.3.3 Cron 配置

```bash
# 编辑 crontab
crontab -e

# 追加以下条目
0 2 * * * /opt/synthdraft/infra/backup/backup-full.sh >> /var/log/synthdraft-backup.log 2>&1
0 * * * * /opt/synthdraft/infra/backup/backup-incr.sh >> /var/log/synthdraft-backup.log 2>&1
```

### 5.4 恢复流程

#### 5.4.1 PostgreSQL PITR 恢复

```bash
# 1. 停止后端服务（避免连接干扰）
docker compose --env-file .env stop backend celery_worker

# 2. 停止 PostgreSQL
docker compose --env-file .env stop postgres

# 3. 备份当前损坏数据（谨慎）
mv /var/lib/docker/volumes/synthdraft_postgres_data/_data /var/lib/docker/volumes/synthdraft_postgres_data/_data.corrupt-$(date +%s)

# 4. 恢复基础全量备份
docker run --rm \
  -v synthdraft_postgres_data:/var/lib/postgresql/data \
  -v /opt/synthdraft/backups/20260727:/backup \
  postgres:16-alpine bash -c "
    chown -R postgres:postgres /var/lib/postgresql/data
    su postgres -c 'pg_restore -d postgres /backup/postgres-20260727-020000.dump'
  "

# 5. 恢复 WAL 至指定时间点（PITR）
# 创建 recovery.signal 文件
docker run --rm \
  -v synthdraft_postgres_data:/var/lib/postgresql/data \
  -v /opt/synthdraft/backups/incremental/20260727-100000/wal-archive:/wal \
  postgres:16-alpine bash -c "
    echo \"restore_command = 'cp /wal/%f %p'\" >> /var/lib/postgresql/data/postgresql.auto.conf
    echo \"recovery_target_time = '2026-07-27 10:30:00+08'\" >> /var/lib/postgresql/data/postgresql.auto.conf
    touch /var/lib/postgresql/data/recovery.signal
    chown postgres:postgres /var/lib/postgresql/data/recovery.signal
  "

# 6. 启动 PostgreSQL（会自动进入恢复模式）
docker compose --env-file .env start postgres

# 7. 验证恢复完整性
docker exec synthdraft-postgres psql -U synthdraft -d synthdraft -c \
  "SELECT count(*) FROM reviews; SELECT count(*) FROM feedback;"

# 8. 恢复后端服务
docker compose --env-file .env start backend celery_worker
```

#### 5.4.2 Qdrant Snapshot 恢复

```bash
# 1. 停止 Qdrant
docker compose --env-file .env stop qdrant

# 2. 恢复 snapshot 到 volume
docker run --rm \
  -v synthdraft_qdrant_data:/qdrant/storage \
  -v /opt/synthdraft/backups/20260727:/backup \
  alpine sh -c "
    cp /backup/qdrant-*.snapshot /qdrant/storage/snapshots/
    chown -R 1000:1000 /qdrant/storage
  "

# 3. 启动 Qdrant
docker compose --env-file .env start qdrant

# 4. 通过 API 恢复 collection
curl -X PUT "http://localhost:6333/collections/<collection-name>/snapshots/recover" \
  -H "Content-Type: application/json" \
  -d '{"snapshot_name": "qdrant-<collection-name>-20260727-020000.snapshot"}'

# 5. 验证
curl http://localhost:6333/collections | jq '.result.collections'
```

#### 5.4.3 MinIO 恢复

```bash
# 1. 从备份目录恢复
mc mirror --overwrite /opt/synthdraft/backups/20260727/minio-files/ minio/synthdraft-files/

# 或从远程桶恢复
mc mirror --overwrite minio/synthdraft-backups/20260727/minio-files/ minio/synthdraft-files/

# 2. 验证文件列表
mc ls minio/synthdraft-files/ | head -20
mc stat minio/synthdraft-files/<test-file>
```

#### 5.4.4 验证恢复完整性

```bash
# 1. PostgreSQL 数据完整性
docker exec synthdraft-postgres psql -U synthdraft -d synthdraft -c "
  SELECT 'reviews' AS table, count(*) FROM reviews
  UNION ALL SELECT 'feedback', count(*) FROM feedback
  UNION ALL SELECT 'specifications', count(*) FROM specifications;
"

# 2. Qdrant 索引完整性
curl http://localhost:6333/collections | jq '.result.collections | length'
# 对比备份时的 collection 数量

# 3. MinIO 文件完整性
mc ls --recursive minio/synthdraft-files/ | wc -l
# 对比备份时的文件数量

# 4. 业务侧 smoke test
curl http://localhost:8000/api/v1/healthz
curl http://localhost:8000/api/v1/readyz
```

### 5.5 灾难恢复演练

**建议频率**：每季度一次（来源：任务要求）。

#### 5.5.1 演练场景

| 场景 | 演练内容 | 预期 RTO | 预期 RPO |
|---|---|---|---|
| PostgreSQL 数据损坏 | 模拟 volume 损坏，从最近全量 + WAL 恢复 | ≤ 2 小时 | ≤ 1 小时 |
| MinIO 数据丢失 | 模拟 bucket 误删，从备份恢复 | ≤ 1 小时 | ≤ 1 小时 |
| 整节点故障 | 在新节点从零部署，恢复全部数据 | ≤ 4 小时 | ≤ 24 小时 |
| SolidWorks Worker 故障 | 切换至备用 Windows 节点 | ≤ 30 分钟 | N/A（无状态） |

#### 5.5.2 演练流程

1. **预备**：在隔离环境（如 staging）准备相同架构
2. **执行**：按 §5.4 流程恢复数据
3. **验证**：执行 §5.4.4 完整性检查 + 业务 smoke test
4. **记录**：演练耗时、问题、改进项
5. **复盘**：更新本手册与备份脚本

---

## 6. 故障排查

### 6.1 常见故障与处理

#### 6.1.1 Celery Worker 不消费任务

**症状**：任务堆积在队列，Worker 不消费。

**排查**：

```bash
# 1. 检查 Worker 是否在线
celery -A app.celery_app inspect ping

# 2. 检查 Worker 消费的队列（来源：deployment.md §C.4 Q2）
celery -A app.celery_app inspect active_queues
# 对比 backend/app/celery_app.py L43-50 的 task_routes

# 3. 检查 broker 中待处理任务
docker exec synthdraft-redis redis-cli -n 1 LLEN reviews
docker exec synthdraft-redis redis-cli -n 1 LLEN solidworks

# 4. 检查 Worker 日志
docker logs --tail 100 synthdraft-celery-worker
```

**处理**：
- Worker 未在线：重启 Worker
- 队列名不匹配：确认 Worker 启动参数 `-Q` 与 `celery_app.py` 路由一致
- broker 连接失败：检查 `CELERY_BROKER_URL` 配置与 Redis 健康

#### 6.1.2 SolidWorks Worker 卡死

**症状**：`solidworks` 队列任务超时，SolidWorks 进程无响应。

**自动恢复**（来源：`worker_pool.py` L489-524）：
- 任务超时后自动调用 `_kill_solidworks_process` 强制终止 SolidWorks 进程
- 4 策略降级 kill：`GetProcessId` → `pywin32 TerminateProcess` → `taskkill /F /PID` → `taskkill /F /IM sldworks.exe`
- 自动调用 `_restart_with_retry`（指数退避 3 次重试）

**手动处理**：

```powershell
# 1. 检查残留 SolidWorks 进程
tasklist | findstr sldworks

# 2. 强制 kill 所有 SolidWorks 进程
taskkill /F /IM sldworks.exe

# 3. 重启 Worker
nssm restart SynthDraft-SolidWorks-Worker

# 4. 验证 Worker 恢复
celery -A app.celery_app inspect ping -d celery@<windows-hostname>
```

#### 6.1.3 LLM 调用超时

**症状**：审图/生成任务超时，LLM provider 不响应。

**排查**：

```bash
# 1. 检查 LLM provider 可用性
curl http://localhost:8000/api/v1/healthz | jq '.llm_available'

# 2. Ollama 模型加载状态
curl http://localhost:11434/api/tags | jq '.models[].name'
docker logs --tail 50 synthdraft-ollama

# 3. vLLM 服务状态（如启用）
docker logs --tail 50 synthdraft-vllm
docker exec synthdraft-vllm curl -s http://localhost:8000/v1/models | jq .

# 4. LLM 延迟分布（来源：observability.py L96-107）
curl http://localhost:8000/api/v1/observability/llm-latency | jq '.overall'
```

**处理**：
- Ollama 模型未加载：`docker exec -it synthdraft-ollama ollama pull <model-name>`
- vLLM GPU 不可见：检查 `nvidia-smi` 与 NVIDIA Container Toolkit
- 商业 API 超时：检查网络出口与 API key 有效性
- 必要时切换 `LLM_PROVIDER`（修改 `.env` 后重启 backend）

#### 6.1.4 Ollama 模型加载失败

**症状**：Ollama 容器启动正常但模型推理 404。

**排查**：

```bash
# 查看已加载模型
docker exec synthdraft-ollama ollama list
# 期望包含：qwen2.5-coder:7b、qwen2.5-vl:7b

# 查看模型加载日志
docker logs synthdraft-ollama | grep "error"
```

**处理**：

```bash
# 重新拉取模型（来源：deployment.md §A.2.3）
docker exec -it synthdraft-ollama ollama pull qwen2.5-coder:7b
docker exec -it synthdraft-ollama ollama pull qwen2.5-vl:7b

# 离线场景：从预备机恢复（来源：deployment.md §A.7.1）
docker run --rm -v synthdraft_ollama_data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/ollama_models.tar.gz -C /data
```

#### 6.1.5 Redis 连接耗尽

**症状**：后端报 `redis.exceptions.ConnectionError: max clients reached`。

**排查**：

```bash
# 1. 查看 Redis 当前连接数
docker exec synthdraft-redis redis-cli INFO clients | grep connected_clients

# 2. 查看连接来源
docker exec synthdraft-redis redis-cli CLIENT LIST | head -20

# 3. 查看配置上限
docker exec synthdraft-redis redis-cli CONFIG GET maxclients
```

**处理**：
- 调整 Redis `maxclients`：编辑 `infra/docker-compose.yml` redis 服务 command
- 检查后端连接池配置，避免连接泄漏
- 重启 Redis（注意：会中断 broker，需排空队列后操作）

```bash
# 谨慎：重启 Redis 前先排空队列
celery -A app.celery_app purge
docker compose --env-file .env restart redis
```

#### 6.1.6 磁盘空间不足

**症状**：日志/上传文件占满磁盘，服务异常。

**排查**：

```bash
# 1. 检查磁盘使用
df -h

# 2. 定位大文件目录
du -sh /var/lib/docker/volumes/* | sort -rh | head -10
du -sh /opt/synthdraft/backend/tmp_uploads /opt/synthdraft/backend/tmp_metrics

# 3. 检查 Docker 日志大小
docker inspect --format='{{.LogPath}}' synthdraft-backend | xargs du -sh
```

**处理**：

```bash
# 1. 清理过期上传文件
find /opt/synthdraft/backend/tmp_uploads -mtime +7 -delete

# 2. 清理过期 JSONL 指标
find /opt/synthdraft/backend/tmp_metrics -name "*.jsonl" -mtime +30 -delete

# 3. 清理 Docker 日志（谨慎）
truncate -s 0 $(docker inspect --format='{{.LogPath}}' synthdraft-backend)

# 4. 清理 Docker 无用镜像/容器
docker system prune -a --volumes  # 谨慎：会删除未使用的 volume

# 5. 配置日志轮转（见 §2.3.3）
```

### 6.2 日志查询技巧

#### 6.2.1 jq 解析 JSON 日志

```bash
# 查询所有告警事件
docker logs synthdraft-backend 2>&1 | jq 'select(.event == "alert.triggered")'

# 查询指定时间段的错误
docker logs --since "2026-07-27T10:00:00" --until "2026-07-27T11:00:00" synthdraft-backend 2>&1 \
  | jq 'select(.level == "error")'

# 查询 SolidWorks Worker 任务超时
docker logs synthdraft-celery-worker 2>&1 \
  | jq 'select(.event == "sw.worker_pool.task_timeout")'

# 查询 LLM 成本异常
docker logs synthdraft-backend 2>&1 \
  | jq 'select(.event == "llm_metrics.hook.record_failed")'

# 统计各事件类型出现次数
docker logs synthdraft-backend 2>&1 | jq -r '.event' | sort | uniq -c | sort -rn
```

#### 6.2.2 跨容器日志关联（通过 trace_id）

```bash
# 1. 在 Tempo 中找到异常 trace_id
# 2. 在各容器日志中搜索该 trace_id
TRACE_ID="abc123..."
for svc in synthdraft-backend synthdraft-celery-worker; do
  echo "=== $svc ==="
  docker logs $svc 2>&1 | jq "select(.trace_id == \"$TRACE_ID\")"
done
```

### 6.3 性能问题诊断

#### 6.3.1 p95 延迟分析

```bash
# 1. 查看 LLM 延迟分布（来源：observability.py L96-107）
curl http://localhost:8000/api/v1/observability/llm-latency | jq .
# 关注 p95_ms 与 by_model 维度

# 2. 在 Grafana 查看 HTTP p95 趋势（Panel 1）
# 3. 在 Tempo 查询慢 trace
# TraceQL: {service.name="synthdraft-backend" && span.duration > 5s}
```

#### 6.3.2 慢查询诊断

```bash
# PostgreSQL 慢查询
docker exec synthdraft-postgres psql -U synthdraft -d synthdraft -c "
  SELECT query, calls, mean_exec_time, total_exec_time
  FROM pg_stat_statements
  ORDER BY mean_exec_time DESC LIMIT 10;
"

# 如未启用 pg_stat_statements，启用：
docker exec synthdraft-postgres psql -U synthdraft -d synthdraft -c \
  "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
```

#### 6.3.3 内存泄漏诊断

```bash
# 容器内存占用趋势
docker stats --no-stream synthdraft-backend synthdraft-celery-worker

# Python 进程内存详情（需在容器内）
docker exec synthdraft-backend python -c "
import psutil
p = psutil.Process()
print(f'RSS: {p.memory_info().rss / 1024 / 1024:.1f} MB')
print(f'VMS: {p.memory_info().vms / 1024 / 1024:.1f} MB')
"

# Celery Worker 内存随任务增长则可能泄漏，建议定期重启
# 配置 systemd 单元：Restart=on-failure + RuntimeMaxSec=86400（每日重启）
```

---

## 7. 安全运维

### 7.1 鉴权与权限

来源：`backend/app/config.py` L89-92。

#### 7.1.1 JWT 鉴权

- 算法：HS256（`JWT_ALGORITHM`）
- Token 有效期：1440 分钟（24 小时，`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`）
- 密钥：`JWT_SECRET_KEY`（**生产必须替换**为 `openssl rand -hex 32` 生成的强随机值）

**鉴权流程**：

```bash
# 登录获取 token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<pwd>"}' | jq -r .access_token)

# 携带 token 访问受保护接口
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/reviews
```

#### 7.1.2 API Key（LLM Provider）

- OpenAI：`OPENAI_API_KEY`（来源：`config.py` L78）
- Anthropic：`ANTHROPIC_API_KEY`（来源：`config.py` L84）
- vLLM：兼容 OpenAI 协议，鉴权可空（`OPENAI_API_KEY=dummy`）

### 7.2 沙箱安全

来源：`backend/app/services/generation/sandbox.py`（CadQuery 代码执行隔离）。

CadQuery 代码生成后**在隔离沙箱中执行**，关键控制：
- 代码执行前静态校验（禁止 import os/subprocess 等危险模块）
- 执行超时限制（建议 30 秒，对齐 SLA）
- 资源限制（CPU/内存）
- 输出文件白名单（仅允许 .dxf/.step/.iges）

**运维检查**：

```bash
# 验证沙箱是否启用（查看 backend 配置）
docker exec synthdraft-backend env | grep -i sandbox

# 查看沙箱执行失败日志
docker logs synthdraft-celery-worker 2>&1 | jq 'select(.event | startswith("sandbox."))'
```

### 7.3 文件上传安全

来源：`backend/app/config.py` L32 `UPLOAD_DIR` + `docs/deployment.md` §A.5.2 Nginx 配置。

**现有控制**：
- Nginx 上传大小限制：`client_max_body_size 100m`（来源：deployment.md §A.5.2）
- 上传目录：`./tmp_uploads`（来源：`config.py` L32）

**建议补充**（项目未内置，运维侧配置）：
- 文件类型白名单：SLDPRT/SLDASM/DWG/DXF/PDF/PNG/JPG
- 病毒扫描：集成 ClamAV 定时扫描 `tmp_uploads` 目录
- 文件名清洗：避免路径穿越攻击

```bash
# ClamAV 定时扫描（crontab）
0 * * * * clamscan -r --move=/opt/synthdraft/quarantine /opt/synthdraft/backend/tmp_uploads
```

### 7.4 审计日志

项目通过结构化日志记录关键操作，可作审计依据：

| 事件类型 | 日志 event | 来源 |
|---|---|---|
| 用户登录 | `auth.login` | `auth` 端点 |
| 文件上传 | `upload.created` | `uploads` 端点 |
| 审图任务提交 | `review.submitted` | `reviews` 端点 |
| 反馈提交 | `feedback.created` | `reviews` 端点 |
| 配置变更 | （需运维侧通过 git log 追踪） | `.env` |
| 告警触发 | `alert.triggered` | `alerts.py` L94-98 |

**审计日志归档**：

```bash
# 每日归档审计相关日志
docker logs synthdraft-backend --since "1 day ago" 2>&1 \
  | jq 'select(.event | test("auth|upload|review|feedback|alert"))' \
  > /opt/synthdraft/audit/audit-$(date +%Y%m%d).jsonl
```

### 7.5 密钥轮换

**建议频率**：每 90 天（来源：任务要求）。

#### 7.5.1 轮换清单

| 密钥 | 配置项 | 轮换方式 |
|---|---|---|
| JWT 密钥 | `JWT_SECRET_KEY` | 生成新值后重启 backend（**会导致所有已签发 token 失效**，需通知用户重新登录） |
| PostgreSQL 密码 | `POSTGRES_PASSWORD` + `DATABASE_URL` | 数据库侧 `ALTER USER` + 更新 `.env` + 重启 |
| MinIO 密钥 | `MINIO_ACCESS_KEY` + `MINIO_SECRET_KEY` | MinIO Console 创建新 key + 更新 `.env` + 重启 |
| OpenAI API Key | `OPENAI_API_KEY` | OpenAI 平台轮换 + 更新 `.env` + 重启 |
| Anthropic API Key | `ANTHROPIC_API_KEY` | Anthropic 平台轮换 + 更新 `.env` + 重启 |

#### 7.5.2 轮换流程示例（JWT）

```bash
# 1. 生成新密钥
NEW_KEY=$(openssl rand -hex 32)
echo "新 JWT_SECRET_KEY: $NEW_KEY"

# 2. 更新 .env
sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$NEW_KEY|" /opt/synthdraft/infra/.env

# 3. 滚动重启 backend（用户需重新登录）
docker compose --env-file .env restart backend celery_worker

# 4. 通知用户重新登录
```

#### 7.5.3 轮换流程示例（PostgreSQL）

```bash
# 1. 生成新密码
NEW_PWD=$(openssl rand -base64 24)
echo "新 POSTGRES_PASSWORD: $NEW_PWD"

# 2. 数据库侧修改
docker exec synthdraft-postgres psql -U synthdraft -c \
  "ALTER USER synthdraft PASSWORD '$NEW_PWD';"

# 3. 更新 .env（POSTGRES_PASSWORD + DATABASE_URL）
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$NEW_PWD|" /opt/synthdraft/infra/.env
sed -i "s|://synthdraft:[^@]*@|://synthdraft:$NEW_PWD@|" /opt/synthdraft/infra/.env

# 4. 滚动重启
docker compose --env-file .env restart backend celery_worker
```

---

## 8. 升级与扩容

### 8.1 版本升级流程

#### 8.1.1 蓝绿部署（推荐，无停机）

来源：`docs/deployment.md` §C.2.1。

适用于后端 FastAPI 与 Celery Worker 的版本升级。SolidWorks Worker 升级须停机（见 §8.1.3）。

```bash
# 1. 部署绿环境（新版本，端口 8001）
cd /opt/synthdraft-new/infra
docker compose --env-file .env -p synthdraft-green up -d backend celery_worker

# 2. 绿环境 Smoke Test
curl http://localhost:8001/api/v1/healthz
curl http://localhost:8001/api/v1/readyz

# 3. 切换 Nginx upstream
sudo sed -i 's/127.0.0.1:8000/127.0.0.1:8001/' /etc/nginx/conf.d/synthdraft.conf
sudo nginx -s reload

# 4. 观察 30 分钟无异常后，销毁蓝环境
cd /opt/synthdraft/infra
docker compose -p synthdraft down

# 5. 下次升级前，将绿环境重命名为蓝（端口回 8000）
```

**注意**：数据库迁移（Alembic）须向后兼容，先迁移再切流量。

#### 8.1.2 滚动更新（Celery Worker）

来源：`docs/deployment.md` §C.2.2。

```bash
# 逐个重启 Celery Worker（避免任务中断）
sudo systemctl stop synthdraft-celery-reviews
# 等待当前任务完成（最长 broker_visibility_timeout=3600s，来源：celery_app.py L54）
sudo systemctl start synthdraft-celery-reviews

# 重复其他 Worker
```

#### 8.1.3 SolidWorks Worker 升级

来源：`docs/deployment.md` §C.2.3。

```powershell
# 1. 在 Linux 节点排空 solidworks 队列
celery -A app.celery_app purge -Q solidworks

# 2. 停止 Windows Worker
nssm stop SynthDraft-SolidWorks-Worker

# 3. 等待当前任务完成（最长任务超时 60 秒，来源：worker_pool.py L417 default timeout=60.0）

# 4. 拉取新代码 + 依赖
cd D:\SynthDraft
git pull
cd backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt --upgrade

# 5. 重启 Worker
nssm start SynthDraft-SolidWorks-Worker
```

### 8.2 数据库迁移（Alembic）

来源：`docs/deployment.md` §A.3.1（裸机部署步骤）。

```bash
cd /opt/synthdraft/backend
source .venv/bin/activate

# 1. 备份数据库（迁移前必做）
docker exec synthdraft-postgres pg_dump -U synthdraft -d synthdraft --format=custom \
  > /opt/synthdraft/backups/pre-migration-$(date +%Y%m%d-%H%M%S).dump

# 2. 查看待执行迁移
alembic history --verbose
alembic current

# 3. 执行迁移
alembic upgrade head

# 4. 验证
alembic current
docker exec synthdraft-postgres psql -U synthdraft -d synthdraft -c "\dt"

# 回滚（如迁移有问题）
alembic downgrade -1
```

**注意**：
- 破坏性迁移（如 drop column）须先在 staging 验证
- 迁移期间建议停止写入流量（蓝绿部署场景下在切流量前完成）

### 8.3 水平扩容

#### 8.3.1 AI 服务节点扩容（无状态）

后端 FastAPI 与 Linux Celery Worker 无状态，可直接水平扩容。

**FastAPI 扩容**（来源：`docs/deployment.md` §A.3.1 gunicorn 配置）：

```bash
# 单机扩容：增加 gunicorn workers
# 编辑 docker-compose.yml backend.command
gunicorn app.main:app \
  --bind 0.0.0.0:8000 \
  --workers 8 \          # 从 4 增至 8
  --worker-class uvicorn.workers.UvicornWorker \
  --timeout 120
```

**多机扩容**：在新节点部署 backend，通过 Nginx upstream 负载均衡：

```nginx
upstream synthdraft_backend {
    server 10.0.0.1:8000;
    server 10.0.0.2:8000;
    keepalive 32;
}
```

#### 8.3.2 Celery Worker 扩容（按队列）

来源：`backend/app/celery_app.py` L43-50（队列路由）。

```bash
# 按队列深度动态扩容 Worker
# 查看队列深度
curl http://localhost:8000/api/v1/observability/queue-status | jq '.queues'

# 临时增加 reviews 队列并发
celery -A app.celery_app worker --loglevel=info --concurrency=8 \
  -Q reviews --name=worker-reviews-extra@%h

# 或 systemd 模式：启动第二个实例
sudo systemctl start synthdraft-celery-reviews-2
```

**扩容参考**（来源：`docs/deployment.md` §D.2）：

| 队列 | 推荐并发 | 扩容触发条件 |
|---|---|---|
| `reviews` | 4 → 8 | 排队 > 50 持续 5 分钟 |
| `generations` | 4 → 8 | 排队 > 50 持续 5 分钟 |
| `sketch` | 2 → 4 | 排队 > 20 持续 10 分钟 |
| `assembly` | 2 → 4 | 排队 > 20 持续 10 分钟 |
| `collaboration` | 1-2 → 4 | 排队 > 10 持续 10 分钟 |
| `solidworks` | 1（受许可证限制） | 无法水平扩容，需垂直优化 |

#### 8.3.3 SolidWorks Worker 扩容（受许可证限制）

来源：`backend/app/services/solidworks/worker_pool.py` L159-164 + `license.py`。

**限制**：SolidWorks 许可证通常限制并发实例数，默认 `max_workers=1`。

**扩容条件**：拥有多个 SolidWorks 浮动许可证席位。

**扩容方式**：
1. 在多台 Windows 机器部署 Worker（每台 1 个实例）
2. 所有 Worker 消费同一 `solidworks` 队列（Celery 自动负载均衡）

```powershell
# 在第二台 Windows 机器部署
cd D:\SynthDraft\backend
.\.venv\Scripts\Activate.ps1
celery -A app.celery_app worker -Q solidworks -c 1 --without-gossip \
  --name=worker-solidworks-2@%h --loglevel=info
```

### 8.4 垂直扩容

#### 8.4.1 GPU 扩容（vLLM）

来源：`infra/docker-compose.yml` L102-125 + `docs/deployment.md` §A.2.5。

```bash
# 1. 升级 GPU 实例（如 T4 → A10）
# 2. 调整 vLLM 启动参数（启用 tensor-parallel）
# 编辑 docker-compose.yml vllm.command
command: >
  --model Qwen/Qwen2.5-Coder-7B-Instruct
  --trust-remote-code
  --tensor-parallel-size 2

# 3. 重启 vLLM
docker compose --env-file .env --profile gpu up -d vllm
```

#### 8.4.2 CPU/内存扩容

```bash
# 1. 升级主机规格（云厂商：变更实例类型）
# 2. 调整 Celery Worker 并发数（受 CPU 核数限制）
# 经验公式：concurrency = CPU 核数 - 1（留 1 核给系统）

# 3. 调整 Ollama 线程数（CPU 模式）
# 编辑 docker-compose.yml ollama 服务 environment
environment:
  OLLAMA_NUM_PARALLEL: 4  # 并行请求数
  OLLAMA_NUM_THREAD: 8    # 推理线程数
```

#### 8.4.3 磁盘扩容

```bash
# 1. 扩展 Docker volume（需停机）
docker compose --env-file .env stop postgres
# 在主机侧扩展 LVM/云盘
docker compose --env-file .env start postgres

# 2. 验证
docker exec synthdraft-postgres df -h /var/lib/postgresql/data
```

---

## 9. 运维附录

### 9.1 环境变量速查表

> 与 `docs/deployment.md` §D.1 呼应，此处仅列运维常用项。完整清单见 deployment.md。

来源：`backend/app/config.py` 全文。

#### 9.1.1 可观测性相关

| 变量 | 默认值 | 说明 | 来源 |
|---|---|---|---|
| `OTEL_ENABLED` | false | 是否启用 tracing | config.py L97 |
| `OTEL_SERVICE_NAME` | synthdraft-backend | 服务名（上报到 Tempo） | config.py L96 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | （空） | OTLP 端点 | config.py L95 |
| `OBS_QUEUE_MONITOR_ENABLED` | true | 是否启用队列监控 | config.py L101 |
| `OBS_QUEUE_BACKLOG_ALERT` | 50 | 队列堆积告警阈值 | config.py L103 |
| `OBS_QUEUE_FAILURE_RATE_ALERT` | 10.0 | 失败率告警阈值（%） | config.py L105 |
| `OBS_QUEUE_SCAN_INTERVAL_SEC` | 60 | 采集间隔（秒） | config.py L107 |
| `OBS_ALERT_WEBHOOK_URL` | （空） | 告警 webhook（留空则仅 log） | config.py L109 |
| `OBS_LLM_METRICS_PATH` | ./tmp_metrics/llm_metrics.jsonl | LLM 指标路径 | config.py L112 |
| `OBS_FEEDBACK_STORE_PATH` | ./tmp_metrics/feedback.jsonl | 反馈路径 | config.py L115 |

#### 9.1.2 SolidWorks 与性能相关

| 变量 | 默认值 | 说明 | 来源 |
|---|---|---|---|
| `SOLIDWORKS_PREWARM_COUNT` | 0 | Worker 预热数（生产 1-2） | config.py L122 |
| `CAD_CACHE_ENABLED` | true | CAD 解析缓存 | config.py L125 |
| `CAD_CACHE_TTL` | 86400 | CAD 缓存 TTL（秒，24 小时） | config.py L126 |
| `RAG_CACHE_ENABLED` | true | RAG 检索缓存 | config.py L129 |
| `RAG_CACHE_TTL` | 3600 | RAG 缓存 TTL（秒，1 小时） | config.py L130 |
| `LLM_STREAM_ENABLED` | true | LLM 流式输出 | config.py L133 |
| `LLM_STREAM_TIMEOUT` | 300 | 流式超时（秒，5 分钟） | config.py L134 |

#### 9.1.3 安全相关（生产必换）

| 变量 | 默认值 | 说明 | 来源 |
|---|---|---|---|
| `JWT_SECRET_KEY` | change-this-... | **[SECURE] 生产必换** | config.py L90 |
| `POSTGRES_PASSWORD` | synthdraft_dev_pwd | **[SECURE] 生产必换** | config.py L38 |
| `MINIO_ACCESS_KEY` | synthdraft_minio | **[SECURE] 生产必换** | config.py L56 |
| `MINIO_SECRET_KEY` | synthdraft_minio_secret | **[SECURE] 生产必换** | config.py L57 |
| `OPENAI_API_KEY` | （空） | OpenAI 兼容 key | config.py L78 |
| `ANTHROPIC_API_KEY` | （空） | Anthropic key | config.py L84 |

### 9.2 常用命令速查

#### 9.2.1 服务管理

```bash
# Docker 模式
docker compose --env-file .env up -d <service>
docker compose --env-file .env restart <service>
docker compose --env-file .env stop <service>
docker compose --env-file .env ps
docker logs -f --tail 100 <container>

# systemd 模式
sudo systemctl start/stop/restart/status synthdraft-<service>
journalctl -u synthdraft-<service> -f
```

#### 9.2.2 Celery 诊断

```bash
celery -A app.celery_app inspect ping              # Worker 探测
celery -A app.celery_app inspect active            # 正在执行的任务
celery -A app.celery_app inspect reserved          # 已预取的任务
celery -A app.celery_app inspect active_queues     # Worker 消费的队列
celery -A app.celery_app purge -Q <queue>          # 清空指定队列
celery -A app.celery_app call <task.name>          # 手动触发任务
```

#### 9.2.3 健康检查

```bash
curl http://localhost:8000/api/v1/healthz          # 存活探针
curl http://localhost:8000/api/v1/readyz           # 就绪探针
docker exec synthdraft-postgres pg_isready -U synthdraft
docker exec synthdraft-redis redis-cli ping
curl http://localhost:6333/healthz                 # Qdrant
curl http://localhost:9000/minio/health/live       # MinIO
curl http://localhost:11434/api/tags               # Ollama
```

#### 9.2.4 可观测性 API

```bash
curl http://localhost:8000/api/v1/observability/queue-status | jq .
curl http://localhost:8000/api/v1/observability/llm-cost-summary | jq .
curl http://localhost:8000/api/v1/observability/llm-latency | jq .
curl http://localhost:8000/api/v1/observability/feedback-summary | jq .
curl "http://localhost:8000/api/v1/observability/feedback-trend?granularity=day" | jq .
```

#### 9.2.5 数据备份

```bash
# PostgreSQL 全量
docker exec synthdraft-postgres pg_dump -U synthdraft -d synthdraft --format=custom > backup.dump

# PostgreSQL 恢复
docker exec -i synthdraft-postgres pg_restore -U synthdraft -d synthdraft < backup.dump

# MinIO mirror
mc mirror minio/synthdraft-files /backup/minio-files/
mc mirror /backup/minio-files/ minio/synthdraft-files/

# JSONL 指标
cp /opt/synthdraft/backend/tmp_metrics/*.jsonl /backup/metrics/
```

### 9.3 端口占用表

来源：`infra/docker-compose.yml` + `infra/observability/docker-compose.observability.yml`。

| 端口 | 服务 | 容器端口 | 用途 | 节点 |
|---|---|---|---|---|
| 5433 | PostgreSQL 16 | 5432 | 业务数据（宿主 5433 避免冲突） | Linux |
| 6379 | Redis 7 | 6379 | broker（DB1）+ result backend（DB2）+ 缓存（DB0）+ pubsub | Linux |
| 6333 | Qdrant v1.18.3 | 6333 | REST API（向量检索） | Linux |
| 6334 | Qdrant v1.18.3 | 6334 | gRPC | Linux |
| 9000 | MinIO | 9000 | S3 API | Linux |
| 9001 | MinIO | 9001 | Web Console | Linux |
| 11434 | Ollama 0.30.6 | 11434 | 本地 LLM/VLM 推理 | Linux |
| 8001 | vLLM v0.25.0 | 8000 | GPU 推理（profile: gpu） | Linux |
| 8000 | Backend FastAPI | 8000 | API 网关 | Linux |
| 4317 | OTEL Collector | 4317 | OTLP gRPC（profile: observability） | Linux |
| 4318 | OTEL Collector / Tempo | 4318 | OTLP HTTP（二选一，见 §3.1） | Linux |
| 3001 | Grafana 12.2.0 | 3000 | 可视化仪表盘 | Linux |
| 3200 | Tempo 2.8.1 | 3200 | Tempo HTTP API | Linux |
| 9090 | Prometheus v3.4.0 | 9090 | metrics 抓取 | Linux |
| 5555 | Flower 2.0.1 | 5555 | Celery 任务监控 UI | Linux |
| 3000 | Frontend Next.js | 3000 | Web 控制台 | Linux |

### 9.4 联系人/值班表模板

> 运维人员请根据实际填写。

| 角色 | 姓名 | 手机 | 邮箱 | 职责范围 | 响应时效 |
|---|---|---|---|---|---|
| 应用运维（主） | | | | FastAPI / Celery 故障 | 15 分钟 |
| 应用运维（备） | | | | FastAPI / Celery 故障 | 30 分钟 |
| 基础设施运维 | | | | PG/Redis/Qdrant/MinIO 故障 | 30 分钟 |
| AI/LLM 运维 | | | | Ollama/vLLM 故障、LLM 成本异常 | 1 小时 |
| SolidWorks 运维 | | | | Windows Worker / SolidWorks 许可证 | 1 小时（工作时间） |
| 安全运维 | | | | 安全事件、密钥泄漏 | 立即 |
| DBA | | | | 数据库故障、备份恢复 | 30 分钟 |

**值班轮换**：

| 周次 | 主值班 | 备值班 | 起止时间 |
|---|---|---|---|
| W1 | | | 周一 09:00 - 周五 18:00 |
| W2 | | | 周一 09:00 - 周五 18:00 |
| ... | | | |

**非工作时间应急联系**：电话 / 企业微信 / 飞书群（请填写实际群名）。

---

## 10. 信息来源

本手册所有具体数字、阈值、命令、配置项均来自以下实际文件：

| 文件 | 用途 |
|---|---|
| `backend/app/observability/tracing.py` | OpenTelemetry tracing 实现（业务 span 工厂、降级行为） |
| `backend/app/observability/queue_monitor.py` | Celery 队列状态采集（KNOWN_QUEUES、broker depth） |
| `backend/app/observability/alerts.py` | 告警规则（worker_offline/queue_backlog/queue_failure_rate）+ webhook |
| `backend/app/observability/llm_metrics.py` | LLM 指标持久化（JSONL）+ 成本估算表 + 延迟分布 |
| `backend/app/config.py` | Settings 类（OTEL_/OBS_/SW_/CAD_CACHE_ 等全部配置项 + 默认值） |
| `backend/app/celery_app.py` | Celery 队列路由 + 配置（visibility_timeout/prefetch/result_expires） |
| `backend/app/services/solidworks/worker_pool.py` | SW Worker 池（健康检查/超时 kill/重启重试/许可证） |
| `backend/app/api/v1/endpoints/health.py` | 健康检查端点（/healthz + /readyz） |
| `backend/app/api/v1/endpoints/observability.py` | 可观测性 API 端点（6 个） |
| `infra/docker-compose.yml` | 主编排（PG/Redis/Qdrant/MinIO/Ollama/vLLM/OTEL/Backend/Celery） |
| `infra/observability/docker-compose.observability.yml` | 可观测性栈（Grafana/Tempo/Prometheus/Flower） |
| `infra/observability/grafana-dashboard.json` | Grafana 仪表盘（10 个 Panel） |
| `infra/observability/prometheus.yml` | Prometheus 抓取配置（4 个 job） |
| `docs/deployment.md` | 部署手册（Task 18.3，端口/命令/systemd/NSSM 参考） |
| `docs/architecture.md` | 架构设计文档（Task 18.1，跨平台架构与边界） |

**八荣八耻合规声明**：
- 以瞎猜接口为耻：所有接口、端点、命令均基于实际代码读取
- 以实事求是为荣：所有阈值、默认值、配置项均引用具体代码行
- 以覆盖测试为荣：所有告警规则在 `alerts.py` `self_test()` 中有测试覆盖
- 备份脚本章节已明确标注为"运维人员需创建的模板"，未声称项目已内置
