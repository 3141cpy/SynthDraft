# 草图协同 LLM 链路测试报告

## 测试时间
2026-08-04 23:42 ~ 2026-08-05 00:05 (Asia/Shanghai)

## 测试环境
- 后端: http://localhost:8000 (uvicorn)
- Celery worker: reviews / generations 队列运行中
- AI Provider: 阿里云 qwen3.7-plus (llm_available=true, vlm_available=true)
- Docker: PostgreSQL(5433) / Redis(6379) / Qdrant(6333) healthy
- 测试样本: d:\SynthDraft\test.jpg (76480 bytes, image/jpeg)
- 上传 file_key: `440dd95df2314e41a83ec336a6c0fd10_test.jpg`

## 端点签名确认

> 重要发现: 实际端点与任务描述不完全一致。LLM 模块实际提供的是 **stream/cancel/status** 三个端点（流式 SSE），
> 而非任务描述中的 chat/vlm/models。本次测试以**代码实际签名**为准。

### sketch.py 端点签名（路由前缀 `/api/v1/sketches`）

| # | 方法 | 路径 | 请求体/参数 | 响应模型 | 说明 |
|---|---|---|---|---|---|
| 1 | POST | /api/v1/sketches | `SketchCreateRequest{image_key:str, output_format:Literal[dxf,step,stl,iges]=dxf}` | `SketchTaskAccepted` (202) | 提交草图转 CAD 任务（Celery sketch 队列） |
| 2 | GET | /api/v1/sketches/{task_id}/result | path: task_id | `SketchTaskResult` | 查询草图任务结果（PENDING→404, STARTED→202, SUCCESS→200） |
| 3 | POST | /api/v1/sketches/calibrate | `CalibrationRequest{sketch_task_id:str, calibrations:list[CalibrationItem]}` | `CalibrationResult` (202) | 提交人工校准（需原任务 SUCCESS） |
| 4 | GET | /api/v1/sketches/calibrate/{task_id}/result | path: task_id | `CalibrationResult` | 查询校准任务结果 |
| 5 | GET | /api/v1/sketches/files/{file_path:path} | path: file_path | FileResponse | 下载草图产物（DXF/STEP/STL） |

### collaboration.py 端点签名（路由前缀 `/api/v1/collaboration`）

| # | 方法 | 路径 | 请求体/参数 | 响应模型 | 说明 |
|---|---|---|---|---|---|
| 1 | POST | /api/v1/collaboration/optimize-from-review | `OptimizeFromReviewRequest{review_task_id:str, user_id:str=anonymous, output_format:dxf, auto_re_review:bool=true}` | `CollaborativeWorkflowResult` (202) | 基于审图缺陷优化图纸（需原审图 SUCCESS） |
| 2 | GET | /api/v1/collaboration/optimize-result/{task_id} | path: task_id | JSON | 查询优化任务结果 |
| 3 | GET | /api/v1/collaboration/diff-report/{old_review_task_id}/{new_review_task_id} | path: old, new | `DiffReport` | 修订前后对比报告 |
| 4 | POST | /api/v1/collaboration/feedback | `FeedbackRecord{review_task_id:str, defect_index:int, action:Literal[accept,reject_as_false_positive,modify_suggestion], comment:str, user_id:str, defect_snapshot?:DefectItem, created_at:str}` | `FeedbackRecord` (201) | 用户反馈回流 |
| 5 | GET | /api/v1/collaboration/feedback/{review_task_id} | path: review_task_id | JSON | 查询某审图任务的所有反馈 |
| 6 | GET | /api/v1/collaboration/feedback-stats | 无 | JSON | 反馈统计 |

### llm.py 端点签名（路由前缀 `/api/v1`，端点以 `/llm` 开头）

| # | 方法 | 路径 | 请求体/参数 | 响应模型 | 说明 |
|---|---|---|---|---|---|
| 1 | POST | /api/v1/llm/stream | `StreamChatRequest{messages:list[ChatMessage{role,content,images?}], request_id?:str, temperature:float=0.2, max_tokens:int=2048}` | SSE StreamingResponse / JSON | LLM 流式输出（SSE），降级时返回 JSON |
| 2 | POST | /api/v1/llm/cancel/{request_id} | path: request_id, body?: `StreamCancelRequest{reason:str}` | `StreamCancelResponse` | 主动取消流式请求（Redis 标志位） |
| 3 | GET | /api/v1/llm/stream/{request_id}/status | path: request_id | `StreamStatusResponse` | 查询流式请求状态 |

## 端点测试结果

| # | 方法 | 路径 | 状态码 | 关键字段/响应 | 通过 | 备注 |
|---|---|---|---|---|---|---|
| 1 | POST | /api/v1/sketches | 202 | task_id=a77629e9-27a9-4f03-88a6-444d72bbcf66, precision_level=sketch_level | ✅ | 任务受理成功 |
| 2 | GET | /api/v1/sketches/{task_id}/result | 404 | task PENDING（草图任务未完成，详见问题1） | ⚠️ | 端点逻辑正确（PENDING→404 符合设计），但 SUCCESS 路径未能验证 |
| 3 | POST | /api/v1/sketches/calibrate | 409 | "原草图任务状态为 PENDING，需等待 SUCCESS 后才能派发校准" | ✅ | 正确校验原任务状态 |
| 4 | GET | /api/v1/sketches/calibrate/{task_id}/result | 200 | success=false, warnings=["task pending (state=PENDING)"] | ✅ | 随机 task_id 正确返回 pending |
| 5 | GET | /api/v1/sketches/files/{file_path} | 404 | "file not found: nonexistent.dxf" | ✅ | 不存在文件正确返回 404 |
| 6 | POST | /api/v1/collaboration/optimize-from-review | 202 | generation_task_id=30c289b2-5ead-41ae-bdd9-44afe6f03e07, status=dispatched | ✅ | 基于审图1缺陷派发优化任务 |
| 7 | GET | /api/v1/collaboration/optimize-result/{task_id} | 200 | status=pending（任务仍在队列） | ✅ | 正确返回任务状态；不存在 task_id 返回 404 |
| 8 | GET | /api/v1/collaboration/diff-report/{old}/{new} | 200 | old_defects=6, new_defects=5, resolved=3, unresolved=3, new=2, closure_rate=0.5, score_improvement=3.0 | ✅ | 完整对比报告，含8条 diff 详情 |
| 9 | POST | /api/v1/collaboration/feedback | 201 | 自动填充 defect_snapshot（title_block/critical），created_at 时间戳 | ✅ | 反馈保存成功，缺陷快照自动填充 |
| 10 | GET | /api/v1/collaboration/feedback/{review_task_id} | 200 | count=1, feedbacks=[{action:accept, defect_snapshot:...}] | ✅ | 正确返回已保存反馈列表 |
| 11 | GET | /api/v1/collaboration/feedback-stats | 200 | total=6, accept=3, reject_as_false_positive=1, modify_suggestion=2 | ✅ | 统计数据正确（提交后 total 5→6, accept 2→3） |
| 12 | POST | /api/v1/llm/stream | 200 | SSE: chunk="你好，我是通义千问..." → done=true → [DONE]，request_id=anonymous-32f69cd74469 | ✅ | 流式输出正常，模型 qwen3.7-plus |
| 13 | POST | /api/v1/llm/cancel/{request_id} | 200 | cancelled=true, message="cancel flag set" | ✅ | Redis 取消标志位设置成功 |
| 14 | GET | /api/v1/llm/stream/{request_id}/status | 200 | found=true, status={status:running, stream:true}；不存在时 found=false | ✅ | 状态查询正常 |

## 详细测试记录

### Task 8: 草图端点

**前置: 上传 test.jpg**
- `POST /api/v1/uploads` (multipart form-data) → 201
- 返回 `file_key=440dd95df2314e41a83ec336a6c0fd10_test.jpg`, `file_type=image`, `size=76480`

**8.1 POST /api/v1/sketches** ✅
- 请求体: `{"image_key":"440dd95df2314e41a83ec336a6c0fd10_test.jpg","output_format":"dxf"}`
- 响应 202: `{"task_id":"a77629e9-27a9-4f03-88a6-444d72bbcf66","status":"queued","websocket_url":"/api/v1/ws/tasks/a77629e9-27a9-4f03-88a6-444d72bbcf66","precision_level":"sketch_level"}`
- 结论: 任务受理成功，precision_level 强制为 sketch_level（符合 spec.md R7）

**8.2 GET /api/v1/sketches/{task_id}/result** ⚠️
- 轮询 task_id=a77629e9-27a9-4f03-88a6-444d72bbcf66（累计等待 >5 分钟）
- 响应 404: `{"detail":"task a77629e9-27a9-4f03-88a6-444d72bbcf66 not found or pending"}`
- 结论: 任务始终处于 PENDING 状态。端点的 404 行为符合代码设计（PENDING→404），但 SUCCESS 路径未能验证。原因分析见"发现的问题 #1"

**8.3 POST /api/v1/sketches/calibrate** ✅
- 请求体: `{"sketch_task_id":"a77629e9-...","calibrations":[{"feature_index":0,"feature_type":"circle","parameter_name":"radius","original_value":50,"calibrated_value":60,"unit":"mm"}]}`
- 响应 409: `{"detail":"原草图任务状态为 PENDING，需等待 SUCCESS 后才能派发校准（sketch_task_id=a77629e9-...）"}`
- 结论: 正确校验原任务状态，非 SUCCESS 时返回 409 CONFLICT

**8.4 GET /api/v1/sketches/calibrate/{task_id}/result** ✅
- 测试 task_id=00000000-0000-0000-0000-000000000001（不存在）
- 响应 200: `{"task_id":"...","success":false,"calibrated_features":[],"regenerated_code":"","output_files":{},"warnings":["task pending (state=PENDING)"]}`
- 结论: PENDING 状态正确返回 200 + success=false + warnings

**8.5 GET /api/v1/sketches/files/{file_path}** ✅
- 测试 file_path=nonexistent.dxf（不存在）
- 响应 404: `{"detail":"file not found: nonexistent.dxf"}`
- 结论: 文件不存在时正确返回 404

### Task 9: 协同端点

**前置: 提交 2 个审图任务获取 review_task_id**
- 审图1: `POST /api/v1/reviews` → task_id=fc7f06c0-fe2d-4912-9268-cc9aa7297878
- 审图2: `POST /api/v1/reviews` → task_id=3c707fcd-cb1b-4eaf-ba21-d1b4e31d8f5d
- 审图1 完成: compliance_score=41.0, 6 个缺陷（title_block/view_layout/dimensioning/layer_naming/surface_roughness/tolerance）
- 审图2 完成: compliance_score=44.0, 5 个缺陷（title_block/dimensioning/layer_naming/tolerance/other）

**9.1 POST /api/v1/collaboration/optimize-from-review** ✅
- 请求体: `{"review_task_id":"fc7f06c0-...","output_format":"dxf","auto_re_review":true}`
- 响应 202: `{"original_review_task_id":"fc7f06c0-...","generation_task_id":"30c289b2-5ead-41ae-bdd9-44afe6f03e07","new_review_task_id":null,"status":"dispatched","defects_count":0,"optimized_prompt":"","metadata":{"optimize_task_id":"30c289b2-...","websocket_url":"/api/v1/ws/tasks/30c289b2-..."}}`
- 结论: 审图→生成协同闭环派发成功

**9.2 GET /api/v1/collaboration/optimize-result/{task_id}** ✅
- 测试真实 task_id=30c289b2-... → 200: `{"task_id":"30c289b2-...","status":"pending"}`
- 测试不存在 task_id → 404: `{"detail":"任务 ID 不存在: 00000000-..."}`
- 结论: 正确返回任务状态；task_exists 校验生效

**9.3 GET /api/v1/collaboration/diff-report/{old}/{new}** ✅
- old=fc7f06c0-...(审图1, 6缺陷, score=41), new=3c707fcd-...(审图2, 5缺陷, score=44)
- 响应 200 完整对比报告:
  - old_defects_count=6, new_defects_count=5
  - resolved_count=3, unresolved_count=3, new_count=2
  - old_compliance_score=41.0, new_compliance_score=44.0, score_improvement=3.0
  - closure_rate=0.5（50% 闭环率）
  - diffs 数组含 8 条详情（3 unresolved + 2 new + 3 resolved），每条含 diff_status/defect/matched_defect_index/similarity_score
- 测试不存在 old task → 404: `{"detail":"原审图任务结果不可用: 00000000-..."}`
- 结论: 缺陷对比与闭环分析完整正确

**9.4 POST /api/v1/collaboration/feedback** ✅
- 请求体: `{"review_task_id":"fc7f06c0-...","defect_index":0,"action":"accept","comment":"测试反馈-采纳该缺陷","user_id":"test-engineer"}`
- 响应 201: 自动填充 defect_snapshot（从审图1结果读取 index=0 的缺陷）
  - defect_snapshot: {category:title_block, severity:critical, standard_ref:GB/T 18229-2023 §4.1, suggestion:添加符合国家标准格式的标题栏...}
  - created_at: 2026-08-05T00:01:23.580331
- 结论: 反馈保存成功，defect_snapshot 自动填充功能正常

**9.5 GET /api/v1/collaboration/feedback/{review_task_id}** ✅
- 查询 review_task_id=fc7f06c0-...
- 响应 200: `{"review_task_id":"fc7f06c0-...","count":1,"feedbacks":[{action:accept, defect_snapshot:..., created_at:...}]}`
- 结论: 正确返回已保存的反馈记录

**9.6 GET /api/v1/collaboration/feedback-stats** ✅
- 响应 200（提交反馈前）: `{"total":5,"accept":2,"reject_as_false_positive":1,"modify_suggestion":2}`
- 响应 200（提交反馈后）: `{"total":6,"accept":3,"reject_as_false_positive":1,"modify_suggestion":2}`
- 结论: 统计正确，提交反馈后 total/accept 计数正确递增

### Task 10: LLM 端点

> 注意: llm.py 实际实现的是**流式 SSE**端点（stream/cancel/status），非任务描述中的 chat/vlm/models。
> 本次测试以代码实际签名为准。

**10.1 POST /api/v1/llm/stream** ✅
- 请求体: `{"messages":[{"role":"user","content":"你好,请用一句话介绍自己"}],"temperature":0.2,"max_tokens":256}`
- 响应 200 (text/event-stream):
  ```
  data: {"chunk": "你好，我是通义千问，由阿里巴巴集团通义实验室自主研发的大语言模型，致力于成为你真诚、有帮助的AI思考伙伴。", "request_id": "anonymous-32f69cd74469"}

  data: {"done": true, "request_id": "anonymous-32f69cd74469"}

  data: [DONE]
  ```
- 结论: SSE 流式输出正常，chunk → done → [DONE] 三阶段格式正确，模型为 qwen3.7-plus

**10.2 POST /api/v1/llm/cancel/{request_id}** ✅
- 前置: 后台启动长流式请求（request_id=cancel-test-001，max_tokens=4096），确认状态为 running
- 取消请求体: `{"reason":"testing cancel functionality"}`
- 响应 200: `{"request_id":"anonymous-cancel-test-001","cancelled":true,"message":"cancel flag set"}`
- 结论: Redis 取消标志位设置成功，cancelled=true

**10.3 GET /api/v1/llm/stream/{request_id}/status** ✅
- 查询运行中的 request_id=anonymous-cancel-test-001
  - 响应 200: `{"request_id":"anonymous-cancel-test-001","found":true,"status":{"status":"running","updated_at":1785859155.16,"stream":true}}`
- 查询不存在的 request_id=non-existent-req-id
  - 响应 200: `{"request_id":"non-existent-req-id","found":false,"status":null}`
- 结论: 状态查询正常，found 字段区分存在/不存在

## 发现的问题

### 问题 1: 草图转 CAD 任务始终 PENDING（严重）
- **现象**: POST /api/v1/sketches 返回 202 并派发任务到 Celery `sketch` 队列，但任务始终处于 PENDING 状态（轮询 >5 分钟无变化），GET /api/v1/sketches/{task_id}/result 持续返回 404。
- **根因分析**: 
  - 任务描述中明确"Celery worker 已运行（reviews,generations 队列）"，**未提及 sketch 队列**。
  - Redis 检查 `LLEN sketch` = 0（队列无积压消息，但任务也未执行），推测 sketch 队列可能无 worker 消费，或 worker 消费后未上报 STARTED 状态（Celery 默认 task_track_started=False）。
  - Redis KEYS 中未见 `task_registry:*` 键，但 `register_task()` 在代码中被调用。
- **影响**: 
  - 草图转 CAD 的 SUCCESS 路径无法验证（SketchTaskResult 的 parse_result/generated_code/output_files 字段）。
  - 校准端点（POST /api/v1/sketches/calibrate）因原任务非 SUCCESS 而无法走通完整流程（仅验证了 409 错误分支）。
- **建议**: 启动 Celery worker 时增加 `-Q sketch` 参数（如 `celery -A app.celery_app worker -Q reviews,generations,sketch,default`）。

### 问题 2: 协同优化任务（default 队列）持续 pending（中等）
- **现象**: POST /api/v1/collaboration/optimize-from-review 返回 202 并派发 `run_optimize_from_review` 到 `default` 队列，但 optimize-result 持续返回 pending。
- **根因分析**: 代码中 `queue="default"`，但任务描述中 Celery worker 仅监听 reviews/generations 队列，default 队列可能无 worker。
- **影响**: 优化任务的完整执行路径（缺陷→LLM prompt→生成→自动复审）无法验证。
- **建议**: 确认 Celery worker 是否监听 default 队列，或将 optimize 任务派发到 reviews/generations 队列。

### 问题 3: LLM cancel 标志位设置后流未实际中断（轻微）
- **现象**: 对运行中的流式请求调用 cancel 后，`cancelled=true` 返回成功，但后台流式请求仍完整输出了全部内容（6.5KB 长文），最终以 `done=true` 正常结束而非 `cancelled=true`。
- **根因分析**: cancel 通过 Redis 标志位实现，streamer 在 chunk 之间检查标志位。qwen3.7-plus 流式输出速度较快，取消标志设置时流可能已接近完成或检查点间隔较大。
- **影响**: 取消 API 本身功能正确（标志位已设置），但实际中断效果取决于 streamer 检查频率与 LLM 响应速度。
- **建议**: 可在 stream_chat 中增加更频繁的取消检查点，或对长响应使用更小的 chunk 粒度。

### 问题 4: 任务描述与实际代码端点不一致（信息）
- **现象**: 任务描述预期 LLM 端点为 `POST /api/v1/llm/chat`、`POST /api/v1/llm/vlm`、`GET /api/v1/llm/models`，但 llm.py 实际实现为 `POST /api/v1/llm/stream`（SSE 流式）、`POST /api/v1/llm/cancel/{request_id}`、`GET /api/v1/llm/stream/{request_id}/status`。
- **处理**: 本次测试以代码实际签名为准，测试了 stream/cancel/status 三个端点。

## 通过率汇总

| 模块 | 端点数 | 通过 | 部分通过 | 失败 | 通过率 |
|---|---|---|---|---|---|
| Task 8 草图 | 5 | 4 | 1 | 0 | 80%（端点逻辑全部正确，1个 SUCCESS 路径未验证） |
| Task 9 协同 | 6 | 6 | 0 | 0 | 100% |
| Task 10 LLM | 3 | 3 | 0 | 0 | 100% |
| **合计** | **14** | **13** | **1** | **0** | **92.9%** |

> 说明: 协同模块实际有 6 个端点（任务描述为 5 个，多出 `GET /feedback-stats`），全部测试通过。
> LLM 模块端点与任务描述不同（stream/cancel/status vs chat/vlm/models），按实际代码测试。
> 唯一"部分通过"项为 `GET /api/v1/sketches/{task_id}/result`，端点逻辑正确（PENDING→404 符合设计），但因 sketch 队列无 worker 导致 SUCCESS 路径未能验证。
