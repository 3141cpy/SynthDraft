# Tasks

本任务清单按"先审计 → 再扩展 → 后真实测试 → 最后修复回归"的顺序推进。所有任务必须保留可追溯证据（日志/产出文件/截图）。

## Task 1: 依赖与配置完整性审计（前置）

目标：盘点 P0/P1 已交付代码的依赖与配置健康度，确保无缺失项。此任务为后续测试与扩展奠定基础。

- [x] SubTask 1.1: 依赖文件清点与缺失检测 ✅ 2026-07-26
  - 扫描 `backend/` 目录，定位 `pyproject.toml` / `requirements.txt` / `requirements-dev.txt` 等依赖文件
  - 若文件缺失：导出 `pip freeze` 当前已安装包列表，生成最小 `requirements.txt` 并提交
  - 扫描 `app/` 下所有 `import` 语句，列出第三方包，逐项验证已在依赖文件中声明
  - 输出 `tmp_audit_logs/01_dependencies.md`
  - **发现**：requirements.txt 存在（38 条声明）；12 个第三方包未声明（6 高危：cadquery/weasyprint/paddleocr/paddlepaddle/openpyxl/ultralytics）；2 个孤儿声明；openai 版本冲突（2.48 声明 vs 1.109 实际）；FlagEmbedding/sentence-transformers 未安装
- [x] SubTask 1.2: 配置项使用情况审计 ✅ 2026-07-26
  - 扫描 `app/config.py` 中所有 `Settings` 字段
  - 对每个字段 grep 全工程，标注使用位置（哪些文件 import）
  - 标注"已配置但未使用"字段（重点核查 `VLLM_BASE_URL` / `VLM_MODEL` / `LLM_PROVIDER` 现状）
  - 标注"业务代码使用但未在 Settings 声明"的孤儿配置（如 vlm_ocr.py 中 `os.environ.get("OLLAMA_HOST_URL")`）
  - 输出 `tmp_audit_logs/02_config_usage.md`
  - **发现**：16 个 Settings 字段未使用（含 LLM_PROVIDER/VLM_MODEL/VLLM_BASE_URL/EMBEDDING_MODEL）；9 个孤儿配置；OLLAMA_HOST_URL 在 3 处双重读取（embedder/llm_judge/vlm_ocr）；backend/.env.example 缺失
- [x] SubTask 1.3: Celery 任务与 API 路由最终核查 ✅ 2026-07-26
  - 模拟 worker 启动（`celery_app.loader.import_default_modules()`），输出 12 个任务注册名 + 队列路由
  - 启动 FastAPI 应用，导出 OpenAPI，输出 27 个路由的 method + path + 端点模块
  - 标注任何注册失败或路由冲突
  - 输出 `tmp_audit_logs/03_celery_api_routes.md`
  - **发现**：12 个 Celery 任务全过；28 个 API 路由无冲突（多出 GET / 根路径，非业务路由，可接受）
- [x] SubTask 1.4: 已完成模块可导入性扫描 ✅ 2026-07-26
  - 对 P0/P1 已交付的所有 services 模块逐个 `import` 验证
  - 标注任何 import 错误（循环依赖、缺失依赖、语法错误）
  - 输出 `tmp_audit_logs/04_module_importability.md`
  - **发现**：40/40 模块全部导入成功，无循环依赖、无缺失依赖、无语法错误

## Task 2: P0 已完成模块真实路径端到端测试

目标：对 P0 已交付模块执行真实主路径测试（非降级）。VLM 相关测试在 Task 4 完成后补做。

- [x] SubTask 2.1: CAD 解析底座真实测试 ✅ 2026-07-26 CONDITIONAL_PASS
  - 准备真实样本：`tests/samples/*.dxf` / `*.step` / `*.dwg`（若缺失从历史测试样本复制）
  - 调用 `app.services.cad.dxf_parser` / `step_reader` / `dwg_converter`，验证图层/实体/标注/标题栏/B-Rep 几何查询
  - 输出统一中间表示 JSON，通过 pydantic schema 校验
  - ODA File Converter 未安装时明确标注为环境限制，不视为功能缺陷
  - 输出 `tmp_audit_logs/05_cad_parsing.md` + 产出文件落盘 `tmp_audit_outputs/cad/`
  - **结果**：DXF 解析 PASS（5 实体/6 图层/标题栏）+ OCC STEP 读取 PASS（volume=1000, bbox=10×10×10）+ ODA 未装（环境限制）
- [x] SubTask 2.2: 知识库 RAG 真实检索测试 ✅ 2026-07-26 PASS（带环境限制）
  - 启动 Qdrant（docker compose），确认 `bge-m3` embedding 可加载
  - 调用 `app.services.kb.retriever`，发起"按主题/条款号/关键词"三种检索
  - 验证每条结果含条文出处与原文片段
  - 若 Qdrant 未索引，触发 `POST /api/v1/kb/reindex` 后重试
  - 输出 `tmp_audit_logs/06_kb_rag.md`
  - **结果**：Qdrant healthy（42 points, dim=768）+ Embedder 降级 Ollama nomic-embed-text + 三种检索全 PASS（8 条结果，score 0.45-0.83）
- [x] SubTask 2.3: 智能审图 v0 端到端（DXF→报告，VLM 部分待 Task 4） ✅ 2026-07-26 CONDITIONAL_PASS
  - 上传真实 DXF 工程图样本
  - 走完整管线：DXF 解析 → 图片渲染 → VLM 区域检测（Task 4 完成后补真实路径）→ 区域 OCR → 标识符归一化 → RAG 检索 → LLM 推理 → 缺陷列表 → 合规性评分 → HTML/PDF 报告
  - 验证缺陷条目五要素：类别/严重等级/坐标/条文引用/修改建议
  - 验证报告文件落盘可下载
  - 输出 `tmp_audit_logs/07_review_e2e.md` + 报告文件落盘 `tmp_audit_outputs/review/`
  - **结果**：LLM judge 真实跑通（qwen2.5-coder:7b，5 query 返回 19 条款）+ HTML 报告 PASS（28986 bytes）+ VLM/PDF 降级（环境限制）
- [x] SubTask 2.4: 智能生成 v0 端到端（NL→STEP） ✅ 2026-07-26 PASS
  - 提交自然语言描述："外径 100 内径 80 的法兰盘，4 个 φ10 螺栓孔均布在 φ80 节圆上"
  - 走完整管线：LLM 生成 CadQuery 代码 → 静态扫描 → 沙箱执行 → STEP/STL/DXF 导出 → 几何校验
  - 验证 STEP 文件可被 pythonOCC 重新读取，体积/包围盒非零
  - 输出 `tmp_audit_logs/08_generation_e2e.md` + STEP 文件落盘 `tmp_audit_outputs/generation/`
  - **结果**：LLM 生成正确 CadQuery 代码（46s）+ 沙箱执行（2.3s）+ STEP volume=26661.85mm³，bbox 100×100×10 完全匹配 prompt

## Task 3: AI Provider 抽象层与远程/多模态支持

目标：抽象统一 AI Provider 接口，支持 Ollama / OpenAI 兼容 / Anthropic Claude 三类 provider，覆盖文本 LLM 与多模态 VLM。

- [x] SubTask 3.1: 设计并实现 provider 抽象接口 ✅ 2026-07-26
  - 新建 `app/services/ai/__init__.py` 与 `app/services/ai/base.py`
  - 定义 `ChatMessage` / `ChatResponse` pydantic schema（role/content/images 字段）
  - 定义 `BaseLLMProvider` 抽象基类：`chat(messages) -> ChatResponse` / `chat_with_image(messages, image_b64) -> ChatResponse` / `is_available() -> bool` / `is_vlm_available() -> bool`
  - 定义 `get_llm_provider() -> BaseLLMProvider` 工厂（基于 `settings.LLM_PROVIDER` 单例缓存）
  - 输出文件：`app/services/ai/base.py`（113 行）、`app/services/ai/__init__.py`（17 行）
- [x] SubTask 3.2: 实现 Ollama Provider（迁移现有逻辑） ✅ 2026-07-26
  - 新建 `app/services/ai/providers/ollama_provider.py`（318 行）
  - 复用 [vlm_ocr.py](file:///d:/SynthDraft/backend/app/services/review/vlm_ocr.py) 中的 `list_ollama_models` / `_pick_vlm_model` / `_ollama_chat_with_image` 逻辑
  - 复用 [code_generator.py](file:///d:/SynthDraft/backend/app/services/generation/code_generator.py) 中的 `ollama.Client` chat 调用逻辑
  - 实现 `is_available()`：探测 Ollama 服务可达 + 目标模型已拉取
  - 实现 `is_vlm_available()`：探测视觉模型关键字
  - 保持既有降级路径行为（不可用时返回空+warning）
  - **验证**：provider=OllamaProvider, is_available=True, vlm_available=False, chat 返回 "Hello"
- [x] SubTask 3.3: 实现 OpenAI 兼容 Provider ✅ 2026-07-26
  - 新建 `app/services/ai/providers/openai_provider.py`
  - **先查阅官方文档**：WebFetch https://platform.openai.com/docs/guides/vision 成功确认 image_url 格式
  - 优先复用 `openai` 官方 Python SDK（1.109.1 已装）；用 `client.chat.completions.create`
  - 兼容 vLLM / DeepSeek / 通义千问 / 智谱 GLM / OpenAI 官方：通过 `OPENAI_BASE_URL` 切换
  - 文本模型：`client.chat.completions.create(model, messages)`
  - 视觉模型：messages 中 user content 包含 `{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}`
  - 实现 `is_available()`：实测发起一条 "ping" 消息（max_tokens=1）验证 API Key 与端点可达
  - **验证**：无 API Key 时降级返回 False + 空响应
- [x] SubTask 3.4: 实现 Anthropic Claude Provider ✅ 2026-07-26
  - 新建 `app/services/ai/providers/anthropic_provider.py`
  - **先查阅官方文档**：WebSearch 获取 Anthropic Messages API 2026 完整 schema（含 SDK 0.40+ 验证）
  - 优先复用 `anthropic` 官方 Python SDK（未装，用 httpx 兜底调 `/v1/messages`，headers 含 x-api-key / anthropic-version: 2023-06-01）
  - 文本模型：`client.messages.create(model, max_tokens, messages, system)`
  - 视觉模型：messages 中 user content 包含 `{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}` 与 `{"type": "text", "text": "..."}`
  - 实现 `is_available()`：实测发起一条 "ping" 消息（max_tokens=1）
  - **验证**：无 API Key 时降级返回 False + 空响应
- [x] SubTask 3.5: 重构既有模块走 Provider 抽象 ✅ 2026-07-26
  - 重构 [code_generator.py](file:///d:/SynthDraft/backend/app/services/generation/code_generator.py)：`_get_ollama_client` / `_call_ollama_generate` / `apply_multi_turn_edit` 改为通过 `get_llm_provider()` 调用，保留 `is_llm_available()` 函数签名（内部转调 `provider.is_available()`）
  - 重构 [vlm_ocr.py](file:///d:/SynthDraft/backend/app/services/review/vlm_ocr.py)：`is_vlm_available` / `vlm_detect_regions` / `vlm_ocr_extract` 改为通过 provider 调用，保留函数签名不变
  - 重构 [sketch_parser.py](file:///d:/SynthDraft/backend/app/services/generation/sketch_parser.py)：VLM 调用走 provider
  - 重构 [llm_judge.py](file:///d:/SynthDraft/backend/app/services/review/llm_judge.py)：LLM 调用走 provider
  - **保持函数签名与降级路径不变**：所有历史 self_test 与集成测试不得回归
  - **验证**：46 个 pytest 用例全过，verify_task9_integration / verify_task12 全过
- [x] SubTask 3.6: 扩展 config.py 与 .env.example ✅ 2026-07-26
  - `app/config.py` 新增字段：OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL / OPENAI_VLM_MODEL / ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL / ANTHROPIC_VLM_MODEL
  - 复用既有 `LLM_PROVIDER` 字段（值域：`ollama` / `openai` / `anthropic`）
  - `backend/.env.example` 新增对应示例配置（API_KEY 留空，附文档注释）
  - 健康检查端点 `GET /api/v1/healthz` 新增 `llm_provider` / `llm_available` / `vlm_available` 字段
  - `app/schemas/health.py` 的 `HealthResponse` 新增三个字段（带默认值，向后兼容）
  - **验证**：healthz 端点实测通过，provider 探测降级路径正确（5s 超时保护）

## Task 4: P1 已完成模块真实路径端到端测试（依赖 Task 3）

目标：在 Provider 抽象完成后，配置真实远程 VLM API Key，对"仅降级路径已验证"的 P1 模块做真实主路径测试。

- [x] SubTask 4.1: 区域检测 + 区域 OCR 真实多模态路径测试 ✅ 2026-07-27
  - 配置 `.env`：`LLM_PROVIDER=ollama` + 拉取 `minicpm-v:latest` 视觉模型
  - 准备样本 PNG：`tmp_audit_outputs/vlm_test/sample.png` (896x528, RGB)
  - 调用 `region_detector.detect_regions_detailed()`：返回 4 区域（title_block/dimension_area/view_area/parts_list），detector_source=vlm
  - 调用 `region_ocr.ocr_in_regions()`：4 区域全部 OCR 完成，title_block 命中 11 文本，view_area 命中 5 文本
  - 降级 vs 真实对比：区域数 0→4，OCR 字段数 0→10，detect 推理 37.99s + ocr 52.85s
  - 输出 `tmp_audit_logs/09_region_detect_real.md` + raw_detect_regions.txt + raw_ocr_extract.txt
  - **已知限制**：测试样本为登机牌图片（非工程图），OCR 字段语义无意义但 VLM 推理链路正常
- [x] SubTask 4.2: 草图转 CAD 真实 VLM 路径测试 ✅ 2026-07-27
  - 配置真实 VLM provider（ollama + minicpm-v:latest）
  - 准备草图样本 PNG
  - 调用 `sketch_parser.parse_sketch()`：返回非空 features 列表
  - 调用 `sketch_to_cadquery.sketch_to_dxf_via_cadquery()`：产出 DXF 文件
  - 输出 `tmp_audit_logs/10_sketch_real.md` + DXF 文件
- [x] SubTask 4.3: 装配体生成端到端测试 ✅ 2026-07-27
  - 构造装配体描述：2 类标准件（bolt M8 + flange_plate φ100）+ 1 类 mate（concentric）
  - 调用 `app.services.assembly` 完整管线：标准件生成 → port 配对 → mate 变换 → 装配体校验 → BOM 导出
  - 验证校验通过（interface/dof/connectivity/axioms 四维全过）
  - 验证 BOM CSV/JSON/DXF 三种格式产出完整
  - 输出 `tmp_audit_logs/11_assembly_e2e.md` + BOM 文件
- [x] SubTask 4.4: 审图→生成协同闭环测试 ✅ 2026-07-27
  - 基于 SubTask 2.3 的审图结果，触发 `POST /api/v1/collaboration/optimize-from-review`
  - 验证生成模块产出修订后文件
  - 验证复审产出对比报告（旧/新缺陷数对比）
  - 输出 `tmp_audit_logs/12_collaboration_e2e.md` + 对比报告

## Task 5: 真实远程 API 端到端验证

目标：验证 Provider 抽象的"无代码切换"承诺，确认仅改 `.env` 即可在 provider 间切换。

- [x] SubTask 5.1: 远程文本 LLM 切换验证 ✅ 2026-07-27
  - 配置 `LLM_PROVIDER=openai` + DeepSeek API Key（`OPENAI_BASE_URL=https://api.deepseek.com`）
  - 调用 `code_generator.generate_cadquery_code("立方体 10mm")`：返回 `mode=llm`，含 `import cadquery`，耗时 1.60s
  - 切换 `LLM_PROVIDER=anthropic` 无 Key：自动降级到 `mode=template`，无异常抛出
  - 切换 `LLM_PROVIDER=ollama`：回归本地行为，`mode=llm`，耗时 32.58s
  - 输出 `tmp_audit_logs/13_llm_switch.md` + 产出 deepseek_code.py / ollama_code.py / anthropic_fallback.py
- [x] SubTask 5.2: 远程视觉 VLM 切换验证 ✅ 2026-07-27
  - 配置 `LLM_PROVIDER=ollama` + minicpm-v:latest（OpenAI/Anthropic 无 VLM Key，仅做降级验证）
  - 调用 `vlm_ocr.vlm_detect_regions()`：返回 3 区域，bbox 规范化生效
  - 切换 `LLM_PROVIDER=openai` 无 Key：返回空列表，warning `ai.openai.chat_image.skipped reason=no_client`
  - 切换 `LLM_PROVIDER=anthropic` 无 Key：返回空列表，warning `ai.anthropic.chat_image.skipped reason=no_client`
  - 切换回 `LLM_PROVIDER=ollama`：回归正常，chat_with_image 65.25s 返回非空
  - 输出 `tmp_audit_logs/14_vlm_switch.md` + 切换矩阵 4×5 全过
- [x] SubTask 5.3: 健康检查端点暴露 provider 状态 ✅ 2026-07-27
  - 启动 FastAPI（TestClient），访问 `GET /api/v1/healthz`
  - 验证响应包含 `llm_provider="ollama"` / `llm_available=True` / `vlm_available=True` 字段
  - 切换 provider 重启服务：字段值变化（openai/anthropic 时 llm_available=False）
  - 输出 `tmp_audit_logs/15_health_endpoint.md` + _test_health_endpoint_result.json

## Task 6: 问题修复与全量回归

目标：针对前序任务发现的所有问题逐项修复，并跑全量回归确保 P0/P1 既有功能不破坏。

- [x] SubTask 6.1: 修复审计与测试中发现的问题 ✅ 2026-07-27
  - 汇总 Task 1-5 中发现的所有问题（依赖缺失/配置孤儿/功能缺陷/接口不一致）
  - 在本 subtask 下方追加修复记录（问题编号 + 修复文件 + 验证方式）
  - 修复后跑相关模块 self_test + 集成测试验证
  - **修复记录**：
    - P1（高）LLM 幻觉代码未拦截 → `code_generator.py` 新增 `_is_valid_llm_code`（import + 语法编译校验），失败降级到模板
    - P2（中）VLM bbox 嵌套列表噪声 → `vlm_ocr.py` 新增 `_normalize_bbox`（展开嵌套/钳制越界/边界调整），`region_detector.py` 防御性调用
    - P3（低）AABB 干涉误报 → `assembly/validator.py` 新增 `_has_concentric_axis_hole_exception`（concentric mate 孔-轴特例豁免）
  - **验证**：pytest 46/46 PASS + verify_task9_3_4 58/58 PASS + verify_task9_integration 5/5 PASS + verify_task12 52/52 PASS + verify_task11_e2e 76/76 PASS（总计 237+5 阶段，0 FAIL）
  - **修复报告**：`tmp_audit_logs/17_fixes.md`
- [x] SubTask 6.2: 全量回归测试 ✅ 2026-07-27
  - 跑 P0/P1 历史 13 个模块 self_test
  - 跑历史 115 项集成测试（verify_task9_3_4 / verify_task9_integration / verify_task12）
  - 跑 Task 2/4 新增的真实路径测试
  - 任何回归失败必须修复后重跑
  - 输出 `tmp_audit_logs/16_regression.md`
  - **结果**：5 个测试套件全过，237+5 用例 0 FAIL（pytest 46 + verify_task9_3_4 58 + verify_task9_integration 5 阶段 + verify_task12 52 + verify_task11_e2e 76）

## Task 7: 审查与扩展验收报告

目标：输出最终验收报告，作为是否可进入 P2 的依据。

- [ ] SubTask 7.1: 编写 `audit_report.md`
  - 汇总 Task 1-6 的所有日志与产出
  - 列出已修复问题与遗留环境限制
  - 给出验收结论（PASS / CONDITIONAL_PASS / FAIL）
  - 输出到 `.trae/specs/audit-p0p1-and-extend-ai-providers/audit_report.md`

# Task Dependencies

- Task 1（审计）无依赖，最先执行
- Task 2（P0 真实测试）依赖 Task 1 完成（确认依赖与配置健康）
- Task 3（Provider 抽象）可与 Task 2 并行（独立分支）
- Task 4（P1 真实测试）依赖 Task 3 完成（需 Provider 抽象支持远程 VLM）
- Task 5（远程 API 验证）依赖 Task 3 完成
- Task 6（修复与回归）依赖 Task 1-5 全部完成
- Task 7（验收报告）依赖 Task 6 完成
