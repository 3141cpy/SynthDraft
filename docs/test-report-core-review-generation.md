# 核心审图生成链路测试报告

## 测试时间
2026-08-05 00:12 (Asia/Shanghai)

## 测试环境
- 后端: http://localhost:8000 (uvicorn)
- Celery worker: reviews / generations 队列运行中
- AI Provider: 阿里云 qwen3.7-plus 活跃 (llm_available=true, vlm_available=true)
- Docker: PostgreSQL(5433) / Redis(6379) / Qdrant(6333) healthy
- 测试客户端: Windows PowerShell 5.1 (.NET ClientWebSocket)
- 测试样本: d:\SynthDraft\test\安全阀.pdf (237255 bytes)

## 端点测试结果

| # | 方法 | 路径 | 状态码 | 关键字段/响应 | 通过 | 备注 |
|---|---|---|---|---|---|---|
| 1 | GET | /api/v1/healthz | 200 | llm_available=true, vlm_available=true | ✅ | |
| 2 | GET | /api/v1/readyz | 200 | postgres=ok, redis=ok | ✅ | |
| 3 | POST | /api/v1/uploads | 201 | file_key=a4e58e7d...safety_valve.pdf | ✅ | 201非200;中文文件名编码乱码 |
| 4 | GET | /api/v1/uploads | 200 | uploads数组, total=81 | ✅ | |
| 5 | POST | /api/v1/uploads (空文件) | 400 | (空响应体) | ✅ | 正确拒绝空文件 |
| 6 | POST | /api/v1/reviews | 202 | task_id=9f8f2393... | ✅ | 需file_key+file_type,非file_path |
| 7 | GET | /api/v1/tasks/{task_id} (轮询) | 200 | /tasks显示queued(PROGRESS bug) | ⚠️ | PROGRESS未映射;用/reviews/result确认完成 |
| 8 | GET | /api/v1/reviews/{task_id}/result | 200 | score=54.0, 4缺陷, vlm_result 10字段 | ✅ | |
| 9 | GET | /api/v1/reviews/{task_id}/report | 200 | text/html, 2.86MB, 含<html>/<img> | ✅ | |
| 10 | GET | /api/v1/reviews/nonexistent/result | 404 | (空响应体) | ✅ | 正确返回404 |
| 11 | POST | /api/v1/generations | 202 | task_id=f01b37d3... | ✅ | |
| 12 | GET | /api/v1/generations/{task_id}/result (轮询) | 200 | ~10s完成, success=true | ✅ | |
| 13 | GET | /api/v1/generations/{task_id}/result | 200 | cadquery代码+output文件路径 | ✅ | |
| 14 | GET | /api/v1/generations/files/{file_path} | 200 | application/step, 15504字节 | ✅ | |
| 15 | POST | /api/v1/generations/execute | 200 | sync, volume=6283.19 (π·10²·20) | ✅ | 同步执行无需task_id |
| 16 | GET | /api/v1/tasks/{task_id} | 200 | status=succeeded, progress=0 | ✅ | 术语"succeeded"非"completed" |
| 17 | POST | /api/v1/tasks/{task_id}/cancel | 202 | status=canceled | ⚠️ | 已完成任务仍返回canceled,应返回409 |
| 18 | WS | /api/v1/ws/tasks/{task_id} | Open | 31条消息,首条status=running | ✅ | PROGRESS映射为queued(P2-2) |

## 详细测试记录

### Task 2: 健康检查

**1. GET /api/v1/healthz**
```
StatusCode: 200
Content: {"status":"ok","service":"SynthDraft Backend","version":"0.1.0",
  "llm_provider":"openai_compatible","llm_available":true,
  "vlm_provider":"openai_compatible","vlm_available":true}
```
验证: llm_available=true ✅, vlm_available=true ✅

**2. GET /api/v1/readyz**
```
StatusCode: 200
Content: {"status":"ok","service":"SynthDraft Backend","version":"0.1.0",
  "components":[
    {"name":"postgres","status":"ok","detail":null},
    {"name":"redis","status":"ok","detail":null}
  ]}
```
验证: postgres=ok ✅, redis=ok ✅

### Task 3: 文件上传

**3. POST /api/v1/uploads (安全阀.pdf)**
```
StatusCode: 201
Content: {"file_key":"a4e58e7dae904f6abb4c0cb6c594525b_safety_valve.pdf",
  "file_name":"safety_valve.pdf","file_type":"pdf","size":237255,
  "content_type":"application/pdf"}
```
- 注1: 返回 201 Created(非200)
- 注2: 任务描述使用 `file_path` 字段,实际 API 返回 `file_key` 字段
- 注3: 上传中文文件名"安全阀.pdf"时, file_name 显示为乱码 "å®å¨é.pdf"(UTF-8 字节被 Latin-1 解码)。为避免下游编码问题,改用 ASCII 文件名 safety_valve.pdf 重新上传

**4. GET /api/v1/uploads**
```
StatusCode: 200
Content: {"uploads":[...81个文件对象...], "total":81}
```
验证: 返回数组 ✅, 含 file_key/file_name/file_type/size 字段

**5. POST /api/v1/uploads (空文件边界条件)**
```
StatusCode: 400
Content: (空响应体)
```
验证: 空文件被正确拒绝,返回 400 ✅

### Task 4: 审图

**6. POST /api/v1/reviews**
```
请求体: {"file_key":"a4e58e7d...safety_valve.pdf","file_type":"pdf"}
StatusCode: 202
Content: {"task_id":"9f8f2393-f410-4190-80e4-a507f004e6d6",
  "status":"queued","websocket_url":"/api/v1/ws/tasks/9f8f2393-..."}
```
- 注: 任务描述使用 `file_path` 字段提交,实际 API 要求 `file_key` + `file_type` 两个字段(见 ReviewCreateRequest schema)。首次用 file_path 提交返回 400

**7. 轮询任务状态**
- 轮询 `GET /api/v1/tasks/{task_id}`: 180秒内始终返回 `status=queued, progress=0`(PROGRESS 状态未映射 bug)
- 改用 `GET /api/v1/reviews/{task_id}/result` 轮询: 首次返回 `status=running, step=vlm_ocr, progress=40`,约2秒后返回 `status=completed`
- 审图任务实际耗时: metadata.elapsed_ms = 227142ms (~227秒 / 3.8分钟)

**8. GET /api/v1/reviews/{task_id}/result**
```
StatusCode: 200
关键字段:
  status: "completed"
  compliance_score: 54.0
  defects: 4个缺陷
    - title_block (critical) - 缺失标题栏
    - dimensioning (critical) - 缺失尺寸标注
    - tolerance (major) - 缺失公差信息
    - layer_naming (major) - 未进行图层管理
  standards_applied: ["GB/T 1182","GB/T 4457.4"]
  review_mode: "vlm"
  report_path: "reports\\review_9f8f2393-...html"
  pdf_report_path: "reports\\review_9f8f2393-...pdf"
  metadata.vlm_result_keys: ["title","drawing_number","material","scale",
    "dimensions","technical_requirements","surface_roughness","tolerance",
    "regions","vlm_model"]  (10个字段 ✅)
  metadata.llm_model: "qwen3.7-plus"
  metadata.judge_mode: "llm"
  metadata.elapsed_ms: 227142
  precision_level: "reference_level"
```
验证: score=54.0 ✅, defects=4 ✅, vlm_result 含10个字段 ✅

**9. GET /api/v1/reviews/{task_id}/report**
```
StatusCode: 200
Content-Type: text/html; charset=utf-8
ContentLength: 2865684 bytes (2.86MB)
含 <html> 标签: True
含 <img> 标签: True
```
验证: HTML 报告含渲染图 ✅

**10. GET /api/v1/reviews/nonexistent-task-id/result (错误路径)**
```
StatusCode: 404
```
验证: 不存在的 task_id 返回 404 ✅

### Task 5: 生成

**11. POST /api/v1/generations (异步)**
```
请求体: {"input_type":"text","prompt":"生成长方体 50x30x20","output_format":"step"}
StatusCode: 202
Content: {"task_id":"f01b37d3-b4b7-461c-ae25-7bbf45946323",
  "status":"queued","websocket_url":"/api/v1/ws/tasks/f01b37d3-..."}
```

**12. 轮询生成结果**
- 首次轮询(0s): HTTP 202 (task still running)
- 第二次轮询(10s): HTTP 200 (completed)
- 生成耗时: codegen_elapsed_ms = 15734ms (~15.7秒)

**13. GET /api/v1/generations/{task_id}/result**
```
StatusCode: 200
关键字段:
  generated_code: |
    import cadquery as cq
    # 长方体参数
    length = 50.0   # 长 mm
    width = 30.0    # 宽 mm
    height = 20.0   # 高 mm
    # 创建 50x30x20 的长方体
    result = cq.Workplane("XY").box(length, width, height)
  execution.success: true
  execution.output_files: [
    "D:\\SynthDraft\\backend\\tmp_uploads\\generations\\2fbec5eefb04\\output.step",
    "D:\\SynthDraft\\backend\\tmp_uploads\\generations\\2fbec5eefb04\\output.stl"
  ]
  geometry_validation.is_valid: true
  geometry_validation.volume: 30000.0  (50×30×20=30000 ✅)
  geometry_validation.bounding_box: [-25,-15,-10, 25,15,10]
  metadata.llm_model: "qwen2.5-coder:7b"  (与审图的 qwen3.7-plus 不同)
  metadata.codegen_elapsed_ms: 15734
  mode: "llm"
```
验证: cadquery 代码 ✅, 输出文件路径 ✅, 几何校验通过 ✅

**14. GET /api/v1/generations/files/2fbec5eefb04/output.step**
```
StatusCode: 200
Content-Type: application/step
ContentLength: 15504 bytes
```
验证: 文件下载流正常 ✅

**15. POST /api/v1/generations/execute (同步执行)**
```
请求体: {"code":"import cadquery as cq\nresult = cq.Workplane(\"XY\").circle(10).extrude(20)",
  "output_format":"step","timeout":30}
StatusCode: 200
execution.success: true
execution.exit_code: 0
execution.elapsed_ms: 2280
output_files: [output.step, output.stl]
geometry_validation.is_valid: true
geometry_validation.volume: 6283.185307179586  (π×10²×20=6283.19 ✅)
geometry_validation.bounding_box: [-10,-10,0, 10,10,20]
download_urls: ["/api/v1/generations/files/32ff9461febd/output.step", ...]
执行耗时: 4.56s (同步, 无 task_id)
```
验证: 同步执行直接返回结果 ✅, 圆柱体体积正确 ✅

### Task 6: 任务

**16. GET /api/v1/tasks/{task_id} (审图任务,已完成)**
```
StatusCode: 200
Content: {"task_id":"9f8f2393-...","status":"succeeded","progress":0,
  "result":{...完整审图结果...},"error":null}
```
验证: 返回 status 字段 ✅
- 注1: status 值为 "succeeded"(非 "completed"),与 /reviews/result 的 "completed" 术语不一致
- 注2: progress 固定为 0(硬编码,未读取实际进度)

**17. POST /api/v1/tasks/{task_id}/cancel (取消已完成任务)**
```
StatusCode: 202
Content: {"task_id":"9f8f2393-...","status":"canceled"}
```
- 问题: 已处于终态(succeeded)的任务仍可被"取消",返回 202/canceled
- 期望行为: 对已完成任务应返回 409 Conflict 或提示"任务已完成,不可取消"
- 实际行为: 盲目调用 celery_app.control.revoke() 并返回 canceled,语义误导

### Task 7: WebSocket

**18. WS /api/v1/ws/tasks/{task_id}**
- 提交新审图任务: task_id=fdc4802a-ad7e-472e-99c3-c82bd44232a7
- WebSocket 连接: ws://localhost:8000/api/v1/ws/tasks/fdc4802a-...
- 连接状态: Open ✅
- 收到消息数: 31 条
- 首条消息: `{"task_id":"fdc4802a-...","status":"running","progress":0}`
- 后续消息: status=queued (PROGRESS 状态映射 bug,实际任务正在执行 vlm_ocr)
- 消息推送频率: 约每秒1条(符合 ws.py 中 asyncio.sleep(1.0) 设计)
- 30秒后连接仍为 Open(任务未完成,服务端未关闭连接)

验证: 连接成功 ✅, 收到进度消息 ✅

## 发现的问题

### P2-1: metadata.llm_model 不正确 (已知问题)
- **审图任务**: metadata.llm_model = "qwen3.7-plus" — 与活跃 Provider 一致
- **生成任务**: metadata.llm_model = "qwen2.5-coder:7b" — 与活跃 Provider(qwen3.7-plus)不一致
- **分析**: 生成代码路径(codegen)使用了不同的模型(qwen2.5-coder:7b,疑为本地 Ollama 模型),而非配置的活跃 LLM Provider。metadata 中记录的 llm_model 反映了实际使用的模型,但与系统配置的活跃 Provider 不符
- **影响**: 生成质量可能低于预期(7B 本地模型 vs 云端大模型);metadata 误导排查
- **位置**: 生成任务 Celery task / codegen service

### P2-2: 状态术语不一致 + PROGRESS 状态映射缺失 (已知问题)
- **术语不一致**: SUCCESS 状态在不同端点映射为不同字符串:
  - `/api/v1/tasks` → "succeeded"
  - `/api/v1/reviews/{id}/result` → "completed"
  - `/api/v1/sketches` → success=true (布尔字段)
- **PROGRESS 状态映射缺失**: `tasks.py` 的 `_map_celery_state()` 和 `ws.py` 的 `_map_state()` 均未处理 Celery 的 `PROGRESS` 状态,导致回退到默认值 "queued"
  - 审图任务执行中(VLM OCR 阶段, progress=40)时, `/tasks` 和 WebSocket 均错误显示 "queued"
  - 实际任务正在运行,但 API 报告为排队中,严重误导客户端
- **progress 字段硬编码**: `/tasks` 端点 progress 固定返回 0,未从 PROGRESS state info 读取实际进度
- **位置**: 
  - `backend/app/api/v1/endpoints/tasks.py` 第 14-25 行 `_map_celery_state()`
  - `backend/app/api/v1/endpoints/ws.py` 第 20-30 行 `_map_state()`
  - `backend/app/api/v1/endpoints/tasks.py` 第 53 行 `progress=0` (硬编码)

### P3-1: 中文文件名编码乱码 (新发现)
- 上传中文文件名(如"安全阀.pdf")时,服务端 file_name/file_key 出现乱码("å®å¨é.pdf")
- 原因: multipart Content-Disposition 中 filename 以 UTF-8 编码,但服务端按 Latin-1/ISO-8859-1 解码
- 影响: 中文文件名在文件列表、审图结果中均显示为乱码;file_key 含乱码可能导致下游引用问题
- **位置**: 文件上传端点 multipart 解析逻辑

### P3-2: 取消已完成任务返回不当响应 (新发现)
- `POST /api/v1/tasks/{task_id}/cancel` 对已处于终态(succeeded/failed)的任务仍返回 202/canceled
- 未检查任务当前状态,盲目调用 `celery_app.control.revoke(terminate=False)`
- 期望: 对终态任务返回 409 Conflict 或 400,提示"任务已完成,不可取消"
- **位置**: `backend/app/api/v1/endpoints/tasks.py` 第 56-68 行 `cancel_task()`

### P3-3: 审图结果中文内容编码问题 (新发现)
- 审图结果中 defects[].suggestion 和 evidence 字段含中文,但显示为乱码(如 "æ·»å ç¬¦åå½å®¶æ åè§å®ç...")
- 与 P3-1 同源: VLM 响应的中文内容编码处理不当
- 影响: 审图报告中的修改建议和证据描述不可读
- **位置**: VLM 响应解析 / 审图结果序列化逻辑

### P3-4: 上传成功状态码为 201 非 200 (轻微)
- `POST /api/v1/uploads` 返回 201 Created 而非 200 OK
- 这是 RESTful 规范的正确行为(资源创建),但与部分客户端期望的 200 不一致
- **建议**: 文档中明确标注返回 201

## 通过率汇总

| 类别 | 数量 | 占比 |
|---|---|---|
| ✅ 通过 | 16 | 88.9% |
| ⚠️ 部分通过(功能可用但有缺陷) | 2 | 11.1% |
| ❌ 失败 | 0 | 0% |
| **合计** | **18** | **100%** |

- **通过率(严格)**: 16/18 = 88.9%
- **通过率(功能可用)**: 18/18 = 100%(所有端点均可正常工作,2个存在语义/编码缺陷)
- **部分通过的端点**:
  - #7 轮询 /tasks: PROGRESS 状态映射 bug 导致轮询期间显示 "queued",需改用 /reviews/result 确认真实状态
  - #17 取消已完成任务: 返回 202/canceled 而非 409,语义不当
