# Checklist

## 阶段 0：环境准备

- [x] Task 0.1: Docker Desktop 已启动并就绪
- [x] Task 0.2: PostgreSQL 容器运行中（端口 5433），`psycopg2.connect()` 成功
- [x] Task 0.3: Qdrant 容器运行中（端口 6333），`GET /collections` 返回 200
- [x] Task 0.4: Redis 容器运行中（端口 6379），Celery backend 可达
- [x] Task 0.5: Ollama 服务运行中（端口 11434），`qwen2.5-coder:7b` 与 `minicpm-v:latest` 模型可用
- [x] Task 0.6: FastAPI uvicorn 服务运行中（端口 8000），`GET /healthz` 返回 200
- [x] Task 0.7: 环境快照已记录（容器列表 + Python 依赖版本 + 模型列表）

## 阶段 1：V2 单元测试

### Task 1: health + uploads V2
- [x] Task 1.1: `GET /healthz` + `GET /readyz` 路由注册 PASS + 响应 Schema 验证
- [x] Task 1.2: `POST /uploads` 空 body → 422
- [x] Task 1.3: `GET /uploads` 路由注册 PASS

### Task 2: reviews + generations V2
- [x] Task 2.1: `POST /reviews` 缺 file_key → 422
- [x] Task 2.2: `GET /reviews/{task_id}/result` + `/report` 路由注册 PASS
- [x] Task 2.3: `POST /generations` 非法 body → 422
- [x] Task 2.4: `POST /generations/execute` + `GET /generations/files/{path}` 路由注册 PASS

### Task 3: kb V2
- [x] Task 3.1: `verify_task15.py` 运行通过（80 PASS / 0 FAIL，复用上次结果）
- [x] Task 3.2: 13 个 kb 端点路由注册 PASS（用 TestClient 校验）
- [x] Task 3.3: `POST /kb/profiles` + `POST /kb/enterprise-standards/import` 非法 body → 422
- [x] Task 3.4: `GET /kb/standards/library/invalid-category` → 400/422

### Task 4: llm + sketch + collaboration + observability + tasks V2
- [x] Task 4.1: `POST /llm/stream` 路由注册 + 非法 body 422
- [x] Task 4.2: sketch.py 5 端点路由注册 PASS
- [x] Task 4.3: collaboration.py 6 端点路由注册 + `POST /collaboration/feedback` 非法 body 422
- [x] Task 4.4: observability.py 6 端点路由注册 PASS
- [x] Task 4.5: tasks.py 2 端点路由注册 PASS
- [x] Task 4.6: `GET /tasks/nonexistent` → 404

## 阶段 2：V3 端到端

### Task 5: health + uploads V3
- [x] Task 5.1: `GET /healthz` → 200 + `status=ok`（REAL-PATH）
- [x] Task 5.2: `GET /readyz` → 200 + 依赖检查字段（REAL-PATH）
- [x] Task 5.3: `POST /uploads` 上传 DXF 样本 → 200 + `file_key` 非空（REAL-PATH）
- [x] Task 5.4: `GET /uploads` → 200 + 数组（REAL-PATH）
- [x] Task 5.5: ERROR-PATH: `POST /uploads` 空 body → 422

### Task 6: reviews V3
- [x] Task 6.1: `POST /reviews` → 记录 task_id
- [x] Task 6.2: 轮询确认 Celery worker 卡死（PENDING 不变）
- [x] Task 6.3: SYNC-BYPASS: `task.apply()` 同步执行审图管线
- [x] Task 6.4: 验证 `compliance_score` 数值 + `defects` 数组结构（REAL-PATH）
- [x] Task 6.5: `GET /reviews/{task_id}/report` → HTML 报告（REAL-PATH）
- [x] Task 6.6: ERROR-PATH: `GET /reviews/nonexistent/result` → 404
- [x] Task 6.7: FALLBACK-PATH: VLM 不可用 → `vector_only` 或 `rule_engine` 模式

### Task 7: generations V3
- [x] Task 7.1: `POST /generations` 提交 text→step 任务
- [x] Task 7.2: SYNC-BYPASS: `task.apply()` 同步执行
- [x] Task 7.3: 验证 `mode=llm` + STEP 文件产出（REAL-PATH）
- [x] Task 7.4: FALLBACK-PATH: LLM 不可用 → `mode=template`
- [x] Task 7.5: `POST /generations/execute` 执行编辑代码（REAL-PATH）
- [x] Task 7.6: `GET /generations/files/{path}` 下载 STEP（REAL-PATH）
- [x] Task 7.7: ERROR-PATH: `POST /generations` 空 body → 422
- [x] Task 7.8: ERROR-PATH: `GET /generations/nonexistent/result` → 404

### Task 8: kb V3
- [x] Task 8.1: `POST /kb/reindex` 索引文档（REAL-PATH）
- [x] Task 8.2: `GET /kb/clauses?query=尺寸标注` → clause_id/standard/original_text（REAL-PATH）
- [x] Task 8.3: `GET /kb/standards` → 200（REAL-PATH）
- [x] Task 8.4: `GET /kb/standards/library` → ≥15 条（REAL-PATH）
- [x] Task 8.5: `GET /kb/standards/library/national` 按类别筛选（REAL-PATH）
- [x] Task 8.6: `GET /kb/standards/versions?standard_id=GB%2FT%204458.4` %2F 修复验证（REAL-PATH）
- [x] Task 8.7: `POST /kb/standards/versions?standard_id=TEST-V3-X` 注册新版本（REAL-PATH）
- [x] Task 8.8: `GET /kb/standards/notifications` → 200（REAL-PATH）
- [x] Task 8.9: `GET /kb/standards/conflicts` → 200（REAL-PATH）
- [x] Task 8.10: `GET /kb/profiles` + `POST /kb/profiles` + `POST /kb/profiles/active` profile CRUD（REAL-PATH）
- [x] Task 8.11: `POST /kb/enterprise-standards/import` 导入企业标准（REAL-PATH）
- [x] Task 8.12: FALLBACK-PATH: Qdrant 不可用时 `GET /kb/clauses` 降级
- [x] Task 8.13: ERROR-PATH: `GET /kb/standards/library/invalid-category` → 400/422
- [x] Task 8.14: ERROR-PATH: `POST /kb/standards/versions` 缺 query 参数 → 422

### Task 9: llm V3
- [x] Task 9.1: `POST /llm/stream` → SSE 流 + 至少 1 token chunk + [DONE]（REAL-PATH）
- [x] Task 9.2: LLM provider 标注（ollama / qwen2.5-coder:7b）
- [x] Task 9.3: `GET /llm/stream/{request_id}/status` → 200（REAL-PATH）
- [x] Task 9.4: `POST /llm/cancel/{request_id}` → 200 或已完成的合理响应（REAL-PATH/ERROR-PATH）
- [x] Task 9.5: ERROR-PATH: `POST /llm/stream` 空 body → 422

### Task 10: sketch V3
- [x] Task 10.1: `POST /sketches` 上传草图样本
- [x] Task 10.2: SYNC-BYPASS: `task.apply()` 同步执行
- [x] Task 10.3: 验证 `parameters` + `bbox`（REAL-PATH，本地 VLM minicpm-v:latest）
- [x] Task 10.4: `GET /sketches/{task_id}/result` → 200（REAL-PATH）
- [x] Task 10.5: `POST /sketches/calibrate` → 200（REAL-PATH）
- [x] Task 10.6: `GET /sketches/calibrate/{task_id}/result` → 200（REAL-PATH）
- [x] Task 10.7: `GET /sketches/files/{path}` 下载草图文件（REAL-PATH）
- [x] Task 10.8: FALLBACK-PATH: VLM 不可用 → 降级路径
- [x] Task 10.9: ERROR-PATH: `GET /sketches/nonexistent/result` → 404
- [x] Task 10.10: 远程 VLM API 显式跳过（用户要求，标 SKIP 非 FAIL/ENV-LIMIT）

### Task 11: collaboration V3
- [x] Task 11.1: `POST /collaboration/optimize-from-review` → 200 或 409（REAL-PATH）
- [x] Task 11.2: `GET /collaboration/optimize-result/{task_id}` → 200（REAL-PATH）
- [x] Task 11.3: `GET /collaboration/diff-report/{old}/{new}` → 200（REAL-PATH）
- [x] Task 11.4: `POST /collaboration/feedback` → 201（REAL-PATH）
- [x] Task 11.5: `GET /collaboration/feedback/{review_task_id}` → 200（REAL-PATH）
- [x] Task 11.6: `GET /collaboration/feedback-stats` → 200（REAL-PATH）
- [x] Task 11.7: ERROR-PATH: `POST /collaboration/feedback` 非法 body → 422
- [x] Task 11.8: ERROR-PATH: `GET /collaboration/feedback/nonexistent` → 200 + 空数组 或 404

### Task 12: observability V3
- [x] Task 12.1: `GET /observability/queue-status` → 200 + worker_count/queues/alerts（REAL-PATH）
- [x] Task 12.2: `GET /observability/feedback-summary` → 200（REAL-PATH）
- [x] Task 12.3: `GET /observability/feedback-by-category` → 200（REAL-PATH）
- [x] Task 12.4: `GET /observability/feedback-trend` → 200（REAL-PATH）
- [x] Task 12.5: `GET /observability/llm-cost-summary` → 200（REAL-PATH）
- [x] Task 12.6: `GET /observability/llm-latency` → 200（REAL-PATH）
- [x] Task 12.7: 队列名包含 reviews/generations/sketch

### Task 13: tasks + ws V3
- [x] Task 13.1: `GET /tasks/{task_id}` → 200 + 状态字段（REAL-PATH）
- [x] Task 13.2: `POST /tasks/{task_id}/cancel` → 200（REAL-PATH）
- [x] Task 13.3: ERROR-PATH: `GET /tasks/nonexistent` → 404
- [x] Task 13.4: WebSocket `/ws/tasks/{task_id}` 握手成功 + 至少收到 1 条消息或保持连接

## 阶段 3：V4 数据一致性

### Task 14: PostgreSQL 写入一致性
- [x] Task 14.1: `standard_versions` 表含 `TEST-V3-X` 行（POST /kb/standards/versions 写入）
- [x] Task 14.2: `standard_id` 字段不含 `%2F`（query 参数正确解码）
- [x] Task 14.3: `feedback` 表含 Task 11.4 提交的反馈行
- [x] Task 14.4: `standard_profiles` 表（或 JSON 降级）含 Task 8.10 创建的 profile
- [x] Task 14.5: `enterprise_standards` 表（或 JSON 降级）含 Task 8.11 导入的标准
- [x] Task 14.6: JSON 文件未被修改（确认 PG 后端，非降级）

### Task 15: Qdrant 索引一致性
- [x] Task 15.1: Qdrant 中向量数 > 0（POST /kb/reindex 后）
- [x] Task 15.2: `GET /kb/clauses` 返回的 `clause_id` 在 Qdrant 中可查
- [x] Task 15.3: embedding 模型标注（bge-m3 / nomic-embed-text）

### Task 16: 文件系统产物一致性
- [x] Task 16.1: 上传的 DXF 文件在 `uploads/` 目录存在 + size > 0
- [x] Task 16.2: 审图 HTML 报告文件存在 + size > 0
- [x] Task 16.3: 审图 PDF 报告文件存在 + size > 0（若 WeasyPrint 可用）
- [x] Task 16.4: 生成 STEP 文件存在 + size > 0 + 可被 CadQuery 解析
- [x] Task 16.5: 生成 DXF 文件存在 + size > 0 + 可被 ezdxf 读取
- [x] Task 16.6: 草图文件存在 + size > 0

## 阶段 4：报告

### Task 17: 报告生成
- [x] Task 17.1: 报告含 11 节（按 endpoints 文件分组）
- [x] Task 17.2: 每端点含 V2/V3/V4 三维度记录
- [x] Task 17.3: 汇总矩阵（端点 × V2 × V3-Path-Type × V4 × 总判定）已生成
- [x] Task 17.4: 问题清单（含 file:line 引用）已生成
- [x] Task 17.5: 结论（PASS / CONDITIONAL_PASS / FAIL）已写入
- [x] Task 17.6: 环境快照与依赖版本已写入报告头部

## 八荣八耻合规自检

- [x] 以认真查询为荣：所有端点路径已实际扫描代码确认，非臆测
- [x] 以寻求确认为荣：spec 已提交用户审批
- [x] 以人类确认为荣：VLM 远程 API 排除范围来自用户明确指示
- [x] 以复用现有为荣：复用 verify_task15.py / verify_task5_e2e.py / SYNC-BYPASS 模式
- [x] 以主动测试为荣：覆盖 REAL/FALLBACK/ERROR 三类路径，不止于 happy path
- [x] 以遵循规范为荣：遵循 spec-driven 模式
- [x] 以诚实无知为荣：环境缺失时主动修复，不假装可用
- [x] 以谨慎重构为荣：本 spec 不修改源码，仅新增测试报告

## 总体验证标准

- 47 个 HTTP 端点 + 1 WebSocket 全部覆盖
- 每端点至少 1 REAL-PATH + 1 ERROR-PATH（写端点需 + 1 FALLBACK-PATH）
- 每写操作验证持久化层（PG / Qdrant / 文件系统）
- 远程 VLM API 显式跳过（非 FAIL/ENV-LIMIT）
- 所有 PASS 项有真实证据（HTTP 状态码 + 响应片段 + DB 行 / 文件 size）
