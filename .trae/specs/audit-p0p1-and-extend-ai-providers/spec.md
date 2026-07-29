# P0+P1 全面审查与 AI Provider 扩展 Spec

## Why

P0/P1 阶段已交付大量功能，但 P1-GATE 报告显示：本机环境对 VLM、SolidWorks、YOLOv11 等关键路径仅验证了**降级路径**，未真正端到端实测主路径；同时 AI 调用层存在架构性 gap——`config.py` 暴露了 `LLM_PROVIDER` / `VLLM_BASE_URL` / `VLM_MODEL` 配置项，但 [code_generator.py](file:///d:/SynthDraft/backend/app/services/generation/code_generator.py) 与 [vlm_ocr.py](file:///d:/SynthDraft/backend/app/services/review/vlm_ocr.py) 实际硬编码走 Ollama，远程 API（OpenAI 兼容、Anthropic Claude 等）与多模态视觉模型均不可用。这违背"以瞎猜接口为耻、以覆盖测试为荣"原则，需在进入 P2 前回溯审查并补齐。

## What Changes

- **审查**：对 P0/P1 所有已完成模块做全面深入实际测试，不止于兜底路径；盘点依赖、配置、Celery 任务、API 路由的完整性，确保无缺失项。
- **重构**：抽象统一 AI Provider 接口（LLM 文本 + VLM 视觉），支持通过 `.env` 在 Ollama / OpenAI 兼容（vLLM / DeepSeek / 通义千问 / 智谱 GLM / OpenAI 官方）/ Anthropic Claude 之间无代码切换。
- **迁移**：将 [code_generator.py](file:///d:/SynthDraft/backend/app/services/generation/code_generator.py) / [vlm_ocr.py](file:///d:/SynthDraft/backend/app/services/review/vlm_ocr.py) / [sketch_parser.py](file:///d:/SynthDraft/backend/app/services/generation/sketch_parser.py) / [llm_judge.py](file:///d:/SynthDraft/backend/app/services/review/llm_judge.py) 迁移至新 Provider 抽象，保持既有 Ollama 路径行为不破坏。
- **测试**：在配置真实远程 API Key 的前提下，对 VLM 区域检测、区域 OCR、草图解析等"仅降级路径已验证"的模块做真实主路径端到端测试。
- **修复**：针对审查与测试中发现的问题逐项修复，并跑全量回归确保 P0/P1 既有功能不破坏。
- **报告**：输出 P0+P1 审查与 AI Provider 扩展验收报告。

## Impact

- **Affected specs**: `ai-engineering-design-assistant`（主 spec 的 P1 交付物质量与 P2 进入条件；不修改主 spec 阶段划分）
- **Affected code**:
  - 新增：`app/services/ai/providers/`（provider 抽象 + 各实现）
  - 重构：`app/services/generation/code_generator.py`、`app/services/review/vlm_ocr.py`、`app/services/generation/sketch_parser.py`、`app/services/review/llm_judge.py`
  - 配置：`app/config.py`（新增 API_KEY/BASE_URL/MODEL 三元组）、`.env.example`
  - 端点：`app/api/v1/endpoints/health.py`（暴露 provider 可用性）
  - 测试：`backend/tests/`（新增审查与远程 API E2E 测试脚本）
  - 报告：`.trae/specs/audit-p0p1-and-extend-ai-providers/audit_report.md`

## ADDED Requirements

### Requirement: P0/P1 模块真实路径端到端测试

系统 SHALL 对 P0/P1 已交付的所有模块执行真实主路径端到端测试（非降级路径），并保存可追溯的测试证据（日志 + 截图 + 产出文件）。

#### Scenario: CAD 解析底座真实测试
- **WHEN** 审查脚本向 CAD 解析模块投入真实 DXF / STEP / DWG 样本文件
- **THEN** 系统完成图层/实体/标注/标题栏解析、B-Rep 几何查询、ODA DWG→DXF 转换（如可用）
- **AND** 输出统一中间表示 JSON 并通过 schema 校验
- **AND** 若 ODA File Converter 未安装则明确标注为环境限制，不视为功能缺陷

#### Scenario: 知识库 RAG 真实检索测试
- **WHEN** 审查脚本向 KB 模块发起"按主题/条款号/关键词"检索请求
- **THEN** 系统通过 bge-m3 Embedding + Qdrant 返回条文级结果
- **AND** 每条结果附带条文出处与原文片段（强制引用原文机制）
- **AND** 若 Qdrant 未索引则触发 reindex 后重试

#### Scenario: 智能审图 v0 端到端测试
- **WHEN** 审查脚本上传真实 DXF 工程图样本
- **THEN** 系统完成 DXF 解析 → 图片渲染 → VLM 区域检测 → 区域受限 OCR → 标识符归一化 → RAG 检索 → LLM 推理 → 缺陷列表 → 合规性评分 → HTML/PDF 报告导出
- **AND** 全流程产出文件落盘可下载
- **AND** 缺陷条目包含类别/严重等级/坐标/条文引用/修改建议五要素

#### Scenario: 智能生成 v0 端到端测试
- **WHEN** 审查脚本提交自然语言零件描述（如"外径 100 内径 80 的法兰盘"）
- **THEN** 系统完成 LLM 生成 CadQuery 代码 → 静态扫描 → 沙箱执行 → STEP/STL/DXF 导出 → 几何校验
- **AND** 输出 STEP 文件可被 pythonOCC 重新读取且体积/包围盒非零

#### Scenario: 装配体生成端到端测试
- **WHEN** 审查脚本提交装配体描述（含至少 2 类标准件 + 1 类 mate）
- **THEN** 系统完成标准件生成 → port 配对 → mate 变换计算 → 装配体校验（interface/dof/connectivity/axioms 四维）→ BOM 导出（CSV/JSON/DXF）
- **AND** 校验通过且 BOM 包含完整 part_number / quantity / metadata

#### Scenario: 审图→生成协同闭环测试
- **WHEN** 审查脚本基于审图缺陷触发"一键优化图纸"
- **THEN** 系统完成缺陷列表 → 生成模块修订 → 修订后文件复审 → 修订前后对比报告
- **AND** 对比报告包含旧/新缺陷数对比与差异高亮

### Requirement: AI Provider 抽象与远程 API 支持

系统 SHALL 提供统一的 AI Provider 抽象层，支持通过环境变量在本地 Ollama 与远程 API 之间无代码切换，且同时覆盖文本 LLM 与多模态 VLM 两类模型。

#### Scenario: Provider 配置驱动切换
- **WHEN** 用户仅修改 `.env` 中的 `LLM_PROVIDER` 与对应 API_KEY/BASE_URL/MODEL
- **THEN** 系统在下次进程启动时切换至目标 provider，无需修改任何业务代码
- **AND** 切换后所有依赖 LLM/VLM 的模块（code_generator / vlm_ocr / sketch_parser / llm_judge）自动走新 provider

#### Scenario: Ollama Provider 保持兼容
- **WHEN** `LLM_PROVIDER=ollama`
- **THEN** 系统行为与现有 P0/P1 实现完全一致（自动探测可用视觉模型、降级路径保持）
- **AND** 历史所有 self_test 与集成测试不发生回归

#### Scenario: OpenAI 兼容 Provider 可用
- **WHEN** `LLM_PROVIDER=openai` 且配置 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`
- **THEN** 系统通过 OpenAI Chat Completions API 调用文本模型
- **AND** 通过 OpenAI Vision API（image_url base64）调用视觉模型
- **AND** 兼容 vLLM / DeepSeek / 通义千问 / 智谱 GLM / OpenAI 官方等 OpenAI 兼容端点

#### Scenario: Anthropic Claude Provider 可用
- **WHEN** `LLM_PROVIDER=anthropic` 且配置 `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL`
- **THEN** 系统通过 Anthropic Messages API 调用文本模型
- **AND** 通过 Claude 多模态能力（image content block）调用视觉模型

#### Scenario: Provider 健康检查
- **WHEN** 用户访问 `GET /api/v1/healthz`
- **THEN** 响应包含 `llm_provider` / `llm_available` / `vlm_available` 字段
- **AND** 字段值反映当前 provider 真实可达性（实测 ping，非配置存在性判断）

### Requirement: 依赖与配置完整性审计

系统 SHALL 输出完整的依赖与配置审计报告，确保无依赖项缺失、无配置项孤儿。

#### Scenario: 依赖文件清点
- **WHEN** 审查脚本扫描 `backend/` 目录
- **THEN** 输出 `pyproject.toml` / `requirements.txt` / `requirements-dev.txt` 等依赖文件清单
- **AND** 若文件缺失则明确标注为 gap 并创建最小依赖清单
- **AND** 对每个 `app/` 下 import 的第三方包验证在依赖文件中已声明

#### Scenario: 配置项使用情况审计
- **WHEN** 审查脚本扫描 `app/config.py` 与 `.env.example`
- **THEN** 输出每个 Settings 字段的使用位置（被哪些文件 import）
- **AND** 标注"已配置但未使用"的字段（如 `VLLM_BASE_URL` / `VLM_MODEL` 现状）
- **AND** 标注"业务代码使用但未在 Settings 声明"的孤儿配置

#### Scenario: Celery 任务与 API 路由核查
- **WHEN** 审查脚本启动 Celery worker 模拟与 FastAPI 应用
- **THEN** 输出 12 个 Celery 任务的注册名与队列路由（接 P1-GATE 修复）
- **AND** 输出 27 个 API 路由的 method + path + 端点模块
- **AND** 任何注册失败或路由冲突明确标注

### Requirement: 问题修复与全量回归

系统 SHALL 针对审查与测试中发现的所有问题逐项修复，并跑全量回归测试确保不破坏 P0/P1 既有功能。

#### Scenario: 问题修复闭环
- **WHEN** 审查或测试发现任何功能缺陷、配置 gap、依赖缺失
- **THEN** 在 `tasks.md` 中新增对应修复 subtask
- **AND** 修复后跑相关模块 self_test + 集成测试验证
- **AND** 修复记录写入最终验收报告

#### Scenario: 全量回归无破坏
- **WHEN** 所有修复与扩展完成后执行全量回归
- **THEN** P0/P1 历史 13 个模块 self_test 全部通过
- **AND** 历史 115 项集成测试 + 146 项端到端实测全部通过
- **AND** 新增 provider 抽象与远程 API 测试全部通过

## MODIFIED Requirements

### Requirement: AI 调用层（重构现有实现）

现有 [code_generator.py](file:///d:/SynthDraft/backend/app/services/generation/code_generator.py) / [vlm_ocr.py](file:///d:/SynthDraft/backend/app/services/review/vlm_ocr.py) / [sketch_parser.py](file:///d:/SynthDraft/backend/app/services/generation/sketch_parser.py) / [llm_judge.py](file:///d:/SynthDraft/backend/app/services/review/llm_judge.py) 直接调用 Ollama 客户端或 HTTP API。修改为：通过 `app.services.ai.providers` 工厂获取 provider 实例，统一调用 `provider.chat(messages)` / `provider.chat_with_image(messages, image_b64)` 接口。provider 实例由 `settings.LLM_PROVIDER` 决定，参数从 `settings` 读取。

## 禁止行为

- ❌ 跳过真实主路径测试，仅以降级路径作为通过依据
- ❌ 在未配置真实 API Key 的情况下假装远程 API 测试通过
- ❌ 修改主 spec `ai-engineering-design-assistant` 的阶段划分
- ❌ 引入新 provider 时破坏既有 Ollama 路径行为
- ❌ 在 Provider 抽象中瞎猜 OpenAI / Anthropic API 接口（必须查阅官方文档并以实际响应为准）
- ❌ 删除或弱化既有降级路径（Ollama 不可用时仍需返回空+warning）

## 八荣八耻合规

- **以瞎猜接口为耻，以认真查询为荣**：OpenAI / Anthropic API 调用必须基于官方文档与实际响应验证，不臆测参数名与响应结构。
- **以模糊执行为耻，以寻求确认为荣**：测试发现的功能缺陷在修复前需确认是 bug 还是环境限制。
- **以臆想业务为耻，以人类确认为荣**：Provider 抽象的接口设计需对齐既有调用方的真实使用方式。
- **以创造接口为耻，以复用现有为荣**：优先复用 `httpx` / `ollama` / `openai` / `anthropic` 官方 SDK，不重造 HTTP 客户端。
- **以跳过验证为耻，以主动测试为荣**：所有"仅降级路径已验证"的模块必须补做真实主路径测试。
- **以破坏架构为耻，以遵循规范为荣**：Provider 抽象需遵循 spec.md 既有架构分层（services 层不直接调 HTTP）。
- **以假装理解为耻，以诚实无知为荣**：测试中遇到未知响应或异常需如实记录，不掩盖。
- **以盲目修改为耻，以谨慎重构为荣**：迁移既有模块至 Provider 抽象时保持函数签名与降级路径不变。
