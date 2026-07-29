# 彻底补救剩余未正确测试项 Spec

## Why

上一轮 `remediate-audit-gaps-retest` spec 声称"9 项敷衍全部补救完成、最终验收 PASS",但经逐文件核查证据发现仍存在 **5 项未正确测试/误判 PASS** 的敷衍问题,以及 **2 项已诚实标注但需进一步处理** 的限制项。这违反了"以跳过验证为耻,以主动测试为荣;以假装理解为耻,以诚实无知为荣"原则。本 spec 旨在彻底补救所有剩余未正确测试项,确保每一项验收基于真实证据,不可主观断言或误判 PASS。

## 经核查发现的剩余敷衍/未测试项

### A. 误判 PASS 类(标称 PASS 但实际未真正验证)

1. **草图 VLM 尺寸幻觉误判 PASS**(证据 `tmp_audit_logs/10_sketch_real.md`)
   - 输入草图描述:"带孔圆盘:外圆 φ100 + 中心孔 φ20 + 厚度 10mm"
   - VLM 实际返回:`parameters={'radius': 10, 'thickness': 2}`(radius 应为 50,thickness 应为 10,**偏差 5-10 倍**)
   - VLM 返回 bbox=`[0.35, 0.4, 0.85, 0.7]` 疑似 `[x1,y1,x2,y2]` 格式而非 `[x,y,w,h]`,且 0.85+0.4>1.0 越界但未被 `_normalize_bbox` 钳制
   - 测试报告却标 **PASS**,仅检查"VLM 返回非空",未校验尺寸语义正确性
   - 这是典型敷衍:把"返回了 JSON"等同于"语义正确"

2. **HTML 报告模板未渲染 vlm_ocr_extras**(证据 `tmp_audit_logs/22_review_vlm_retest.md`)
   - VLM OCR 真实提取了 `title="SynthDraft Sample"` + `dimensions=[...]` 字段并注入语义模型
   - 但 HTML 报告(29627 bytes)中**搜索这些字段值返回空**——模板未渲染 `vlm_ocr_extras`
   - 测试报告标 PASS 并附"已知模板限制,非阻塞性"——但用户视角看,VLM OCR 数据对最终用户完全不可见
   - 这是"功能闭环未真正打通"的敷衍:数据采集了但未到达用户

3. **apply_multi_turn_edit 真实 LLM 路径未单独验证**(核查 `tests/verify_task5_e2e.py`)
   - verify_task5_e2e.py 步骤 7 调用了 `apply_multi_turn_edit`,但该测试在 pytest 回归中可能因 LLM 不可用走正则降级路径
   - 无单独的 audit log 记录"真实 LLM 路径下 apply_multi_turn_edit 生效且 mode=llm"
   - 无法区分"LLM 真实修改代码"与"正则字符串替换"两条路径

4. **DeepSeek 远程 LLM 仅做隔离 chat 测试,未走全链路**(证据 `tmp_audit_logs/13_llm_switch.md`)
   - 13_llm_switch.md 仅测试了 `provider.chat()` + 隔离的 `generate_cadquery_code("立方体 10mm")`
   - 未测试"缺陷 → prompt → DeepSeek 生成 → 沙箱执行 → STEP 产出"全链路
   - 远程 LLM 在协同闭环中的真实可用性未验证

### B. 已诚实标注但需进一步处理项

5. **远程 VLM API 真实调用未测试**(证据 `tmp_audit_logs/14_vlm_switch.md`)
   - OpenAI/Anthropic 在无 Key 时返回空列表是降级路径,非真实 API 调用
   - 上一轮已诚实标注"本地 VLM PASS,远程待补"
   - 用户原话"后续再增加 API 类的测试"——本轮需明确处理:或补做(若有 Key),或正式声明为延后项

6. **DWG 路径未测试 + embedding 质量未对比**(证据 `23_dwg_path.md` / `24_embedding_compare.md`)
   - 已诚实标注为"未测试/未对比",不再用 CONDITIONAL_PASS 模糊处理
   - 本轮需尝试更进一步的安装/对比路径,或正式声明为环境限制不再补救

### C. 文档一致性问题

7. **tasks.md 与 checklist.md 状态不同步**(核查 `remediate-audit-gaps-retest/tasks.md`)
   - tasks.md 中 Task 1/4/5/7/8/9 仍标 `[ ]` 未完成
   - 但 checklist.md 中所有项已打勾并附真实证据
   - 这是文档敷衍:声称做完了但 tasks.md 未同步更新

## What Changes

- **修复草图 VLM 尺寸校验**:在 `sketch_parser.py` 或测试脚本中增加 VLM 返回尺寸与草图描述尺寸的语义对比校验,偏差超阈值时标 FAIL 而非 PASS
- **修复 HTML 报告模板渲染 vlm_ocr_extras**:在审图 HTML 模板中增加 VLM OCR 字段渲染区块,确保 `title`/`drawing_number`/`material`/`scale`/`dimensions` 等字段对用户可见
- **补做 apply_multi_turn_edit 真实 LLM 路径测试**:在 LLM 可用环境下单独执行 `apply_multi_turn_edit`,记录 `mode=llm` 与代码实际变更,产出独立 audit log
- **补做 DeepSeek 全链路协同闭环测试**:用 DeepSeek 作为 LLM_PROVIDER 重跑协同闭环 E2E(缺陷 → prompt → LLM → 沙箱 → STEP),验证远程 LLM 在完整管线中的可用性
- **远程 VLM API 处理**:询问用户是否有可用 VLM API Key;若有则补做真实调用测试,若无则正式声明为延后项并标注原因
- **DWG/embedding 进一步尝试**:尝试 ODA File Converter 下载安装或 alternative 方案;尝试 FlagEmbedding 离线安装或 alternative embedding 对比;若仍不可得则正式声明为环境限制
- **同步 tasks.md 与 checklist.md**:把 `remediate-audit-gaps-retest/tasks.md` 中已完成项打勾,与 checklist.md 一致
- **更新 audit_report.md**:基于本轮补救结果再次修正结论,补登"第二轮敷衍补救对照表"

## Impact

- Affected specs: `remediate-audit-gaps-retest`(tasks.md 同步 + audit_report.md 二次修正)
- Affected code:
  - `app/services/review/report_generator.py` 或 HTML 模板文件(渲染 vlm_ocr_extras)
  - `app/services/sketch/sketch_parser.py` 或对应测试脚本(尺寸语义校验)
  - 可能涉及 `app/services/generation/code_generator.py`(若多轮修改需调整)
- Affected docs: `audit_report.md` / `checklist.md` 基于真实证据二次修正
- 测试样本: 草图测试需准备已知尺寸的样本(外圆 φ100 + 中心孔 φ20 + 厚度 10mm)

## ADDED Requirements

### Requirement: 草图 VLM 尺寸语义校验

系统 SHALL 在草图 VLM 测试中,对 VLM 返回的 `parameters` 字段做语义正确性校验,不可仅因"返回了 JSON"即标 PASS。

#### Scenario: 草图 VLM 返回尺寸与描述偏差超阈值

- **WHEN** 输入草图描述为"外圆 φ100 + 中心孔 φ20 + 厚度 10mm"
- **AND** VLM 返回 `parameters={'radius': 10, 'thickness': 2}`(radius 偏差 5 倍, thickness 偏差 5 倍)
- **THEN** 测试 SHALL 标记为 **FAIL**,记录实际值与期望值的偏差比例
- **AND** 不可仅因"VLM 返回非空"即标 PASS
- **AND** 需在 audit log 中明确说明:VLM 对草图尺寸识别存在严重幻觉,不可用于生产

#### Scenario: 草图 VLM bbox 格式与归一化校验

- **WHEN** VLM 返回 bbox=`[0.35, 0.4, 0.85, 0.7]`(疑似 `[x1,y1,x2,y2]` 格式而非 `[x,y,w,h]`)
- **AND** `0.85 + 0.4 > 1.0` 越界
- **THEN** 测试 SHALL 验证 `_normalize_bbox` 函数正确钳制或转换该 bbox
- **AND** 若 `_normalize_bbox` 未正确处理该格式,需标 FAIL 并定位根因

### Requirement: HTML 报告渲染 VLM OCR 字段

系统 SHALL 在审图 HTML 报告中渲染 `vlm_ocr_extras` 字段,确保 VLM OCR 提取的语义信息对最终用户可见。

#### Scenario: VLM OCR 字段在 HTML 报告中可见

- **WHEN** 调用 `generate_review_report()` 生成 HTML 报告
- **AND** 语义模型中 `vlm_ocr_extras` 非空(含 `title` / `dimensions` 等字段)
- **THEN** HTML 报告中 SHALL 包含 "VLM OCR 识别结果" 区块
- **AND** 该区块 SHALL 显示所有非空的 `vlm_ocr_extras` 字段值
- **AND** 不可标"已知模板限制,非阻塞性"即视为 PASS——数据对用户不可见即功能未闭环

### Requirement: apply_multi_turn_edit 真实 LLM 路径验证

系统 SHALL 在 LLM 可用环境下单独验证 `apply_multi_turn_edit` 走真实 LLM 路径,不可与正则降级路径混淆。

#### Scenario: 真实 LLM 多轮修改代码

- **WHEN** LLM 可用(`is_llm_available()` 返回 True)
- **AND** 调用 `apply_multi_turn_edit(original_code, "把外径改为120mm, 孔数改为8", history)`
- **THEN** 测试 SHALL 验证返回的 `new_code` 与 `original_code` 不同
- **AND** 需在 audit log 中记录:LLM 模型名、推理耗时、修改前后代码 diff
- **AND** 不可仅依赖 verify_task5_e2e.py 的混合路径测试结果

### Requirement: DeepSeek 远程 LLM 全链路协同闭环验证

系统 SHALL 使用 DeepSeek 作为 LLM_PROVIDER 重跑协同闭环 E2E,验证远程 LLM 在完整管线中的可用性。

#### Scenario: DeepSeek 驱动协同闭环产出真实文件

- **WHEN** 设置 `LLM_PROVIDER=openai` + `OPENAI_BASE_URL=https://api.deepseek.com` + `OPENAI_MODEL=deepseek-chat` + 有效 API Key
- **AND** 输入 3 条真实审图缺陷(尺寸/粗糙度/标题栏)
- **THEN** 系统 SHALL 走 `defects_to_optimization_prompt` → `generate_cadquery_code`(DeepSeek) → `execute_cadquery_code` → 真实 STEP/DXF 产出
- **AND** 需记录 mode(llm/template)、LLM 推理耗时、沙箱执行 exit_code、产出文件 size/volume
- **AND** 产出真实 `revised.step`(volume > 0) + `revised.dxf`(entity_count > 0)
- **AND** 不可仅因 13_llm_switch.md 的隔离 chat 测试通过即认为 DeepSeek 在全链路可用

### Requirement: 远程 VLM API 真实调用或正式声明延后

系统 SHALL 对远程 VLM API 真实调用做出明确处理:或补做真实测试,或正式声明为延后项并标注原因。

#### Scenario: 有 VLM API Key 时补做真实调用

- **WHEN** 用户提供了 OpenAI gpt-4o / 通义千问 VL / 其他 OpenAI 兼容 VLM API Key
- **THEN** 系统 SHALL 切换 `LLM_PROVIDER` + `OPENAI_VLM_MODEL` 调用真实远程 VLM
- **AND** 验证 `chat_with_image()` 返回非空、`vlm_detect_regions()` 返回语义正确区域
- **AND** 产出独立 audit log 记录真实远程调用证据

#### Scenario: 无 VLM API Key 时正式声明延后

- **WHEN** 用户确认无可用 VLM API Key
- **THEN** audit_report.md SHALL 明确声明"远程 VLM API 真实调用测试延后,原因:无可用 API Key"
- **AND** 不可再标"本地 VLM PASS,远程待补"等模糊表述——需明确为延后项 + 阻塞性评估

### Requirement: DWG/embedding 限制项进一步尝试或正式声明

系统 SHALL 对 DWG 路径与 embedding 质量对比做出进一步尝试,若仍不可得则正式声明为环境限制。

#### Scenario: DWG 路径进一步尝试

- **WHEN** 尝试下载/安装 ODA File Converter 或 alternative DWG 转换方案
- **THEN** 若成功:补做真实 DWG → DXF 转换测试
- **AND** 若失败:audit_report.md 明确声明"DWG 路径未测试,原因:ODA File Converter 安装失败 + 无 alternative 方案"

#### Scenario: embedding 质量对比进一步尝试

- **WHEN** 尝试 FlagEmbedding 离线安装或 alternative embedding 模型(如 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`)
- **THEN** 若成功:对比 bge-m3/alternative vs nomic-embed-text 在同一查询下的 top-5 重叠度
- **AND** 若失败:audit_report.md 明确声明"embedding 质量对比未做,原因:FlagEmbedding 安装失败 + 无 alternative 模型"

### Requirement: tasks.md 与 checklist.md 状态同步

系统 SHALL 把 `remediate-audit-gaps-retest/tasks.md` 中已完成项打勾,与 checklist.md 状态一致。

#### Scenario: tasks.md 同步打勾

- **WHEN** `remediate-audit-gaps-retest/checklist.md` 中某 Task 所有 checkpoint 已打勾且有真实证据
- **THEN** `remediate-audit-gaps-retest/tasks.md` 中对应 Task SHALL 标 `[x]` 完成
- **AND** 不可出现 tasks.md 标 `[ ]` 但 checklist.md 全打勾的不一致状态

## MODIFIED Requirements

### Requirement: audit_report.md 最终验收结论

[原要求] 第一轮 remediate 后 audit_report.md 标"总体 PASS(含明确环境限制清单)"

[修改为] 第二轮补救完成后,audit_report.md SHALL 基于本轮真实证据再次修正:
- 补登"第二轮敷衍补救对照表"(含本 spec 7 项的处理结果)
- 若所有项已补救至真实 PASS 或正式声明延后,可保留总体 PASS
- 若仍有误判 PASS 项,必须降级为 CONDITIONAL_PASS 并列出阻塞项
- 不可使用"PASS(带样本限制)"等过度宽容表述

## REMOVED Requirements

### Requirement: 把"VLM 返回非空"等同于"VLM 语义正确"

**Reason**: 10_sketch_real.md 把 VLM 返回 `radius=10`(期望 50) 标 PASS,这是把"返回了 JSON"等同于"语义正确"。VLM 测试必须校验返回值的语义正确性,不可仅因非空即 PASS。

**Migration**: 所有 VLM 测试 SHALL 增加语义校验环节,对关键字段(尺寸/类型/区域名)做期望值对比。

### Requirement: 把"数据已注入语义模型"等同于"用户可见"

**Reason**: 22_review_vlm_retest.md 把 VLM OCR 数据注入语义模型标 PASS,但 HTML 报告未渲染这些字段,用户实际看不到。这是把"数据采集"等同于"功能闭环"。功能闭环必须验证数据到达最终用户。

**Migration**: 所有涉及用户可见输出的测试 SHALL 验证数据在最终产出(HTML/PDF/API 响应)中可见,不可仅因中间层数据存在即 PASS。
