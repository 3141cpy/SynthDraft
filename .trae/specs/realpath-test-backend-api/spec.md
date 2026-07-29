# 后端 API 真实路径测试 Spec

## Why

SynthDraft 后端已完成 P0/P1/P2 多轮开发与单元/集成测试，但缺少一份**端到端、基于真实 HTTP 调用、明确区分真实路径与降级路径**的后端 API 验收报告。之前的 `tmp_audit_logs/01-35_*.md` 系列审计日志按主题分块测试，但没有以"端点为粒度"统一组织、也未明确标注每一项的 REAL-PATH / FALLBACK-PATH 归属。本 spec 旨在产出一份覆盖全部 v1 端点的真实路径测试报告 `task8_backend_realtest.md`，作为后端 API 最终验收依据。

遵循"以跳过验证为耻，以主动测试为荣；以假装理解为耻，以诚实无知为荣"原则：每一项必须基于真实证据（HTTP 状态码 + 响应片段 + 产出文件），不可主观断言 PASS。

## What Changes

- **新增测试报告**：`backend/tmp_audit_logs/task8_backend_realtest.md`，以端点为粒度组织，覆盖 `app/api/v1/endpoints/*.py` 全部端点
- **真实路径优先**：对每个端点优先走 REAL-PATH（真实 HTTP 调用 + 真实业务管线），降级路径（fallback/template/rule_engine）需明确标注并区分
- **Celery worker 卡死兜底**：Windows 环境下 Celery prefork 池可能卡死（reserved 不执行），允许使用 `task.apply()` 同步执行以验证真实业务管线，但必须在报告中明确标注"绕过 worker 调度，业务管线真实执行"
- **产出文件验证**：审图报告 (HTML/PDF)、生成产物 (STEP/DXF)、知识库索引、LLM 流式响应等必须验证真实产出，不可仅因 HTTP 200 即 PASS
- **问题清单**：测试中发现的问题需带 `file:line` 引用，便于后续修复
- **汇总表**：报告末尾必须包含端点 × 状态 × 路径类型的汇总矩阵

## Impact

- Affected specs: 无（本 spec 是验收性 spec，不修改代码）
- Affected code: 无源码修改（除非测试发现新 bug，则记录到报告"问题清单"并视情况新建 fix spec）
- Affected docs: 新增 `backend/tmp_audit_logs/task8_backend_realtest.md`
- 测试样本: 
  - DXF 样本：`36d73f5319d54818889fb3746408f5cc_sample.dxf`（已上传）
  - 文本生成 prompt："生成一个 50x30x10 的长方体，中心有直径 10 的孔"
  - KB 索引文档：GB/T 1182 / GB/T 4457.4 标准文本

## ADDED Requirements

### Requirement: 端点级真实路径测试覆盖

系统 SHALL 对 `app/api/v1/endpoints/` 下全部端点做真实 HTTP 调用测试，覆盖：health / uploads / reviews / generations / kb / llm / sketch / collaboration / observability / tasks。

#### Scenario: 健康检查端点真实响应

- **WHEN** 对运行中的 FastAPI 服务发起 `GET /healthz` 与 `GET /api/v1/health/`
- **THEN** SHALL 收到 HTTP 200 + JSON 响应，包含 `status=ok` 或 `status=healthy`
- **AND** 需记录响应片段与响应耗时
- **AND** 不可仅因 TCP 连接成功即 PASS

#### Scenario: 上传 + 审图真实路径

- **WHEN** `POST /api/v1/uploads/` 上传 DXF 文件
- **AND** `POST /api/v1/reviews/` 提交审图任务
- **AND** 轮询 `GET /api/v1/reviews/{task_id}` 直到 completed
- **THEN** SHALL 验证：
  - 审图结果含 `compliance_score`（数值，非 null）
  - `defects` 数组非空（含 category/severity/standard_ref/suggestion）
  - `report_path` 指向真实存在的 HTML 文件（size > 0）
  - `review_mode` 为 `vlm` / `vector_only` / `rule_engine` 之一并明确标注路径类型
- **AND** 若 Celery worker 卡死，允许 `task.apply()` 同步执行，但需标注"绕过 worker 调度"

#### Scenario: 文本生成真实路径

- **WHEN** `POST /api/v1/generations/` 提交 text→step 生成任务
- **AND** 轮询直到 completed
- **THEN** SHALL 验证：
  - `mode` 为 `llm` / `template` 之一并明确标注
  - `execution.output_files` 非空且文件真实存在
  - `geometry_validation.is_valid=true` 且 `volume > 0`
- **AND** 不可仅因 task_id 返回即 PASS

#### Scenario: 知识库索引与检索

- **WHEN** `POST /api/v1/kb/index` 索引标准文档
- **AND** `POST /api/v1/kb/search` 检索相关条款
- **THEN** SHALL 验证检索结果含 `clause_id` / `standard_ref` / `text` 字段
- **AND** 需明确标注 embedding 模型（bge-m3 / nomic-embed-text / 其他）与路径类型

#### Scenario: LLM 流式响应

- **WHEN** `POST /api/v1/llm/stream` 发起流式 chat 请求
- **THEN** SHALL 收到 SSE 流，含 `data:` 行 + `[DONE]` 终止标记
- **AND** 需记录至少 1 个真实 token chunk
- **AND** 需标注 LLM provider（ollama / openai-compatible / deepseek）

#### Scenario: 草图转 CAD 端点

- **WHEN** `POST /api/v1/sketch/parse` 或对应草图端点
- **THEN** SHALL 验证返回 `parameters` / `bbox` 等字段
- **AND** 若 VLM 不可用需明确标注降级路径

#### Scenario: 协同闭环端点

- **WHEN** `POST /api/v1/collaboration/optimize` 提交缺陷列表
- **THEN** SHALL 返回 task_id 或 202 Accepted
- **AND** 若 422/409 需记录请求体与响应片段

#### Scenario: 可观测性端点

- **WHEN** `GET /api/v1/observability/queue-status` 查询队列状态
- **THEN** SHALL 返回 `worker_count` / `queues` / `alerts` 字段
- **AND** 需验证队列名包含 reviews/generations/sketch 等

### Requirement: 测试报告格式规范

报告 `task8_backend_realtest.md` SHALL 包含以下结构：

1. **头部元信息**：测试时间、FastAPI 基址、Celery 状态、Docker 服务状态
2. **逐端点测试记录**（每个端点一节）：
   - 端点路径与 HTTP 方法
   - 请求体（脱敏）
   - HTTP 状态码
   - 响应片段（前 N 行 / 关键字段）
   - 判定：PASS / FAIL / ENV-LIMIT
   - 路径类型：REAL-PATH / FALLBACK-PATH / SYNC-BYPASS（绕过 worker）
   - 问题：若有则带 `file:line` 引用
3. **汇总表**：端点 × 状态 × 路径类型 矩阵
4. **问题清单**：所有 FAIL/ENV-LIMIT 项的根因与建议
5. **结论**：总体 PASS / CONDITIONAL_PASS / FAIL

#### Scenario: 报告包含汇总矩阵

- **WHEN** 报告生成完成
- **THEN** 末尾 SHALL 包含 markdown 表格，列含：Endpoint / Method / Status / Verdict / Path-Type / Notes
- **AND** 每一行对应一次真实测试调用

### Requirement: 真实路径与降级路径明确区分

报告 SHALL 对每一项测试明确标注路径类型，不可混为一谈。

#### Scenario: LLM 降级到 template

- **WHEN** LLM 不可用导致生成走 template_match
- **THEN** 报告 SHALL 标注 `Path-Type: FALLBACK-PATH (template_match)`
- **AND** 不可标为 REAL-PATH

#### Scenario: Celery worker 卡死走同步

- **WHEN** Celery prefork 池卡死，使用 `task.apply()` 同步执行
- **THEN** 报告 SHALL 标注 `Path-Type: SYNC-BYPASS (worker stuck, business pipeline real)`
- **AND** 需说明 worker 卡死的根因（Windows prefork 限制）

## MODIFIED Requirements

无（本 spec 为新增验收性 spec，不修改既有 requirements）

## REMOVED Requirements

无
