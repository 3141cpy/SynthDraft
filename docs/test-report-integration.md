# 跨端点联动测试报告

## 测试时间
2026-08-05 00:30 - 00:46 (Asia/Shanghai)

## 测试环境
- Backend: http://localhost:8000 (FastAPI, SynthDraft Backend v0.1.0)
- LLM Provider: openai_compatible (qwen3.7-plus), available
- VLM Provider: openai_compatible, available
- Celery worker: 运行中（reviews / generations 队列）
- 测试样本: test/安全阀.pdf (237255 bytes)
  - 注：任务描述中的 test/test.pdf 不存在，改用 test/安全阀.pdf
- 测试方式: curl.exe 调用 REST API + PowerShell 轮询

## 测试结果矩阵

| 联动场景 | 步骤数 | 通过步骤 | 失败步骤 | 通过 |
|---|---|---|---|---|
| 场景1：审图→协同→生成闭环 | 7 | 5 | 2 | 部分通过 |
| 场景2：知识库全链路 | 7 | 4 | 3 | 部分通过 |
| 场景3：上传→生成文件下载 | 4 | 4 | 0 | ✅ 通过 |

---

## 详细测试

### 场景 1：审图→协同→生成闭环

#### 步骤 1.1：上传文件
- 请求: `POST /api/v1/uploads` (multipart/form-data, file=安全阀.pdf)
- 响应:
  ```json
  {
    "file_key": "e429c9e9bbb74adfaa57d85bb39e0022_安全阀.pdf",
    "file_name": "安全阀.pdf",
    "file_type": "pdf",
    "size": 237255,
    "content_type": "application/pdf"
  }
  ```
- HTTP 状态: 201
- 结果: ✅ 通过

#### 步骤 1.2：提交审图
- 请求: `POST /api/v1/reviews`
  ```json
  {
    "file_key": "e429c9e9bbb74adfaa57d85bb39e0022_安全阀.pdf",
    "file_type": "pdf",
    "standard_set": ["GB/T 1182", "GB/T 4457.4"]
  }
  ```
- 响应:
  ```json
  {
    "task_id": "c2228294-5d31-49ab-b116-e9ff31790396",
    "status": "queued",
    "websocket_url": "/api/v1/ws/tasks/c2228294-5d31-49ab-b116-e9ff31790396"
  }
  ```
- HTTP 状态: 202
- 结果: ✅ 通过

#### 步骤 1.3：轮询审图状态
- 请求: `GET /api/v1/tasks/c2228294-5d31-49ab-b116-e9ff31790396`（每 4s 轮询）
- 最终状态: succeeded (Celery SUCCESS)
- 耗时: ~194s（VLM OCR + LLM judge 较慢，初次轮询 180s 超时后直接查询确认完成）
- metadata.elapsed_ms: 194451
- 结果: ✅ 通过

#### 步骤 1.4：获取审图结果
- 请求: `GET /api/v1/reviews/c2228294-5d31-49ab-b116-e9ff31790396/result`
- 响应关键字段:
  - compliance_score: **66.0**
  - defects: **4 条**
    1. `{category: "title_block", severity: "critical", standard_ref: "GB/T 18229-2023 §4.1"}` - 缺失标题栏
    2. `{category: "tolerance", severity: "major", standard_ref: "GB/T 1804-2000 §6.1"}` - 未标注一般公差
    3. `{category: "dimensioning", severity: "major", standard_ref: "GB/T 18229-2023 §7.1"}` - 未使用关联尺寸标注
    4. `{category: "layer_naming", severity: "minor", standard_ref: "GB/T 18229-2023 §4.1"}` - 未进行图层管理
  - review_mode: vlm
  - judge_mode: llm
  - llm_model: qwen3.7-plus
  - report_path: reports\review_c2228294-5d31-49ab-b116-e9ff31790396.html
  - pdf_report_path: reports\review_c2228294-5d31-49ab-b116-e9ff31790396.pdf
- HTTP 状态: 200
- 结果: ✅ 通过

#### 步骤 1.5：调用 optimize-from-review
- 请求: `POST /api/v1/collaboration/optimize-from-review`
  ```json
  {
    "review_task_id": "c2228294-5d31-49ab-b116-e9ff31790396",
    "output_format": "dxf",
    "auto_re_review": true
  }
  ```
- 响应:
  ```json
  {
    "original_review_task_id": "c2228294-5d31-49ab-b116-e9ff31790396",
    "generation_task_id": "abeed63f-c941-4718-8a97-489758220605",
    "new_review_task_id": null,
    "status": "dispatched",
    "defects_count": 0,
    "optimized_prompt": "",
    "metadata": {
      "optimize_task_id": "abeed63f-c941-4718-8a97-489758220605",
      "websocket_url": "/api/v1/ws/tasks/abeed63f-c941-4718-8a97-489758220605"
    }
  }
  ```
- HTTP 状态: 202
- 结果: ✅ 通过（任务派发成功）

#### 步骤 1.6：轮询 optimize-result
- 请求: `GET /api/v1/collaboration/optimize-result/abeed63f-c941-4718-8a97-489758220605`（每 6s 轮询）
- 最终状态: **pending**（持续 6 分钟未变化）
- 耗时: 363s（超时退出）
- 结果: ❌ 失败
- 根因分析: `run_optimize_from_review` 任务被派发到 `queue="default"`，但 Celery worker 仅监听 `reviews` 和 `generations` 队列，导致任务永远无法被消费。
  - 代码位置: `backend/app/api/v1/endpoints/collaboration.py` 第 86 行
    ```python
    async_result = run_optimize_from_review.apply_async(
        kwargs={...},
        queue="default",  # ← 无 worker 监听此队列
    )
    ```

#### 步骤 1.7：diff 报告
- 请求: `GET /api/v1/collaboration/diff-report/c2228294-5d31-49ab-b116-e9ff31790396/c2228294-5d31-49ab-b116-e9ff31790396`
  - 注：因步骤 1.6 失败无 new_review_task_id，使用同一 task_id 验证端点结构
- 响应:
  ```json
  {
    "original_review_task_id": "c2228294-5d31-49ab-b116-e9ff31790396",
    "new_review_task_id": "c2228294-5d31-49ab-b116-e9ff31790396",
    "generation_task_id": null,
    "old_defects_count": 4,
    "new_defects_count": 4,
    "resolved_count": 0,
    "unresolved_count": 4,
    "new_count": 0,
    "old_compliance_score": 66.0,
    "new_compliance_score": 66.0,
    "score_improvement": 0.0,
    "diffs": [4 条 unresolved，similarity_score=1.0],
    "closure_rate": 0.0,
    "generated_at": "2026-08-05T00:43:24.959363"
  }
  ```
- HTTP 状态: 200
- 结果: ✅ 通过（端点结构验证完整：old_score/new_score/changes/diffs/closure_rate 均有）
- 注：因无法获得真实 new_review_task_id，未验证"缺陷已修复"场景

---

### 场景 2：知识库全链路

#### 步骤 2.1：索引建立
- 请求: `POST /api/v1/kb/reindex`
- 响应:
  ```json
  {
    "detail": "重建索引失败：无法加载任何 embedding 模型：bge-m3 / sentence-transformers / Ollama 均失败"
  }
  ```
- HTTP 状态: 503
- 结果: ❌ 失败
- 根因: embedding 模型（bge-m3 / sentence-transformers / Ollama）均不可用，无法生成向量索引

#### 步骤 2.2：检索验证
- 请求: `GET /api/v1/kb/clauses?query=形位公差&top_k=3`
- 响应:
  ```json
  {
    "detail": "知识库检索失败：无法加载任何 embedding 模型：bge-m3 / sentence-transformers / Ollama 均失败"
  }
  ```
- HTTP 状态: 503
- 结果: ❌ 失败
- 注：Qdrant 中存在之前索引的数据（6 个规范），但检索需要 embedding query 向量，模型不可用导致 503

#### 步骤 2.3：已索引规范列表
- 请求: `GET /api/v1/kb/standards`
- 响应:
  ```json
  {
    "standards": [
      "GB/T 1182-2018", "GB/T 131-2006", "GB/T 17450-1998",
      "GB/T 1804-2000", "GB/T 18229-2023", "GB/T 4457.4-2002"
    ],
    "count": 6
  }
  ```
- HTTP 状态: 200
- 结果: ✅ 通过（6 个规范已索引，来自之前的索引数据）

#### 步骤 2.4：冲突检测
- 请求: `GET /api/v1/kb/standards/conflicts?standard_a=GB/T 1182-2018&standard_b=GB/T 1804-2000&use_llm=false`
- 响应:
  ```json
  {
    "standard_a": "GB/T 1182-2018",
    "standard_b": "GB/T 1804-2000",
    "conflicts": [8 条 missing 类型冲突],
    "total": 8,
    "by_type": {"missing": 8},
    "by_severity": {"minor": 8},
    "llm_used": false
  }
  ```
- HTTP 状态: 200
- 结果: ✅ 通过
- 说明: 检测到 8 条"missing"类型冲突（GB/T 1182-2018 中的形位公差条款在 GB/T 1804-2000 中无对应），均 minor 严重度，使用关键词匹配方法

#### 步骤 2.5：配置列表
- 请求: `GET /api/v1/kb/profiles`
- 响应:
  ```json
  {
    "profiles": [
      {
        "name": "v3-e2e-profile-e7a74127",
        "description": "V3 e2e 自动创建",
        "standards": ["GB/T 1182", "GB/T 4458.4"],
        "priority": 10,
        "is_active": true
      },
      {
        "name": "test-profile",
        "description": "API test profile",
        "standards": ["GB/T 1182-2018", "GB/T 1804-2000"],
        "priority": 5,
        "is_active": false
      }
    ],
    "active_profile": "v3-e2e-profile-e7a74127",
    "total": 2
  }
  ```
- HTTP 状态: 200
- 结果: ✅ 通过（2 个配置，多于 1 个，可测试切换）

#### 步骤 2.6：配置切换
- 请求1: `POST /api/v1/kb/profiles/active` `{"name":"test-profile"}`
- 响应1: active_profile="test-profile", test-profile.is_active=true ✅
- 请求2: `POST /api/v1/kb/profiles/active` `{"name":"v3-e2e-profile-e7a74127"}`（切回原配置）
- 响应2: active_profile="v3-e2e-profile-e7a74127", v3-e2e-profile.is_active=true ✅
- HTTP 状态: 200 (两次均成功)
- 结果: ✅ 通过

#### 步骤 2.7：切换后检索验证
- 请求: `GET /api/v1/kb/clauses?query=形位公差` (切换后再次检索)
- 结果: ❌ 失败（同步骤 2.2，embedding 模型不可用）
- 注: 配置切换功能本身正常，但无法验证检索结果变化

---

### 场景 3：上传→生成文件下载链路

#### 步骤 3.1：同步执行生成
- 请求: `POST /api/v1/generations/execute`
  ```json
  {
    "code": "import cadquery as cq\nresult = cq.Workplane(\"XY\").box(50, 30, 20)",
    "output_format": "step",
    "timeout": 60
  }
  ```
  - 注：`/generations/execute` 端点需要 CadQuery 代码（`code` 字段），非自然语言 prompt。使用 `cq.Workplane("XY").box(50, 30, 20)` 生成长方体。
- 响应:
  ```json
  {
    "execution": {
      "success": true,
      "stdout": "EXPORT_OK step ...\\output.step\nEXPORT_OK stl ...\\output.stl\n",
      "stderr": "",
      "output_files": [
        "...\\generations\\8ab0e54dde34\\output.step",
        "...\\generations\\8ab0e54dde34\\output.stl"
      ],
      "elapsed_ms": 2277,
      "exit_code": 0,
      "violations": []
    },
    "geometry_validation": {
      "is_valid": true,
      "volume": 30000.0,
      "bounding_box": [-25.0, -15.0, -10.0, 25.0, 15.0, 10.0],
      "surface_area": 6200.0,
      "errors": [],
      "backend": "OCP"
    },
    "download_urls": [
      "/api/v1/generations/files/8ab0e54dde34/output.step",
      "/api/v1/generations/files/8ab0e54dde34/output.stl"
    ]
  }
  ```
- HTTP 状态: 200
- 结果: ✅ 通过
- 验证: 体积=30000mm³ (50×30×20=30000 ✓)，包围盒正确，几何校验通过

#### 步骤 3.2：下载 STEP 文件
- 请求: `GET /api/v1/generations/files/8ab0e54dde34/output.step`
- HTTP 状态: 200
- 文件大小: 15504 bytes
- 文件内容（前 5 行）:
  ```
  ISO-10303-21;
  HEADER;
  FILE_DESCRIPTION(('Open CASCADE Model'),'2;1');
  FILE_NAME('Open CASCADE Shape Model','2026-08-05T00:45:34',...);
  ```
- 结果: ✅ 通过（标准 STEP 格式，内容非空）

#### 步骤 3.3：下载 STL 文件
- 请求: `GET /api/v1/generations/files/8ab0e54dde34/output.stl`
- HTTP 状态: 200
- 文件大小: 684 bytes
- 文件内容: 二进制 STL 格式（Open CASCADE Technology 导出）
- 结果: ✅ 通过（内容非空）

#### 步骤 3.4：文件内容验证
- STEP 文件: 15504 bytes，标准 ISO-10303-21 头部，有效 STEP 文件 ✅
- STL 文件: 684 bytes，二进制 STL 格式，有效 STL 文件 ✅
- 结果: ✅ 通过

---

## 发现的问题

| 编号 | 问题 | 严重度 | 场景 | 复现步骤 |
|---|---|---|---|---|
| P-001 | Celery "default" 队列无 worker，`optimize-from-review` 任务永远 pending | **高** | 场景1 步骤1.6 | 1. 提交审图任务并等待 SUCCESS<br>2. 调用 `POST /api/v1/collaboration/optimize-from-review`<br>3. 轮询 `GET /api/v1/collaboration/optimize-result/{task_id}`<br>4. 任务状态持续 pending 不变 |
| P-002 | Embedding 模型不可用（bge-m3 / sentence-transformers / Ollama 均失败），KB 索引重建与条款检索 503 | **高** | 场景2 步骤2.1/2.2/2.7 | 1. 调用 `POST /api/v1/kb/reindex`<br>2. 返回 503 "无法加载任何 embedding 模型"<br>3. 调用 `GET /api/v1/kb/clauses?query=形位公差`<br>4. 同样 503 错误 |
| P-003 | 任务描述中的 `test/test.pdf` 样本文件不存在 | **低** | 全局 | `LS d:\SynthDraft\test` 无 test.pdf，仅有 安全阀.pdf / 旋塞.pdf / 阀体.pdf 等 |
| P-004 | 审图任务耗时较长（~194s），超出常规轮询超时 | **中** | 场景1 步骤1.3 | VLM OCR + LLM judge 流程耗时接近 3.5 分钟，建议前端/WebSocket 进度展示并设置合理超时 |

## 问题修复建议

### P-001：Celery "default" 队列无 worker
- **方案 A**（推荐）：将 `collaboration.py` 中 `queue="default"` 改为 `queue="generations"`（复用已有 worker）
  ```python
  # backend/app/api/v1/endpoints/collaboration.py:86
  queue="generations",  # 原为 "default"
  ```
- **方案 B**：启动额外 worker 监听 default 队列
  ```powershell
  celery -A app.celery_app worker -Q default --loglevel=info
  ```

### P-002：Embedding 模型不可用
- **方案 A**：安装 sentence-transformers + bge-m3 模型
  ```bash
  pip install sentence-transformers
  # 首次运行会自动下载 bge-m3 模型（约 2GB）
  ```
- **方案 B**：启动本地 Ollama 并拉取 embedding 模型
  ```bash
  ollama pull bge-m3
  ```
- **方案 C**：配置外部 embedding API（如 Volcano Engine / OpenAI embedding）

---

## 总结

- **通过率**: 1/3 场景完全通过（场景3），2/3 场景部分通过（场景1、场景2）
- **端到端链路完整性**: 部分断裂
  - ✅ 审图链路完整：上传 → 审图 → 获取结果 → diff 报告
  - ❌ 协同闭环断裂：optimize-from-review 任务卡在 pending（default 队列无 worker）
  - ❌ 知识库检索断裂：reindex/clauses 检索失败（embedding 模型不可用）
  - ✅ 生成下载链路完整：执行 CadQuery 代码 → 产出 STEP/STL → 下载文件
- **可用功能**: 审图（VLM+LLM）、规范列表、冲突检测、配置切换、CadQuery 沙箱执行、文件下载
- **阻断性问题**: 2 个（P-001 协同队列无 worker、P-002 embedding 模型不可用）
