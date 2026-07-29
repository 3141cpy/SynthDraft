# Tasks

- [x] Task 0: 创建 spec 文档（spec.md / tasks.md / checklist.md）
  - 依赖: 无
  - SubTask 0.1: 创建 spec.md，描述 Why / What Changes / Impact / Requirements
  - SubTask 0.2: 创建 tasks.md，分解任务
  - SubTask 0.3: 创建 checklist.md，定义验证清单

## 阶段 1：实际调研（发现新幻觉模式 + 复测 v3 残留 4 类）

- [x] Task 1: 设计 v4 调研测试用例（12-15 个）
  - 依赖: Task 0
  - SubTask 1.1: 复测 v3 残留 4 类幻觉用例（mirror/shell/cut/rarray），用当前 prompts.py 重新执行确认仍存在
  - SubTask 1.2: 设计 8-11 个覆盖 v3 未涉及建模原语的新用例，至少覆盖：
    - loft 放样：如"创建一个放样体，底面圆 Φ40，顶面圆 Φ20，高 30"
    - combine 布尔运算链：如"长方体与圆柱求交/求差"
    - counterbore 沉孔：如"在板上打沉头孔，通孔 Φ10，沉孔 Φ15 深 3"
    - countersink 倒角孔：如"在板上打倒角孔，通孔 Φ10，倒角 90°"
    - slot 凹槽/键槽：如"在圆柱面上开一个键槽"
    - tangentArc 相切弧：如"用相切弧连接两段直线"
    - spline 样条曲线：如"用样条曲线创建截面"
    - text 3D 文字：如"在板上凸起 3D 文字 HELLO"
    - 复杂组合：如"带沉孔和倒角的法兰盘"
  - SubTask 1.3: 每个用例定义 prompt 与 expected_pattern（期望使用的 CadQuery API）
  - 验证标准: 测试用例总数 ≥ 12 个，覆盖 ≥ 8 类新原语 + 4 类 v3 残留

- [x] Task 2: 执行 v4 调研测试，收集结果
  - 依赖: Task 1
  - SubTask 2.1: 确认 Ollama `qwen2.5-coder:7b` 服务可用
  - SubTask 2.2: 新建 `_test_hallucination_research_v4.py`，复用 SYNC-BYPASS 模式
  - SubTask 2.3: 执行调研测试，每个用例记录：LLM 生成代码、mode、沙箱结果、stderr、cadquery 独立验证、verdict
  - SubTask 2.4: 对沙箱 PASS 的用例，增加语义层验证（对比期望几何与实际几何，识别隐性幻觉）
  - SubTask 2.5: 结果写入 `_test_hallucination_research_v4_result.json`
  - 验证标准: 所有用例真实执行，结果 JSON 完整含生成代码与语义分析

- [x] Task 3: 分析失败用例，识别新幻觉模式
  - 依赖: Task 2
  - SubTask 3.1: 从结果 JSON 筛选所有 FAIL/DEGRADED/语义错误用例
  - SubTask 3.2: 对每个失败用例，提取幻觉 API 调用
  - SubTask 3.3: 通过 `inspect.signature()` 或 `help()` 查询真实签名验证（非瞎猜）
  - SubTask 3.4: 分类幻觉模式（签名错误 / 不存在的 API / 参数顺序错误 / 语义误用 / 数值错误 / 选择器错误）
  - SubTask 3.5: 为每个幻觉 API 给出正确替代写法
  - SubTask 3.6: 重点关注 v3 残留 4 类幻觉是否仍存在，以及新原语（loft/counterbore/slot 等）的幻觉模式
  - 验证标准: 每个失败用例的幻觉 API 已识别 + 真实签名已查询 + 正确替代已给出

- [x] Task 4: 生成 v4 调研报告
  - 依赖: Task 3
  - SubTask 4.1: 生成 `backend/tmp_audit_logs/cadquery_hallucination_research_v4.md`，含：
    - 调研目的与方法
    - 测试用例清单（含 expected_pattern）
    - 逐用例结果（pass/fail + 生成代码 + stderr + 语义分析）
    - v3 残留 4 类幻觉复测结果
    - 新发现的幻觉模式分类汇总表
    - 根因分析
    - 优化方向建议
  - SubTask 4.2: 如实记录所有失败用例，不掩饰
  - 验证标准: 报告完整、数据真实、幻觉模式分类清晰

## 阶段 2：针对性 Prompt 优化（仅改 prompts.py）

- [x] Task 5: 新增「强制语义映射」章节
  - 依赖: Task 4
  - SubTask 5.1: 在 SYSTEM_PROMPT 中新增「强制语义映射（必须遵循）」章节
  - SubTask 5.2: 对 mirror/shell/cut/rarray 4 类高频幻觉使用"必须使用 X，禁止使用 Y"强制措辞
  - SubTask 5.3: 每条给出反例对照（错误代码 vs 正确代码）
  - SubTask 5.4: 保留已有禁止项与场景范式（不回归）
  - 验证标准: 强制语义映射章节覆盖 4 类残留幻觉，措辞明确

- [x] Task 6: 扩展少样本示例（shell/cut/rarray/mirror 专项）
  - 依赖: Task 4
  - SubTask 6.1: 在 `_BUILD_STEPS_EXAMPLES` 新增 4 个专项示例：
    - 示例 8：空心盒抽壳（shell 范式）
    - 示例 9：顶面切矩形凹槽（cutBlind 范式）
    - 示例 10：4x4 矩形阵列孔（rarray 范式）
    - 示例 11：L 形支架镜像（mirror 范式）
  - SubTask 6.2: 每个示例含完整建模步骤分解 + 参数化代码 + 中文注释
  - SubTask 6.3: 新示例代码用 cadquery 独立验证可执行（STEP 导出 + volume > 0）
  - SubTask 6.4: 保留已有 7 个示例（不回归）
  - 验证标准: 4 个新示例代码可独立执行，volume > 0

- [x] Task 7: 根据新幻觉模式扩展禁止清单与场景范式
  - 依赖: Task 4
  - SubTask 7.1: 根据 Task 3 识别的新幻觉 API（如 loft/counterbore/slot 等），在禁止清单新增条目
  - SubTask 7.2: 如发现新原语需要正确范式，在「常见场景正确范式」新增场景
  - SubTask 7.3: 每条新禁止项区分错误形式与正确替代
  - SubTask 7.4: 保留已有禁止项与场景（不回归）
  - 验证标准: 新幻觉 API 已加入禁止清单，正确替代写法已给出

- [x] Task 8: 强化自检清单
  - 依赖: Task 5, 6, 7
  - SubTask 8.1: 新增"场景范式遵循检查"项（输出前确认是否匹配场景 5-11 范式）
  - SubTask 8.2: 新增"数值一致性检查"项（如 rarray 阵列数与用户要求一致）
  - SubTask 8.3: 新增"轴/面语义检查"项（如"沿 X 轴镜像"→ `.mirror("YZ")`）
  - SubTask 8.4: 根据新幻觉模式新增对应检查项
  - SubTask 8.5: 保留已有 21 项自检（不回归）
  - 验证标准: 自检清单总数 ≥ 25 项，覆盖残留幻觉与新幻觉

## 阶段 3：测试验证

- [x] Task 9: 回归测试（v3 用例不回归）
  - 依赖: Task 5, 6, 7, 8
  - SubTask 9.1: 复用 v3 回归测试脚本（6 用例）执行
  - SubTask 9.2: 验证 mode=llm 通过率 ≥ 5/6
  - SubTask 9.3: 结果写入 `_test_hallucination_v4_regression_result.json`
  - 验证标准: 原用例不回归，mode=llm 通过率 ≥ 5/6

- [x] Task 10: 新用例测试（v4 幻觉率下降验证）
  - 依赖: Task 9
  - SubTask 10.1: 复用 Task 2 的 v4 调研测试脚本（12-15 用例），用优化后 prompts.py 重新执行
  - SubTask 10.2: 收集优化后结果，写入 `_test_hallucination_v4_after_result.json`
  - SubTask 10.3: 对比优化前（Task 2）与优化后的 pass/fail + 语义正确率
  - SubTask 10.4: 重点验证 v3 残留 4 类幻觉是否已消除
  - SubTask 10.5: 验证语义幻觉率从 50% 降至 ≤ 30%（下降幅度 ≥ 40%）
  - 验证标准: 语义幻觉率 ≤ 30%，v3 残留 4 类幻觉至少消除 3 类

## 阶段 4：生成对比报告与 Spec 更新

- [x] Task 11: 生成 v4 综合对比报告
  - 依赖: Task 9, Task 10
  - SubTask 11.1: 生成 `backend/tmp_audit_logs/hallucination_v4_comparison_report.md`，含：
    - 优化前/后调研用例 pass/fail 对比表
    - v3 残留 4 类幻觉的修复情况
    - 新发现幻觉模式的修复情况
    - 回归测试结果（6 用例）
    - 幻觉率下降百分比统计
    - 八荣八耻合规性自检表
  - SubTask 11.2: 如实记录所有结果，不掩饰失败
  - 验证标准: 报告完整、对比清晰、数据真实

- [x] Task 12: 更新 spec 文档与历史报告
  - 依赖: Task 11
  - SubTask 12.1: 在 `tasks.md` 中勾选所有完成项
  - SubTask 12.2: 在 `checklist.md` 中勾选所有验证项
  - SubTask 12.3: 在 `v2v4_followup_fix_report.md` 中追加"修复项 4 进一步优化（v4）"章节
  - 验证标准: 所有 spec 文档同步更新

# Task Dependencies

- Task 1, 2, 3, 4 串行（调研阶段，逐层深入）
- Task 5, 6, 7, 8 串行（均修改 prompts.py，避免冲突）
- Task 9 依赖 Task 5, 6, 7, 8
- Task 10 依赖 Task 9
- Task 11 依赖 Task 9, Task 10
- Task 12 依赖 Task 11
