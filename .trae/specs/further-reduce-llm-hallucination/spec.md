# 进一步降低 LLM 幻觉率 Spec

## Why

上一轮 spec `optimize-llm-prompt-reduce-hallucination` 仅针对 `centerX/centerY` 这一种高频幻觉进行了优化，v2 测试 3/3 mode=llm PASS。但该测试用例仅覆盖"长方体打孔 / 法兰盘 / 阶梯轴 / 圆柱打孔 / 矩形板打孔 / 立方体盲孔"等有限场景，**尚未发现其他潜在的 LLM 幻觉模式**（如倒角/圆角/旋转体/扫掠/镜像/抽壳/切槽/多特征组合等场景）。

qwen2.5-coder:7b 在面对更复杂的建模场景时，可能产生新的幻觉 API 误用（如 `.fillet()` 签名错误、`.revolve()` 轴向误用、`.sweep()` 路径构造错误、`.shell()` 不存在等）。需要通过**更广泛的实际调研**发现这些幻觉，再针对性优化提示词，进一步降低幻觉率。

**核心原则（八荣八耻）**：先实际调研（以认真查询为荣），再针对性优化（以谨慎重构为荣），最后真实测试（以主动测试为荣），如实记录（以诚实无知为荣）。

## What Changes

- **新增调研测试脚本**：设计 8-10 个覆盖更多 CadQuery 建模原语的测试用例（倒角/圆角/旋转体/扫掠/镜像/抽壳/切槽/螺纹/多特征组合），执行后收集 LLM 生成代码与沙箱执行结果
- **生成调研报告**：分析失败用例，识别新的幻觉 API/模式，整理到 `backend/tmp_audit_logs/cadquery_hallucination_research_v3.md`
- **优化 prompts.py**：根据调研发现的新幻觉，针对性更新禁止清单、增加正确范式、扩展示例、强化自检清单
- **测试验证**：复用原 6 用例（不回归）+ 新增用例（幻觉率下降），生成对比报告
- 不改动 code_generator.py / templates.py / 沙箱逻辑（仅改 prompts.py）

## Impact

- **Affected specs**：
  - `optimize-llm-prompt-reduce-hallucination`（前置 spec，已完成）
  - `remediate-v2v4-followup-suggestions`（修复项 3 的后续延伸）
- **Affected code**：
  - `backend/app/services/generation/prompts.py`（核心修改文件）
  - `backend/tmp_audit_logs/_test_hallucination_research_v3.py`（新建调研脚本）
  - `backend/tmp_audit_logs/_test_hallucination_v3_regression.py`（新建回归测试脚本）
  - `backend/tmp_audit_logs/cadquery_hallucination_research_v3.md`（新建调研报告）
  - `backend/tmp_audit_logs/hallucination_v3_comparison_report.md`（新建对比报告）

## ADDED Requirements

### Requirement: 广泛调研 LLM 幻觉模式

系统 SHALL 通过执行 8-10 个覆盖更多 CadQuery 建模原语的测试用例，发现 qwen2.5-coder:7b 在复杂场景下的幻觉 API 误用模式。

#### Scenario: 调研测试覆盖多种建模原语
- **WHEN** 执行调研测试脚本
- **THEN** 测试用例覆盖以下场景至少 8 类：倒角/圆角、旋转体、扫掠、镜像、抽壳、切槽/凹槽、多特征组合、复杂阵列
- **AND** 每个用例记录 LLM 生成代码、沙箱执行结果（成功/失败）、失败时的 stderr
- **AND** 生成调研报告 `cadquery_hallucination_research_v3.md`，含幻觉模式分类与根因分析

#### Scenario: 调研报告如实记录
- **WHEN** 调研测试完成
- **THEN** 报告如实记录每个用例的 pass/fail 状态
- **AND** 对失败用例提取 LLM 生成代码中的幻觉 API 调用
- **AND** 给出每个幻觉 API 的正确替代写法

### Requirement: 针对性 Prompt 优化

系统 SHALL 根据调研发现的新幻觉模式，针对性优化 `prompts.py` 的 SYSTEM_PROMPT。

#### Scenario: 禁止清单更新
- **WHEN** 调研发现新的幻觉 API
- **THEN** 在 SYSTEM_PROMPT 的「禁止使用的 API」章节中新增对应条目
- **AND** 每条新增禁止项区分错误形式与正确替代写法

#### Scenario: 正确范式扩展
- **WHEN** 调研发现某类场景高频失败
- **THEN** 在「常见场景正确范式」章节中新增对应场景的正确写法
- **AND** 给出完整可执行代码示例

#### Scenario: 少样本示例扩展
- **WHEN** 调研发现某类建模原语缺乏示例
- **THEN** 在 `_BUILD_STEPS_EXAMPLES` 中新增对应示例
- **AND** 新示例代码已用 cadquery 独立验证可执行

#### Scenario: 自检清单强化
- **WHEN** 调研发现新的幻觉模式
- **THEN** 在「输出前自检清单」中新增对应检查项
- **AND** 自检清单总数 ≥ 14 项（当前 11 项）

## MODIFIED Requirements

### Requirement: LLM 幻觉率进一步降低

[基于上一轮 spec 的要求升级]

#### Scenario: 原有用例不回归
- **WHEN** 复用 v2 测试的 3 个原用例 + 3 个扩展用例执行
- **THEN** mode=llm 通过率 ≥ 5/6（允许 1 个因 LLM 随机性降级）
- **AND** 无新增的幻觉 API 误用

#### Scenario: 新增用例幻觉率下降
- **WHEN** 执行调研阶段设计的 8-10 个新用例
- **THEN** 优化后 mode=llm 通过率较优化前提升 ≥ 30%
- **AND** 失败用例的幻觉 API 误用数量减少

#### Scenario: 综合对比报告
- **WHEN** 所有测试完成
- **THEN** 生成 `hallucination_v3_comparison_report.md`，含：
- 优化前/后各用例 pass/fail 对比
- 每个失败用例的幻觉 API 与修复后正确代码对比
- 幻觉率下降百分比统计
- 八荣八耻合规性自检表
