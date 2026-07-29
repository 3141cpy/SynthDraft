# Tasks

- [ ] Task 0: 创建 spec 文档（spec.md / tasks.md / checklist.md）
  - 依赖: 无
  - SubTask 0.1: 创建 spec.md，描述 Why / What Changes / Impact / Requirements ✓
  - SubTask 0.2: 创建 tasks.md，分解任务 ✓
  - SubTask 0.3: 创建 checklist.md，定义验证清单 ✓

## 阶段 1：实际调研（无代码改动）

- [ ] Task 1: 实际调研 CadQuery API 真实签名
  - 依赖: Task 0
  - SubTask 1.1: 查询 `cq.Workplane.workplane()` 真实签名（通过 `python -c "import cadquery as cq; help(cq.Workplane.workplane)"`）
  - SubTask 1.2: 查询 `cq.Workplane.center()` 真实签名
  - SubTask 1.3: 查询 `cq.Workplane.faces()` 真实签名（验证 ">Z" 选择器语义）
  - SubTask 1.4: 验证 `.faces(">Z").workplane()` 是否默认在面中心（写最小测试代码验证）
  - SubTask 1.5: 查询 `cq.Workplane.hole()` 真实签名
  - SubTask 1.6: 整理调研结果到 `backend/tmp_audit_logs/cadquery_api_research.md`
  - 验证标准: 调研报告包含所有上述 API 的真实签名 + 关键行为验证证据

- [ ] Task 2: 分析 Task 8 用例 1 失败根因
  - 依赖: Task 0
  - SubTask 2.1: 从 `_test_task8_followup.log` 提取 LLM 原始生成代码（含 `.workplane(centerX=..., centerY=...)`）
  - SubTask 2.2: 分析 LLM 为何误用此 API（缺乏正确范式？示例未覆盖？）
  - SubTask 2.3: 在调研报告（Task 1.6）中追加"用例 1 根因分析"章节
  - 验证标准: 根因分析明确指出 LLM 误用 API 的具体形式 + 原因假设 + 优化方向

## 阶段 2：Prompt 针对性优化（仅改 prompts.py）

- [ ] Task 3: 优化 SYSTEM_PROMPT 禁止清单
  - 依赖: Task 1, Task 2
  - SubTask 3.1: 修正禁止清单中 `Workplane(centerX=..., centerY=...)` 为两种形式（构造器 + 方法）
  - SubTask 3.2: 增加 `.workplane(offset=...)` 等其他常见误用形式（如有调研发现）
  - SubTask 3.3: 每条禁止项必须给出正确替代写法
  - 验证标准: 禁止清单每条都区分形式 + 给出替代方案

- [ ] Task 4: 增加「常见场景正确范式」章节
  - 依赖: Task 1
  - SubTask 4.1: 在 SYSTEM_PROMPT 中增加"常见场景正确范式"章节
  - SubTask 4.2: 列出"在面中心打孔"正确写法：`.faces(">Z").workplane().hole(d)`
  - SubTask 4.3: 列出"在偏移位置打孔"正确写法：`.faces(">Z").workplane().center(x, y).hole(d)`
  - SubTask 4.4: 列出"创建长方体并在顶面打孔"完整范式
  - 验证标准: 章节覆盖 ≥ 3 个高频场景，每个场景给出完整正确代码

- [ ] Task 5: 扩展少样本示例
  - 依赖: Task 1
  - SubTask 5.1: 在 `_BUILD_STEPS_EXAMPLES` 中增加"示例 4：长方体顶面中心打孔"
  - SubTask 5.2: 示例含完整建模步骤分解 + 参数化代码 + 中文注释
  - SubTask 5.3: 代码必须真实可执行（用 cadquery 在调研阶段验证）
  - 验证标准: 新示例代码可在沙箱外独立执行成功 + STEP 导出 + volume > 0

- [ ] Task 6: 强化自检清单
  - 依赖: Task 3
  - SubTask 6.1: 在自检清单中增加"是否未使用 centerX / centerY 关键字参数"
  - SubTask 6.2: 在自检清单中增加"打孔定位是否使用了 .workplane() 或 .center(x, y) 而非偏移参数"
  - SubTask 6.3: 保留原有 8 项自检
  - 验证标准: 自检清单 ≥ 10 项，新增项针对 Task 8 用例 1 失败场景

## 阶段 3：测试验证

- [ ] Task 7: 复用 Task 8 测试脚本验证
  - 依赖: Task 3, 4, 5, 6
  - SubTask 7.1: 确认 Ollama `qwen2.5-coder:7b` 服务可用（GET http://localhost:11434/api/tags）
  - SubTask 7.2: 直接复用 `_test_task8_followup.py`（不修改测试用例）
  - SubTask 7.3: 执行 `python _test_task8_followup.py`
  - SubTask 7.4: 收集结果到 `_test_task8_followup_v2_result.json`
  - 验证标准: mode=llm 通过率 ≥ 3/3（用例 1 必须从 DEGRADED → PASS）

- [ ] Task 8: 扩展测试用例验证泛化能力
  - 依赖: Task 7
  - SubTask 8.1: 新建 `_test_task8_v2_extended.py`，增加 2-3 个变体用例：
    - "圆柱，直径30高50，顶面中心打直径10的孔"
    - "矩形板 100x60x5，顶面中心打直径15的孔"
    - "立方体 40x40x40，顶面中心打直径8的孔深10"
  - SubTask 8.2: 执行扩展测试，收集结果
  - SubTask 8.3: 验证变体用例的 mode=llm 通过率 ≥ 2/3
  - 验证标准: 变体用例至少 2/3 mode=llm 且 STEP 有效

- [ ] Task 9: 生成对比报告
  - 依赖: Task 7, Task 8
  - SubTask 9.1: 整理修复前（v1）+ 修复后（v2）的测试数据
  - SubTask 9.2: 生成 `backend/tmp_audit_logs/v2v4_followup_task8_v2.md`，含：
    - 修复前后 mode=llm 通过率对比
    - 每用例的 LLM 原始生成代码（修复前 vs 修复后）
    - 变体用例测试结果
  - SubTask 9.3: 在报告中如实记录（如某用例仍失败，不得掩饰）
  - 验证标准: 报告完整、对比清晰、数据真实

## 阶段 4：Spec 文档更新

- [ ] Task 10: 更新 spec 文档
  - 依赖: Task 9
  - SubTask 10.1: 在 `tasks.md` 中勾选所有完成项
  - SubTask 10.2: 在 `checklist.md` 中勾选所有验证项
  - SubTask 10.3: 在 `v2v4_followup_fix_report.md` 中追加"修复项 3 后续优化"章节（引用 v2 报告）
  - 验证标准: 所有 spec 文档同步更新

# Task Dependencies

- Task 1, Task 2 可并行（均依赖 Task 0）
- Task 3 依赖 Task 1, Task 2
- Task 4, Task 5, Task 6 可并行（均依赖 Task 1，但实际都修改 prompts.py，建议串行避免冲突）
- Task 7 依赖 Task 3, 4, 5, 6
- Task 8 依赖 Task 7
- Task 9 依赖 Task 7, Task 8
- Task 10 依赖 Task 9
