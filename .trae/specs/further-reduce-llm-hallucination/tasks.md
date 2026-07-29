# Tasks

- [ ] Task 0: 创建 spec 文档（spec.md / tasks.md / checklist.md）
  - 依赖: 无
  - SubTask 0.1: 创建 spec.md，描述 Why / What Changes / Impact / Requirements
  - SubTask 0.2: 创建 tasks.md，分解任务
  - SubTask 0.3: 创建 checklist.md，定义验证清单

## 阶段 1：实际调研（发现新的幻觉模式，无 prompts.py 改动）

- [ ] Task 1: 设计广泛覆盖的调研测试用例
  - 依赖: Task 0
  - SubTask 1.1: 设计 8-10 个覆盖更多 CadQuery 建模原语的测试用例，至少覆盖以下场景：
    - 倒角/圆角（fillet/chamfer）：如"长方体 50x30x10，顶面四条边倒圆角 R2"
    - 旋转体（revolve）：如"绕 Y 轴旋转创建回转体，截面为 (0,0)-(20,0)-(20,10)-(0,10)"
    - 扫掠（sweep）：如"沿 Z 轴路径扫掠一个圆形截面"
    - 镜像（mirror）：如"创建一个 L 形支架并镜像"
    - 抽壳（shell）：如"创建一个空心长方体盒，壁厚 2mm"
    - 切槽/凹槽（cut）：如"在长方体顶面切一个 20x10x3 的凹槽"
    - 多特征组合：如"带倒角和打孔的法兰盘"
    - 复杂阵列：如"在圆盘上矩形阵列 4x4 个孔"
    - 盲孔/沉孔：如"在长方体顶面打沉头孔"
    - 倾斜特征：如"创建一个 30 度斜面"
  - SubTask 1.2: 在调研脚本中为每个用例定义 expected_pattern（期望使用的 CadQuery API）
  - 验证标准: 测试用例覆盖 ≥ 8 类建模原语，每个用例有明确的 prompt 与 expected_pattern

- [ ] Task 2: 执行调研测试，收集 LLM 生成代码与执行结果
  - 依赖: Task 1
  - SubTask 2.1: 确认 Ollama `qwen2.5-coder:7b` 服务可用
  - SubTask 2.2: 新建 `_test_hallucination_research_v3.py`，复用 SYNC-BYPASS 模式（`run_generation.apply()`）
  - SubTask 2.3: 执行调研测试，每个用例记录：
    - LLM 生成代码（完整）
    - mode（llm/template）
    - 沙箱执行结果（success/exit_code/stderr）
    - cadquery 独立验证 STEP（ok/volume/error）
    - verdict（PASS/FAIL/DEGRADED）
  - SubTask 2.4: 结果写入 `_test_hallucination_research_v3_result.json`
  - 验证标准: 所有用例真实执行，结果 JSON 完整，含每个用例的生成代码与执行详情

- [ ] Task 3: 分析失败用例，识别幻觉模式
  - 依赖: Task 2
  - SubTask 3.1: 从结果 JSON 中筛选所有 FAIL/DEGRADED 用例
  - SubTask 3.2: 对每个失败用例，提取 LLM 生成代码中的幻觉 API 调用（与正确签名对比）
  - SubTask 3.3: 通过 `python -c "import cadquery as cq; help(cq.Workplane.xxx)"` 查询真实签名验证
  - SubTask 3.4: 分类幻觉模式（如：签名错误 / 不存在的 API / 参数顺序错误 / 语义误用）
  - SubTask 3.5: 为每个幻觉 API 给出正确替代写法
  - 验证标准: 每个失败用例的幻觉 API 已识别 + 真实签名已查询 + 正确替代写法已给出

- [ ] Task 4: 生成调研报告
  - 依赖: Task 3
  - SubTask 4.1: 生成 `backend/tmp_audit_logs/cadquery_hallucination_research_v3.md`，含：
    - 调研目的与方法
    - 测试用例清单（含 expected_pattern）
    - 逐用例结果（pass/fail + 生成代码 + stderr）
    - 幻觉模式分类汇总表
    - 根因分析（为何 LLM 会产生这些幻觉）
    - 优化方向建议（禁止清单 / 正确范式 / 示例 / 自检清单）
  - SubTask 4.2: 如实在报告中记录所有失败用例，不掩饰
  - 验证标准: 报告完整、数据真实、幻觉模式分类清晰、优化方向具体可执行

## 阶段 2：针对性 Prompt 优化（仅改 prompts.py）

- [ ] Task 5: 更新禁止清单
  - 依赖: Task 4
  - SubTask 5.1: 根据 Task 3 识别的新幻觉 API，在 SYSTEM_PROMPT「禁止使用的 API」章节新增对应条目
  - SubTask 5.2: 每条新增禁止项区分错误形式与正确替代写法
  - SubTask 5.3: 保留已有的 centerX/centerY 等禁止项（不回归）
  - 验证标准: 禁止清单覆盖所有调研发现的幻觉 API，每条有正确替代

- [ ] Task 6: 扩展「常见场景正确范式」章节
  - 依赖: Task 4
  - SubTask 6.1: 根据 Task 3 识别的高频失败场景，新增对应正确范式
  - SubTask 6.2: 每个新场景给出完整可执行代码示例（用 cadquery 独立验证）
  - SubTask 6.3: 保留已有的 4 个场景（不回归）
  - 验证标准: 新增场景覆盖调研发现的高频失败类别，代码示例可独立执行

- [ ] Task 7: 扩展少样本示例
  - 依赖: Task 4
  - SubTask 7.1: 根据 Task 3 识别的缺乏示例的建模原语，在 `_BUILD_STEPS_EXAMPLES` 中新增示例
  - SubTask 7.2: 新示例含完整建模步骤分解 + 参数化代码 + 中文注释
  - SubTask 7.3: 新示例代码已用 cadquery 独立验证可执行（STEP 导出 + volume > 0）
  - 验证标准: 新示例覆盖调研发现的示例缺口，代码可独立执行

- [ ] Task 8: 强化自检清单
  - 依赖: Task 5
  - SubTask 8.1: 根据 Task 3 识别的幻觉模式，在「输出前自检清单」中新增对应检查项
  - SubTask 8.2: 保留已有的 11 项自检（不回归）
  - SubTask 8.3: 自检清单总数 ≥ 14 项
  - 验证标准: 自检清单覆盖新幻觉模式，总数 ≥ 14

## 阶段 3：测试验证

- [ ] Task 9: 回归测试（原用例不回归）
  - 依赖: Task 5, 6, 7, 8
  - SubTask 9.1: 复用 `_test_task8_followup.py`（3 个原用例）+ `_test_task8_v2_extended.py`（3 个扩展用例）
  - SubTask 9.2: 执行回归测试，收集结果
  - SubTask 9.3: 验证 mode=llm 通过率 ≥ 5/6（允许 1 个因 LLM 随机性降级）
  - SubTask 9.4: 结果写入 `_test_hallucination_v3_regression_result.json`
  - 验证标准: 原用例不回归，mode=llm 通过率 ≥ 5/6

- [ ] Task 10: 新用例测试（幻觉率下降验证）
  - 依赖: Task 9
  - SubTask 10.1: 复用 Task 2 的调研测试脚本（8-10 个新用例），用优化后的 prompts.py 重新执行
  - SubTask 10.2: 收集优化后的测试结果，写入 `_test_hallucination_v3_after_result.json`
  - SubTask 10.3: 对比优化前（Task 2 结果）与优化后的 pass/fail
  - SubTask 10.4: 验证 mode=llm 通过率较优化前提升 ≥ 30%
  - 验证标准: 优化后 mode=llm 通过率显著提升，幻觉率下降 ≥ 30%

## 阶段 4：生成对比报告与 Spec 更新

- [ ] Task 11: 生成综合对比报告
  - 依赖: Task 9, Task 10
  - SubTask 11.1: 生成 `backend/tmp_audit_logs/hallucination_v3_comparison_report.md`，含：
    - 优化前/后调研用例 pass/fail 对比表
    - 回归测试结果（原 6 用例）
    - 每个失败用例的幻觉 API 与修复后正确代码对比
    - 幻觉率下降百分比统计
    - 八荣八耻合规性自检表
  - SubTask 11.2: 如实记录所有结果，不掩饰失败
  - 验证标准: 报告完整、对比清晰、数据真实

- [ ] Task 12: 更新 spec 文档
  - 依赖: Task 11
  - SubTask 12.1: 在 `tasks.md` 中勾选所有完成项
  - SubTask 12.2: 在 `checklist.md` 中勾选所有验证项
  - SubTask 12.3: 在 `v2v4_followup_fix_report.md` 中追加"修复项 3 进一步优化（v3）"章节
  - 验证标准: 所有 spec 文档同步更新

# Task Dependencies

- Task 1, 2, 3, 4 串行（调研阶段，逐层深入）
- Task 5, 6, 7, 8 可并行（均依赖 Task 4，但实际都修改 prompts.py，建议串行避免冲突）
- Task 9 依赖 Task 5, 6, 7, 8
- Task 10 依赖 Task 9
- Task 11 依赖 Task 9, Task 10
- Task 12 依赖 Task 11
