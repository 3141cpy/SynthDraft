# 进一步降低 LLM 幻觉率 v4 Spec

## Why

v3 优化已将语义幻觉率从 71.4% 降至 50%（30% 降幅），但仍有 4 类语义幻觉顽固存在：
- **mirror 轴/面语义混淆**：LLM 用 `.mirror("XZ")`（Y→-Y）替代 `.mirror("YZ")`（X→-X），未区分"沿轴镜像"与"关于平面镜像"
- **shell→hole 退化**：LLM 用熟悉的 `.hole()` 替代 `.shell()`
- **cut→extrude 误用**：LLM 用 `.extrude(-h)`（默认 union 不切除）替代 `.cutBlind(-h)`
- **rarray 阵列数自行降级**：LLM 用 `rarray(60,60,2,2)` 替代用户指定的 `rarray(20,20,4,4)`

需通过更广泛的实际调研发现 v3 未覆盖的新幻觉模式，并针对性强化提示词，进一步将语义幻觉率从 50% 降至 ≤ 30%。

## What Changes

- 扩展调研测试用例至 12-15 个，覆盖 v3 未涉及的新建模原语（如 loft 放样、combine 布尔运算链、text 3D 文字、tangentArc 相切弧、splines 样条、counterbore 沉孔、countersink 倒角孔、 Slot 凹槽）
- 针对 v3 残留的 4 类幻觉，在 prompts.py 中新增"强制语义映射"章节（"必须使用"措辞 + 反例对照）
- 新增 shell/cut/rarray/mirror 的专项少样本示例（v3 仅 chamfer/revolve/sweep 有示例）
- 强化自检清单：新增"场景范式遵循检查"（输出前必须确认是否匹配某场景范式）
- 仅修改 `backend/app/services/generation/prompts.py`（不破坏架构）

## Impact

- Affected specs: `further-reduce-llm-hallucination`（v3，已完成，本 spec 为其延续）
- Affected code: `backend/app/services/generation/prompts.py`（唯一修改文件）
- 测试脚本：复用 SYNC-BYPASS 模式，新增 v4 调研脚本

## ADDED Requirements

### Requirement: 强制语义映射章节
系统 SHALL 在 SYSTEM_PROMPT 中新增「强制语义映射（必须遵循）」章节，对 mirror/shell/cut/rarray 4 类高频幻觉场景使用"必须使用 X，禁止使用 Y"的强制措辞，并给出反例对照。

#### Scenario: LLM 接收到 mirror 需求
- **WHEN** 用户描述包含"沿 X 轴镜像"
- **THEN** LLM 必须生成 `.mirror("YZ")`，禁止生成 `.mirror("X")` / `.mirror("XZ")`

#### Scenario: LLM 接收到 shell 需求
- **WHEN** 用户描述包含"抽壳" / "空心盒" / "壁厚"
- **THEN** LLM 必须生成 `.shell(thickness)`，禁止用 `.hole()` / `.cutThruAll()` 替代

### Requirement: 场景范式遵循自检
系统 SHALL 在自检清单中新增"场景范式遵循检查"项，要求 LLM 输出前确认是否匹配场景 5-11 中的某一项范式。

#### Scenario: LLM 生成代码包含 extrude(-h)
- **WHEN** LLM 生成 `.extrude(-h)` 用于切除
- **THEN** 自检必须触发"是否应改用 `.cutBlind(-h)`"提醒

### Requirement: 新增专项少样本示例
系统 SHALL 在 `_BUILD_STEPS_EXAMPLES` 中新增 shell/cut/rarray/mirror 4 个专项示例，每个示例含完整建模步骤分解 + 参数化代码 + 中文注释。

#### Scenario: shell 示例可独立执行
- **WHEN** 用 cadquery 独立执行 shell 示例代码
- **THEN** STEP 导出成功且 volume > 0

## MODIFIED Requirements

### Requirement: 调研测试覆盖
v3 覆盖 10 类建模原语；v4 扩展至 12-15 类，新增 loft/combine/text/tangentArc/spline/counterbore/countersink/slot 等原语，并复测 v3 的 4 个残留幻觉用例。

### Requirement: 幻觉率下降目标
v3 目标：语义幻觉率下降 ≥ 30%（达成 30%）。v4 目标：在 v3 基础上进一步下降至 ≤ 30%（即从 50% 降至 ≤ 30%，下降幅度 ≥ 40%）。
