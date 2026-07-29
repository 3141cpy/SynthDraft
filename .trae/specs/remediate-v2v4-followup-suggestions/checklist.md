# Checklist

## 阶段 0：环境准备

- [x] Docker Desktop 运行中，PG/Redis/Qdrant/Ollama 容器全部 healthy
- [x] FastAPI uvicorn 服务运行在端口 8000，`/api/v1/healthz` 返回 200
- [x] Redis 连接正常（用于 task_registry）

## 阶段 1：代码修复

### Task 1: uploads 路径穿越拒绝

- [x] `uploads.py` 新增 `_detect_path_traversal(name)` 函数，检测 `/`、`\\`、`..`
- [x] `upload_file` 在 `_sanitize_filename` 前调用检测，命中则抛 400
- [x] 保留原有 `_sanitize_filename` 逻辑（正常文件名净化）
- [x] 代码 diff 已记录

### Task 2: 任务 ID 注册表 + 404 语义

- [x] 新建 `app/celery/task_registry.py`，实现 `register_task` 和 `task_exists`
- [x] `register_task` 写入 Redis key `synthdraft:task:{task_id}`，TTL 86400
- [x] `task_exists` 检查 Redis key 是否存在
- [x] `reviews.py:create_review` 调用 `register_task`
- [x] `generations.py:create_generation` 调用 `register_task`
- [x] `collaboration.py:optimize_from_review` 调用 `register_task`
- [x] `sketch.py:create_sketch` 和 `calibrate_sketch` 调用 `register_task`
- [x] `reviews.py:get_review_result` 增加 `task_exists` 检查，不存在则 404
- [x] `tasks.py:get_task_status` 增加 `task_exists` 检查，不存在则 404
- [x] `tasks.py:cancel_task` 增加 `task_exists` 检查，不存在则 404
- [x] `collaboration.py:get_optimize_result` 增加 `task_exists` 检查，不存在则 404
- [x] 代码 diff 已记录

### Task 3: LLM 提示词 anti-hallucination 增强

- [x] `prompts.py` 的 `SYSTEM_PROMPT` 新增「禁止使用的 API」章节
- [x] `SYSTEM_PROMPT` 新增「CadQuery API 签名参考」章节
- [x] `SYSTEM_PROMPT` 新增「输出前自检清单」章节
- [x] 少样本示例未被破坏
- [x] 代码 diff 已记录

### Task 4: Celery solo pool 启动脚本

- [x] 新建 `backend/scripts/start_celery_solo.ps1`
- [x] 脚本使用 `--pool=solo --queues=default,reviews,generations,sketch,collaboration`
- [x] solo worker 实际启动成功，进程不卡死
- [x] 至少 1 个任务通过 solo worker 真实执行完成

### Task 5: verify_task15.py PG 感知断言

- [x] `verify_task15.py` 新增 `_check_pg_available()` 函数
- [x] `test_version_management` 根据 PG 可用性分支断言
- [x] 其他受影响测试函数已修改
- [x] 运行 `verify_task15.py` 全部 PASS（或仅 ENV-LIMIT）

## 阶段 2：针对性全面实际测试

### Task 6: uploads 路径穿越拒绝测试

- [x] `../evil.dxf` → 400
- [x] `dir\\file.dxf` → 400
- [x] `..evil.dxf` → 400
- [x] `flange.dxf` → 201（回归）
- [x] `中文文件.dxf` → 201（回归）

### Task 7: reviews/tasks/collaboration 404 语义测试

- [x] `GET /reviews/nonexistent/result` → 404
- [x] `GET /tasks/nonexistent` → 404
- [x] `POST /tasks/nonexistent/cancel` → 404
- [x] `GET /collaboration/optimize-result/nonexistent` → 404
- [x] 真实 review 任务查询 → 非 404（回归）
- [x] 真实 generation 任务查询 → 非 404（回归）

### Task 8: LLM 生成幻觉率测试

- [x] 提交 3 个不同 prompt 的生成任务
- [x] 记录每个任务的 mode（llm/template）
- [x] 若 mode=llm，验证 STEP 文件可被 CadQuery 解析
- [x] 对比修复前后 mode 分布

### Task 9: Celery solo pool 实测

- [x] solo worker 启动成功
- [x] 提交 review 任务，不使用 SYNC-BYPASS
- [x] 任务状态从 queued → running → succeeded
- [x] 结果可通过 HTTP 端点访问

### Task 10: verify_task15.py 重跑验证

- [x] 运行 `verify_task15.py` 完成
- [x] PASS/FAIL/ENV-LIMIT 统计已记录
- [x] 9 FAIL → 0 FAIL（或仅 ENV-LIMIT）

## 阶段 3：报告生成

### Task 11: V2-V4 后续建议修复验证报告

- [x] 所有修复项的代码 diff 已整理
- [x] 所有验证测试的证据已整理
- [x] `backend/tmp_audit_logs/v2v4_followup_fix_report.md` 已生成
- [x] `v2v4_comprehensive_verification.md` 的后续建议章节已更新为已修复
- [x] 报告含八荣八耻合规性自检

## 八荣八耻合规性自检

- [x] **以认真查询为荣**：所有修复基于真实代码查询，非臆测
- [x] **以寻求确认为荣**：spec 已用户审批；方案决策有明确理由
- [x] **以人类确认为荣**：方案决策点已在 spec 中说明
- [x] **以复用现有为荣**：复用现有 Celery Redis backend、FastAPI 异常处理
- [x] **以主动测试为荣**：每个修复都有对应的真实路径测试
- [x] **以遵循规范为荣**：遵循 spec-driven 模式
- [x] **以诚实无知为荣**：超出能力范围的问题诚实标注
- [x] **以谨慎重构为荣**：最小改动，不破坏现有架构
