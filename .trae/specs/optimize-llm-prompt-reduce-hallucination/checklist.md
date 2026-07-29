# Checklist

## 阶段 0：Spec 文档

- [x] `spec.md` 已创建，含 Why / What Changes / Impact / Requirements
- [x] `tasks.md` 已创建，任务分解清晰
- [x] `checklist.md` 已创建（本文件）

## 阶段 1：实际调研

### Task 1: CadQuery API 真实签名调研
- [ ] 通过 `python -c "import cadquery as cq; help(cq.Workplane.workplane)"` 查询 workplane 真实签名
- [ ] 通过 `python -c "import cadquery as cq; help(cq.Workplane.center)"` 查询 center 真实签名
- [ ] 通过 `python -c "import cadquery as cq; help(cq.Workplane.faces)"` 查询 faces 真实签名
- [ ] 通过 `python -c "import cadquery as cq; help(cq.Workplane.hole)"` 查询 hole 真实签名
- [ ] 写最小测试代码验证 `.faces(">Z").workplane()` 默认行为（是否在面中心）
- [ ] 调研报告 `backend/tmp_audit_logs/cadquery_api_research.md` 已生成，含所有 API 真实签名

### Task 2: 用例 1 失败根因分析
- [ ] 从 `_test_task8_followup.log` 提取 LLM 原始生成代码（含 `.workplane(centerX=..., centerY=...)`）
- [ ] 根因分析明确（区分构造器 vs 方法形式 / 缺乏正确范式 / 示例未覆盖）
- [ ] 在调研报告中追加"用例 1 根因分析"章节

## 阶段 2：Prompt 针对性优化

### Task 3: 优化禁止清单
- [ ] 禁止清单中 `Workplane(centerX=, centerY=)` 修正为两种形式（构造器 + 方法）
- [ ] 每条禁止项给出正确替代写法
- [ ] 代码 diff 已记录

### Task 4: 增加「常见场景正确范式」章节
- [ ] SYSTEM_PROMPT 中新增「常见场景正确范式」章节
- [ ] 包含"在面中心打孔"正确写法
- [ ] 包含"在偏移位置打孔"正确写法
- [ ] 包含"创建长方体并在顶面打孔"完整范式
- [ ] 代码 diff 已记录

### Task 5: 扩展少样本示例
- [ ] `_BUILD_STEPS_EXAMPLES` 新增"示例 4：长方体顶面中心打孔"
- [ ] 新示例含完整建模步骤分解 + 参数化代码 + 中文注释
- [ ] 新示例代码已用 cadquery 独立验证可执行（STEP 导出 + volume > 0）
- [ ] 代码 diff 已记录

### Task 6: 强化自检清单
- [ ] 自检清单增加"是否未使用 centerX / centerY 关键字参数"
- [ ] 自检清单增加"打孔定位是否使用了 .workplane() 或 .center(x, y)"
- [ ] 保留原有 8 项自检
- [ ] 自检清单总数 ≥ 10 项
- [ ] 代码 diff 已记录

## 阶段 3：测试验证

### Task 7: 复用 Task 8 测试脚本验证
- [ ] Ollama `qwen2.5-coder:7b` 服务可用性已确认
- [ ] 直接复用 `_test_task8_followup.py`（未修改测试用例）
- [ ] 测试执行完成，3 个用例全部跑通
- [ ] 用例 1 (`长方体 50x30x10，顶面中心打直径10的孔`) verdict = PASS（从 DEGRADED → PASS）
- [ ] 用例 2, 3 仍为 PASS（未回归）
- [ ] mode=llm 通过率 ≥ 3/3
- [ ] 结果 JSON 已写入 `_test_task8_followup_v2_result.json`

### Task 8: 扩展测试用例验证泛化能力
- [ ] 新建 `_test_task8_v2_extended.py`
- [ ] 含 3 个变体用例（圆柱顶面打孔 / 矩形板顶面打孔 / 立方体顶面打孔深10）
- [ ] 扩展测试执行完成
- [ ] 变体用例 mode=llm 通过率 ≥ 2/3
- [ ] 结果 JSON 已写入 `_test_task8_v2_extended_result.json`

### Task 9: 生成对比报告
- [ ] `backend/tmp_audit_logs/v2v4_followup_task8_v2.md` 已生成
- [ ] 报告含修复前后 mode=llm 通过率对比表
- [ ] 报告含每用例 LLM 原始生成代码（修复前 vs 修复后）
- [ ] 报告含变体用例测试结果
- [ ] 报告如实记录（失败用例不掩饰）
- [ ] 报告含八荣八耻合规性自检表

## 阶段 4：Spec 文档更新

### Task 10: 更新 spec 文档
- [ ] `tasks.md` 所有完成项已勾选
- [ ] `checklist.md` 所有验证项已勾选
- [ ] `v2v4_followup_fix_report.md` 追加"修复项 3 后续优化"章节

## 八荣八耻合规性自检

- [ ] **以认真查询为荣**：所有 API 签名通过实际 `help()` 查询，非瞎猜
- [ ] **以寻求确认为荣**：spec 已用户审批后再实施
- [ ] **以人类确认为荣**：方案决策点（如禁止清单修正策略）已在 spec 中说明
- [ ] **以复用现有为荣**：复用 `_test_task8_followup.py` 测试框架，不重写
- [ ] **以主动测试为荣**：3 + 3 = 6 个测试用例全部真实执行
- [ ] **以遵循规范为荣**：遵循 spec-driven 模式，仅改 prompts.py
- [ ] **以诚实无知为荣**：测试结果如实记录，失败不掩饰
- [ ] **以谨慎重构为荣**：未破坏现有架构，仅新增章节和示例
