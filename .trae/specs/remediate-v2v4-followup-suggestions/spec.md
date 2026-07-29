# V2-V4 后续建议修复 Spec

## Why

V2-V4 全面验证报告（`backend/tmp_audit_logs/v2v4_comprehensive_verification.md`）总判定为 PASS，但识别了 5 项非阻塞后续建议。用户要求基于这些建议和实际情况制定最优方案并实施，最后再次进行针对性全面实际测试。本 spec 聚焦于这 5 项建议的修复、验证与报告更新。

## 核心执行原则（HARD RULES）

1. **主动修复原则**：遇到依赖项/服务缺失，必须优先修复，不轻易标注 ENV-LIMIT
2. **实事求是原则**：每项修复必须基于真实证据（代码 diff + 重新测试结果）
3. **谨慎重构原则**：遵循最小改动，不破坏现有架构，复用现有实现
4. **深入工作原则**：每个修复必须有对应的重新测试，验证修复后真实业务产出正确
5. **诚实无知原则**：超出能力范围的问题诚实标注，不掩饰

## 最优方案决策

### 建议 1：uploads 路径穿越 spec 偏差（P1）→ 采用"拒绝"策略

**决策理由**：安全最佳实践是"fail fast, fail explicit"。路径穿越字符在文件名中几乎总是恶意或 bug。返回 400 使安全边界清晰，优于当前的"净化后接受"策略。

**实施方案**：在 `_sanitize_filename` 之前增加路径穿越检测，若原始 filename 含 `/`、`\\`、`..` 则抛 400。

### 建议 2：reviews / tasks 404 语义（P2）→ 增加任务 ID 注册表，返回 404

**决策理由**：Celery 的 `AsyncResult` 无法区分"排队中"与"ID 不存在"。通过在 Redis 中维护任务 ID 注册表（带 TTL），可在查询时区分。这是最干净、不破坏现有架构的方案。

**实施方案**：
- 新建 `app/celery/task_registry.py`，提供 `register_task(task_id, task_type)` 和 `task_exists(task_id)` 函数
- 在所有 API 层 `apply_async` 调用点（5 处）注册任务 ID
- 在 `reviews.py:get_review_result`、`tasks.py:get_task_status`、`tasks.py:cancel_task`、`collaboration.py:get_optimize_result` 中增加 `task_exists` 检查，不存在则返回 404

### 建议 3：LLM 提示词优化 → 增强 anti-hallucination 约束

**决策理由**：当前 prompt 已有约束，但 LLM 仍生成幻觉 API（如 `workplane(centerX=..., centerY=...)`）。需增加明确的禁止 API 列表、正确 API 签名参考、自检清单。

**实施方案**：在 `prompts.py` 的 `SYSTEM_PROMPT` 中增加：
- 「禁止使用的 API」章节（列出常见幻觉 API）
- 「CadQuery API 签名参考」章节（列出正确签名）
- 「输出前自检清单」（LLM 输出前应自检的项）

### 建议 4：Celery Windows 支持 → 评估 `--pool=solo` 并创建启动脚本

**决策理由**：`--pool=solo` 是 Windows 上最可靠的 Celery 池，单线程顺序执行，避免 prefork 卡死。`--pool=gevent` 对 CPU 密集任务（CadQuery 执行）可能有 GIL 问题。

**实施方案**：
- 创建 `backend/scripts/start_celery_solo.ps1` 启动脚本，使用 `--pool=solo`
- 实际测试：启动 solo worker，提交一个任务，验证任务真实执行完成
- 若成功，更新验证报告标注 SYNC-BYPASS 可被 solo pool 替代

### 建议 5：verify_task15.py 测试更新 → 增加 PG 可用性感知

**决策理由**：测试当前硬编码断言 `backend_name == "json"`，但 PG 现已可用，导致 9 项失败。需让测试感知 PG 可用性并分支断言。

**实施方案**：在 `verify_task15.py` 中增加 PG 可用性检测函数，根据检测结果分支断言：
- PG 可用：断言 `backend_name == "postgres"`，验证 PG 行写入
- PG 不可用：断言 `backend_name == "json"`，验证 JSON 降级

## What Changes

### 代码修复（5 项）

- **uploads.py**：增加路径穿越检测，含 `/`、`\\`、`..` 的 filename 返回 400
- **task_registry.py**（新建）：Redis 任务 ID 注册表，`register_task` / `task_exists`
- **reviews.py / tasks.py / collaboration.py / generations.py / sketch.py**：在 `apply_async` 后调用 `register_task`；在查询端点增加 `task_exists` 检查
- **prompts.py**：增强 SYSTEM_PROMPT，增加禁止 API 列表 + API 签名参考 + 自检清单
- **scripts/start_celery_solo.ps1**（新建）：Celery solo pool 启动脚本
- **verify_task15.py**：增加 PG 可用性感知，分支断言

### 验证测试（针对性全面实际测试）

- 重新测试 uploads 路径穿越拒绝（含正常文件上传回归）
- 重新测试 reviews/tasks/collaboration 404 语义（含真实任务查询回归）
- 重新测试 LLM 生成（验证幻觉率降低）
- 实际测试 Celery solo pool（提交任务并等待真实完成）
- 重新运行 verify_task15.py（验证 PG 感知断言通过）

## Impact

- Affected specs:
  - `execute-comprehensive-v2v4-verification`（更新其问题清单状态）
- Affected code:
  - `backend/app/api/v1/endpoints/uploads.py`（路径穿越拒绝）
  - `backend/app/celery/task_registry.py`（新建）
  - `backend/app/api/v1/endpoints/reviews.py`（404 语义 + register_task）
  - `backend/app/api/v1/endpoints/tasks.py`（404 语义）
  - `backend/app/api/v1/endpoints/collaboration.py`（404 语义 + register_task）
  - `backend/app/api/v1/endpoints/generations.py`（register_task）
  - `backend/app/api/v1/endpoints/sketch.py`（register_task）
  - `backend/app/services/generation/prompts.py`（anti-hallucination）
  - `backend/scripts/start_celery_solo.ps1`（新建）
  - `backend/tests/verify_task15.py`（PG 感知断言）
- Affected docs:
  - 新增 `backend/tmp_audit_logs/v2v4_followup_fix_report.md`（本次修复验证报告）

## ADDED Requirements

### Requirement: uploads 路径穿越拒绝

系统 SHALL 在 `POST /uploads` 中检测原始 filename 是否含路径穿越字符，含则返回 400。

#### Scenario: filename 含路径分隔符

- **WHEN** 上传文件 filename 含 `/` 或 `\\`（如 `../evil.dxf` 或 `dir\\file.dxf`）
- **THEN** SHALL 返回 400 `{"detail": "文件名含非法路径字符: /, \\"}`
- **AND** 不创建文件

#### Scenario: filename 含 `..` 序列

- **WHEN** 上传文件 filename 含 `..`（如 `..evil.dxf`）
- **THEN** SHALL 返回 400 `{"detail": "文件名含非法路径穿越序列: .."}`

#### Scenario: 正常 filename 不受影响

- **WHEN** 上传文件 filename 为正常名称（如 `flange.dxf`、`中文文件.dxf`）
- **THEN** SHALL 正常处理，返回 201

### Requirement: 任务 ID 注册表

系统 SHALL 在 Redis 中维护任务 ID 注册表，用于区分"排队中"与"ID 不存在"。

#### Scenario: 任务提交时注册

- **WHEN** API 端点调用 `apply_async` 提交任务
- **THEN** SHALL 调用 `register_task(task_id, task_type)` 写入 Redis key `synthdraft:task:{task_id}`
- **AND** TTL 为 86400 秒（24 小时）

#### Scenario: 查询时检查存在性

- **WHEN** 查询任务状态/结果时
- **THEN** SHALL 先调用 `task_exists(task_id)` 检查 Redis key 是否存在
- **AND** 若不存在，返回 404 `{"detail": "任务 ID 不存在: {task_id}"}`
- **AND** 若存在，继续原有逻辑

### Requirement: reviews / tasks / collaboration 404 语义

系统 SHALL 对不存在的任务 ID 返回 404，而非 200+pending/queued。

#### Scenario: 查询不存在的 review task

- **WHEN** `GET /reviews/{nonexistent_id}/result`
- **THEN** SHALL 返回 404 `{"detail": "任务 ID 不存在: {task_id}"}`

#### Scenario: 查询不存在的 task status

- **WHEN** `GET /tasks/{nonexistent_id}`
- **THEN** SHALL 返回 404 `{"detail": "任务 ID 不存在: {task_id}"}`

#### Scenario: 取消不存在的 task

- **WHEN** `POST /tasks/{nonexistent_id}/cancel`
- **THEN** SHALL 返回 404 `{"detail": "任务 ID 不存在: {task_id}"}`

#### Scenario: 查询不存在的 collaboration optimize result

- **WHEN** `GET /collaboration/optimize-result/{nonexistent_id}`
- **THEN** SHALL 返回 404 `{"detail": "任务 ID 不存在: {task_id}"}`

#### Scenario: 查询真实存在的任务不受影响

- **WHEN** 查询通过 `apply_async` 提交的真实任务
- **THEN** SHALL 返回原有状态（queued/running/succeeded/failed）

### Requirement: LLM 提示词 anti-hallucination 增强

系统 SHALL 在 `prompts.py` 的 `SYSTEM_PROMPT` 中增加 anti-hallucination 约束。

#### Scenario: 禁止 API 列表

- **WHEN** LLM 生成 CadQuery 代码
- **THEN** SHALL 在 prompt 中看到「禁止使用的 API」章节，列出常见幻觉 API：
  - `Workplane(centerX=..., centerY=...)`（错误签名）
  - `Workplane.translate(...)`（不存在的方法）
  - `cq.assemble(...)`（不存在的方法）
- **AND** SHALL 在 prompt 中看到「CadQuery API 签名参考」章节，列出正确签名

#### Scenario: 输出前自检清单

- **WHEN** LLM 输出代码前
- **THEN** SHALL 在 prompt 中看到「输出前自检清单」，包含：
  - 是否只用了 `import cadquery as cq`
  - 是否所有 API 调用都在签名参考中
  - 是否最终结果赋值给 `result`
  - 是否所有尺寸为正数

### Requirement: Celery solo pool 启动脚本

系统 SHALL 提供 `scripts/start_celery_solo.ps1` 启动脚本，使用 `--pool=solo` 在 Windows 上可靠运行。

#### Scenario: 启动 solo worker

- **WHEN** 运行 `start_celery_solo.ps1`
- **THEN** SHALL 启动 Celery worker with `--pool=solo --queues=default,reviews,generations,sketch,collaboration`
- **AND** worker 应能正常消费任务（不卡死）

### Requirement: verify_task15.py PG 感知断言

系统 SHALL 在 `verify_task15.py` 中增加 PG 可用性检测，根据检测结果分支断言。

#### Scenario: PG 可用时断言 postgres 后端

- **WHEN** PG 可用（连接成功）
- **THEN** SHALL 断言 `mgr.backend_name == "postgres"`
- **AND** 验证 PG 行写入（直接 SELECT）

#### Scenario: PG 不可用时断言 json 降级

- **WHEN** PG 不可用（连接失败）
- **THEN** SHALL 断言 `mgr.backend_name == "json"`
- **AND** 验证 JSON 文件写入

## MODIFIED Requirements

### Requirement: V2-V4 验证报告更新

`backend/tmp_audit_logs/v2v4_comprehensive_verification.md` 的后续建议章节 SHALL 更新为已修复状态，附修复方案与重新测试证据。

## REMOVED Requirements

无
