# SynthDraft API 文档

> **版本**：v0.1.0（P0/P1/P2 阶段）
> **生成时间**：2026-07-27
> **对应代码**：`backend/app/main.py` + `backend/app/api/v1/`
> **OpenAPI 入口**：`/openapi.json` / `/docs` / `/redoc`

---

## 1. 概述

### 1.1 服务简介

SynthDraft 是 AI 驱动的工程设计辅助系统后端，基于 FastAPI 构建，提供智能审图、智能生成、工程规范知识库检索、草图转 CAD、协同闭环、可观测性等能力。后端通过 Celery + Redis 处理异步长任务，通过 PostgreSQL 持久化、Qdrant 做向量检索、MinIO/本地目录做文件存储。

### 1.2 基础 URL

| 环境 | Base URL |
|---|---|
| 本地开发 | `http://localhost:8000` |
| 容器内 | `http://backend:8000` |
| API 前缀 | `/api/v1` |

根路径 `/` 不带前缀；其余业务端点均挂在 `/api/v1` 下。交互式文档：`/docs`（Swagger）与 `/redoc`。

### 1.3 版本管理

- 当前版本号由 `settings.APP_VERSION`（默认 `0.1.0`）控制，体现在 `/`、`/healthz`、`/readyz` 响应的 `version` 字段。
- 路径前缀 `/api/v1` 表示 v1 版本；后续破坏性变更将引入 `/api/v2` 并保留 v1 一段过渡期。
- 向后兼容：所有 pydantic schema 字段显式标注默认值，新增字段不破坏旧客户端。

### 1.4 认证方式

**Bearer JWT（可选）**。受保护端点通过 `Authorization: Bearer <jwt>` 头部解析 `user_id`。

| 场景 | 行为 |
|---|---|
| 未提供 `Authorization` 头 | 返回 `user_id = "anonymous"`（P0 阶段开发态宽容模式） |
| 头部格式非 `Bearer <token>` | `401 Unauthorized`，`detail="Invalid authorization header"` |
| token 解码失败 | `401 Unauthorized`，`detail="Invalid token: ..."` |
| 合法 token | 从 JWT `sub` claim 读取 `user_id` |

- 算法：`HS256`（`settings.JWT_ALGORITHM`）
- 密钥：`settings.JWT_SECRET_KEY`（**生产环境必须替换为强随机值**）
- Access Token 有效期：`settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES`（默认 1440 分钟 = 24 小时）

> ⚠️ **P0 安全提示**：当前未提供 `/login` 或 `/token` 端点，JWT 需外部签发。生产环境应关闭 anonymous 兜底，强制鉴权。

### 1.5 错误码体系

#### HTTP 状态码

| 状态码 | 含义 | 触发场景 |
|---|---|---|
| `200 OK` | 请求成功 | 同步端点成功；异步结果查询成功 |
| `201 Created` | 资源创建成功 | 文件上传、反馈提交 |
| `202 Accepted` | 异步任务已受理 | 审图/生成/草图/协同任务提交；任务取消 |
| `400 Bad Request` | 参数错误 | 文件类型不支持；prompt 缺失；路径穿越；文件为空 |
| `401 Unauthorized` | 鉴权失败 | JWT 缺失或无效 |
| `404 Not Found` | 资源不存在 | 任务 ID 不存在；报告未就绪；文件不存在 |
| `409 Conflict` | 状态冲突 | 协同/校准依赖的前置任务未 SUCCESS |
| `413 Payload Too Large` | 文件过大 | 上传超过 100 MB |
| `500 Internal Server Error` | 服务器错误 | 任务结果类型异常；沙箱执行失败透传 |
| `503 Service Unavailable` | 依赖不可用 | readyz 探测依赖失败；KB 检索/索引失败 |

#### 错误响应体

FastAPI 标准错误格式（无 response_model 时亦如此）：

```json
{
  "detail": "错误描述文本"
}
```

#### 业务状态码（异步任务）

异步任务通过 Celery 状态机映射为业务状态字符串，见 §3。

### 1.6 CORS

`settings.CORS_ORIGINS`（逗号分隔，默认 `http://localhost:3000,http://localhost:8000`）。允许所有方法与头部，`allow_credentials=True`。

---

## 2. 端点分组索引

实际代码注册的端点共 **38 个**（37 个 HTTP + 1 个 WebSocket），分布在 12 个模块。任务描述中提及的"33 个"基于 P1 报告（OpenAPI 将同路径 GET/POST 合并为 1 条，且未计 llm/ws 模块）；本文档遵循"实事求是"原则，按实际路由逐条记录。

| 模块 | 端点数 | 路径前缀 | 说明 |
|---|---|---|---|
| root | 1 | `/` | 服务基本信息 |
| health | 2 | `/api/v1` | 存活/就绪探针 |
| uploads | 2 | `/api/v1/uploads` | 文件上传与列表 |
| reviews | 3 | `/api/v1/reviews` | 智能审图 |
| generations | 4 | `/api/v1/generations` | 智能生成 |
| collaboration | 6 | `/api/v1/collaboration` | 审图→生成协同闭环 |
| sketches | 5 | `/api/v1/sketches` | 草图转 CAD |
| kb | 3 | `/api/v1/kb` | 工程规范知识库 |
| tasks | 2 | `/api/v1/tasks` | 通用任务状态/取消 |
| observability | 6 | `/api/v1/observability` | 队列/反馈/LLM 指标 |
| llm | 3 | `/api/v1/llm` | LLM 流式输出与取消 |
| websocket | 1 | `/api/v1/ws` | 任务进度推送 |
| **合计** | **38** | | |

### 端点速查表

| # | 方法 | 路径 | 模块 | 摘要 |
|---|---|---|---|---|
| 1 | GET | `/` | root | 服务基本信息 |
| 2 | GET | `/api/v1/healthz` | health | 存活探针 |
| 3 | GET | `/api/v1/readyz` | health | 就绪探针 |
| 4 | POST | `/api/v1/uploads` | uploads | 上传文件 |
| 5 | GET | `/api/v1/uploads` | uploads | 列出已上传文件 |
| 6 | POST | `/api/v1/reviews` | reviews | 提交审图任务 |
| 7 | GET | `/api/v1/reviews/{task_id}/result` | reviews | 查询审图结果 |
| 8 | GET | `/api/v1/reviews/{task_id}/report` | reviews | 下载审图报告 |
| 9 | POST | `/api/v1/generations` | generations | 提交生成任务 |
| 10 | GET | `/api/v1/generations/{task_id}/result` | generations | 查询生成结果 |
| 11 | POST | `/api/v1/generations/execute` | generations | 同步执行 CadQuery 代码 |
| 12 | GET | `/api/v1/generations/files/{file_path}` | generations | 下载生成产物 |
| 13 | POST | `/api/v1/collaboration/optimize-from-review` | collaboration | 基于审图缺陷优化图纸 |
| 14 | GET | `/api/v1/collaboration/optimize-result/{task_id}` | collaboration | 查询优化任务结果 |
| 15 | GET | `/api/v1/collaboration/diff-report/{old_review_task_id}/{new_review_task_id}` | collaboration | 修订前后对比报告 |
| 16 | POST | `/api/v1/collaboration/feedback` | collaboration | 提交用户反馈 |
| 17 | GET | `/api/v1/collaboration/feedback/{review_task_id}` | collaboration | 查询某审图任务的反馈 |
| 18 | GET | `/api/v1/collaboration/feedback-stats` | collaboration | 反馈统计 |
| 19 | POST | `/api/v1/sketches` | sketches | 提交草图转 CAD 任务 |
| 20 | GET | `/api/v1/sketches/{task_id}/result` | sketches | 查询草图任务结果 |
| 21 | POST | `/api/v1/sketches/calibrate` | sketches | 提交人工校准任务 |
| 22 | GET | `/api/v1/sketches/calibrate/{task_id}/result` | sketches | 查询校准任务结果 |
| 23 | GET | `/api/v1/sketches/files/{file_path}` | sketches | 下载草图产物 |
| 24 | GET | `/api/v1/kb/clauses` | kb | 规范条款检索 |
| 25 | GET | `/api/v1/kb/standards` | kb | 已索引规范列表 |
| 26 | POST | `/api/v1/kb/reindex` | kb | 重建索引 |
| 27 | GET | `/api/v1/tasks/{task_id}` | tasks | 查询任务状态 |
| 28 | POST | `/api/v1/tasks/{task_id}/cancel` | tasks | 取消任务 |
| 29 | GET | `/api/v1/observability/queue-status` | observability | Celery 队列状态 |
| 30 | GET | `/api/v1/observability/feedback-summary` | observability | 反馈总体统计 |
| 31 | GET | `/api/v1/observability/feedback-by-category` | observability | 按类别统计反馈 |
| 32 | GET | `/api/v1/observability/feedback-trend` | observability | 反馈时间趋势 |
| 33 | GET | `/api/v1/observability/llm-cost-summary` | observability | LLM 成本汇总 |
| 34 | GET | `/api/v1/observability/llm-latency` | observability | LLM 延迟分布 |
| 35 | POST | `/api/v1/llm/stream` | llm | LLM 流式输出（SSE） |
| 36 | POST | `/api/v1/llm/cancel/{request_id}` | llm | 取消流式请求 |
| 37 | GET | `/api/v1/llm/stream/{request_id}/status` | llm | 查询流式请求状态 |
| 38 | WS | `/api/v1/ws/tasks/{task_id}` | websocket | 任务进度推送 |

---

## 3. 异步任务模式说明

### 3.1 Celery 状态机

后端长任务（审图、生成、草图、协同优化、校准）统一通过 Celery 派发，结果存于 Redis result backend。Celery 原生状态与业务状态映射如下（见 `backend/app/api/v1/endpoints/tasks.py` `_map_celery_state` 与 `ws.py` `_map_state`）：

| Celery 原生状态 | 业务状态字符串 | 含义 | 是否终态 |
|---|---|---|---|
| `PENDING` | `queued` / `pending` | 任务排队中或 ID 不存在 | 否 |
| `RECEIVED` | `queued` | worker 已收到未执行 | 否 |
| `STARTED` | `running` | 执行中 | 否 |
| `RETRY` | `running` | 失败重试中 | 否 |
| `SUCCESS` | `succeeded` / `completed` | 成功完成 | ✅ 是 |
| `FAILURE` | `failed` | 执行失败 | ✅ 是 |
| `REVOKED` | `canceled` | 已取消 | ✅ 是 |

> 注意：不同端点对 `SUCCESS` 的字符串映射略有差异——`/tasks` 用 `succeeded`，`/reviews/result` 与 `/collaboration/optimize-result` 用 `completed`，`/sketches` 用 `success=true` 布尔字段。详见各端点文档。

### 3.2 队列路由

| 队列名 | 消费者 | 路由规则 |
|---|---|---|
| `reviews` | Linux AI Worker | `app.celery.tasks.reviews.*` |
| `generations` | Linux AI Worker | `app.celery.tasks.generations.*` |
| `solidworks` | Windows SolidWorks Worker | `app.celery.tasks.solidworks.*` |
| `sketch` | Linux AI Worker | `app.celery.tasks.sketch.*` |
| `assembly` | Windows SolidWorks Worker | `app.celery.tasks.assembly.*` |
| `collaboration` | Linux AI Worker | `app.celery.tasks.collaboration.*` |
| `default` | 通用 Worker | 兜底（注：`optimize-from-review` 显式派发到 `default` 队列） |

### 3.3 轮询策略建议

1. 客户端提交异步任务后获得 `task_id` 与 `websocket_url`。
2. **推荐**：建立 WebSocket 连接（`/api/v1/ws/tasks/{task_id}`）实时接收状态推送，每秒一次。
3. **备选**：HTTP 轮询 `GET /api/v1/tasks/{task_id}` 或对应模块的 `/result` 端点，建议间隔 1-3 秒。
4. 终态（`succeeded` / `failed` / `canceled` / `completed`）后停止轮询/断开 WS。
5. result backend 结果保留 7 天（`result_expires = 604800` 秒），超期后查询返回 `PENDING`。

### 3.4 取消任务

`POST /api/v1/tasks/{task_id}/cancel` 调用 `celery_app.control.revoke(task_id, terminate=False)`，仅阻止任务开始执行（已在执行中的任务不会被强杀）。返回 `202` 与 `{"task_id": "...", "status": "canceled"}`。

---

## 4. 文件上传规范

### 4.1 端点

`POST /api/v1/uploads`，`multipart/form-data`，字段名 `file`。

### 4.2 扩展名白名单

| 扩展名 | 推断 file_type |
|---|---|
| `.dxf` | `dxf` |
| `.dwg` | `dwg` |
| `.step` / `.stp` | `step` |
| `.iges` / `.igs` | `iges` |
| `.pdf` | `pdf` |
| `.png` / `.jpg` / `.jpeg` | `image` |
| `.sldprt` | `sldprt` |
| `.sldasm` | `sldasm` |

不在白名单内的扩展名返回 `400`。

### 4.3 大小限制

- 单文件上限：**100 MB**（`100 * 1024 * 1024` 字节）
- 空文件：返回 `400`，`detail="文件为空"`
- 超限：返回 `413`

### 4.4 存储位置

- 根目录：`settings.UPLOAD_DIR`（默认 `./tmp_uploads`）
- 文件名格式：`{uuid_hex}_{净化后文件名}`（uuid 前缀防冲突）
- `file_key`：相对 `UPLOAD_DIR` 的路径（如 `a1b2c3..._零件.dxf`），供后续 `/reviews`、`/generations`、`/sketches` 引用
- 文件名净化：取 basename 防路径穿越；去除控制字符

### 4.5 安全提示

- 当前未按 `user_id` 隔离文件（P0 阶段），P2 需改为按用户过滤。
- `GET /api/v1/uploads` 列出全部上传文件，仅供开发态调试。

---

## 5. WebSocket 接口

### 5.1 任务进度推送

**端点**：`WS /api/v1/ws/tasks/{task_id}`

**协议**：每秒轮询 Celery `AsyncResult`，推送 JSON 帧直到终态。

**推送帧格式**：

```json
{
  "task_id": "abc123",
  "status": "running",
  "progress": 0
}
```

终态帧附加字段：

| status | 附加字段 |
|---|---|
| `succeeded` | `result`: dict（任务返回值） |
| `failed` | `error`: str（错误信息） |
| `canceled` | 无 |

**生命周期**：进入 `succeeded` / `failed` / `canceled` 后服务端主动关闭连接。

> P0 实现为轻量轮询；Task 6 前端落地时升级为 Redis pubsub 实时推送。

详见 §6.12 端点文档。

---

## 6. 端点详细文档

### 6.1 root 模块

#### 1. GET `/` — 服务基本信息

**标签**：`root`

**说明**：返回服务名称、版本、文档入口与健康检查路径。无需鉴权。

**请求参数**：无

**响应**（`200 OK`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `service` | string | 服务名（`settings.APP_NAME`） |
| `version` | string | 版本号（`settings.APP_VERSION`） |
| `docs` | string | Swagger 文档路径 `/docs` |
| `health` | string | 存活探针路径 `/api/v1/healthz` |
| `ready` | string | 就绪探针路径 `/api/v1/readyz` |

**curl 示例**：

```bash
curl http://localhost:8000/
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/")
print(r.json())
# {'service': 'SynthDraft Backend', 'version': '0.1.0', 'docs': '/docs', ...}
```

---

### 6.2 health 模块

#### 2. GET `/api/v1/healthz` — 存活探针

**标签**：`health`

**说明**：表明进程在运行。会附带当前 LLM provider 的可用性快照（5 秒超时探测，失败降级为 `false`）。

**请求参数**：无

**响应**（`200 OK`，`HealthResponse`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `"ok"` | 固定值 |
| `service` | string | 服务名 |
| `version` | string | 版本号 |
| `llm_provider` | string | 当前 LLM provider（`ollama`/`openai`/`anthropic`） |
| `llm_available` | bool | 文本模型是否可用 |
| `vlm_available` | bool | 视觉模型是否可用 |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/healthz
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/healthz")
print(r.json())
# {'status': 'ok', 'service': 'SynthDraft Backend', 'version': '0.1.0',
#  'llm_provider': 'ollama', 'llm_available': True, 'vlm_available': False}
```

#### 3. GET `/api/v1/readyz` — 就绪探针

**标签**：`health`

**说明**：探测 PostgreSQL / Redis 等关键依赖（各 3 秒超时）；任一不可用则返回 `503`。

**请求参数**：无

**响应**（`200 OK` 或 `503 Service Unavailable`，`ReadinessResponse`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `"ok"` \| `"down"` | 整体状态（所有组件 ok 才 ok） |
| `service` | string | 服务名 |
| `version` | string | 版本号 |
| `components` | list[`ReadinessComponent`] | 各依赖组件状态 |

`ReadinessComponent`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 组件名（`postgres` / `redis`） |
| `status` | `"ok"` \| `"down"` | 组件状态 |
| `detail` | string \| null | 失败原因（ok 时为 null） |

**curl 示例**：

```bash
curl -i http://localhost:8000/api/v1/readyz
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/readyz")
print(r.status_code, r.json())
```

---

### 6.3 uploads 模块

#### 4. POST `/api/v1/uploads` — 上传文件

**标签**：`uploads`

**说明**：上传单个文件，返回 `file_key` 供后续 `/reviews`、`/generations`、`/sketches` 使用。

**请求参数**：

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `file` | form-data body | binary | 是 | 文件二进制 |
| `Authorization` | header | string | 否 | `Bearer <jwt>`；缺省 user_id=anonymous |

**约束**：见 §4 文件上传规范。

**响应**（`201 Created`，`UploadResponse`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `file_key` | string | 文件 key（相对 UPLOAD_DIR） |
| `file_name` | string | 净化后的原始文件名 |
| `file_type` | `sldprt` \| `sldasm` \| `dwg` \| `dxf` \| `pdf` \| `image` \| `step` \| `iges` | 推断的文件类型 |
| `size` | int | 文件大小（字节） |
| `content_type` | string | 上传时的 Content-Type |

**错误码**：

| 状态码 | 场景 |
|---|---|
| `400` | 不支持的文件类型 / 文件为空 |
| `413` | 文件超过 100 MB |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/v1/uploads \
  -H "Authorization: Bearer <jwt>" \
  -F "file=@/path/to/零件.dxf"
```

**Python 示例**：

```python
import requests
with open("零件.dxf", "rb") as f:
    r = requests.post(
        "http://localhost:8000/api/v1/uploads",
        headers={"Authorization": "Bearer <jwt>"},
        files={"file": f},
    )
print(r.json())
# {'file_key': 'a1b2c3..._零件.dxf', 'file_name': '零件.dxf',
#  'file_type': 'dxf', 'size': 12345, 'content_type': 'application/octet-stream'}
```

#### 5. GET `/api/v1/uploads` — 列出已上传文件

**标签**：`uploads`

**说明**：列出 `UPLOAD_DIR` 下的文件（开发态调试用，不分页、不鉴权过滤）。

**请求参数**：无

**响应**（`200 OK`，无 response_model，返回裸 dict）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `uploads` | list[object] | 文件列表 |
| `uploads[].file_key` | string | 文件 key |
| `uploads[].file_name` | string | 文件名 |
| `uploads[].file_type` | string | 文件类型 |
| `uploads[].size` | int | 文件大小（字节） |
| `total` | int | 文件总数 |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/uploads
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/uploads")
print(r.json())
```

---

### 6.4 reviews 模块

#### 6. POST `/api/v1/reviews` — 提交审图任务

**标签**：`reviews`

**说明**：提交审图任务到 Celery `reviews` 队列，返回 `task_id`。

**请求参数**：

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `Authorization` | header | string | 否 | Bearer JWT |
| `file_key` | body | string | 是 | 已上传文件的 key |
| `file_type` | body | `sldprt` \| `sldasm` \| `dwg` \| `dxf` \| `pdf` \| `image` | 是 | 输入文件类型 |
| `standard_set` | body | list[string] | 否 | 适用的规范集合，默认 `["GB/T 1182", "GB/T 4457.4"]` |

**响应**（`202 Accepted`，`ReviewTaskAccepted`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | Celery 任务 ID |
| `status` | `"queued"` | 固定值 |
| `websocket_url` | string | 进度推送 WS 路径 `/api/v1/ws/tasks/{task_id}` |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/v1/reviews \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt>" \
  -d '{"file_key":"a1b2c3_零件.dxf","file_type":"dxf","standard_set":["GB/T 1182"]}'
```

**Python 示例**：

```python
import requests
r = requests.post(
    "http://localhost:8000/api/v1/reviews",
    headers={"Authorization": "Bearer <jwt>"},
    json={"file_key": "a1b2c3_零件.dxf", "file_type": "dxf"},
)
print(r.json())
# {'task_id': 'f7e6d5...','status': 'queued', 'websocket_url': '/api/v1/ws/tasks/f7e6d5...'}
```

#### 7. GET `/api/v1/reviews/{task_id}/result` — 查询审图结果

**标签**：`reviews`

**说明**：从 Celery result backend 读取任务状态与返回值。始终返回 `200`，通过 `status` 字段区分阶段。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | Celery 任务 ID |

**响应**（`200 OK`，无 response_model，返回裸 dict）：

按 `status` 字段区分：

- `pending`：`{"task_id": "...", "status": "pending", "message": "任务排队中或任务 ID 不存在"}`
- `running`：`{"task_id": "...", "status": "running", "message": "任务执行中（state=STARTED）"}`
- `failed`：`{"task_id": "...", "status": "failed", "error": "..."}`
- `completed`：`ReviewResult`（见下）+ `status="completed"` 字段

`ReviewResult`（`SUCCESS` 时）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务 ID |
| `file_key` | string | 输入文件 key |
| `file_type` | string | 输入文件类型 |
| `status` | `"completed"` \| `"failed"` | 任务状态 |
| `compliance_score` | float | 合规性评分（0-100） |
| `defects` | list[`DefectItem`] | 缺陷列表 |
| `standards_applied` | list[string] | 实际应用的规范集合 |
| `review_mode` | `"vlm"` \| `"vector_only"` \| `"rule_engine"` | 实际审图模式 |
| `report_path` | string \| null | HTML 报告路径 |
| `pdf_report_path` | string \| null | PDF 报告路径 |
| `metadata` | object | 附加元信息 |
| `precision_level` | string | 精度等级 |
| `precision_evidence` | object | 精度判定证据 |

`DefectItem`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `category` | `title_block` \| `layer_naming` \| `dimensioning` \| `tolerance` \| `surface_roughness` \| `line_type` \| `view_layout` \| `text_annotation` \| `other` | 缺陷类别 |
| `severity` | `critical` \| `major` \| `minor` \| `warning` | 严重等级 |
| `coordinate` | object \| null | 缺陷坐标（如 `{"x":120.5,"y":45.0}`） |
| `standard_ref` | string | 规范引用文本 |
| `standard_clause_id` | string \| null | 知识库条款 ID |
| `suggestion` | string | 修改建议 |
| `evidence` | string | 缺陷证据描述 |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/reviews/f7e6d5.../result
```

**Python 示例**：

```python
import requests
task_id = "f7e6d5..."
r = requests.get(f"http://localhost:8000/api/v1/reviews/{task_id}/result")
data = r.json()
if data["status"] == "completed":
    print("合规分:", data["compliance_score"], "缺陷数:", len(data["defects"]))
```

#### 8. GET `/api/v1/reviews/{task_id}/report` — 下载审图报告

**标签**：`reviews`

**说明**：下载 HTML 或 PDF 报告文件。任务未 `SUCCESS` 时返回 `404`。

**路径/查询参数**：

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `task_id` | path | string | 是 | 任务 ID |
| `format` | query | string | 否 | `html`（默认）或 `pdf`；pdf 不可用时回退 html |

**响应**：`FileResponse`，`media_type` 为 `text/html` 或 `application/pdf`。

**错误码**：

| 状态码 | 场景 |
|---|---|
| `404` | 任务未 SUCCESS；结果中无 report_path；文件不存在 |
| `500` | 任务结果格式异常 |

**curl 示例**：

```bash
# HTML 报告
curl -o report.html http://localhost:8000/api/v1/reviews/f7e6d5.../report
# PDF 报告（不可用时回退 HTML）
curl -o report.pdf "http://localhost:8000/api/v1/reviews/f7e6d5.../report?format=pdf"
```

**Python 示例**：

```python
import requests
task_id = "f7e6d5..."
r = requests.get(f"http://localhost:8000/api/v1/reviews/{task_id}/report",
                 params={"format": "pdf"})
with open("report.pdf", "wb") as f:
    f.write(r.content)
```

---

### 6.5 generations 模块

#### 9. POST `/api/v1/generations` — 提交生成任务（异步）

**标签**：`generations`

**说明**：提交生成任务到 Celery `generations` 队列。

**请求参数**（`GenerationCreateRequest`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `input_type` | `"text"` \| `"sketch"` | 是 | 输入类型 |
| `prompt` | string \| null | 条件必填 | `input_type=text` 时必填 |
| `sketch_key` | string \| null | 条件必填 | `input_type=sketch` 时必填 |
| `output_format` | `"step"` \| `"iges"` \| `"stl"` \| `"dxf"` | 否 | 默认 `step` |

**响应**（`202 Accepted`，`GenerationTaskAccepted`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | Celery 任务 ID |
| `status` | `"queued"` | 固定值 |
| `websocket_url` | string | WS 路径 |

**错误码**：

| 状态码 | 场景 |
|---|---|
| `400` | `input_type=text` 但 `prompt` 为空；`input_type=sketch` 但 `sketch_key` 为空 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/v1/generations \
  -H "Content-Type: application/json" \
  -d '{"input_type":"text","prompt":"带 M10 螺纹孔的法兰盘","output_format":"step"}'
```

**Python 示例**：

```python
import requests
r = requests.post(
    "http://localhost:8000/api/v1/generations",
    json={"input_type": "text", "prompt": "带 M10 螺纹孔的法兰盘", "output_format": "step"},
)
print(r.json())
```

#### 10. GET `/api/v1/generations/{task_id}/result` — 查询生成任务结果

**标签**：`generations`

**说明**：根据 `task_id` 查询生成结果。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | Celery 任务 ID |

**响应**（`GenerationResult`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务 ID |
| `input_prompt` | string | 原始输入 prompt |
| `generated_code` | string | 生成的 CadQuery 代码 |
| `execution` | `ExecutionResult` | 沙箱执行结果 |
| `geometry_validation` | `GeometryValidation` \| null | 几何校验结果 |
| `output_files` | list[string] | 产出文件路径 |
| `mode` | `"llm"` \| `"template"` | 生成模式 |
| `metadata` | object | 附加元数据 |

`ExecutionResult`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `success` | bool | 是否成功 |
| `stdout` | string | 子进程标准输出 |
| `stderr` | string | 子进程标准错误 |
| `output_files` | list[string] | 产出文件绝对路径 |
| `elapsed_ms` | int | 执行耗时（毫秒） |
| `exit_code` | int \| null | 子进程退出码 |
| `violations` | list[string] | 静态扫描违规列表 |

`GeometryValidation`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `is_valid` | bool | 是否通过校验 |
| `volume` | float | 体积（mm³） |
| `bounding_box` | [float×6] \| null | `(xmin,ymin,zmin,xmax,ymax,zmax)` |
| `surface_area` | float | 表面积（mm²） |
| `errors` | list[string] | 校验失败原因 |
| `backend` | string \| null | OCC 后端标识 |

**状态码与状态映射**：

| Celery 状态 | HTTP 状态 | 行为 |
|---|---|---|
| `PENDING` | `404` | `detail="task {id} not found or pending"` |
| `STARTED`/`RETRY` | `202` | 返回空 `GenerationResult`，metadata 含 `state` |
| `FAILURE` | `500` | `detail="task failed: ..."` |
| `SUCCESS` | `200` | 返回完整 `GenerationResult` |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/generations/abc123.../result
```

**Python 示例**：

```python
import requests
r = requests.get(f"http://localhost:8000/api/v1/generations/{task_id}/result")
print(r.status_code, r.json().get("mode"))
```

#### 11. POST `/api/v1/generations/execute` — 同步执行 CadQuery 代码

**标签**：`generations`

**说明**：接收 Monaco Editor 编辑后的 CadQuery 代码，沙箱同步执行（静态扫描 + subprocess + timeout 隔离），自动产出 STEP/STL 并返回下载 URL。

**请求参数**（`ExecuteCodeRequest`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `code` | string | 是 | CadQuery Python 代码 |
| `output_format` | `"step"` \| `"stl"` \| `"dxf"` \| `"iges"` | 否 | 默认 `step` |
| `timeout` | int | 否 | 执行超时秒数，1-120，默认 30 |

**响应**（`200 OK`，`ExecuteCodeResponse`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `execution` | `ExecutionResult` | 执行结果（见 §6.5.10） |
| `geometry_validation` | `GeometryValidation` \| null | 几何校验结果 |
| `download_urls` | list[string] | 产出文件下载 URL（相对路径 `/api/v1/generations/files/...`） |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/v1/generations/execute \
  -H "Content-Type: application/json" \
  -d '{"code":"import cadquery as cq\nresult = cq.Workplane().box(10,10,10)","output_format":"step","timeout":30}'
```

**Python 示例**：

```python
import requests
code = "import cadquery as cq\nresult = cq.Workplane().box(10,10,10)"
r = requests.post(
    "http://localhost:8000/api/v1/generations/execute",
    json={"code": code, "output_format": "step", "timeout": 30},
)
data = r.json()
print(data["download_urls"])
```

#### 12. GET `/api/v1/generations/files/{file_path}` — 下载生成产物

**标签**：`generations`

**说明**：下载生成产物（STEP/STL/DXF 等）。防路径穿越校验。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `file_path` | string（路径参数，匹配 `/api/v1/generations/files/{file_path:path}`） | 相对 `UPLOAD_DIR/generations/` 的文件路径 |

**响应**：`FileResponse`，`media_type` 按扩展名映射：`.step/.stp`→`application/step`，`.stl`→`model/stl`，`.dxf`→`image/vnd.dxf`，其他→`application/octet-stream`。

**错误码**：

| 状态码 | 场景 |
|---|---|
| `400` | 路径穿越（`file_path` 解析后超出根目录） |
| `404` | 文件不存在 |

**curl 示例**：

```bash
curl -o part.step http://localhost:8000/api/v1/generations/files/abc123/run.step
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/generations/files/abc123/run.step")
with open("part.step", "wb") as f:
    f.write(r.content)
```

---

### 6.6 collaboration 模块

#### 13. POST `/api/v1/collaboration/optimize-from-review` — 基于审图缺陷优化图纸

**标签**：`collaboration`

**说明**：基于审图缺陷自动派发生成任务，实现"审图→生成"协同闭环。

**请求参数**（`OptimizeFromReviewRequest`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `review_task_id` | string | 是 | 原审图任务 ID |
| `user_id` | string | 否 | 默认 `anonymous`（注：实际 user_id 从 JWT 覆盖） |
| `output_format` | `"dxf"` \| `"step"` \| `"stl"` \| `"iges"` | 否 | 默认 `dxf`（便于复审闭环） |
| `auto_re_review` | bool | 否 | 是否自动触发修订后复审，默认 `true` |

**响应**（`202 Accepted`，`CollaborativeWorkflowResult`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `original_review_task_id` | string | 原审图任务 ID |
| `generation_task_id` | string | 生成任务 ID |
| `new_review_task_id` | string \| null | 修订后审图任务 ID（auto_re_review=False 时为 null） |
| `status` | `"dispatched"` \| `"partial"` \| `"failed"` | 闭环状态 |
| `defects_count` | int | 原审图缺陷数量 |
| `optimized_prompt` | string | 基于缺陷生成的 LLM prompt（截断前 500 字符） |
| `metadata` | object | 附加元信息（含 `optimize_task_id`、`websocket_url`） |

**错误码**：

| 状态码 | 场景 |
|---|---|
| `409` | 原审图任务状态非 `SUCCESS` |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/v1/collaboration/optimize-from-review \
  -H "Content-Type: application/json" \
  -d '{"review_task_id":"f7e6d5...","output_format":"dxf","auto_re_review":true}'
```

**Python 示例**：

```python
import requests
r = requests.post(
    "http://localhost:8000/api/v1/collaboration/optimize-from-review",
    json={"review_task_id": "f7e6d5...", "output_format": "dxf"},
)
print(r.json())
```

#### 14. GET `/api/v1/collaboration/optimize-result/{task_id}` — 查询优化任务结果

**标签**：`collaboration`

**说明**：查询 `run_optimize_from_review` 任务结果。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 优化任务 ID |

**响应**（`200 OK`，无 response_model，返回裸 dict）：

按 `status` 区分：

- `pending`：`{"task_id": "...", "status": "pending"}`
- `running`：`{"task_id": "...", "status": "running"}`
- `failed`：`{"task_id": "...", "status": "failed", "error": "..."}`
- `completed`：任务返回 dict + `status="completed"`
- `unknown`：兜底

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/collaboration/optimize-result/abc123...
```

**Python 示例**：

```python
import requests
r = requests.get(f"http://localhost:8000/api/v1/collaboration/optimize-result/{task_id}")
print(r.json()["status"])
```

#### 15. GET `/api/v1/collaboration/diff-report/{old_review_task_id}/{new_review_task_id}` — 修订前后对比报告

**标签**：`collaboration`

**说明**：生成修订前后两次审图的缺陷对比报告，标注 `resolved`/`unresolved`/`new` 闭环状态。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `old_review_task_id` | string | 原审图任务 ID |
| `new_review_task_id` | string | 修订后审图任务 ID |

**响应**（`200 OK`，`DiffReport`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `original_review_task_id` | string | 原审图任务 ID |
| `new_review_task_id` | string | 修订后审图任务 ID |
| `generation_task_id` | string \| null | 关联的生成任务 ID |
| `old_defects_count` | int | 原缺陷总数 |
| `new_defects_count` | int | 修订后缺陷总数 |
| `resolved_count` | int | 已修复缺陷数 |
| `unresolved_count` | int | 未修复缺陷数 |
| `new_count` | int | 新增缺陷数 |
| `old_compliance_score` | float \| null | 原合规性评分 |
| `new_compliance_score` | float \| null | 修订后合规性评分 |
| `score_improvement` | float \| null | 评分提升（new - old） |
| `diffs` | list[`DefectDiffItem`] | 缺陷对比详情 |
| `closure_rate` | float | 缺陷闭环率（0-1） |
| `generated_at` | string | 报告生成时间 ISO |
| `metadata` | object | 附加元数据 |

`DefectDiffItem`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `diff_status` | `"resolved"` \| `"unresolved"` \| `"new"` | 缺陷闭环状态 |
| `defect` | `DefectItem` | 缺陷条目（见 §6.4.7） |
| `matched_defect_index` | int \| null | 匹配的原缺陷索引（new 缺陷为 null） |
| `similarity_score` | float \| null | 匹配相似度（0-1） |

**错误码**：

| 状态码 | 场景 |
|---|---|
| `404` | 原审图/修订后审图任务结果不可用（非 SUCCESS） |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/collaboration/diff-report/old123.../new456...
```

**Python 示例**：

```python
import requests
r = requests.get(f"http://localhost:8000/api/v1/collaboration/diff-report/{old_id}/{new_id}")
d = r.json()
print(f"闭环率: {d['closure_rate']}, 评分提升: {d['score_improvement']}")
```

#### 16. POST `/api/v1/collaboration/feedback` — 提交用户反馈

**标签**：`collaboration`

**说明**：提交用户对审图缺陷的反馈（采纳/误报/修改建议）。反馈持久化到文件系统，后续可被 LLM 推理检索。

**请求参数**（`FeedbackRecord`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `review_task_id` | string | 是 | 审图任务 ID |
| `defect_index` | int | 是 | 缺陷在 `ReviewResult.defects` 中的索引（≥0） |
| `action` | `"accept"` \| `"reject_as_false_positive"` \| `"modify_suggestion"` | 是 | 反馈动作 |
| `comment` | string | 否 | 用户备注/新建议 |
| `user_id` | string | 否 | 反馈用户 ID（默认 anonymous） |
| `defect_snapshot` | `DefectItem` \| null | 否 | 被反馈的缺陷快照（未提供时自动填充） |
| `created_at` | string | 否 | 反馈时间 ISO（自动填充） |

**响应**（`201 Created`，`FeedbackRecord`）：回显提交的反馈记录（含自动填充的 `defect_snapshot`）。

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/v1/collaboration/feedback \
  -H "Content-Type: application/json" \
  -d '{"review_task_id":"f7e6d5...","defect_index":0,"action":"reject_as_false_positive","comment":"尺寸实际已标注"}'
```

**Python 示例**：

```python
import requests
r = requests.post(
    "http://localhost:8000/api/v1/collaboration/feedback",
    json={
        "review_task_id": "f7e6d5...",
        "defect_index": 0,
        "action": "accept",
        "comment": "确认缺陷",
    },
)
print(r.json())
```

#### 17. GET `/api/v1/collaboration/feedback/{review_task_id}` — 查询某审图任务的反馈

**标签**：`collaboration`

**说明**：查询某审图任务的所有用户反馈。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `review_task_id` | string | 审图任务 ID |

**响应**（`200 OK`，无 response_model，返回裸 dict）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `review_task_id` | string | 审图任务 ID |
| `count` | int | 反馈数 |
| `feedbacks` | list[`FeedbackRecord`] | 反馈记录列表 |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/collaboration/feedback/f7e6d5...
```

**Python 示例**：

```python
import requests
r = requests.get(f"http://localhost:8000/api/v1/collaboration/feedback/{review_task_id}")
print(r.json()["count"])
```

#### 18. GET `/api/v1/collaboration/feedback-stats` — 反馈统计

**标签**：`collaboration`

**说明**：全局反馈统计（用于仪表盘）。基于文件系统 `feedback.jsonl` 聚合。

**请求参数**：无

**响应**（`200 OK`，无 response_model，返回裸 dict）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `total` | int | 总反馈数 |
| `accept` | int | 采纳数 |
| `reject_as_false_positive` | int | 误报数 |
| `modify_suggestion` | int | 修改建议数 |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/collaboration/feedback-stats
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/collaboration/feedback-stats")
print(r.json())
# {'total': 6, 'accept': 3, 'reject_as_false_positive': 2, 'modify_suggestion': 1}
```

---

### 6.7 sketches 模块

#### 19. POST `/api/v1/sketches` — 提交草图转 CAD 任务（异步）

**标签**：`sketch`

**说明**：提交草图转 CAD 任务到 Celery `sketch` 队列（VLM 解析 + CadQuery 代码生成 + 沙箱执行）。强制标注 `precision_level=sketch_level`（spec.md R7）。

**请求参数**（`SketchCreateRequest`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `image_key` | string | 是 | 已上传草图图片的 file_key 或绝对路径 |
| `output_format` | `"dxf"` \| `"step"` \| `"stl"` \| `"iges"` | 否 | 默认 `dxf`（可编辑） |

**响应**（`202 Accepted`，`SketchTaskAccepted`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | Celery 任务 ID |
| `status` | `"queued"` | 固定值 |
| `websocket_url` | string | WS 路径 |
| `precision_level` | `"sketch_level"` | 固定值（强制草图级精度） |

**错误码**：

| 状态码 | 场景 |
|---|---|
| `400` | `image_key` 为空 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/v1/sketches \
  -H "Content-Type: application/json" \
  -d '{"image_key":"abc123_手绘.png","output_format":"dxf"}'
```

**Python 示例**：

```python
import requests
r = requests.post(
    "http://localhost:8000/api/v1/sketches",
    json={"image_key": "abc123_手绘.png", "output_format": "dxf"},
)
print(r.json())
```

#### 20. GET `/api/v1/sketches/{task_id}/result` — 查询草图转 CAD 任务结果

**标签**：`sketch`

**说明**：查询草图转 CAD 任务结果。所有 `output_files` 路径转换为下载 URL；原始路径保留在 `metadata.original_output_paths`。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | Celery 任务 ID |

**响应**（`SketchTaskResult`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务 ID |
| `success` | bool | 是否成功 |
| `precision_level` | `"sketch_level"` | 精度等级（强制） |
| `parse_result` | `SketchParseResult` | 草图解析结果 |
| `generated_code` | string | 生成的 CadQuery 代码 |
| `output_files` | list[string] | 输出文件下载 URL 列表 |
| `output_format` | string | 输出格式 |
| `warnings` | list[string] | 警告信息 |
| `metadata` | object | 附加元数据（含 `original_output_paths`） |

`SketchParseResult`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `features` | list[`SketchFeature`] | 识别到的几何特征列表 |
| `overall_shape` | string | 整体形状描述 |
| `dimensions_hint` | object | 草图中标注的尺寸 |
| `vlm_model` | string | VLM 模型名 |
| `elapsed_ms` | int | 解析耗时（毫秒） |
| `warnings` | list[string] | 警告信息 |

`SketchFeature`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `feature_type` | `line` \| `circle` \| `arc` \| `rectangle` \| `hole` \| `chamfer` \| `fillet` \| `polygon` \| `unknown` | 几何类型 |
| `parameters` | object | 类型相关参数 |
| `bbox` | list[float] \| null | 图像位置 `[x1,y1,x2,y2]`（归一化 0-1） |
| `confidence` | float | VLM 置信度（0-1） |
| `raw_text` | string | VLM 原始描述 |

**状态码与状态映射**：

| Celery 状态 | HTTP 状态 | 行为 |
|---|---|---|
| `PENDING` | `404` | `detail="task {id} not found or pending"` |
| `STARTED`/`RETRY` | `202` | 返回 `success=false`，warnings 含运行中提示 |
| `FAILURE` | `500` | `detail="task failed: ..."` |
| `SUCCESS` | `200` | 返回完整 `SketchTaskResult` |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/sketches/abc123.../result
```

**Python 示例**：

```python
import requests
r = requests.get(f"http://localhost:8000/api/v1/sketches/{task_id}/result")
d = r.json()
print("成功:", d["success"], "特征数:", len(d["parse_result"]["features"]))
```

#### 21. POST `/api/v1/sketches/calibrate` — 提交人工校准任务

**标签**：`sketch`

**说明**：基于原草图任务结果应用校准项并重新生成。校准后默认输出 DXF（可编辑）。

**请求参数**（`CalibrationRequest`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sketch_task_id` | string | 是 | 原草图任务 ID |
| `calibrations` | list[`CalibrationItem`] | 否 | 校准项列表 |

`CalibrationItem`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `feature_index` | int | 是 | 对应特征索引（≥0） |
| `feature_type` | string | 是 | 特征类型 |
| `parameter_name` | string | 是 | 参数名（如 `radius`/`length`/`diameter`） |
| `original_value` | float \| null | 否 | VLM 推断值 |
| `calibrated_value` | float | 是 | 用户校准值 |
| `unit` | string | 否 | 单位，默认 `mm` |

**响应**（`202 Accepted`，`CalibrationResult`）：受理响应（`success=false`，实际结果需轮询 `/calibrate/{task_id}/result`）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 校准任务 ID |
| `success` | bool | 是否成功（受理时为 false） |
| `calibrated_features` | list[`SketchFeature`] | 校准后特征（受理时为空） |
| `regenerated_code` | string | 重新生成的 CadQuery 代码（受理时为空） |
| `output_files` | object | 输出文件路径（格式→路径，受理时为空） |
| `warnings` | list[string] | 警告信息 |

**错误码**：

| 状态码 | 场景 |
|---|---|
| `409` | 原草图任务状态非 `SUCCESS` |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/v1/sketches/calibrate \
  -H "Content-Type: application/json" \
  -d '{"sketch_task_id":"abc123...","calibrations":[{"feature_index":0,"feature_type":"circle","parameter_name":"radius","calibrated_value":50.0,"unit":"mm"}]}'
```

**Python 示例**：

```python
import requests
r = requests.post(
    "http://localhost:8000/api/v1/sketches/calibrate",
    json={
        "sketch_task_id": "abc123...",
        "calibrations": [
            {"feature_index": 0, "feature_type": "circle",
             "parameter_name": "radius", "calibrated_value": 50.0}
        ],
    },
)
print(r.json()["task_id"])
```

#### 22. GET `/api/v1/sketches/calibrate/{task_id}/result` — 查询校准任务结果

**标签**：`sketch`

**说明**：查询 `run_sketch_calibration` 任务结果。`output_files`（dict）的值转换为下载 URL。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 校准任务 ID |

**响应**（`200 OK`，`CalibrationResult`，见 §6.7.21）。各状态均返回 `200`，通过 `success` 与 `warnings` 区分：

- `PENDING`/`STARTED`/`RETRY`/`FAILURE`：`success=false`，warnings 含状态提示
- `SUCCESS`：返回完整结果，`output_files` 为 `{格式: 下载URL}`

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/sketches/calibrate/abc123.../result
```

**Python 示例**：

```python
import requests, time
while True:
    r = requests.get(f"http://localhost:8000/api/v1/sketches/calibrate/{task_id}/result")
    d = r.json()
    if d["success"]:
        print(d["output_files"]); break
    time.sleep(2)
```

#### 23. GET `/api/v1/sketches/files/{file_path}` — 下载草图产物

**标签**：`sketch`

**说明**：下载草图产物（DXF/STEP/STL 等）。防路径穿越校验。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `file_path` | string（`{file_path:path}`） | 相对 `UPLOAD_DIR/sketches/` 的文件路径 |

**响应**：`FileResponse`，`media_type` 按扩展名映射（同 §6.5.12）。

**错误码**：

| 状态码 | 场景 |
|---|---|
| `400` | 路径穿越 |
| `404` | 文件不存在 |

**curl 示例**：

```bash
curl -o out.dxf http://localhost:8000/api/v1/sketches/files/abc123/run.dxf
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/sketches/files/abc123/run.dxf")
with open("out.dxf", "wb") as f:
    f.write(r.content)
```

---

### 6.8 kb 模块

#### 24. GET `/api/v1/kb/clauses` — 规范条款检索

**标签**：`knowledge-base`

**说明**：按自然语言检索工程规范条款，支持按规范编号与分类过滤。每条结果强制包含原文片段与来源文件，缺失时 `completeness=incomplete`。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | 是 | 查询文本（min_length=1） |
| `top_k` | int | 否 | 返回条数，1-50，默认 5 |
| `standard` | string | 否 | 规范编号过滤，逗号分隔 |
| `category` | string | 否 | 分类过滤，逗号分隔 |

**响应**（`200 OK`，`ClausesQueryResponse`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `query` | string | 查询文本 |
| `top_k` | int | 返回条数 |
| `results` | list[`ClauseSearchResult`] | 检索结果列表 |
| `total` | int | 实际返回条数 |

`ClauseSearchResult`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `standard` | string | 规范编号 |
| `clause_id` | string | 条款号 |
| `title` | string | 条款标题 |
| `original_text` | string | 条款原文片段 |
| `score` | float | 相似度得分 |
| `source_file` | string | 来源文件名 |
| `category` | string | 分类 |
| `keywords` | list[string] | 关键词 |
| `completeness` | `"complete"` \| `"incomplete"` | 完整性标记 |

**错误码**：

| 状态码 | 场景 |
|---|---|
| `503` | 知识库检索失败（Qdrant 不可用等） |

**curl 示例**：

```bash
curl "http://localhost:8000/api/v1/kb/clauses?query=尺寸标注&top_k=5&standard=GB/T%204457.4"
```

**Python 示例**：

```python
import requests
r = requests.get(
    "http://localhost:8000/api/v1/kb/clauses",
    params={"query": "尺寸标注", "top_k": 5, "standard": "GB/T 4457.4"},
)
print(r.json()["results"])
```

#### 25. GET `/api/v1/kb/standards` — 已索引规范列表

**标签**：`knowledge-base`

**说明**：返回当前 Qdrant collection 中已索引的规范编号列表。

**请求参数**：无

**响应**（`200 OK`，`StandardsListResponse`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `standards` | list[string] | 规范编号列表 |
| `count` | int | 规范数量 |

**错误码**：

| 状态码 | 场景 |
|---|---|
| `503` | 获取规范列表失败 |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/kb/standards
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/kb/standards")
print(r.json())
# {'standards': ['GB/T 1182', 'GB/T 4457.4'], 'count': 2}
```

#### 26. POST `/api/v1/kb/reindex` — 重建索引

**标签**：`knowledge-base`

**说明**：从 `kb/standards/` 目录重新构建向量索引，会删除并重建 Qdrant collection。

**请求参数**：无

**响应**（`200 OK`，`ReindexResponse`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `indexed_count` | int | 已索引条款数 |
| `collection` | string | Qdrant collection 名 |
| `message` | string | 附加消息 |

**错误码**：

| 状态码 | 场景 |
|---|---|
| `404` | 样本目录 `kb/standards/` 不存在 |
| `503` | 重建索引失败 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/v1/kb/reindex
```

**Python 示例**：

```python
import requests
r = requests.post("http://localhost:8000/api/v1/kb/reindex")
print(r.json())
# {'indexed_count': 42, 'collection': 'clauses', 'message': '已从 standards 重建索引'}
```

---

### 6.9 tasks 模块

#### 27. GET `/api/v1/tasks/{task_id}` — 查询任务状态

**标签**：`tasks`

**说明**：通用任务状态查询，适用于所有 Celery 任务（reviews/generations/sketch/collaboration/solidworks/assembly）。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | Celery 任务 ID |

**响应**（`200 OK`，`TaskStatusResponse`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务 ID |
| `status` | `"queued"` \| `"running"` \| `"succeeded"` \| `"failed"` \| `"canceled"` | 业务状态 |
| `progress` | int | 进度（当前固定 0，未实现细分） |
| `result` | object \| null | 结果（succeeded 时返回 dict；非 dict 时包装为 `{"value": str}`） |
| `error` | string \| null | 错误信息（failed 时） |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/tasks/abc123...
```

**Python 示例**：

```python
import requests, time
while True:
    r = requests.get(f"http://localhost:8000/api/v1/tasks/{task_id}")
    d = r.json()
    print(d["status"])
    if d["status"] in ("succeeded", "failed", "canceled"):
        break
    time.sleep(2)
```

#### 28. POST `/api/v1/tasks/{task_id}/cancel` — 取消任务

**标签**：`tasks`

**说明**：调用 `celery_app.control.revoke(task_id, terminate=False)`，阻止排队中的任务开始执行（不强制终止已执行中的任务）。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | Celery 任务 ID |

**响应**（`202 Accepted`，返回裸 dict）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务 ID |
| `status` | `"canceled"` | 固定值 |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/v1/tasks/abc123.../cancel
```

**Python 示例**：

```python
import requests
r = requests.post(f"http://localhost:8000/api/v1/tasks/{task_id}/cancel")
print(r.json())
# {'task_id': 'abc123...', 'status': 'canceled'}
```

---

### 6.10 observability 模块

> **说明**：本模块 6 个端点均无显式 `response_model`，返回裸 dict。以下字段表基于 `backend/app/observability/` 与 `backend/app/services/review/feedback_analytics.py` 实际实现，非 pydantic 强类型约束。

#### 29. GET `/api/v1/observability/queue-status` — Celery 队列状态

**标签**：`observability`

**说明**：采集各 Celery 队列的活跃/排队/失败任务数与 worker 状态，触发阈值告警。通过 `celery_app.control.inspect()` 与 Redis `LLEN` 采集。

**请求参数**：无

**响应**（`200 OK`，裸 dict）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `collected_at` | string | 采集时间 ISO（UTC） |
| `worker_count` | int | 在线 worker 数 |
| `active_workers` | list[string] | 在线 worker 名称列表 |
| `queues` | object | 各队列状态，key=队列名 |
| `queues[<name>].active` | int | 正在执行任务数 |
| `queues[<name>].reserved` | int | 已预取待执行数 |
| `queues[<name>].scheduled` | int | broker 中排队数（Redis LLEN） |
| `queues[<name>].failed` | int | 失败数（实时探测无法获取，固定 0） |
| `total_failed` | int | 总失败数（固定 0，需历史统计） |
| `alerts` | list[object] | 触发的告警列表 |
| `alerts[].level` | string | `"critical"` \| `"warning"` |
| `alerts[].rule` | string | `"worker_offline"` \| `"queue_backlog"` \| `"queue_failure_rate"` |
| `alerts[].queue` | string | 队列名（worker_offline 时为 `*`） |
| `alerts[].value` | int | 实际值 |
| `alerts[].threshold` | int | 阈值 |
| `alerts[].message` | string | 告警消息 |
| `errors` | list[string] | 采集错误列表（如 `inspect_unavailable`） |

**告警阈值**：`OBS_QUEUE_BACKLOG_ALERT=50`、`OBS_QUEUE_FAILURE_RATE_ALERT=10.0`。

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/observability/queue-status
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/observability/queue-status")
d = r.json()
print(f"worker={d['worker_count']}, queues={list(d['queues'].keys())}, alerts={len(d['alerts'])}")
```

#### 30. GET `/api/v1/observability/feedback-summary` — 反馈总体统计

**标签**：`observability`

**说明**：统计总反馈数 / 误报率 / 采纳率 / 修改建议率。基于 `feedback.jsonl` 聚合。

**请求参数**：无

**响应**（`200 OK`，裸 dict）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `total` | int | 总反馈数 |
| `accept_count` | int | 采纳数 |
| `reject_as_false_positive_count` | int | 误报数 |
| `modify_suggestion_count` | int | 修改建议数 |
| `accept_rate` | float | 采纳率（百分比） |
| `false_positive_rate` | float | 误报率（百分比） |
| `modify_rate` | float | 修改建议率（百分比） |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/observability/feedback-summary
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/observability/feedback-summary")
print(r.json())
# {'total': 6, 'accept_count': 3, 'reject_as_false_positive_count': 2,
#  'modify_suggestion_count': 1, 'accept_rate': 50.0,
#  'false_positive_rate': 33.33, 'modify_rate': 16.67}
```

#### 31. GET `/api/v1/observability/feedback-by-category` — 按类别统计反馈

**标签**：`observability`

**说明**：按缺陷类别分组统计反馈。

**请求参数**：无

**响应**（`200 OK`，裸 dict）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `categories` | list[object] | 类别统计列表 |
| `categories[].category` | string | 类别名 |
| `categories[].total` | int | 该类别反馈总数 |
| `categories[].accept_count` | int | 采纳数 |
| `categories[].reject_as_false_positive_count` | int | 误报数 |
| `categories[].modify_suggestion_count` | int | 修改建议数 |
| `categories[].false_positive_rate` | float | 误报率（百分比） |
| `categories[].accept_rate` | float | 采纳率（百分比） |
| `category_count` | int | 类别数量 |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/observability/feedback-by-category
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/observability/feedback-by-category")
print(r.json()["category_count"])
```

#### 32. GET `/api/v1/observability/feedback-trend` — 反馈时间趋势

**标签**：`observability`

**说明**：按时间粒度统计反馈趋势。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `granularity` | `"day"` \| `"week"` \| `"month"` | 否 | 默认 `day` |

**响应**（`200 OK`，裸 dict）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `granularity` | string | 时间粒度 |
| `bucket_count` | int | 时间桶数量 |
| `skipped_records` | int | 无法解析时间而被跳过的记录数 |
| `trend` | list[object] | 趋势列表 |
| `trend[].bucket` | string | 时间桶 key |
| `trend[].total` | int | 该桶反馈总数 |
| `trend[].accept` | int | 采纳数 |
| `trend[].reject_as_false_positive` | int | 误报数 |
| `trend[].modify_suggestion` | int | 修改建议数 |

**curl 示例**：

```bash
curl "http://localhost:8000/api/v1/observability/feedback-trend?granularity=day"
```

**Python 示例**：

```python
import requests
r = requests.get(
    "http://localhost:8000/api/v1/observability/feedback-trend",
    params={"granularity": "week"},
)
print(r.json()["bucket_count"])
```

#### 33. GET `/api/v1/observability/llm-cost-summary` — LLM 推理成本汇总

**标签**：`observability`

**说明**：按模型汇总 LLM 推理成本，基于 `tmp_metrics/llm_metrics.jsonl` 聚合。

**请求参数**：无

**响应**（`200 OK`，裸 dict）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `total_calls` | int | 总调用数 |
| `total_cost_usd` | float | 总成本（USD） |
| `total_input_tokens` | int | 总输入 token 数 |
| `total_output_tokens` | int | 总输出 token 数 |
| `by_model` | list[object] | 按模型汇总（按成本降序） |
| `by_model[].model` | string | 模型名 |
| `by_model[].calls` | int | 调用数 |
| `by_model[].input_tokens` | int | 输入 token 数 |
| `by_model[].output_tokens` | int | 输出 token 数 |
| `by_model[].total_tokens` | int | 总 token 数 |
| `by_model[].cost_usd` | float | 成本（USD） |
| `by_model[].elapsed_ms_total` | float | 总耗时（毫秒） |
| `by_model[].avg_latency_ms` | float | 平均耗时（毫秒） |
| `by_model[].failures` | int | 失败次数 |
| `by_model[].failure_rate` | float | 失败率（百分比） |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/observability/llm-cost-summary
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/observability/llm-cost-summary")
d = r.json()
print(f"总调用 {d['total_calls']}, 总成本 ${d['total_cost_usd']}")
```

#### 34. GET `/api/v1/observability/llm-latency` — LLM 推理延迟分布

**标签**：`observability`

**说明**：计算 LLM 推理延迟分布（p50/p95/p99 + 平均 + 最大）。

**请求参数**：无

**响应**（`200 OK`，裸 dict）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `overall` | object | 总体延迟分布 |
| `overall.count` | int | 样本数 |
| `overall.avg_ms` | float | 平均（毫秒） |
| `overall.p50_ms` | float | p50（毫秒） |
| `overall.p95_ms` | float | p95（毫秒） |
| `overall.p99_ms` | float | p99（毫秒） |
| `overall.max_ms` | float | 最大（毫秒） |
| `by_model` | object | 按模型分组，key=模型名，value 同 `overall` 结构 |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/observability/llm-latency
```

**Python 示例**：

```python
import requests
r = requests.get("http://localhost:8000/api/v1/observability/llm-latency")
d = r.json()
print(f"p95={d['overall']['p95_ms']}ms, count={d['overall']['count']}")
```

---

### 6.11 llm 模块

#### 35. POST `/api/v1/llm/stream` — LLM 流式输出（SSE）

**标签**：`llm`

**说明**：以 Server-Sent Events 形式流式输出 LLM 响应。`LLM_STREAM_ENABLED=False` 时回退为普通 JSON 响应（一次性返回完整内容）。

**请求参数**（`StreamChatRequest`，定义于 `endpoints/llm.py`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `messages` | list[`ChatMessage`] | 是 | 对话消息列表 |
| `request_id` | string \| null | 否 | 流请求 ID（None 时自动生成）；客户端可传入以便主动取消 |
| `temperature` | float | 否 | 0.0-2.0，默认 0.2 |
| `max_tokens` | int | 否 | 1-32768，默认 2048 |

`ChatMessage`（`app.services.ai.base`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `role` | `"system"` \| `"user"` \| `"assistant"` | 角色 |
| `content` | string | 内容 |
| `images` | list[string] \| null | base64 编码图片列表 |

**响应**：

- **流式模式**（`LLM_STREAM_ENABLED=True`）：`StreamingResponse`，`media_type="text/event-stream"`
  - SSE 事件：
    - `data: {"chunk": "...", "request_id": "..."}\n\n` — 文本片段
    - `data: {"done": true, "request_id": "..."}\n\n` — 流结束
    - `data: {"cancelled": true, "request_id": "..."}\n\n` — 被取消
    - `data: {"error": "...", "request_id": "..."}\n\n` — 错误
  - 响应头：`Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`、`X-Request-Id: <id>`
- **降级模式**（`LLM_STREAM_ENABLED=False`）：`JSONResponse`
  - `{"request_id": "...", "content": "...", "model": "...", "streamed": false}`

**curl 示例**：

```bash
curl -N -X POST http://localhost:8000/api/v1/llm/stream \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"解释 CadQuery 的 Workplane"}]}'
```

**Python 示例**（SSE 客户端）：

```python
import requests
r = requests.post(
    "http://localhost:8000/api/v1/llm/stream",
    json={"messages": [{"role": "user", "content": "解释 CadQueue 的 Workplane"}]},
    stream=True,
)
for line in r.iter_lines(decode_unicode=True):
    if line.startswith("data: "):
        print(line[6:])
```

#### 36. POST `/api/v1/llm/cancel/{request_id}` — 主动取消流式请求

**标签**：`llm`

**说明**：设置 Redis 取消标志位，streamer 在下一次 chunk 检查时退出。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `request_id` | string | 流请求 ID |

**请求参数**（`StreamCancelRequest`，可选 body）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `reason` | string | 否 | 取消原因，默认 `client_cancelled` |

**响应**（`200 OK`，`StreamCancelResponse`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `request_id` | string | 流请求 ID |
| `cancelled` | bool | 是否成功设置取消标志 |
| `message` | string | 说明（如 `cancel flag set` / `stream not found` / `stream already in terminal state`） |

**curl 示例**：

```bash
curl -X POST http://localhost:8000/api/v1/llm/cancel/req-abc123 \
  -H "Content-Type: application/json" \
  -d '{"reason":"用户主动取消"}'
```

**Python 示例**：

```python
import requests
r = requests.post(
    f"http://localhost:8000/api/v1/llm/cancel/{request_id}",
    json={"reason": "用户主动取消"},
)
print(r.json())
# {'request_id': 'req-abc123', 'cancelled': True, 'message': 'cancel flag set'}
```

#### 37. GET `/api/v1/llm/stream/{request_id}/status` — 查询流式请求状态

**标签**：`llm`

**说明**：查询流式请求的当前状态。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `request_id` | string | 流请求 ID |

**响应**（`200 OK`，`StreamStatusResponse`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `request_id` | string | 流请求 ID |
| `found` | bool | 是否找到（已结束或从未开始为 false） |
| `status` | object \| null | 状态字典（含 `status` 字段：`running`/`completed`/`cancelled`/`failed`/`timeout`） |

**curl 示例**：

```bash
curl http://localhost:8000/api/v1/llm/stream/req-abc123/status
```

**Python 示例**：

```python
import requests
r = requests.get(f"http://localhost:8000/api/v1/llm/stream/{request_id}/status")
print(r.json())
# {'request_id': 'req-abc123', 'found': True, 'status': {'status': 'running', ...}}
```

---

### 6.12 websocket 模块

#### 38. WS `/api/v1/ws/tasks/{task_id}` — 任务进度推送

**标签**：`websocket`

**说明**：订阅指定任务的进度更新，每秒推送一次状态。P0 阶段为轻量轮询实现（每秒查 Celery `AsyncResult`），Task 6 升级为 Redis pubsub。

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | Celery 任务 ID |

**推送帧格式**（JSON）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务 ID |
| `status` | `"queued"` \| `"running"` \| `"succeeded"` \| `"failed"` \| `"canceled"` | 业务状态 |
| `progress` | int | 进度（固定 0） |
| `result` | object | **仅 succeeded**：任务返回值（dict 或 `{"value": str}`） |
| `error` | string | **仅 failed**：错误信息 |

**生命周期**：

1. 客户端建立 WS 连接 → 服务端 `accept`
2. 每秒推送一帧当前状态
3. 进入终态（`succeeded` / `failed` / `canceled`）→ 推送终态帧后**服务端主动关闭连接**

**Python 示例**（websockets 库）：

```python
import asyncio
import websockets
import json

async def listen(task_id):
    uri = f"ws://localhost:8000/api/v1/ws/tasks/{task_id}"
    async with websockets.connect(uri) as ws:
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            print(data["status"])
            if data["status"] in ("succeeded", "failed", "canceled"):
                break

asyncio.run(listen("abc123..."))
```

**JavaScript 示例**（浏览器原生 WebSocket）：

```javascript
const ws = new WebSocket("ws://localhost:8000/api/v1/ws/tasks/abc123...");
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.status);
  if (["succeeded", "failed", "canceled"].includes(data.status)) {
    ws.close();
  }
};
```

---

## 7. 限流与配额

**当前阶段（P0/P1/P2）未实现限流与配额机制**。所有端点无速率限制、无调用配额、无并发上限。

**规划**（未实施）：

- 生产环境应引入 nginx `limit_req` 或 `slowapi` 做速率限制
- LLM 流式端点应限制并发连接数（避免 OOM）
- 文件上传应按 user_id 隔离配额

> 实事求是声明：上述规划项均**未在代码中实现**，仅作为后续部署建议。

---

## 8. SDK 调用示例

### 8.1 Python（requests）完整工作流

#### 工作流 1：审图 → 协同优化 → 对比报告

```python
import requests
import time

BASE = "http://localhost:8000"
HEADERS = {"Authorization": "Bearer <jwt>"}

# 1) 上传文件
with open("零件.dxf", "rb") as f:
    r = requests.post(f"{BASE}/api/v1/uploads", headers=HEADERS, files={"file": f})
file_key = r.json()["file_key"]

# 2) 提交审图
r = requests.post(
    f"{BASE}/api/v1/reviews", headers=HEADERS,
    json={"file_key": file_key, "file_type": "dxf"},
)
review_task_id = r.json()["task_id"]
print(f"审图任务已提交: {review_task_id}")

# 3) 轮询审图结果
while True:
    r = requests.get(f"{BASE}/api/v1/reviews/{review_task_id}/result")
    d = r.json()
    print(f"  状态: {d['status']}")
    if d["status"] == "completed":
        print(f"  合规分: {d['compliance_score']}, 缺陷数: {len(d['defects'])}")
        break
    if d["status"] == "failed":
        print(f"  失败: {d.get('error')}"); raise SystemExit(1)
    time.sleep(2)

# 4) 基于缺陷优化图纸
r = requests.post(
    f"{BASE}/api/v1/collaboration/optimize-from-review", headers=HEADERS,
    json={"review_task_id": review_task_id, "output_format": "dxf", "auto_re_review": True},
)
gen_task_id = r.json()["generation_task_id"]
new_review_task_id = r.json().get("new_review_task_id")
print(f"优化任务已派发: {gen_task_id}")

# 5) 等待复审完成（auto_re_review=True 时自动触发）
if new_review_task_id:
    while True:
        r = requests.get(f"{BASE}/api/v1/reviews/{new_review_task_id}/result")
        d = r.json()
        if d["status"] == "completed":
            break
        time.sleep(2)

# 6) 获取对比报告
r = requests.get(
    f"{BASE}/api/v1/collaboration/diff-report/{review_task_id}/{new_review_task_id}"
)
diff = r.json()
print(f"闭环率: {diff['closure_rate']}, 评分提升: {diff['score_improvement']}")
```

#### 工作流 2：草图转 CAD + 人工校准

```python
import requests, time, json
from websocket import create_connection  # pip install websocket-client

BASE = "http://localhost:8000"

# 1) 上传草图
with open("手绘.png", "rb") as f:
    r = requests.post(f"{BASE}/api/v1/uploads", files={"file": f})
image_key = r.json()["file_key"]

# 2) 提交草图转 CAD
r = requests.post(
    f"{BASE}/api/v1/sketches",
    json={"image_key": image_key, "output_format": "dxf"},
)
sketch_task_id = r.json()["task_id"]

# 3) WebSocket 监听进度
ws = create_connection(f"ws://localhost:8000/api/v1/ws/tasks/{sketch_task_id}")
while True:
    msg = json.loads(ws.recv())
    print(msg["status"])
    if msg["status"] == "succeeded":
        break
ws.close()

# 4) 查询结果
r = requests.get(f"{BASE}/api/v1/sketches/{sketch_task_id}/result")
result = r.json()
print(f"特征数: {len(result['parse_result']['features'])}")

# 5) 人工校准
calibrations = [
    {"feature_index": 0, "feature_type": "circle",
     "parameter_name": "radius", "calibrated_value": 50.0, "unit": "mm"}
]
r = requests.post(
    f"{BASE}/api/v1/sketches/calibrate",
    json={"sketch_task_id": sketch_task_id, "calibrations": calibrations},
)
calib_task_id = r.json()["task_id"]

# 6) 轮询校准结果
while True:
    r = requests.get(f"{BASE}/api/v1/sketches/calibrate/{calib_task_id}/result")
    d = r.json()
    if d["success"]:
        print(f"校准完成，产物: {d['output_files']}"); break
    time.sleep(2)
```

#### 工作流 3：LLM 流式对话

```python
import requests

# 流式
r = requests.post(
    "http://localhost:8000/api/v1/llm/stream",
    json={"messages": [{"role": "user", "content": "解释形位公差"}],
          "request_id": "my-req-001"},
    stream=True,
)
for line in r.iter_lines(decode_unicode=True):
    if line and line.startswith("data: "):
        print(line[6:])

# 主动取消
requests.post("http://localhost:8000/api/v1/llm/cancel/my-req-001",
              json={"reason": "用户切换话题"})
```

### 8.2 curl 速查

```bash
# 健康检查
curl http://localhost:8000/api/v1/healthz
curl http://localhost:8000/api/v1/readyz

# 上传文件
curl -X POST http://localhost:8000/api/v1/uploads -F "file=@零件.dxf"

# 提交审图
curl -X POST http://localhost:8000/api/v1/reviews \
  -H "Content-Type: application/json" \
  -d '{"file_key":"<file_key>","file_type":"dxf"}'

# 查询任务状态
curl http://localhost:8000/api/v1/tasks/<task_id>

# 取消任务
curl -X POST http://localhost:8000/api/v1/tasks/<task_id>/cancel

# 知识库检索
curl "http://localhost:8000/api/v1/kb/clauses?query=尺寸标注&top_k=5"

# 重建知识库索引
curl -X POST http://localhost:8000/api/v1/kb/reindex

# 队列状态
curl http://localhost:8000/api/v1/observability/queue-status

# LLM 成本汇总
curl http://localhost:8000/api/v1/observability/llm-cost-summary

# LLM 流式（-N 禁用缓冲）
curl -N -X POST http://localhost:8000/api/v1/llm/stream \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}]}'

# 下载产物
curl -o part.step http://localhost:8000/api/v1/generations/files/<path>
```

---

## 9. 附录

### 9.1 OpenAPI 自动生成

FastAPI 自动生成 OpenAPI 3.x 规范，访问：

- `GET /openapi.json` — OpenAPI JSON
- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc

### 9.2 关键配置项

| 配置键 | 默认值 | 说明 |
|---|---|---|
| `APP_NAME` | `SynthDraft Backend` | 服务名 |
| `APP_VERSION` | `0.1.0` | 版本号 |
| `APP_ENV` | `development` | 环境（`production` 时启用生产模式） |
| `UPLOAD_DIR` | `./tmp_uploads` | 上传根目录 |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:8000` | CORS 允许来源 |
| `JWT_SECRET_KEY` | `change-this-in-production-...` | JWT 密钥（生产必改） |
| `JWT_ALGORITHM` | `HS256` | JWT 算法 |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Access Token 有效期（分钟） |
| `LLM_PROVIDER` | `ollama` | LLM provider |
| `LLM_STREAM_ENABLED` | `True` | LLM 流式输出开关 |
| `LLM_STREAM_TIMEOUT` | `300` | 流式超时（秒） |
| `OBS_QUEUE_BACKLOG_ALERT` | `50` | 队列堆积告警阈值 |
| `OBS_QUEUE_FAILURE_RATE_ALERT` | `10.0` | 队列失败率告警阈值（百分比） |
| `OBS_LLM_METRICS_PATH` | `./tmp_metrics/llm_metrics.jsonl` | LLM 指标持久化路径 |
| `OBS_FEEDBACK_STORE_PATH` | `./tmp_metrics/feedback.jsonl` | 反馈持久化路径 |
| `CELERY_BROKER_URL` | `redis://redis:6379/1` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/2` | Celery result backend |

### 9.3 Celery 任务清单

| 任务名 | 队列 | 模块 |
|---|---|---|
| `app.celery.tasks.reviews.run_review` | reviews | 审图 |
| `app.celery.tasks.generations.run_generation` | generations | 生成 |
| `app.celery.tasks.sketch.run_sketch_to_cad` | sketch | 草图转 CAD |
| `app.celery.tasks.sketch.run_sketch_calibration` | sketch | 草图校准 |
| `app.celery.tasks.collaboration.run_optimize_from_review` | collaboration | 协同优化 |
| `app.celery.tasks.assembly.run_assembly_generation` | assembly | 装配体生成 |
| `app.celery.tasks.solidworks.read_sldprt` | solidworks | 读 SLDPRT |
| `app.celery.tasks.solidworks.read_sldasm` | solidworks | 读 SLDASM |
| `app.celery.tasks.solidworks.generate_sldprt_from_cadquery` | solidworks | 从 CadQuery 生成 SLDPRT |
| `app.celery.tasks.solidworks.generate_sldprt_from_features` | solidworks | 从特征生成 SLDPRT |
| `app.celery.tasks.solidworks.generate_sldasm_from_components` | solidworks | 生成 SLDASM |
| `app.celery.tasks.solidworks.license_status` | solidworks | 许可证状态 |

### 9.4 文档信息源

本文档基于以下实际代码文件编写，未做臆测：

- `backend/app/main.py` — FastAPI 入口与全局配置
- `backend/app/api/v1/router.py` — 路由聚合
- `backend/app/api/v1/endpoints/*.py` — 12 个端点模块
- `backend/app/schemas/*.py` — 16 个 schema 模块
- `backend/app/api/deps.py` — 依赖注入（鉴权）
- `backend/app/services/ai/base.py` — ChatMessage schema
- `backend/app/celery_app.py` — Celery 配置
- `backend/app/config.py` — 全局配置
- `backend/app/observability/queue_monitor.py` — 队列监控
- `backend/app/observability/llm_metrics.py` — LLM 指标
- `backend/app/services/review/feedback_analytics.py` — 反馈分析
- `backend/app/services/collaboration/feedback_store.py` — 反馈存储
- `.trae/specs/ai-engineering-design-assistant/P1_GATE_REPORT.md` — P1 阶段报告

### 9.5 已知限制（实事求是声明）

| 项 | 现状 | 说明 |
|---|---|---|
| 鉴权 | 宽容模式 | 未提供 token 时返回 anonymous，生产应强制 |
| 限流 | 未实现 | 无速率限制、无配额 |
| WebSocket | 轮询实现 | 每秒轮询 Celery，未用 Redis pubsub |
| 任务进度 | 固定 0 | `progress` 字段未实现细分百分比 |
| `uploads` 列表 | 无分页 | 开发态调试用，不按 user_id 隔离 |
| `observability` 响应 | 裸 dict | 无 response_model 强类型约束 |
| 队列失败数 | 固定 0 | 实时探测无法获取历史失败数 |
| 限流配额 | 未实现 | 见 §7 |
| `assembly` 端点 | 无 API | 装配体生成任务无独立 HTTP 端点，仅通过 Celery 调用 |
