# SynthDraft 最终验收与修复 Spec

## Why

SynthDraft 项目已完成 P0/P1/P2 多轮开发，Task 8（SolidWorks Add-in）也已实现。但存在以下未完成事项：
1. Task 8 实现已完成但 `implement-solidworks-addin/checklist.md` 48 项检查点未验证
2. `realpath-test-backend-api` spec 已创建但未执行（后端 API 端到端真实路径测试）
3. SolidWorks Worker（Task 7/10/11）真实路径未在集成环境实测
4. VLM 相关模块（region_detector/vlm_ocr/sketch_parser）仅代码审查未做
5. 依赖项完整性未系统验证（Python 包 + 系统工具 + SolidWorks interop + Docker 服务）
6. 测试中发现的问题未修复
7. 无统一最终交付报告

本 spec 旨在产出一份覆盖"Task 8 验证 + 后端 API 实测 + SolidWorks Worker 实测 + VLM 代码审查 + 依赖检查 + 问题修复 + 最终交付报告"的端到端验收，作为项目最终交付依据。

## 核心执行原则（HARD RULES，不可违反）

1. **主动修复原则**：当遇到服务/程序/依赖项不可用/缺失/与文档说明不符时，**必须优先启动/配置/安装该服务/程序/依赖项**以保证完整测试或项目运行。只有当超出能力范围（如需要付费许可证、需要 GUI 交互、需要管理员权限且无法降级）无法处理时，才可在最终交付报告中诚实标注 ENV-LIMIT 并特别提醒用户。
2. **实事求是原则**：每一项测试必须基于真实证据（HTTP 状态码 + 响应片段 + 产出文件），不可主观断言 PASS。降级路径项必须标注 FALLBACK-PATH，环境限制项必须标注 ENV-LIMIT，失败项必须标注 FAIL，严禁将三者标为 PASS。
3. **深入工作原则**：不得偷懒，不得仅因 TCP 连接成功即 PASS，不得仅因导入成功即 PASS，必须验证真实业务产出（文件存在 + 内容正确 + 业务逻辑生效）。
4. **谨慎重构原则**：修复问题时遵循最小改动，不破坏现有架构，不创造新接口，复用现有实现。

遵循八荣八耻原则：以主动测试为荣（每一端点真实调用）；以诚实无知为荣（环境限制明确标注）；以跳过验证为耻（无仅因 TCP 连接成功即 PASS 的敷衍）；以假装理解为耻（路径类型 REAL/FALLBACK/SYNC-BYPASS 明确区分）；以瞎猜接口为耻（所有 API 调用基于已验证签名）；以认真查询为荣（依赖项实际探测）；以臆想业务为耻（业务逻辑基于代码实际阅读）；以人类确认为荣（超出能力范围如实标注并提醒用户）；以创造接口为耻（复用现有接口）；以破坏架构为耻（修复遵循谨慎重构）；以盲目修改为耻（修复前先定位根因）。

## What Changes

- **依赖项主动修复**：检查 Python 包 + 系统工具 + SolidWorks interop + Docker 服务，**缺失项立即安装/启动/配置**，不轻易标注 ENV-LIMIT
- **后端服务主动启动**：启动 Docker Desktop（若未运行）+ Postgres/Redis/Qdrant/Ollama 容器（若未启动）+ 拉取 Ollama 模型（若未拉取）+ 启动 FastAPI + 启动 Celery worker，确保真实路径可用（不止兜底路径）
- **Task 8 验证**：执行 `verify_task8.ps1` 自检脚本，验证 48 项检查点，勾选 `implement-solidworks-addin/checklist.md`
- **后端 API 真实路径测试**：执行 `realpath-test-backend-api` spec 全部 10 个 Task，覆盖 health/uploads/reviews/generations/kb/llm/sketch/collaboration/observability/tasks 端点
- **SolidWorks Worker 真实路径测试**：实测 sw_session/worker_pool/license_manager/reader/writer 实际调用（Task 7/10/11），SolidWorks 已确认本地安装
- **VLM 代码审查**：审查 region_detector.py/vlm_ocr.py/sketch_parser.py 代码质量与降级路径（不实测，仅代码审查）
- **问题修复**：针对测试中发现的问题进行修复（优先 P0，次 P1，P2 视情况）
- **最终交付报告**：`backend/tmp_audit_logs/final_acceptance_report.md`，汇总所有测试结果、问题清单、修复状态、环境限制

## Impact

- Affected specs:
  - `implement-solidworks-addin`（验证并勾选 checklist）
  - `realpath-test-backend-api`（执行并完成全部 Task）
  - `ai-engineering-design-assistant`（更新 Task 8 状态为 ✅ 实现）
- Affected code: 测试中发现 bug 的源码文件（视修复范围而定）
- Affected docs:
  - 新增 `backend/tmp_audit_logs/task8_backend_realtest.md`（后端 API 真实路径测试报告）
  - 新增 `backend/tmp_audit_logs/solidworks_worker_realtest.md`（SolidWorks Worker 真实路径测试报告）
  - 新增 `backend/tmp_audit_logs/vlm_code_review.md`（VLM 代码审查报告）
  - 新增 `backend/tmp_audit_logs/dependency_check.md`（依赖项检查报告）
  - 新增 `backend/tmp_audit_logs/final_acceptance_report.md`（最终交付报告）
  - 更新 `solidworks_addin/verify_task8.ps1` 自检脚本（若 8.6 未实现则补全）
  - 更新 `d:\SynthDraft\.trae\specs\ai-engineering-design-assistant\tasks.md`（Task 8 状态变更）

## ADDED Requirements

### Requirement: 主动服务与依赖管理（HARD RULES）

系统 SHALL 在测试前主动检查并修复所有缺失的服务/程序/依赖项，确保测试走真实路径。**缺失项必须立即安装/启动/配置**，不轻易标注 ENV-LIMIT。

#### Scenario: Docker Desktop 主动启动

- **WHEN** 检查 Docker Desktop 状态发现未运行
- **THEN** SHALL 主动启动 Docker Desktop（`Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"`）
- **AND** 等待 Docker 引擎就绪（轮询 `docker info` 直到成功，超时 120 秒）
- **AND** 若启动失败，记录根因并尝试修复（如重启服务、检查 WSL 后端）

#### Scenario: Docker Compose 服务主动启动

- **WHEN** 检查 `docker ps` 发现 postgres / redis / qdrant / ollama 容器未运行
- **THEN** SHALL 主动执行 `docker-compose up -d`（在 `infra/` 目录）
- **AND** 等待容器健康（轮询 `docker ps` 直到状态为 healthy，超时 60 秒）
- **AND** 验证端口映射可达（5433/6379/6333/11434）

#### Scenario: Ollama 模型主动拉取

- **WHEN** Ollama 容器运行但所需模型（qwen2.5-coder:7b / bge-m3）未拉取
- **THEN** SHALL 主动执行 `docker exec ollama ollama pull qwen2.5-coder:7b` 与 `bge-m3`
- **AND** 等待拉取完成（可能耗时较长，需耐心等待）
- **AND** 验证模型可用（`curl http://localhost:11434/api/tags`）

#### Scenario: Python 包缺失主动安装

- **WHEN** `pip list` 对比 `requirements.txt` 发现缺失包
- **THEN** SHALL 主动执行 `pip install <缺失包>`
- **AND** 验证导入成功（`python -c "import <包名>"`）
- **AND** 若版本冲突，记录并尝试 `pip install <包名>==<版本>`

#### Scenario: ODA File Converter 主动配置

- **WHEN** 检查 ODA File Converter 未安装
- **THEN** SHALL 主动检查 `odafc` Python 包是否可用（`pip show odafc`）
- **AND** 若 odafc 可用，配置环境变量指向 ODA File Converter 路径
- **AND** 若均不可用，检查 `dwg_converter.py` 的降级路径是否生效，并标注 FALLBACK-PATH

#### Scenario: FastAPI 服务主动启动

- **WHEN** 检查 `http://localhost:8000/healthz` 不可达
- **THEN** SHALL 主动启动 FastAPI 服务（`cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`）
- **AND** 等待服务就绪（轮询 `/healthz` 直到 HTTP 200，超时 30 秒）
- **AND** 验证 OpenAPI 文档可达（`/docs`）

#### Scenario: Celery Worker 主动启动

- **WHEN** 检查 Celery worker 未运行
- **THEN** SHALL 主动启动 Celery worker（`cd backend && celery -A app.celery_app worker --loglevel=info --pool=solo`）
- **AND** Windows 环境使用 `--pool=solo` 避免 prefork 卡死
- **AND** 验证 worker 响应（`celery -A app.celery_app inspect ping`）
- **AND** 若 worker 仍卡死，记录根因并准备 `task.apply()` 同步执行方案（标注 SYNC-BYPASS）

### Requirement: Task 8 SolidWorks Add-in 自检验证

系统 SHALL 执行 `solidworks_addin/verify_task8.ps1` 自检脚本，覆盖 48 项检查点（编译/COM 注册/安装脚本/卸载脚本/版本清单/自检脚本/README/主项目状态更新/八荣八耻合规），通过率 ≥ 90%（环境限制项如实标注 ENV-LIMIT）。

#### Scenario: 自检脚本覆盖全部 SubTask

- **WHEN** 执行 `verify_task8.ps1`
- **THEN** SHALL 覆盖 8.1（编译）/8.2（COM 注册）/8.3（安装脚本）/8.4（卸载脚本+版本清单）/8.6（自检）/8.7（README）/8.8（主项目状态）全部检查点
- **AND** 输出结构化报告（x/y PASS + 失败项清单 + 退出码 0/1）
- **AND** 环境限制项（如 HKLM 需管理员权限）明确标注 ENV-LIMIT，不混入 PASS 计数

#### Scenario: 编译产物验证

- **WHEN** 自检脚本执行编译检查
- **THEN** SHALL 验证 `bin\Release\SynthDraftAddIn.dll` 存在且非空（>10KB）
- **AND** 编译命令实测执行成功（无 MSB3644 错误）

#### Scenario: COM 注册验证

- **WHEN** 自检脚本执行 COM 注册检查
- **THEN** SHALL 验证 `HKCU\Software\Classes\CLSID\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}` 注册表项存在（per-user 注册）
- **AND** 验证 `HKCU\Software\SynthDraft\backend_url` 可被 BackendClient.GetBackendUrl() 读取

### Requirement: 后端服务真实可用

系统 SHALL 启动并验证后端服务真实可用，确保测试走真实路径而非仅兜底路径。

#### Scenario: Docker 服务健康

- **WHEN** 启动 Docker Compose 服务
- **THEN** SHALL 验证 postgres / redis / qdrant / ollama 容器健康
- **AND** 验证端口映射可达（5433/6379/6333/11434）
- **AND** 若服务不可用，优先启动/配置/安装该服务

#### Scenario: FastAPI 服务真实响应

- **WHEN** 启动 FastAPI 服务（uvicorn 或 hypercorn）
- **THEN** SHALL 验证 `GET /healthz` 返回 HTTP 200 + `status=ok`
- **AND** 验证 `GET /docs` 返回 OpenAPI 文档

#### Scenario: Celery worker 真实执行

- **WHEN** 启动 Celery worker
- **THEN** SHALL 验证 worker 进程存在且监听 reviews/generations/sketch 队列
- **AND** 若 Windows prefork 池卡死，允许 `task.apply()` 同步执行，但需标注"绕过 worker 调度，业务管线真实执行"

### Requirement: 后端 API 端点真实路径测试

系统 SHALL 对 `app/api/v1/endpoints/` 下全部端点做真实 HTTP 调用测试，覆盖 health / uploads / reviews / generations / kb / llm / sketch / collaboration / observability / tasks。详细要求见 `realpath-test-backend-api/spec.md`。

#### Scenario: 上传 + 审图真实路径

- **WHEN** `POST /api/v1/uploads/` 上传 DXF 文件
- **AND** `POST /api/v1/reviews/` 提交审图任务
- **AND** 轮询 `GET /api/v1/reviews/{task_id}` 直到 completed
- **THEN** SHALL 验证审图结果含 `compliance_score`（数值，非 null）
- **AND** `defects` 数组非空（含 category/severity/standard_ref/suggestion）
- **AND** `report_path` 指向真实存在的 HTML 文件（size > 0）
- **AND** `review_mode` 为 `vlm` / `vector_only` / `rule_engine` 之一并明确标注路径类型

#### Scenario: 文本生成真实路径

- **WHEN** `POST /api/v1/generations/` 提交 text→step 生成任务
- **AND** 轮询直到 completed
- **THEN** SHALL 验证 `execution.output_files` 非空且文件真实存在（STEP 文件 size > 0）
- **AND** `geometry_validation.is_valid=true` 且 `volume > 0`
- **AND** 路径类型明确（REAL-PATH llm / FALLBACK-PATH template / SYNC-BYPASS）

#### Scenario: 知识库索引与检索

- **WHEN** `POST /api/v1/kb/index` 索引标准文档
- **AND** `POST /api/v1/kb/search` 检索相关条款
- **THEN** SHALL 验证检索结果含 `clause_id` / `standard_ref` / `text` 字段
- **AND** 需明确标注 embedding 模型与路径类型

#### Scenario: LLM 流式响应

- **WHEN** `POST /api/v1/llm/stream` 发起流式 chat 请求
- **THEN** SHALL 收到 SSE 流，含 `data:` 行 + `[DONE]` 终止标记
- **AND** 需记录至少 1 个真实 token chunk
- **AND** 需标注 LLM provider（ollama / openai-compatible / deepseek）

### Requirement: SolidWorks Worker 真实路径测试（SolidWorks 已确认本地安装）

系统 SHALL 实测 SolidWorks Worker（Task 7/10/11）真实调用，覆盖 sw_session / worker_pool / license_manager / reader / writer 模块。**SolidWorks 已由用户确认本地安装**，不得轻易标注 ENV-LIMIT。

#### Scenario: SolidWorks 会话管理

- **WHEN** 实测 `sw_session.py` 的 SwSession 类
- **THEN** SHALL 验证 `start_session()` / `open_document()` / `close_document()` / `stop_session()` 真实执行
- **AND** 验证 SolidWorks 进程实际启动与退出
- **AND** 若会话启动失败，**优先排查根因**（如 win32com 未安装则 `pip install pywin32`，如许可证未激活则提示用户激活）
- **AND** 只有当超出能力范围（如许可证需付费激活、需 GUI 交互）时才标注 ENV-LIMIT

#### Scenario: Worker 池与并发控制

- **WHEN** 实测 `worker_pool.py` 的 WorkerPool 类
- **THEN** SHALL 验证 `acquire()` / `release()` / `get_status()` 真实执行
- **AND** 验证 Semaphore 并发控制有效
- **AND** 验证健康检查与自动重启机制

#### Scenario: 许可证管理

- **WHEN** 实测 `license.py` 的 SolidWorksLicenseManager 类
- **THEN** SHALL 验证 `acquire()` / `release()` / `get_status()` 真实执行
- **AND** 验证计数控制（超限拒绝）
- **AND** 验证主动探测机制
- **AND** 若许可证不可用，**优先排查**（检查 SolidWorks 是否已激活、是否为教育版/商业版）

#### Scenario: SLDPRT/SLDASM 读取

- **WHEN** 实测 `reader.py` 的读取功能
- **THEN** SHALL 验证特征树 / 尺寸 / 形位公差 / 表面粗糙度 / 技术要求 / 明细栏提取
- **AND** 若无真实 SLDPRT 样本文件，**主动创建测试样本**（通过 writer.py 生成或使用 SolidWorks 自带样本）
- **AND** 若确实无法获取样本，明确标注 ENV-LIMIT 并说明根因

#### Scenario: SLDPRT/SLDASM 生成

- **WHEN** 实测 `writer.py` 的生成功能
- **THEN** SHALL 验证基于 CadQuery 代码或特征描述重建特征树
- **AND** 验证 3 条生成路径（new_document / open_template / import_step）
- **AND** 若生成失败，**记录失败原因并尝试修复**（如 API 签名错误则查询 SolidWorks API Help 修正）

### Requirement: VLM 模块代码审查

系统 SHALL 对 VLM 相关模块进行代码审查（不实测），覆盖 region_detector.py / vlm_ocr.py / sketch_parser.py。

#### Scenario: region_detector.py 代码审查

- **WHEN** 审查 `app/services/review/region_detector.py`
- **THEN** SHALL 检查：
  - YOLOv11 模型加载逻辑（含 ultralytics 未安装时的降级路径）
  - 区域检测输出 schema（标题栏/修订表/明细栏/视图区/标注区）
  - 错误处理与日志记录
  - 与 region_ocr.py 的接口契约

#### Scenario: vlm_ocr.py 代码审查

- **WHEN** 审查 `app/services/review/vlm_ocr.py`
- **THEN** SHALL 检查：
  - VLM provider 切换逻辑（ollama / openai-compatible / anthropic）
  - 图像编码逻辑（base64 / URL）
  - OCR 结果解析与结构化输出
  - 降级路径（VLM 不可用时的兜底）

#### Scenario: sketch_parser.py 代码审查

- **WHEN** 审查 `app/services/generation/sketch_parser.py`
- **THEN** SHALL 检查：
  - 草图解析逻辑（参数提取 / bbox 计算）
  - VLM 调用与降级路径
  - 与 sketch_to_cadquery.py 的接口契约
  - 错误处理与日志记录

### Requirement: 依赖项主动检查与修复

系统 SHALL 全面检查依赖项完整性，**缺失项必须立即安装/配置**，确保无任何依赖项缺失。只有当超出能力范围（如需要付费许可证、需要 GUI 交互、需要管理员权限且无法降级）时才可标注 ENV-LIMIT。

#### Scenario: Python 包主动检查与安装

- **WHEN** 执行 `pip list` 与 `requirements.txt` 对比
- **THEN** SHALL 验证全部 Python 包已安装且版本兼容
- **AND** 缺失包需**立即执行 `pip install`** 安装
- **AND** 版本冲突需记录并**尝试 `pip install <包名>==<版本>`** 修复
- **AND** 安装后验证导入成功（`python -c "import <包名>"`）

#### Scenario: 系统工具主动检查与配置

- **WHEN** 检查系统工具可达性
- **THEN** SHALL 验证：
  - SolidWorks 2022+ 已安装（用户已确认本地安装，验证 `D:\Program Files\SolidWorks Corp\SOLIDWORKS\` 存在）
  - ODA File Converter 已安装（DWG→DXF 转换，若未安装检查 `odafc` 包或降级路径）
  - FreeCAD 已安装（备用引擎，若未安装检查 `freecad_engine.py` 降级路径）
  - pythonOCC 已安装（STEP/IGES 读取，若未安装 `pip install cadquery-ocp`）
  - .NET Framework 4.8+ 已安装（Add-in 编译，检查注册表 Release ≥ 528040）
  - MSBuild / csc.exe 已安装（Add-in 编译，检查 VS BuildTools 路径）
- **AND** 缺失项需**立即安装或配置**，不轻易标注 ENV-LIMIT

#### Scenario: SolidWorks interop DLL 主动检查

- **WHEN** 检查 SolidWorks interop DLL 可达性
- **THEN** SHALL 验证 4 个 DLL 全部存在：
  - SolidWorks.Interop.sldworks.dll
  - SolidWorks.Interop.swconst.dll
  - SolidWorks.Interop.swpublished.dll
  - SolidWorks.Interop.swcommands.dll
- **AND** 路径与 csproj HintPath 一致
- **AND** 若路径不一致，**主动更新 csproj HintPath**

#### Scenario: Docker 服务主动健康检查

- **WHEN** 执行 `docker ps` 与 `docker-compose ps`
- **THEN** SHALL 验证 postgres / redis / qdrant / ollama 容器健康
- **AND** 验证端口映射（5433/6379/6333/11434）可达
- **AND** 若服务未启动，**主动执行 `docker-compose up -d`** 启动
- **AND** 若镜像缺失，**主动执行 `docker-compose pull`** 拉取

### Requirement: 问题修复与完善

系统 SHALL 针对测试中发现的问题进行修复，优先 P0，次 P1，P2 视情况。

#### Scenario: P0 问题修复

- **WHEN** 测试中发现 P0 问题（阻塞性 bug）
- **THEN** SHALL 立即修复并重新测试
- **AND** 修复需遵循"谨慎重构"原则（最小改动，不破坏架构）

#### Scenario: P1 问题修复

- **WHEN** 测试中发现 P1 问题（影响功能但可降级）
- **THEN** SHALL 修复并记录修复方案
- **AND** 若无法修复，在最终报告中标注并提醒用户

### Requirement: 最终交付报告

系统 SHALL 生成最终交付报告 `backend/tmp_audit_logs/final_acceptance_report.md`，汇总所有测试结果。

#### Scenario: 报告结构

- **WHEN** 报告生成完成
- **THEN** SHALL 包含以下章节：
  1. 头部元信息（测试时间 / 环境 / 服务状态）
  2. Task 8 验证结果（48 项检查点通过率）
  3. 后端 API 真实路径测试结果（端点 × 状态 × 路径类型矩阵）
  4. SolidWorks Worker 真实路径测试结果（模块 × 状态矩阵）
  5. VLM 代码审查结果（模块 × 审查项矩阵）
  6. 依赖项检查结果（依赖 × 状态矩阵）
  7. 问题清单（含 file:line 引用 + 修复状态）
  8. 环境限制清单（ENV-LIMIT 项 + 根因 + 建议）
  9. 结论（PASS / CONDITIONAL_PASS / FAIL）

#### Scenario: 实事求是标注

- **WHEN** 报告生成完成
- **THEN** SHALL 实事求是标注：
  - 真实通过项标为 PASS（基于真实证据）
  - 降级路径项标为 FALLBACK-PATH（明确说明降级原因）
  - 环境限制项标为 ENV-LIMIT（明确说明限制根因）
  - 失败项标为 FAIL（明确说明失败原因 + 修复建议）
- **AND** 不可将 FALLBACK-PATH / ENV-LIMIT / FAIL 标为 PASS

## MODIFIED Requirements

### Requirement: 主项目 Task 8 状态更新

主项目 `d:\SynthDraft\.trae\specs\ai-engineering-design-assistant\tasks.md` 中 Task 8 的状态 SHALL 由"⏸️ 跳过"变更为"✅ 实现"，SubTask 8.1/8.2/8.3/8.4 全部勾选。

#### Scenario: Task 8 状态变更

- **WHEN** Task 8 自检验证通过（通过率 ≥ 90%）
- **THEN** SHALL 在 tasks.md 中将 Task 8 标题由"⏸️ 跳过"变更为"✅ 实现"
- **AND** SubTask 8.1/8.2/8.3/8.4 全部勾选 `[x]`
- **AND** 添加实施日期与实测报告链接

## REMOVED Requirements

无

---

## 后续修复

本 spec 产出的 `final_acceptance_report.md` 总体判定原为 **CONDITIONAL_PASS**，识别了 8 项非阻塞问题。后续通过 `fix-remaining-issues-and-upgrade-to-pass` spec 完成全部修复并升级为 **PASS**：

- **后续修复 spec**: `../fix-remaining-issues-and-upgrade-to-pass/`
- **修复汇总报告**: `backend/tmp_audit_logs/remaining_issues_fix_report.md`
- **最终交付报告**: `backend/tmp_audit_logs/final_acceptance_report.md`（已升级为 PASS）
- **修复项**: SW-04 / SW-05 / SW-06 / VLM-02 / VLM-03 / VLM-04 / P-03 / P-05（8 项全部已修复并通过测试）
