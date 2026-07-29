# Checklist

## 阶段一：准备与端点清单核对

- [x] `app/api/v1/endpoints/*.py` 全部端点已读取并整理为测试矩阵
- [x] 报告头部记录测试环境（FastAPI 基址 http://localhost:8000、Celery 状态、Docker 服务 postgres/redis/ollama/qdrant 健康）

## 阶段二：基础端点真实路径测试

- [x] `GET /healthz` 真实调用返回 HTTP 200 + `status=ok`
- [x] `GET /api/v1/readyz` 真实调用返回 HTTP 200 + 依赖项状态（注：实际端点为 `/readyz` 而非 `/api/v1/health/`，已勘误）
- [x] 响应片段与响应耗时已记录

## 阶段三：上传与审图真实路径测试

- [x] `POST /api/v1/uploads` 上传 DXF 返回 file_key（注：实际无尾斜杠，已勘误）
- [x] `POST /api/v1/reviews` 返回 task_id（worker 卡死但 HTTP 受理正常）
- [x] 审图任务最终状态为 completed（通过 `_task8_review_sync.py` SYNC-BYPASS 执行）
- [x] 审图结果含 `compliance_score`（数值 85.0，非 null）
- [x] `defects` 数组非空，每条含 category / severity / standard_ref / suggestion
- [x] `report_path` 指向真实存在的 HTML 文件（30247 bytes >0）
- [x] `review_mode` 为 `vlm`（vlm/vector_only/rule_engine 之一）并明确标注路径类型
- [x] 走 SYNC-BYPASS，报告中明确标注"绕过 worker 调度，业务管线真实执行"

## 阶段四：生成端点真实路径测试

- [x] `POST /api/v1/generations` 返回 task_id（worker 卡死但 HTTP 受理正常）
- [x] 生成任务最终状态为 completed（通过 `_task8_gen_sync.py` SYNC-BYPASS 执行）
- [x] `mode` 为 `llm`（非 template 降级）并明确标注
- [x] `execution.output_files` 非空且文件真实存在（STEP 文件 5742 bytes >0）
- [x] `geometry_validation.is_valid=true` 且 `volume=15707.96`（>0，π×10²×50 数值正确）
- [x] 路径类型明确（SYNC-BYPASS + 管线内部 REAL-PATH llm）

## 阶段五：知识库端点真实路径测试

- [x] `POST /api/v1/kb/reindex` 索引成功（HTTP 200, indexed_count=42）（注：实际端点为 `/kb/reindex` 而非 `/kb/index`，已勘误）
- [x] `GET /api/v1/kb/clauses?query=尺寸标注` 返回检索结果（total=3，非空）（注：实际端点为 GET `/kb/clauses` 而非 POST `/kb/search`，已勘误）
- [x] 检索结果含 `clause_id` / `standard`（即 standard_ref） / `original_text`（即 text）字段
- [x] embedding 模型已标注（bge-m3, BAAI/bge-m3, 1024 dim）

## 阶段六：LLM 流式端点真实路径测试

- [x] `POST /api/v1/llm/stream` 返回 SSE 流（Content-Type: text/event-stream）
- [x] 流中含 125 个 `data:` 行带真实 token（首批 chunk: "GB"、"/T"、" "）
- [x] 流以 `{"done": true}` 终止（JSON 对象形式，非字面量 [DONE]，设计差异已记录 P-03）
- [x] LLM provider 已标注（ollama, qwen2.5-coder:7b）

## 阶段七：草图端点真实路径测试

- [x] 草图端点 `POST /api/v1/sketches` 真实调用返回 task_id（注：实际端点为 `/sketches` 而非 `/sketch/parse`，已勘误）
- [x] 返回 `parameters`（`{"radius":50,"thickness":10}`）/ `bbox`（`[0.25,0.25,0.5,0.5]`）字段（通过 SYNC-BYPASS 验证）
- [x] VLM 可用性已标注（minicpm-v:latest 可用，无降级）

## 阶段八：协同闭环端点真实路径测试

- [x] `POST /api/v1/collaboration/optimize-from-review` 真实调用（注：实际端点为 `/optimize-from-review` 而非 `/optimize`，已勘误）
- [x] HTTP 状态码已记录（409，因原审图任务 PENDING 无法达 SUCCESS）
- [x] 409 为预期行为（状态守卫生效），202 路径因 ENV-LIMIT 不可达已记录
- [x] `POST /api/v1/collaboration/feedback` 返回 201，GET `/feedback/{id}` 返回 200，GET `/feedback-stats` 返回 200（补测）

## 阶段九：可观测性端点真实路径测试

- [x] `GET /api/v1/observability/queue-status` 返回 HTTP 200
- [x] 返回字段含 `worker_count` / `queues` / `alerts`
- [x] 队列名包含 reviews / generations / sketch
- [x] worker 卡死时的 queue-status 真实快照已记录（reviews.reserved=1, generations.reserved=1, active=0）

## 阶段十：报告生成与汇总

- [x] 报告 `backend/tmp_audit_logs/task8_backend_realtest.md` 已生成
- [x] 报告头部含测试时间 / FastAPI 基址 / Celery 状态 / Docker 服务状态
- [x] 每个端点一节，含：端点 / 方法 / 请求 / 状态码 / 响应片段 / 判定 / 路径类型 / 问题
- [x] 汇总表（Endpoint × Method × Status × Verdict × Path-Type × Notes）已生成（20 行）
- [x] 问题清单含 file:line 引用（P-01 至 P-05，共 5 项）
- [x] 结论已写入（CONDITIONAL_PASS，因 Celery worker 不消费队列）
- [x] 每一项 PASS 基于真实证据（HTTP 状态 + 响应片段 + 产出文件），无主观断言

## 八荣八耻合规自检

- [x] 以主动测试为荣：每一端点真实调用，未跳过（20 个 HTTP 端点 + 3 个 SYNC-BYPASS 管线）
- [x] 以诚实无知为荣：环境限制（Celery worker 卡死）明确标注 ENV-LIMIT，未掩饰
- [x] 以跳过验证为耻：无仅因 TCP 连接成功即 PASS 的敷衍（每项均有响应片段 + 产出文件证据）
- [x] 以假装理解为耻：路径类型（REAL-PATH 14 项 / SYNC-BYPASS 3 项 / FALLBACK-PATH 0 项 / ENV-LIMIT 4 项）明确区分
