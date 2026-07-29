# VLM 尺寸幻觉误判修复 + DeepSeek 全链路协同闭环重测 Spec

## Why

上一轮 `audit-p0p1-and-extend-ai-providers` 的 SubTask 4.2（草图转 CAD 真实 VLM 路径测试）在 `tmp_audit_logs/10_sketch_real.md` 中标称 PASS，但其 PASS 判据仅是"VLM 返回非空 features"，未校验尺寸语义正确性。实际复测发现：VLM 返回 `parameters={'radius': 10, 'thickness': 2}`，而草图标注期望 `radius=50, thickness=10`，偏差高达 5 倍。这违反"以假装理解为耻、以诚实无知为荣；以跳过验证为耻、以主动测试为荣"原则，必须重测并基于真实尺寸偏差重新出具结论。

同时，`audit-p0p1-and-extend-ai-providers` 的 SubTask 5.1（远程文本 LLM 切换验证）虽验证了 DeepSeek provider 可切换且 `generate_cadquery_code()` 返回 `mode=llm`，但仅做了"单步生成代码"层面的验证，未走完整协同闭环（缺陷输入 → prompt 生成 → 代码生成 → 沙箱执行 → 文件校验）。需要补做 DeepSeek 全链路协同闭环验证，确认远程 LLM 在端到端流程中真实可用且产出真实文件。

## What Changes

- **Task 1: 修复草图 VLM 尺寸幻觉误判 PASS**
  - 重跑 `parse_sketch()` 真实 VLM 推理（minicpm-v:latest）
  - 校验 VLM 返回尺寸与草图标注期望值的偏差比例
  - 重新定义 PASS 判据：偏差 < 10% PASS / 10%~2倍 WARN / >2倍 FAIL（基于 max(actual/expected, expected/actual) 倍数判别）
  - 分析 bbox 格式（[x1,y1,x2,y2] vs [x,y,w,h]）以排查 `_normalize_bbox` 误判
  - 输出 `tmp_audit_logs/27_sketch_vlm_dimension_retest.md`

- **Task 4: DeepSeek 远程 LLM 全链路协同闭环验证**
  - 读取 `.env` 中的 DeepSeek API Key（sk-7fc861488a2742ec9e139bdfea894be1, base_url=https://api.deepseek.com, model=deepseek-chat）
  - 设置 `LLM_PROVIDER=openai` + `OPENAI_BASE_URL` + `OPENAI_MODEL` + `OPENAI_API_KEY`，重置 provider cache
  - 准备 3 条真实审图缺陷输入（尺寸标注/表面粗糙度/标题栏）
  - 调用 `defects_to_optimization_prompt()` 生成 prompt
  - 调用 `generate_cadquery_code()` 记录 mode（应为 `llm`）+ 推理耗时
  - 调用 `generate_and_execute_with_fallback()` 走完整协同闭环
  - 验证 `revised.step` 体积 > 0 + `revised.dxf` 实体数 > 0
  - 对比 DeepSeek vs Ollama（13_llm_switch.md）的推理耗时与代码质量
  - 恢复环境（清空 DeepSeek 环境变量，重置 provider cache）
  - 输出 `tmp_audit_logs/28_deepseek_full_pipeline.md`

## Impact

- **Affected specs**:
  - `audit-p0p1-and-extend-ai-providers`（SubTask 4.2 的 PASS 结论需基于真实尺寸偏差重新评估；SubTask 5.1 的 DeepSeek 验证需扩展为全链路协同闭环）
  - `remediate-audit-gaps-retest`（Task 1 协同闭环已基于 ollama 修复，本 spec 补做 DeepSeek 远程侧的全链路）
- **Affected code**: 无源码修改（除非重测发现新 bug 需修复）
- **Affected docs**:
  - `tmp_audit_logs/10_sketch_real.md`（旧 PASS 结论需在 27 号文档中基于真实证据修正）
  - `tmp_audit_logs/13_llm_switch.md`（旧 LLM 切换 PASS 需在 28 号文档中扩展为全链路协同闭环 PASS）
- **依赖环境**:
  - 本地 Ollama 已运行（localhost:11434），minicpm-v:latest 已拉取
  - DeepSeek API Key 可用（sk-7fc861488a2742ec9e139bdfea894be1）
  - Python 虚拟环境：`d:\SynthDraft\backend\.venv\Scripts\python.exe`
- **测试样本**: 合成草图 PNG（外圆 φ100 + 中心孔 φ20 + 厚度 10mm，与上一轮一致以便复现历史问题）

## ADDED Requirements

### Requirement: VLM 尺寸语义真实校验

系统 SHALL 在草图 VLM 解析路径中，对 VLM 返回的尺寸参数（如 radius/thickness/diameter）与草图标注的期望值进行真实偏差校验，不可仅以"返回非空"作为 PASS 判据。

#### Scenario: VLM 返回尺寸偏差在容差范围内

- **WHEN** VLM 解析草图后返回 `parameters={'radius': R, 'thickness': T}`
- **AND** 草图标注期望 `radius=R_exp, thickness=T_exp`
- **THEN** 偏差比例 `max(R/R_exp, R_exp/R)` 与 `max(T/T_exp, T_exp/T)` 必须 < 10% 才能标 PASS
- **AND** 偏差在 10%~2倍之间标 WARN（需在 audit log 中记录原因）
- **AND** 偏差 > 2倍标 FAIL（必须给出根因分析：VLM 推理错误 / bbox 格式误判 / 单位换算错误）

#### Scenario: bbox 格式误判排查

- **WHEN** VLM 返回 bbox（4 元素列表）
- **THEN** 必须分析 bbox 是 `[x1,y1,x2,y2]` 还是 `[x,y,w,h]` 格式
- **AND** 若视为 `[x,y,w,h]` 时 `x+w > 1` 或 `y+h > 1` 越界，则判为 `[x1,y1,x2,y2]` 格式
- **AND** 必须记录 `_normalize_bbox` 对该 bbox 的处理结果，确认无错误截断

#### Scenario: PASS 判据诚实化

- **WHEN** 上一轮 `10_sketch_real.md` 标 PASS 仅因 features 非空
- **THEN** 必须在新 audit log（27 号）中明确标注旧判据不充分
- **AND** 基于真实尺寸偏差重新出具 PASS / WARN / FAIL 结论
- **AND** 不可再以"返回非空"作为唯一 PASS 判据

### Requirement: DeepSeek 远程 LLM 全链路协同闭环

系统 SHALL 在 DeepSeek 远程 LLM 配置下，走完整协同闭环（缺陷输入 → prompt 生成 → 代码生成 → 沙箱执行 → 文件校验），并产出真实 revised.step / revised.dxf 文件，不可仅做单步代码生成验证。

#### Scenario: DeepSeek provider 切换并可用

- **WHEN** 设置 `LLM_PROVIDER=openai` + `OPENAI_BASE_URL=https://api.deepseek.com` + `OPENAI_MODEL=deepseek-chat` + `OPENAI_API_KEY=sk-...`
- **AND** 重置 `get_settings.cache_clear()` 与 `reset_provider_cache()`
- **THEN** `get_llm_provider()` 返回的 provider 类必须为 `OpenAIProvider`
- **AND** `provider.is_available()` 必须为 True（实测 ping 成功）

#### Scenario: 缺陷到 prompt 转换

- **WHEN** 输入 3 条真实审图缺陷（尺寸标注/表面粗糙度/标题栏）
- **THEN** `defects_to_optimization_prompt()` 必须返回非空 prompt
- **AND** prompt 必须包含 "CadQuery" 代码要求
- **AND** prompt 必须包含至少 1 条规范引用（如 GB/T 131 / GB/T 18229）
- **AND** prompt 长度必须 < 4000 字符

#### Scenario: DeepSeek 生成代码可执行

- **WHEN** 调用 `generate_cadquery_code(prompt)` 在 DeepSeek provider 下
- **THEN** 返回 mode 必须为 `llm`（非 template 降级）
- **AND** 代码必须含 `import cadquery` 声明
- **AND** 代码必须通过 `_is_valid_llm_code` 校验（import + 语法编译）
- **AND** 推理耗时必须记录（用于对比 Ollama）

#### Scenario: 协同闭环产出真实文件

- **WHEN** 调用 `generate_and_execute_with_fallback(prompt, fmt="step")`
- **THEN** 沙箱执行必须 `exit_code=0`
- **AND** 必须产出真实 `revised.step` 文件
- **AND** STEP 文件体积 > 0（用 pythonOCC 重新读取验证）
- **WHEN** 用最终代码再执行 `execute_cadquery_code(code, output_format="dxf")`
- **THEN** 必须产出真实 `revised.dxf` 文件
- **AND** DXF 实体数 > 0（用 ezdxf 读取验证）

#### Scenario: DeepSeek vs Ollama 对比

- **WHEN** 在 DeepSeek 全链路通过后
- **THEN** 必须与 `13_llm_switch.md` 的 Ollama 结果对比推理耗时
- **AND** 记录 DeepSeek 推理耗时（远程 API）vs Ollama 推理耗时（本地）
- **AND** 对比代码质量（是否含幻觉 API / 是否通过沙箱执行）

#### Scenario: 环境恢复

- **WHEN** DeepSeek 全链路验证完成
- **THEN** 必须清空 DeepSeek 相关环境变量（OPENAI_BASE_URL / OPENAI_MODEL / OPENAI_API_KEY）
- **AND** 重置 `LLM_PROVIDER=ollama`（或恢复 .env 默认值）
- **AND** 调用 `reset_provider_cache()` 确保下次调用回到 Ollama
- **AND** 验证恢复后 `get_llm_provider()` 返回 OllamaProvider

## MODIFIED Requirements

### Requirement: 草图 VLM 路径测试 PASS 判据（修改现有）

[原要求] SubTask 4.2 仅以"VLM 返回非空 features 列表"作为 PASS 判据

[修改为] PASS 判据必须包含：
1. VLM 返回 features 非空
2. VLM 返回的尺寸参数与草图标注期望值的偏差 < 10%
3. bbox 格式经分析无 `_normalize_bbox` 误判
4. 原始 VLM 输出文本已落盘可追溯

### Requirement: DeepSeek LLM 切换验证（修改现有）

[原要求] SubTask 5.1 仅验证 `generate_cadquery_code()` 单步返回 `mode=llm`

[修改为] 验证必须包含：
1. provider 切换后类为 OpenAIProvider 且 is_available=True
2. 单步 `generate_cadquery_code()` 返回 mode=llm（沿用 13 号结论）
3. 全链路 `generate_and_execute_with_fallback()` 走通
4. 真实产出 revised.step / revised.dxf 文件且体积/实体数 > 0
5. 环境恢复后回到 Ollama provider

## REMOVED Requirements

### Requirement: 以"返回非空"作为 VLM PASS 判据

**Reason**: 该判据过于宽松，无法检出 VLM 尺寸幻觉（如 radius=10 vs 期望 50 的 5 倍偏差）。

**Migration**: 改为基于真实尺寸偏差的 PASS/WARN/FAIL 三档判据（<10% PASS / 10%~2倍 WARN / >2倍 FAIL）。

### Requirement: 以"单步代码生成"作为 DeepSeek 切换 PASS 判据

**Reason**: 单步代码生成只能验证 provider 可达 + 模型可调用，不能验证端到端协同闭环（沙箱执行 + 文件产出）真实可用。

**Migration**: 改为全链路协同闭环验证，包含沙箱执行与真实文件产出校验。
