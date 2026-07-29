# 全面 V2-V4 验证 Spec

## Why

上一轮在 `fix-2f-route-bug.md` 中针对单一 bug 定义了 V1-V4 验证（静态/单元/e2e/数据一致性），范围仅限 KB 模块的两个 `/standards/versions` 端点，且 e2e 仅覆盖了 "happy path"。但全后端共 47 个 HTTP 端点 + 1 个 WebSocket，分散在 11 个 endpoints 文件中，从未做过**统一的、以端点为粒度、覆盖所有路径分支（不止于兜底/降级路径）**的 V2-V4 验证。

用户明确要求："测试应全面深入，各部分路径应当不止于兜底路径，必须全面覆盖所有路径！VLM 远程 API 除外。不准偷懒！不准敷衍！"

遵循"以跳过验证为耻，以主动测试为荣；以假装理解为耻，以诚实无知为荣"原则：每一项必须基于真实证据（HTTP 状态码 + 响应片段 + 产出文件 / DB 行），不可主观断言 PASS。

## What Changes

- **新增统一测试报告**：`backend/tmp_audit_logs/v2v4_comprehensive_verification.md`，按 endpoints 文件分节，每个端点记录 V2/V3/V4 三个维度的真实证据
- **V2 单元测试维度**：对每个 endpoint 模块运行 `verify_taskN.py` 或等效单元测试，覆盖：
  - 路由注册校验（路径 + 方法）
  - Schema 验证（请求/响应 Pydantic 模型）
  - 输入校验（非法输入返回 422）
  - 异常路径（404/409/503 等）
- **V3 端到端维度**：对每个端点发起真实 HTTP 调用，覆盖：
  - **REAL-PATH**（真实业务管线，优先）
  - **FALLBACK-PATH**（降级路径，必须显式覆盖，不可仅测 happy path）
  - **ERROR-PATH**（错误路径：非法参数 / 不存在资源 / 冲突状态）
  - **SYNC-BYPASS**（Celery worker 卡死时 `task.apply()` 同步执行）
- **V4 数据一致性维度**：验证每次 POST/PUT 后的持久化层：
  - PostgreSQL（`standard_versions` / `standard_notifications` / `feedback` 等表）
  - Qdrant（KB 索引 clause 向量）
  - 文件系统（上传文件 / 生成产物 / 报告 HTML/PDF）
  - 内存状态（如 active profile 切换）
- **VLM 远程 API 显式排除**：用户明确要求，本 spec 不测试 OpenAI/Anthropic 远程 VLM API（本地 VLM `minicpm-v:latest` 仍需测）
- **环境主动修复**：测试中遇到缺失依赖/未启动服务，必须主动安装/启动（八荣八耻原则：以跳过验证为耻，以主动测试为荣）

## Impact

- Affected specs:
  - `fix-2f-route-bug`（V2-V4 概念来源，本 spec 是其扩展版）
  - `realpath-test-backend-api`（Task 8 真实路径测试，本 spec 复用其报告格式）
  - `complete-remaining-test-gaps`（第二轮敷衍补救，本 spec 验证其修复是否仍生效）
  - `fix-remaining-env-issues-except-remote-vlm`（环境问题修复，本 spec 验证修复持久性）
- Affected code: 无源码修改（除非测试发现新 bug，则记录到报告"问题清单"并视情况新建 fix spec）
- Affected docs: 新增 `backend/tmp_audit_logs/v2v4_comprehensive_verification.md`

## 端点清单（47 HTTP + 1 WS）

按文件分组（**所有路径均以 `/api/v1` 为全局前缀**，下方已省略前缀，实际调用需补回）：

### 1. health.py（2 端点）
- `GET /healthz` — 健康检查（实际路径 `/api/v1/healthz`）
- `GET /readyz` — 就绪检查（实际路径 `/api/v1/readyz`）

### 2. uploads.py（2 端点）
- `POST /uploads` — 上传文件
- `GET /uploads` — 列出上传

### 3. reviews.py（3 端点）
- `POST /reviews` — 创建审图任务
- `GET /reviews/{task_id}/result` — 获取审图结果
- `GET /reviews/{task_id}/report` — 下载审图报告

### 4. generations.py（4 端点）
- `POST /generations` — 创建文本生成任务
- `GET /generations/{task_id}/result` — 获取生成结果
- `POST /generations/execute` — 执行编辑后的代码
- `GET /generations/files/{file_path:path}` — 下载生成文件

### 5. kb.py（13 端点）
- `GET /kb/clauses` — 检索条款
- `GET /kb/standards` — 列出规范
- `POST /kb/reindex` — 重建索引
- `POST /kb/enterprise-standards/import` — 导入企业标准
- `GET /kb/standards/conflicts` — 检测规范冲突
- `GET /kb/profiles` — 列出规范 profile
- `POST /kb/profiles` — 创建 profile
- `POST /kb/profiles/active` — 设置 active profile
- `GET /kb/standards/library` — 预置规范库
- `GET /kb/standards/library/{category}` — 按类别列出
- `GET /kb/standards/versions` — 列出版本（query 参数，已修复 %2F）
- `POST /kb/standards/versions` — 注册版本（query 参数）
- `GET /kb/standards/notifications` — 更新通知

### 6. llm.py（3 端点）
- `POST /llm/stream` — 流式 chat（SSE）
- `POST /llm/cancel/{request_id}` — 取消流
- `GET /llm/stream/{request_id}/status` — 流状态

### 7. sketch.py（5 端点）
- `POST /sketches` — 草图转 CAD
- `GET /sketches/{task_id}/result` — 获取草图结果
- `POST /sketches/calibrate` — 校准草图
- `GET /sketches/calibrate/{task_id}/result` — 获取校准结果
- `GET /sketches/files/{file_path:path}` — 下载草图文件

### 8. collaboration.py（6 端点）
- `POST /collaboration/optimize-from-review` — 从审图创建优化任务
- `GET /collaboration/optimize-result/{task_id}` — 获取优化结果
- `GET /collaboration/diff-report/{old}/{new}` — 差异报告
- `POST /collaboration/feedback` — 提交反馈
- `GET /collaboration/feedback/{review_task_id}` — 列出反馈
- `GET /collaboration/feedback-stats` — 反馈统计

### 9. observability.py（6 端点）
- `GET /observability/queue-status` — 队列状态
- `GET /observability/feedback-summary` — 反馈汇总
- `GET /observability/feedback-by-category` — 按类别反馈
- `GET /observability/feedback-trend` — 反馈趋势
- `GET /observability/llm-cost-summary` — LLM 成本
- `GET /observability/llm-latency` — LLM 延迟

### 10. tasks.py（2 端点）
- `GET /tasks/{task_id}` — 任务状态
- `POST /tasks/{task_id}/cancel` — 取消任务

### 11. ws.py（1 WebSocket）
- `WEBSOCKET /ws/tasks/{task_id}` — 任务进度推送

## ADDED Requirements

### Requirement: V2 单元测试覆盖（路由 + Schema + 输入校验）

系统 SHALL 对每个 endpoints 模块运行单元测试，验证：
- 所有路由已正确注册（路径 + HTTP 方法）
- 请求/响应 Pydantic Schema 与代码一致
- 非法输入返回 422 Unprocessable Entity
- 异常路径返回正确状态码（404/409/503）

#### Scenario: 路由注册校验

- **WHEN** 读取 `app.main.app.routes`
- **THEN** SHALL 验证每个端点的路径与方法已在 FastAPI app 中注册
- **AND** 不可仅因 `app` 导入成功即 PASS

#### Scenario: Schema 非法输入校验

- **WHEN** 对 `POST /uploads` 提交空 body
- **AND** 对 `POST /reviews` 提交缺少 `file_key` 字段的 body
- **THEN** SHALL 收到 HTTP 422 + 错误详情
- **AND** 不可仅因 200 即 PASS

### Requirement: V3 端到端覆盖（REAL-PATH + FALLBACK-PATH + ERROR-PATH）

系统 SHALL 对每个端点发起真实 HTTP 调用，**显式覆盖所有路径分支**，不止于 happy path。

#### Scenario: REAL-PATH 真实业务管线

- **WHEN** 调用 `POST /reviews` 上传 DXF 并触发审图
- **THEN** SHALL 走 VLM/规则引擎真实管线
- **AND** 验证 `compliance_score` 为数值 + `defects` 数组结构正确
- **AND** 不可仅因 task_id 返回即 PASS

#### Scenario: FALLBACK-PATH 降级路径

- **WHEN** LLM 不可用导致生成走 template_match
- **THEN** SHALL 显式触发降级路径并验证 `mode=template`
- **AND** 不可仅测 `mode=llm` 即认为生成端点 PASS
- **AND** 必须记录降级原因（LLM 不可用 / Qdrant 不可用 / Celery 卡死）

#### Scenario: ERROR-PATH 错误路径

- **WHEN** 对 `GET /reviews/{不存在的 task_id}/result` 发起请求
- **THEN** SHALL 收到 HTTP 404 + 错误信息
- **AND** 不可仅测 happy path 即认为端点 PASS

#### Scenario: SYNC-BYPASS Celery 卡死兜底

- **WHEN** Celery prefork 池卡死（Windows 已知限制）
- **THEN** 允许使用 `task.apply()` 同步执行
- **AND** 必须在报告中标注 `Path-Type: SYNC-BYPASS (worker stuck, business pipeline real)`
- **AND** 不可仅因 worker 不消费即跳过测试

### Requirement: V4 数据一致性验证

系统 SHALL 对每次写操作（POST/PUT/DELETE）验证持久化层数据一致性。

#### Scenario: PostgreSQL 写入一致性

- **WHEN** `POST /kb/standards/versions?standard_id=TEST-VERIFY` 返回 200
- **THEN** SHALL 直接查 PG：`SELECT * FROM standard_versions WHERE standard_id = 'TEST-VERIFY'`
- **AND** 验证 PG 行的 `standard_id` 字段不含 `%2F`（query 参数正确解码）
- **AND** 验证 `registered_at` 字段非空

#### Scenario: Qdrant 索引一致性

- **WHEN** `POST /kb/reindex` 索引文档后调用 `GET /kb/clauses?query=尺寸标注`
- **THEN** SHALL 验证返回结果含 `clause_id` / `standard` / `original_text`
- **AND** 验证 Qdrant 中向量数 > 0

#### Scenario: 文件系统产物一致性

- **WHEN** `POST /generations` 完成生成
- **THEN** SHALL 验证 `execution.output_files` 中的文件真实存在
- **AND** 文件 size > 0
- **AND** STEP/DXF 文件可被对应解析器读取

### Requirement: 测试报告格式规范

报告 `v2v4_comprehensive_verification.md` SHALL 包含：

1. **头部元信息**：测试时间、FastAPI 基址、Celery 状态、PostgreSQL/Qdrant/Ollama 状态、依赖版本
2. **按 endpoints 文件分节**（11 节）
3. **每个端点记录**：
   - HTTP 方法 + 路径
   - V2 单元测试结果（PASS/FAIL/ENV-LIMIT + 证据）
   - V3 端到端结果（路径类型：REAL-PATH/FALLBACK-PATH/ERROR-PATH/SYNC-BYPASS）
   - V4 数据一致性结果（PG/Qdrant/文件系统）
   - 问题：若有则带 `file:line` 引用
4. **汇总矩阵**：端点 × V2 × V3 × V4 × 总判定
5. **问题清单**：所有 FAIL/ENV-LIMIT 项的根因与建议
6. **结论**：总体 PASS / CONDITIONAL_PASS / FAIL

#### Scenario: 报告包含三维度汇总矩阵

- **WHEN** 报告生成完成
- **THEN** 末尾 SHALL 包含 markdown 表格，列含：Endpoint / Method / V2 / V3-Path-Type / V4 / 总判定 / 备注
- **AND** 每一行对应一个端点的真实测试

### Requirement: 环境主动修复

测试中遇到环境缺失时，必须主动修复，不可跳过。

#### Scenario: PostgreSQL 未启动

- **WHEN** 测试启动时 PG 连接失败
- **THEN** SHALL 主动启动 Docker Desktop 并等待 PG 容器就绪
- **AND** 不可仅降级到 JSON 后端即认为通过

#### Scenario: Qdrant 未启动

- **WHEN** 测试启动时 Qdrant 连接失败
- **THEN** SHALL 主动启动 Qdrant Docker 容器
- **AND** 不可仅降级到无索引模式即认为通过

#### Scenario: Ollama LLM 未启动

- **WHEN** 测试启动时 Ollama 连接失败
- **THEN** SHALL 主动启动 `ollama serve`（或对应服务）
- **AND** 不可仅降级到 template 路径即认为 LLM 端点 PASS

### Requirement: 显式排除 VLM 远程 API

按用户要求，VLM 远程 API（OpenAI gpt-4o / Anthropic Claude / 通义千问 VL 等）不在本 spec 测试范围内。

#### Scenario: 远程 VLM 显式跳过

- **WHEN** 测试涉及 VLM 调用
- **THEN** SHALL 仅测试本地 VLM（`minicpm-v:latest`）
- **AND** 远程 VLM API 在报告中显式标注"用户要求跳过，非环境限制"
- **AND** 不可标为 FAIL 或 ENV-LIMIT

## MODIFIED Requirements

无（本 spec 为新增验收性 spec，不修改既有 requirements）

## REMOVED Requirements

### Requirement: 仅测 happy path 即认为端点 PASS

**Reason**：`fix-2f-route-bug.md` 中的 V2-V4 仅覆盖了 `/standards/versions` 的 happy path（standard_id=GB/T 4458.4 返回 200），未覆盖错误路径（不存在的 standard_id / 缺少 query 参数 / PostgreSQL 不可用降级 / 重复注册冲突等）。这是把"happy path 通过"等同于"端点完整 PASS"，违反"以跳过验证为耻"原则。

**Migration**：所有端点测试 SHALL 显式覆盖 REAL-PATH / FALLBACK-PATH / ERROR-PATH 三类路径，并在报告中标注每一类的执行证据。

## 八荣八耻合规性自检

- [x] 以认真查询为荣：已扫描全部 11 个 endpoints 文件，提取 47 个 HTTP + 1 WS 端点
- [x] 以寻求确认为荣：本 spec 提交用户审批后再实施
- [x] 以人类确认为荣：VLM 远程 API 排除范围来自用户明确指示
- [x] 以复用现有为荣：复用 `realpath-test-backend-api` 的报告格式与 SYNC-BYPASS 模式
- [x] 以主动测试为荣：要求覆盖 REAL/FALLBACK/ERROR 三类路径，不止于 happy path
- [x] 以遵循规范为荣：遵循 spec-driven 模式，先 spec 后实现
- [x] 以诚实无知为荣：环境缺失时主动修复，不假装可用
- [x] 以谨慎重构为荣：本 spec 不修改源码，仅新增测试报告
