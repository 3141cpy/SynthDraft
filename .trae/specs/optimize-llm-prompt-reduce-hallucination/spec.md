# LLM 提示词针对性优化降低幻觉率 Spec

## Why

V2-V4 后续建议修复（修复项 3：LLM 提示词 anti-hallucination 增强）已将 mode=llm 通过率从 0/3 提升到 2/3，但仍存在以下问题：

1. **Task 8 用例 1 仍降级**：`长方体 50x30x10，顶面中心打直径10的孔` 生成代码含 `.workplane(centerX=length/2, centerY=width/2)`，沙箱报 `TypeError: Workplane.workplane() got an unexpected keyword argument 'centerX'`
2. **禁止清单不精确**：现有清单将 `Workplane(centerX=..., centerY=...)` 列为构造器错误，但 LLM 实际误用的是**方法形式** `.workplane(centerX=..., centerY=...)`
3. **缺少正确范式**：用户场景"在面中心打孔"是高频需求，但 prompt 中没有给出正确写法（`.faces(">Z").workplane()` 默认在面中心，或 `.workplane().center(x, y).hole(...)` 做偏移定位）
4. **少样本示例覆盖不全**：现有 3 个示例（法兰盘/阶梯轴/矩形板）没有覆盖"在面中心打孔"这一基础场景，LLM 在该场景下缺乏示例参照

用户要求"先实际调研再进一步针对性优化 LLM 提示词并测试"，需先实际查询 CadQuery 真实 API 签名，再针对性优化 prompt，最后用真实测试验证。

## What Changes

### 调研阶段（无代码改动）
- 通过 `python -c "import cadquery as cq; help(cq.Workplane.workplane)"` 等方式实际查询 CadQuery 真实 API 签名
- 重点调研：`Workplane.workplane()`、`Workplane.center()`、`Workplane.faces()`、`Workplane.hole()` 等高频 API 的真实签名
- 调研 `.workplane()` 默认行为（是否默认在面中心）
- 整理 LLM 在 Task 8 中实际生成的错误代码模式（从日志中提取）

### Prompt 优化阶段（仅改 prompts.py）
- 修正禁止清单：明确区分构造器形式 `cq.Workplane(centerX=, centerY=)` 和方法形式 `.workplane(centerX=, centerY=)`，两者都禁止
- 增加"常见场景正确范式"章节：列出"在面中心打孔"、"在偏移位置打孔"等高频场景的正确写法
- 扩展少样本示例：增加"长方体顶面中心打孔"示例（覆盖 Task 8 用例 1 失败场景）
- 强化自检清单：增加"是否使用了 centerX / centerY 关键字参数"等更具体的检查项
- 不改动其他文件（不动沙箱、不动 code_generator、不动测试框架）

### 测试验证阶段
- 复用 `_test_task8_followup.py` 测试脚本（3 个用例）重新跑一遍，对比修复前后
- 扩展测试用例：增加更多变体（如"在矩形板中心打孔"、"在圆柱顶面打孔"）验证泛化能力
- 生成对比报告：mode=llm 通过率、降级率、LLM 原始生成代码对比

## Impact

- Affected specs: 
  - `remediate-v2v4-followup-suggestions`（前置 spec，已完成，本 spec 是其延伸优化）
  - `ai-engineering-design-assistant`（主项目 spec）
- Affected code:
  - `backend/app/services/generation/prompts.py`（核心修改文件）
  - `backend/tmp_audit_logs/_test_task8_followup.py`（复用并扩展测试）
  - `backend/tmp_audit_logs/v2v4_followup_task8.md`（测试报告，对比修复前后）

## ADDED Requirements

### Requirement: CadQuery API 真实签名调研
系统 SHALL 在优化 prompt 前，通过实际 Python REPL 查询 CadQuery 真实 API 签名，确保禁止清单和签名参考的准确性。

#### Scenario: 调研 Workplane.workplane 真实签名
- **WHEN** 调研阶段开始
- **THEN** 通过 `python -c "import cadquery as cq; help(cq.Workplane.workplane)"` 查询真实签名
- **AND** 记录真实签名到调研报告
- **AND** 对比现有禁止清单，发现差异时修正

#### Scenario: 调研常见打孔定位 API
- **WHEN** 调研"在面中心打孔"场景
- **THEN** 查询 `Workplane.center()`、`Workplane.faces()` 等相关 API 签名
- **AND** 验证 `.faces(">Z").workplane()` 是否默认在面中心
- **AND** 整理正确范式

### Requirement: Prompt 针对性优化
系统 SHALL 在 `prompts.py` 的 `SYSTEM_PROMPT` 中增加针对性优化章节，覆盖 Task 8 用例 1 失败场景。

#### Scenario: 修正禁止清单（区分构造器和方法形式）
- **WHEN** 优化禁止清单
- **THEN** 明确禁止 `.workplane(centerX=..., centerY=...)`（方法形式）
- **AND** 明确禁止 `cq.Workplane(centerX=..., centerY=...)`（构造器形式）
- **AND** 给出正确替代写法

#### Scenario: 增加"常见场景正确范式"章节
- **WHEN** 优化 SYSTEM_PROMPT
- **THEN** 增加"在面中心打孔"场景的正确写法（`.faces(">Z").workplane().hole(d)`）
- **AND** 增加"在偏移位置打孔"场景的正确写法（`.faces(">Z").workplane().center(x, y).hole(d)`）
- **AND** 增加"创建长方体并在顶面打孔"完整示例

#### Scenario: 扩展少样本示例
- **WHEN** 优化 `_BUILD_STEPS_EXAMPLES`
- **THEN** 增加"长方体顶面中心打孔"示例（覆盖 Task 8 用例 1 失败场景）
- **AND** 保留原有 3 个示例（法兰盘/阶梯轴/矩形板）

### Requirement: 测试验证
系统 SHALL 通过实际测试验证 prompt 优化效果，生成对比报告。

#### Scenario: 复用 Task 8 测试用例
- **WHEN** 测试阶段
- **THEN** 复用 `_test_task8_followup.py` 的 3 个用例
- **AND** 期望 mode=llm 通过率 ≥ 3/3（即用例 1 也应通过）
- **AND** 记录每用例的 mode、exec_success、cq_volume、verdict

#### Scenario: 扩展测试用例验证泛化能力
- **WHEN** 主测试通过后
- **THEN** 增加 2-3 个变体用例（如"在圆柱顶面打孔"、"矩形板四角倒圆角"）
- **AND** 验证优化后的 prompt 在新场景下也能降低幻觉率
- **AND** 记录到测试报告

#### Scenario: 生成对比报告
- **WHEN** 测试完成
- **THEN** 生成 `backend/tmp_audit_logs/v2v4_followup_task8_v2.md` 对比报告
- **AND** 对比修复前（2/3 PASS）、修复后（期望 3/3 PASS）
- **AND** 记录 LLM 原始生成代码用于人工核对

## MODIFIED Requirements

### Requirement: SYSTEM_PROMPT 反幻觉能力
[原有] SYSTEM_PROMPT 包含「禁止使用的 API」「CadQuery API 签名参考」「输出前自检清单」三个章节，将 mode=llm 通过率从 0/3 提升到 2/3。

[修改后] SYSTEM_PROMPT 在原有基础上：
1. 修正禁止清单，区分构造器和方法形式
2. 增加「常见场景正确范式」章节
3. 自检清单增加更具体的检查项（如 centerX/centerY 关键字参数检测）
4. 少样本示例扩展为 4 个（增加"长方体顶面中心打孔"）
期望将 mode=llm 通过率从 2/3 提升到 3/3。

## REMOVED Requirements

（无移除项，本 spec 是纯增强）
