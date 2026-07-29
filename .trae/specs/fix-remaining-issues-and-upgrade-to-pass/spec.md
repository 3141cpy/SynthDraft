# SynthDraft 剩余问题修复与升级到 PASS Spec

## Why

`complete-final-acceptance-and-fix` spec 已完成主体工作并产出 `final_acceptance_report.md`,总体判定为 **CONDITIONAL_PASS**。但报告中识别了 8 项非阻塞问题(SW-04/SW-05/SW-06/VLM-02/VLM-03/VLM-04/P-03/P-05),需修复后才能升级为 **PASS**。本 spec 聚焦于这 8 项问题的修复、重新验证与最终交付报告升级。

用户最新指示再次强调"主动修复原则"——优先启动/配置/安装缺失服务/程序/依赖项,只有超出能力范围才可标注 ENV-LIMIT;并要求"工作深入,不准偷懒",遵循八荣八耻原则。

## 核心执行原则(HARD RULES,不可违反)

1. **主动修复原则**:遇到依赖项/服务缺失,必须优先 `pip install` / `Start-Process` / `docker-compose up -d` 修复,不轻易标注 ENV-LIMIT。
2. **实事求是原则**:每一项修复必须基于真实证据(代码 diff + 重新测试结果 + 文件存在性),不可主观断言已修复。
3. **谨慎重构原则**:遵循最小改动,不破坏现有架构,不创造新接口,复用现有实现。
4. **深入工作原则**:每个修复必须有对应的重新测试,验证修复后真实业务产出正确,而非仅"代码改了"。
5. **诚实无知原则**:超出能力范围的问题(如 SolidWorks 内核 STEP 兼容性)在报告中诚实标注,不掩饰。

## What Changes

### SolidWorks Worker 剩余问题(3 项)

- **SW-04**: CadQuery→STEP→SLDPRT 导入兼容性修复(OCC STEP 与 SolidWorks 导入器不兼容)
  - 修复方案:在 `generate_sldprt_from_cadquery` 中增加 STEP 预处理/降级路径,失败时自动回退到特征重建路径(路径 B);并尝试使用 `ISldWorks::ImportDxfDwgFile` 或在 OpenDoc6 中添加 `swOpenDocOptions_OverrideDefaultTemplate` 标志组合
  - 同时增加 `swDocumentTypes_e.swDocASSEMBLY` 的 STEP 兼容性测试
- **SW-05**: 装配体生成测试样本和测试用例补充
  - 修复方案:构造真实存在的 SLDPRT 组件文件作为 source_file,补充 `_test_sw_writer_assembly.py` 测试脚本,验证 `generate_sldasm_from_components` 的 AddComponent5 + AddMate5 路径
- **SW-06**: 含真实配合的装配体样本补充
  - 修复方案:通过 writer.py 创建含真实配合的装配体样本,然后实测 reader.py 的 `_extract_mates` 路径 2(特征树遍历)与路径 1(GetMates)是否生效

### VLM 模块改进(3 项,P3 改进建议)

- **VLM-02**: 添加图像大小限制检查
  - 修复方案:在 `_encode_image` 中检查图像像素尺寸与文件大小,超过阈值(如 4096×4096 或 10MB)时降采样或拒绝并 log.warning
- **VLM-03**: 添加 VLM 调用重试机制
  - 修复方案:对 `vlm_detect_regions` / `vlm_ocr_extract` / `parse_sketch` 的 provider.chat_with_image 调用添加指数退避重试(最多 3 次,base 1s)
- **VLM-04**: 使用 Pydantic 类型校验结构化输出
  - 修复方案:为 VLM 输出定义 Pydantic 模型(`VLMRegionList` / `VLMOCRResult` / `SketchParseResult` 已存在),在解析后通过 `Model.model_validate` 校验,无效字段记 warning 并丢弃

### 后端 API 剩余问题(2 项)

- **P-03**: LLM 流式终止标记统一为 `[DONE]`
  - 修复方案:在 `llm.py:144` 的 `{"done": true}` 后追加 `data: [DONE]\n\n` 行,与 OpenAI SSE 规范对齐;同时保留原 `{"done": true}` JSON 对象以保持向后兼容
- **P-05**: 添加可观测性告警规则以监控任务长期 reserved 不执行
  - 修复方案:在 `alerts.py::evaluate_queue_alerts` 中新增 `task_stale_reserved` 告警规则——当某队列 `reserved > 0` 且 `active == 0` 且 `worker_count > 0` 时触发(表示 worker 在线但不消费),level=critical

### 验证与报告升级

- 重新执行受影响端点的真实路径测试,确认修复后真实业务产出正确
- 更新 `backend/tmp_audit_logs/final_acceptance_report.md`,将 CONDITIONAL_PASS 升级为 PASS(或诚实标注仍未修复项)

## Impact

- Affected specs:
  - `complete-final-acceptance-and-fix`(更新其 checklist 与最终报告状态)
  - `ai-engineering-design-assistant`(无变更,Task 8 已完成)
- Affected code:
  - `backend/app/services/solidworks/writer.py`(SW-04/SW-05)
  - `backend/app/services/solidworks/reader.py`(SW-06 验证)
  - `backend/app/services/review/vlm_ocr.py`(VLM-02/VLM-03/VLM-04)
  - `backend/app/services/generation/sketch_parser.py`(VLM-03/VLM-04 一致性)
  - `backend/app/api/v1/endpoints/llm.py`(P-03)
  - `backend/app/observability/alerts.py`(P-05)
- Affected docs:
  - 新增 `backend/tmp_audit_logs/remaining_issues_fix_report.md`(本次修复报告)
  - 更新 `backend/tmp_audit_logs/final_acceptance_report.md`(升级到 PASS)
  - 更新 `backend/tmp_audit_logs/solidworks_worker_realtest.md`(SW-04/SW-05/SW-06 复测结果)
  - 更新 `backend/tmp_audit_logs/vlm_code_review.md`(VLM-02/03/04 修复结果)
  - 更新 `backend/tmp_audit_logs/task8_backend_realtest.md`(P-03/P-05 复测结果)
  - 更新 `d:\SynthDraft\.trae\specs\complete-final-acceptance-and-fix\tasks.md`(勾选已完成项)
  - 更新 `d:\SynthDraft\.trae\specs\complete-final-acceptance-and-fix\checklist.md`(勾选已通过项)

## ADDED Requirements

### Requirement: SW-04 CadQuery STEP 导入兼容性修复

系统 SHALL 在 `generate_sldprt_from_cadquery` 中处理 OCC STEP 与 SolidWorks 导入器不兼容的问题,优先尝试修复 STEP 导入,失败时降级到特征重建路径(路径 B)。

#### Scenario: STEP 导入失败时自动降级到特征重建

- **WHEN** CadQuery 生成 STEP 后,`session.open_document(step_path, SW_DOC_PART)` 抛出 `SolidWorksTaskError` 或返回 None(errors=2097152 swDocFileRequiresRepairError)
- **THEN** SHALL 捕获异常,记录 `sw.writer.cadquery.step_import_failed_fallback_to_features` warning
- **AND** 尝试从 CadQuery 代码静态提取特征描述(若可实现)或返回明确的 fallback 信号给调用方
- **AND** 降级路径在 warnings 中明确标注 `path_type=FALLBACK-PATH`

#### Scenario: 尝试 STEP 导入修复(可选路径)

- **WHEN** OpenDoc6 第一次失败
- **THEN** SHALL 尝试使用 `swOpenDocOptions_Silent(2) | swOpenDocOptions_OverrideDefaultTemplate(16)` 标志组合重新调用
- **AND** 若仍失败,尝试调用 `ISldWorks::RepairDocument` API(SolidWorks 2024+)
- **AND** 所有尝试均失败时降级到特征重建路径

### Requirement: SW-05 装配体生成测试样本补充

系统 SHALL 补充装配体生成测试夹具与测试用例,覆盖 `generate_sldasm_from_components` 的 AddComponent5 + AddMate5 路径。

#### Scenario: 装配体生成测试夹具构造

- **WHEN** 准备装配体生成测试
- **THEN** SHALL 通过 `generate_sldprt_from_features` 生成至少 2 个真实存在的 SLDPRT 组件文件(如 cube.SLDPRT 与 shaft.SLDPRT)
- **AND** 构造 `SWComponent` 列表(含 path / position / orientation)
- **AND** 构造 `SWMate` 列表(含 mate_type / component_a / component_b / references)

#### Scenario: 装配体生成实测

- **WHEN** 调用 `generate_sldasm_from_components(session, components, mates, output_path)`
- **THEN** SHALL 验证生成的 SLDASM 文件存在且 size > 0
- **AND** 验证 AddComponent5 至少成功调用 N 次(N=组件数)
- **AND** 验证 AddMate5 至少成功调用 M 次(M=配合数)
- **AND** 标注路径类型为 REAL-PATH 或 FALLBACK-PATH(若 AddMate5 失败但 AddComponent5 成功)

### Requirement: SW-06 含真实配合的装配体样本补充

系统 SHALL 通过 writer.py 创建含真实配合的装配体样本,验证 reader.py `_extract_mates` 的两条路径均能正确提取配合。

#### Scenario: 含配合装配体样本创建

- **WHEN** 准备 reader 测试夹具
- **THEN** SHALL 通过 `generate_sldasm_from_components` 创建一个含至少 2 个组件 + 1 个重合配合 + 1 个同轴心配合的 SLDASM 样本
- **AND** 验证样本文件存在且 size > 10KB

#### Scenario: 配合提取实测

- **WHEN** 调用 `read_sldasm(session, sample_path)`
- **THEN** SHALL 验证返回结果中 `mates` 数组非空
- **AND** 验证每个 mate 含 `name` / `mate_type` / `component_a` / `component_b` 字段
- **AND** 验证路径 1(GetMates)或路径 2(特征树遍历)至少一条生效
- **AND** 标注路径类型为 REAL-PATH

### Requirement: VLM-02 图像大小限制检查

系统 SHALL 在 `_encode_image` 中检查图像尺寸,防止超大图像导致 VLM 调用超时或内存溢出。

#### Scenario: 图像尺寸超阈值时降采样

- **WHEN** 读取图像后,任一维度 > 4096 像素 或 文件大小 > 10MB
- **THEN** SHALL 调用 `image_preprocess.preprocess_image` 或 Pillow 降采样到 4096×4096 以内
- **AND** log.warning `review.vlm.image_too_large_resized` 记录原始尺寸与降采样后尺寸
- **AND** 继续后续 VLM 调用(降采样后的图像)

#### Scenario: 图像尺寸正常时直接编码

- **WHEN** 图像尺寸 ≤ 4096×4096 且文件大小 ≤ 10MB
- **THEN** SHALL 直接 base64 编码,不触发降采样
- **AND** 无 warning 日志

### Requirement: VLM-03 VLM 调用重试机制

系统 SHALL 对 VLM 调用添加指数退避重试,提升 VLM 不可用时的容错能力。

#### Scenario: VLM 调用失败时重试

- **WHEN** `provider.chat_with_image()` 抛出异常(httpx.ConnectError / httpx.ReadTimeout / HTTPStatusError 5xx)
- **THEN** SHALL 在 1s / 2s / 4s 间隔后重试,最多 3 次
- **AND** 每次重试 log.warning `review.vlm.retry` 记录 attempt / error
- **AND** 全部重试失败后返回空结果(vlm_detect_regions 返回 [],vlm_ocr_extract 返回 {})

#### Scenario: VLM 调用成功时不重试

- **WHEN** `provider.chat_with_image()` 首次调用成功
- **THEN** SHALL 直接返回结果,不触发重试
- **AND** 无重试日志

### Requirement: VLM-04 Pydantic 类型校验结构化输出

系统 SHALL 使用 Pydantic 模型对 VLM 输出做类型校验,丢弃无效字段并 log.warning。

#### Scenario: VLM 输出符合 schema 时通过

- **WHEN** VLM 返回的 JSON 对象符合 `VLMOCRResult` schema(title/drawing_number/material/scale 等字段类型正确)
- **THEN** SHALL 通过 `VLMOCRResult.model_validate()` 校验
- **AND** 返回校验后的 dict(保持向后兼容)

#### Scenario: VLM 输出字段类型错误时丢弃

- **WHEN** VLM 返回的 JSON 中某字段类型错误(如 `dimensions` 为字符串而非数组)
- **THEN** SHALL 通过 Pydantic `model_validate` 抛出 `ValidationError`
- **AND** 捕获异常,log.warning `review.vlm.output_schema_violation` 记录错误详情
- **AND** 丢弃无效字段,保留有效字段(或返回空 dict)

### Requirement: P-03 LLM 流式终止标记统一为 [DONE]

系统 SHALL 在 LLM 流式响应末尾追加 OpenAI 风格的 `data: [DONE]` 行,同时保留原 `{"done": true}` JSON 对象以保持向后兼容。

#### Scenario: 流式正常结束

- **WHEN** LLM 流式响应正常结束
- **THEN** SHALL 先发送 `data: {"done": true, "request_id": "..."}\n\n`
- **AND** 紧接着发送 `data: [DONE]\n\n` 行
- **AND** 客户端可通过任一终止标记判断流结束

#### Scenario: 流式被取消或超时

- **WHEN** 流式被取消(StreamCancelled)或超时(StreamTimeout)
- **THEN** SHALL 发送对应的 cancelled / error JSON 事件
- **AND** 紧接着发送 `data: [DONE]\n\n` 行作为统一终止标记

### Requirement: P-05 可观测性告警规则补充

系统 SHALL 在 `alerts.py::evaluate_queue_alerts` 中新增 `task_stale_reserved` 告警规则,监控"任务长期 reserved 不执行"场景。

#### Scenario: 任务 reserved 但无 active 时告警

- **WHEN** 某队列 `reserved > 0` 且 `active == 0` 且 `worker_count > 0`
- **THEN** SHALL 触发 `task_stale_reserved` 告警
- **AND** level=critical(表示 worker 在线但不消费,疑似卡死)
- **AND** message 含队列名 / reserved 数 / worker_count

#### Scenario: 队列正常消费时不告警

- **WHEN** 某队列 `reserved > 0` 且 `active > 0`(正在消费)
- **THEN** SHALL 不触发 `task_stale_reserved` 告警
- **AND** 可能触发 `queue_backlog` 告警(若 backlog 超阈值)

### Requirement: 修复后重新验证与报告升级

系统 SHALL 对所有修复项重新执行真实路径测试,并更新最终交付报告。

#### Scenario: 修复后重新测试

- **WHEN** 所有 8 项修复完成
- **THEN** SHALL 对每项修复重新执行对应的真实路径测试
- **AND** 记录修复前/后对比证据(状态码 / 文件存在性 / 业务产出)
- **AND** 修复失败项如实标注,不混入 PASS

#### Scenario: 最终报告升级

- **WHEN** 所有可修复项均已修复并重新测试
- **THEN** SHALL 更新 `final_acceptance_report.md` 的总体判定
- **AND** 若所有 FAIL/ENV-LIMIT 项已修复,升级为 PASS
- **AND** 若仍有未修复项(如超出能力范围),保持 CONDITIONAL_PASS 并明确说明剩余项根因与建议

## MODIFIED Requirements

### Requirement: 最终交付报告状态更新

`backend/tmp_audit_logs/final_acceptance_report.md` SHALL 更新以下章节:
- 第六章问题清单:将已修复项从"未修复"移到"已修复",附修复方案与重新测试证据
- 第七章环境限制清单:更新 ENV-LIMIT 项数量(若有变化)
- 第九章结论:更新总体判定与升级路径

## REMOVED Requirements

无
