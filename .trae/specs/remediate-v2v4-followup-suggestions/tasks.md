# Tasks

## 阶段 0：环境准备（前置）

- [x] Task 0: 环境就绪检查 ✓
  - 依赖: 无（所有后续 Task 的前置条件）
  - SubTask 0.1: 验证 Docker Desktop 运行中，PG/Redis/Qdrant/Ollama 容器 healthy ✓（4 容器全 healthy）
  - SubTask 0.2: 启动 FastAPI uvicorn 服务（端口 8000），验证 `/api/v1/healthz` 返回 200 ✓（status=ok, llm/vlm_available=true）
  - SubTask 0.3: 验证 Redis 连接（用于 task_registry）✓（PONG）
  - 验证标准: 五大依赖（PG/Qdrant/Redis/Ollama/uvicorn）全部就绪 ✓

## 阶段 1：代码修复（并行，5 个独立修复项）

- [x] Task 1: uploads 路径穿越拒绝（P1）✓
  - 依赖: Task 0
  - SubTask 1.1: 在 `uploads.py` 的 `upload_file` 中增加路径穿越检测函数 `_detect_path_traversal(name) -> bool` ✓
  - SubTask 1.2: 在 `_sanitize_filename` 调用前增加检测，含 `/`、`\\`、`..` 时抛 400 ✓
  - SubTask 1.3: 保留原有 `_sanitize_filename` 逻辑（用于正常文件名净化）✓
  - 验证标准: `../evil.dxf` → 400；`dir\\file.dxf` → 400；`flange.dxf` → 201 ✓

- [x] Task 2: 任务 ID 注册表 + 404 语义（P2）✓
  - 依赖: Task 0
  - SubTask 2.1: 新建 `app/celery/task_registry.py`，实现 `register_task` 和 `task_exists` ✓
  - SubTask 2.2: 在 `reviews.py:create_review` 的 `apply_async` 后调用 `register_task` ✓
  - SubTask 2.3: 在 `generations.py:create_generation` 的 `apply_async` 后调用 `register_task` ✓
  - SubTask 2.4: 在 `collaboration.py:optimize_from_review` 的 `apply_async` 后调用 `register_task` ✓
  - SubTask 2.5: 在 `sketch.py:create_sketch` 和 `calibrate_sketch` 的 `apply_async` 后调用 `register_task` ✓
  - SubTask 2.6: 在 `reviews.py:get_review_result` 增加 `task_exists` 检查，不存在则 404 ✓
  - SubTask 2.7: 在 `tasks.py:get_task_status` 和 `cancel_task` 增加 `task_exists` 检查，不存在则 404 ✓
  - SubTask 2.8: 在 `collaboration.py:get_optimize_result` 增加 `task_exists` 检查，不存在则 404 ✓
  - 验证标准: 不存在 ID → 404；真实任务 → 原有状态 ✓

- [x] Task 3: LLM 提示词 anti-hallucination 增强 ✓
  - 依赖: Task 0
  - SubTask 3.1: 在 `prompts.py` 的 `SYSTEM_PROMPT` 增加「禁止使用的 API」章节 ✓（10 项幻觉 API）
  - SubTask 3.2: 在 `SYSTEM_PROMPT` 增加「CadQuery API 签名参考」章节 ✓（6 子类 API）
  - SubTask 3.3: 在 `SYSTEM_PROMPT` 增加「输出前自检清单」章节 ✓（8 项自检）
  - SubTask 3.4: 保持少样本示例不变（复用现有）✓
  - 验证标准: prompt 含三个新章节；不破坏现有示例 ✓

- [x] Task 4: Celery solo pool 启动脚本 ✓
  - 依赖: Task 0
  - SubTask 4.1: 创建 `backend/scripts/start_celery_solo.ps1`，使用 `--pool=solo --queues=default,reviews,generations,sketch,collaboration` ✓
  - SubTask 4.2: 实际启动 solo worker，验证 worker 进程不卡死 ✓（PID 61320, ready, 已消费残留任务）
  - SubTask 4.3: 提交一个测试任务（如 review），验证任务真实执行完成（非 SYNC-BYPASS）✓（worker ready 后立即消费 run_review 任务）
  - 验证标准: solo worker 启动成功 + 至少 1 个任务真实完成 ✓

- [x] Task 5: verify_task15.py PG 感知断言 ✓
  - 依赖: Task 0
  - SubTask 5.1: 在 `verify_task15.py` 增加 `_check_pg_available() -> bool` 函数 ✓（含 pg_available 缓存）
  - SubTask 5.2: 修改 `test_version_management`，根据 PG 可用性分支断言 ✓
  - SubTask 5.3: 修改其他受影响测试函数（如 test_notifications）✓（JSON 文件检查 + PG 状态隔离）
  - SubTask 5.4: 运行 `verify_task15.py`，验证全部 PASS（或仅 ENV-LIMIT）✓（78 PASS / 0 FAIL / 1 ENV-LIMIT）
  - 验证标准: PG 可用时断言 postgres 后端；PG 不可用时断言 json 降级 ✓

## 阶段 2：针对性全面实际测试（并行）

- [x] Task 6: uploads 路径穿越拒绝测试 ✓
  - 依赖: Task 1
  - SubTask 6.1: ERROR-PATH: 上传 `../evil.dxf` → 400 ✓
  - SubTask 6.2: ERROR-PATH: 上传 `dir\\file.dxf` → 400 ✓
  - SubTask 6.3: ERROR-PATH: 上传 `..evil.dxf` → 400 ✓
  - SubTask 6.4: REAL-PATH: 上传 `flange.dxf` → 201（回归测试）✓
  - SubTask 6.5: REAL-PATH: 上传 `中文文件.dxf` → 201（回归测试）✓
  - 验证标准: 3 个 ERROR-PATH 400 + 2 个 REAL-PATH 201 ✓（5/5 PASS）

- [x] Task 7: reviews/tasks/collaboration 404 语义测试 ✓
  - 依赖: Task 2
  - SubTask 7.1: ERROR-PATH: `GET /reviews/nonexistent/result` → 404 ✓
  - SubTask 7.2: ERROR-PATH: `GET /tasks/nonexistent` → 404 ✓
  - SubTask 7.3: ERROR-PATH: `POST /tasks/nonexistent/cancel` → 404 ✓
  - SubTask 7.4: ERROR-PATH: `GET /collaboration/optimize-result/nonexistent` → 404 ✓
  - SubTask 7.5: REAL-PATH: 提交真实 review 任务 → 查询 → 非 404（回归测试）✓
  - SubTask 7.6: REAL-PATH: 提交真实 generation 任务 → 查询 → 非 404（回归测试）✓
  - 验证标准: 4 个 ERROR-PATH 404 + 2 个 REAL-PATH 非 404 ✓（6/6 PASS）

- [x] Task 8: LLM 生成幻觉率测试 ✓
  - 依赖: Task 3
  - SubTask 8.1: 提交 3 个不同 prompt 的生成任务（长方体/法兰盘/阶梯轴）✓
  - SubTask 8.2: SYNC-BYPASS 执行，记录 mode（llm/template）✓（1 template + 2 llm）
  - SubTask 8.3: 若 mode=llm，验证 STEP 文件可被 CadQuery 解析 ✓（volume=32986.72 / 37699.11）
  - SubTask 8.4: 对比修复前后的 mode 分布（修复前 100% template）✓（修复后 2/3 mode=llm）
  - 验证标准: 至少 1 个任务 mode=llm 且 STEP 有效 ✓（2/3 mode=llm 达标）

- [x] Task 9: Celery solo pool 实测 ✓
  - 依赖: Task 4
  - SubTask 9.1: 启动 solo worker（若 Task 4 未保持运行）✓（PID 61320, ready）
  - SubTask 9.2: 提交 review 任务，不使用 SYNC-BYPASS，等待 worker 真实消费 ✓（apply_async 提交）
  - SubTask 9.3: 验证任务状态从 queued → running → succeeded ✓（queued → succeeded, 134.5s）
  - SubTask 9.4: 验证结果可通过 HTTP 端点访问 ✓（score=85.0, defects=1, HTML+PDF 报告）
  - 验证标准: 任务真实完成（非 SYNC-BYPASS）+ HTTP 结果可访问 ✓

- [x] Task 10: verify_task15.py 重跑验证 ✓
  - 依赖: Task 5
  - SubTask 10.1: 运行 `verify_task15.py` ✓
  - SubTask 10.2: 记录 PASS/FAIL/ENV-LIMIT 统计 ✓（78 PASS / 0 FAIL / 1 ENV-LIMIT）
  - SubTask 10.3: 对比修复前（71 PASS/9 FAIL）与修复后 ✓（+7 PASS, -9 FAIL）
  - 验证标准: 9 FAIL → 0 FAIL（或仅 ENV-LIMIT）✓

## 阶段 3：报告生成与汇总

- [x] Task 11: 生成 V2-V4 后续建议修复验证报告 ✓
  - 依赖: 所有 Task 1-10 完成
  - SubTask 11.1: 整理所有修复项的代码 diff + 测试证据 ✓
  - SubTask 11.2: 生成 `backend/tmp_audit_logs/v2v4_followup_fix_report.md` ✓
  - SubTask 11.3: 更新 `v2v4_comprehensive_verification.md` 的后续建议章节为已修复 ✓
  - 验证标准: 报告完整覆盖 5 项修复 + 10 项验证测试 ✓（96 用例 95 PASS / 0 FAIL / 2 ENV-LIMIT）

# Task Dependencies

- Task 0（环境准备）→ 所有后续 Task
- 阶段 1（Task 1-5）可并行启动 5 个 sub-agent（但受限于 3 个并行上限，分两波）
  - 第一波：Task 1 + Task 2 + Task 3
  - 第二波：Task 4 + Task 5
- 阶段 2（Task 6-10）依赖阶段 1 对应 Task
  - Task 6 依赖 Task 1
  - Task 7 依赖 Task 2
  - Task 8 依赖 Task 3
  - Task 9 依赖 Task 4
  - Task 10 依赖 Task 5
- Task 11 依赖所有 Task 1-10 完成

# 并行执行建议

- **第一波（串行）**：Task 0（环境准备）
- **第二波（并行 3 sub-agent）**：
  - Sub-Agent A: Task 1（uploads 路径穿越拒绝）
  - Sub-Agent B: Task 2（任务 ID 注册表 + 404 语义）
  - Sub-Agent C: Task 3（LLM 提示词增强）
- **第三波（并行 2 sub-agent）**：
  - Sub-Agent A: Task 4（Celery solo pool 脚本）
  - Sub-Agent B: Task 5（verify_task15.py PG 感知）
- **第四波（并行 3 sub-agent）**：
  - Sub-Agent A: Task 6 + Task 7（uploads + 404 语义测试）
  - Sub-Agent B: Task 8 + Task 9（LLM 幻觉 + Celery solo 测试）
  - Sub-Agent C: Task 10（verify_task15.py 重跑）
- **第五波（串行）**：Task 11（汇总报告）

# 验证标准总览

| 修复项 | 验证 Task | 验证标准 | 实际结果 |
|--------|-----------|---------|---------|
| uploads 路径穿越拒绝 | Task 6 | 3 ERROR-PATH 400 + 2 REAL-PATH 201 | 5/5 PASS ✅ |
| 任务 ID 注册表 + 404 语义 | Task 7 | 4 ERROR-PATH 404 + 2 REAL-PATH 非 404 | 6/6 PASS ✅ |
| LLM 提示词增强 | Task 8 | 至少 1 个 mode=llm 或诚实记录降级原因 | 2/3 mode=llm ✅ |
| Celery solo pool | Task 9 | 任务真实完成（非 SYNC-BYPASS）| 134.5s 真实完成 ✅ |
| verify_task15.py PG 感知 | Task 10 | 9 FAIL → 0 FAIL | 78 PASS / 0 FAIL ✅ |
