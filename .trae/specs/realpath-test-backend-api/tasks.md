# Tasks

## 阶段一：准备与端点清单核对

- [x] Task 1: 核对 `app/api/v1/endpoints/*.py` 全部端点清单，整理为测试矩阵
  - [x] SubTask 1.1: 读取 health.py / uploads.py / reviews.py / generations.py / kb.py / llm.py / sketch.py / collaboration.py / observability.py / tasks.py
  - [x] SubTask 1.2: 提取每个端点的 HTTP 方法、路径、请求 schema、响应 schema
  - [x] SubTask 1.3: 在报告头部记录测试环境（FastAPI 基址、Celery 状态、Docker 服务状态）

## 阶段二：基础端点真实路径测试

- [x] Task 2: 健康检查端点真实路径测试
  - [x] SubTask 2.1: `GET /healthz` 真实调用并记录响应
  - [x] SubTask 2.2: `GET /api/v1/readyz` 真实调用并记录响应（注：实际为 `/readyz` 而非 `/api/v1/health/`）
  - [x] SubTask 2.3: 验证响应字段（status / version / dependencies）

## 阶段三：上传与审图真实路径测试

- [x] Task 3: 上传 + 审图端点真实路径测试
  - [x] SubTask 3.1: `POST /api/v1/uploads` 上传 DXF 样本，记录 file_key（注：无尾斜杠）
  - [x] SubTask 3.2: `POST /api/v1/reviews` 提交审图任务，记录 task_id
  - [x] SubTask 3.3: 轮询 `GET /api/v1/reviews/{task_id}/result` 直到 completed（确认 worker 卡死）
  - [x] SubTask 3.4: 运行 `_task8_review_sync.py` 同步执行审图管线（SYNC-BYPASS）
  - [x] SubTask 3.5: 验证审图结果（compliance_score=85.0 / 1 defect / report_path 真实存在 / review_mode=vlm）
  - [x] SubTask 3.6: 验证 HTML 报告文件 size=30247B >0，PDF 报告 size=24521B >0

## 阶段四：生成端点真实路径测试

- [x] Task 4: 文本生成端点真实路径测试
  - [x] SubTask 4.1: `POST /api/v1/generations` 提交 text→step 任务，记录 task_id
  - [x] SubTask 4.2: 轮询直到确认 worker 卡死
  - [x] SubTask 4.3: 运行 `_task8_gen_sync.py` 同步执行生成管线（SYNC-BYPASS）
  - [x] SubTask 4.4: 验证生成结果（mode=llm / STEP 5742B / is_valid=true / volume=15707.96）
  - [x] SubTask 4.5: 标注路径类型（SYNC-BYPASS + 管线内部 REAL-PATH llm，非 FALLBACK-PATH template）

## 阶段五：知识库端点真实路径测试

- [x] Task 5: KB 索引与检索端点真实路径测试
  - [x] SubTask 5.1: `POST /api/v1/kb/reindex` 索引 GB/T 1182 / GB/T 4457.4 文档（注：非 /kb/index）
  - [x] SubTask 5.2: `GET /api/v1/kb/clauses?query=尺寸标注` 检索（注：非 POST /kb/search）
  - [x] SubTask 5.3: 验证返回字段（clause_id / standard / original_text）
  - [x] SubTask 5.4: 标注 embedding 模型（bge-m3, 1024 dim）与路径类型（REAL-PATH）

## 阶段六：LLM 流式端点真实路径测试

- [x] Task 6: LLM 流式 chat 端点真实路径测试
  - [x] SubTask 6.1: 准备 `_task8_llm_req.json` 请求体并写入文件
  - [x] SubTask 6.2: `curl -N --data-binary @file` 调用 `/api/v1/llm/stream`
  - [x] SubTask 6.3: 验证 SSE 流含 125 个 `data:` 行 + `{"done":true}` 终止标记
  - [x] SubTask 6.4: 标注 LLM provider（ollama, qwen2.5-coder:7b）

## 阶段七：草图端点真实路径测试

- [x] Task 7: 草图转 CAD 端点真实路径测试
  - [x] SubTask 7.1: 读取 sketch.py 端点签名，确认请求 schema（注：端点为 `/sketches` 而非 `/sketch/parse`）
  - [x] SubTask 7.2: `POST /api/v1/sketches` 调用 + SYNC-BYPASS 执行草图管线
  - [x] SubTask 7.3: 验证返回 parameters（radius=50,thickness=10）/ bbox（[0.25,0.25,0.5,0.5]）字段
  - [x] SubTask 7.4: 标注 VLM 可用性（minicpm-v:latest 可用，REAL-PATH）

## 阶段八：协同闭环端点真实路径测试

- [x] Task 8: 协同闭环端点真实路径测试
  - [x] SubTask 8.1: 准备 `_task8_collab_req.json`（注：实际端点为 `/optimize-from-review`，请求体无 defects 字段）
  - [x] SubTask 8.2: `POST /api/v1/collaboration/optimize-from-review` 调用
  - [x] SubTask 8.3: 记录 HTTP 状态（409，因原审图任务 PENDING）与响应片段
  - [x] SubTask 8.4: 补测 `/feedback` POST 201、`/feedback/{id}` GET 200、`/feedback-stats` GET 200

## 阶段九：可观测性端点真实路径测试

- [x] Task 9: 可观测性端点真实路径测试
  - [x] SubTask 9.1: `GET /api/v1/observability/queue-status` 调用
  - [x] SubTask 9.2: 验证返回 worker_count=1 / queues / alerts 字段
  - [x] SubTask 9.3: 验证队列名包含 reviews / generations / sketch
  - [x] SubTask 9.4: 记录 worker 卡死时的 queue-status 真实快照（reviews.reserved=1, generations.reserved=1）

## 阶段十：报告生成与汇总

- [x] Task 10: 生成最终测试报告 `task8_backend_realtest.md`
  - [x] SubTask 10.1: 整理所有测试记录为端点粒度章节（8 节）
  - [x] SubTask 10.2: 每节包含：端点 / 方法 / 请求 / 状态码 / 响应片段 / 判定 / 路径类型 / 问题
  - [x] SubTask 10.3: 生成汇总表（20 行 Endpoint × Method × Status × Verdict × Path-Type × Notes）
  - [x] SubTask 10.4: 生成问题清单（P-01 至 P-05，含 file:line 引用）
  - [x] SubTask 10.5: 写入结论（CONDITIONAL_PASS，因 Celery worker 不消费队列）

# Task Dependencies

- Task 1 → 所有后续任务（需先有端点清单）
- Task 3 ↔ Task 4（共享 Celery worker 状态判断，可并行）
- Task 5 ↔ Task 6（独立，可并行）
- Task 7 ↔ Task 8（独立，可并行）
- Task 9（独立，可在任何时间执行）
- Task 10 依赖所有 Task 2-9 完成

# 并行化建议

- 第一波（串行）：Task 1 → Task 2
- 第二波（并行）：Task 3 / Task 4 / Task 5 / Task 6 / Task 7 / Task 8 / Task 9
- 第三波（串行）：Task 10（汇总报告）
