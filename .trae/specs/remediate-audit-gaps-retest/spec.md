# 审计敷衍问题补救与重新测试 Spec

## Why

上一轮 spec `audit-p0p1-and-extend-ai-providers` 在 audit_report.md 中标称"总体 PASS",但经诚实复盘发现 9 项敷衍问题:包括把实测 FAIL 的协同闭环沙箱执行(步骤 3 LLM 幻觉导致 exit_code=1, files=[])包装成 PASS、用登机牌图片测试工程图区域检测、把"降级路径验证"美化成"远程 VLM 切换 PASS"、修复后未重跑原始失败场景等。这违反了"以跳过验证为耻,以主动测试为荣;以假装理解为耻,以诚实无知为荣"原则。本 spec 旨在补救所有敷衍项,基于真实证据重新出具验收结论。

## What Changes

- **重跑协同闭环 E2E(修复后)**: 验证 `_is_valid_llm_code` 修复后,LLM 幻觉代码被拦截降级到 template,沙箱能产出真实 revised.step / revised.dxf(非模拟数据)
- **重跑 VLM 区域检测(真实工程图样本)**: 替换登机牌图片为真实工程图 PNG,验证 VLM 返回的 title_block / dimension_area / view_area / parts_list 区域名语义正确
- **补做审图 E2E 真实 VLM 路径**: VLM 可用后重跑审图 E2E,验证 VLM OCR 字段真实填充到语义模型(非空)
- **重跑装配体 E2E 确认 P3 修复生效**: 验证 `_has_concentric_axis_hole_exception` 修复后,concentric mate 的 bolt-flange 装配不再被 AABB 误报为干涉
- **启动真实 FastAPI 服务验证健康检查端点**: 用 uvicorn 启动 + curl/requests 真实 HTTP 调用 /healthz,验证 asyncio.to_thread 在真实 ASGI 环境下正常调度
- **CAD DWG 路径测试或明确标注未测试**: 尝试安装 ODA File Converter;若不可得,在 audit_report 中明确标注 DWG 路径未测试而非 CONDITIONAL_PASS
- **KB RAG embedding 质量对比**: 安装 FlagEmbedding(bge-m3),对比 bge-m3 vs nomic-embed-text 在同一查询下的 top-k 结果重叠度
- **修正 audit_report.md**: 把所有"假 PASS"改为基于真实证据的结论(PASS / CONDITIONAL_PASS / FAIL),补登敷衍问题清单与补救结果
- **远程 VLM API 真实测试(可选)**: 用户原话"V多模态/视觉模型暂时先拉取并测试本地模型 后续再增加API类的测试"——本项标为可选,若有 OpenAI gpt-4o 或 Anthropic Claude API Key 则补做

## Impact

- Affected specs: `audit-p0p1-and-extend-ai-providers`(audit_report.md 需修正)
- Affected code: 无源码修改(除非补救测试发现新 bug)
- Affected docs: `audit_report.md` / `checklist.md` 需基于真实证据修正结论
- 测试样本: 需准备真实工程图 PNG(替换登机牌图片)

## ADDED Requirements

### Requirement: 敷衍项补救与真实证据验收

系统 SHALL 对上一轮审计中标称 PASS 但实际未真正测试的 9 项敷衍问题进行补救,每项必须基于真实证据(日志+产出文件+截图)重新出具结论,不可主观断言。

#### Scenario: 协同闭环沙箱执行产出真实文件

- **WHEN** 重跑 SubTask 4.4 协同闭环 E2E(修复 `_is_valid_llm_code` 后)
- **THEN** 必须验证以下三种情况之一:
  - 情况 A: LLM 生成合法代码 → 沙箱执行成功 → 产出真实 revised.step / revised.dxf → STEP 体积非零 → DXF 实体数 > 0
  - 情况 B: LLM 生成幻觉代码 → `_is_valid_llm_code` 拦截 → 降级到 template_match_generate → 沙箱执行成功 → 产出真实文件
  - 情况 C: LLM 与 template 均失败 → 明确标 FAIL 并定位根因
- **AND** 不可使用模拟数据生成 diff_report 后宣称 PASS

#### Scenario: VLM 区域检测使用真实工程图样本

- **WHEN** 用真实工程图 PNG(含标题栏/标注区/视图区/明细栏)重跑 SubTask 4.1
- **THEN** VLM 返回的区域名必须包含至少 2 个语义正确的类别(如 title_block / dimension_area / view_area / parts_list)
- **AND** OCR 提取的字段必须包含至少 1 个语义正确的工程图字段(如图号 / 比例 / 材料 / 日期)
- **AND** 不可用登机牌等非工程图样本测试后宣称 PASS

#### Scenario: 装配体 interference 修复验证

- **WHEN** 重跑 SubTask 4.3 装配体 E2E(修复 `_has_concentric_axis_hole_exception` 后)
- **THEN** `validate_assembly.is_valid` 必须为 True(或 interference 维度 PASS)
- **AND** concentric mate 的 bolt-flange 装配不再被 AABB 误报为干涉
- **AND** 需构造非共线 Port 场景验证非平凡变换分支(可选,若构造困难可标注)

#### Scenario: 真实 FastAPI 服务健康检查

- **WHEN** 用 uvicorn 启动 FastAPI 服务(非 TestClient)
- **THEN** curl/requests 调用 `GET /api/v1/healthz` 必须返回 200
- **AND** 响应包含 `llm_provider` / `llm_available` / `vlm_available` 字段
- **AND** asyncio.to_thread 在真实 ASGI 环境下正常调度(无超时 / 无阻塞)

#### Scenario: audit_report 基于真实证据修正

- **WHEN** 所有补救测试完成
- **THEN** audit_report.md 必须基于真实证据修正所有"假 PASS"结论
- **AND** 必须包含敷衍问题清单与补救结果对照表
- **AND** 不可再使用"PASS(带样本限制)"等过度宽容表述

## MODIFIED Requirements

### Requirement: 依赖项缺失治理

[原要求] 12 个第三方包在代码中直接 import 但未在 requirements.txt 声明

[修改为] 12 个缺失包必须按优先级处理:
- 🔴 高危 6 个(cadquery / weasyprint / paddleocr / paddlepaddle / openpyxl / ultralytics): 必须在 requirements.txt 追加声明,或在 audit_report 明确标注"未声明但已识别"
- 🟡 中危 4 个(numpy / Pillow / matplotlib / Jinja2): 显式声明
- 🟢 低危 2 个(pythonocc-core / FreeCAD): 标注为可选

### Requirement: 环境限制诚实标注

[原要求] 9 项环境限制均标为"非阻塞"

[修改为] 环境限制必须按真实影响分级:
- 阻塞性: DWG 路径未测试 / 协同闭环沙箱未产出真实文件 / VLM 区域检测样本非工程图
- 非阻塞性: WeasyPrint PDF 降级 / embedder 降级 / Anthropic SDK 未装 / SolidWorks 真实环境未接入

## REMOVED Requirements

### Requirement: 把"降级路径验证"等同于"切换验证 PASS"

**Reason**: 上一轮 audit_report 把 OpenAI/Anthropic 无 Key 时返回空列表的降级路径标为"远程视觉 VLM 切换验证 PASS",这是过度美化。降级路径只能验证"无 Key 时不抛异常",不能验证"远程 VLM API 真实可用"。

**Migration**: 远程 VLM API 真实测试改为可选任务(若有 API Key 则补做,否则明确标注"未做真实远程 VLM API 测试")。
