# Checklist

## 阶段 0：Spec 文档

- [ ] `spec.md` 已创建，含 Why / What Changes / Impact / Requirements
- [ ] `tasks.md` 已创建，任务分解清晰
- [ ] `checklist.md` 已创建（本文件）

## 阶段 1：实际调研

### Task 1: 设计调研测试用例
- [ ] 测试用例覆盖 ≥ 8 类建模原语（倒角/圆角/旋转体/扫掠/镜像/抽壳/切槽/多特征组合/复杂阵列/盲孔等）
- [ ] 每个用例有明确的 prompt 与 expected_pattern
- [ ] 用例难度适中（能暴露幻觉但非故意刁难）

### Task 2: 执行调研测试
- [ ] Ollama `qwen2.5-coder:7b` 服务可用性已确认
- [ ] `_test_hallucination_research_v3.py` 脚本已创建，复用 SYNC-BYPASS 模式
- [ ] 所有用例真实执行（非模拟）
- [ ] 每个用例记录：生成代码、mode、执行结果、stderr、cadquery 独立验证
- [ ] 结果 JSON 已写入 `_test_hallucination_research_v3_result.json`

### Task 3: 分析失败用例
- [ ] 所有 FAIL/DEGRADED 用例已筛选
- [ ] 每个失败用例的幻觉 API 已提取
- [ ] 通过 `help()` 查询真实签名验证（非瞎猜）
- [ ] 幻觉模式已分类（签名错误 / 不存在的 API / 参数顺序错误 / 语义误用）
- [ ] 每个幻觉 API 的正确替代写法已给出

### Task 4: 生成调研报告
- [ ] `cadquery_hallucination_research_v3.md` 已生成
- [ ] 报告含测试用例清单
- [ ] 报告含逐用例结果（pass/fail + 生成代码 + stderr）
- [ ] 报告含幻觉模式分类汇总表
- [ ] 报告含根因分析
- [ ] 报告含优化方向建议
- [ ] 报告如实记录失败用例（不掩饰）

## 阶段 2：Prompt 针对性优化

### Task 5: 更新禁止清单
- [ ] 调研发现的所有新幻觉 API 已加入禁止清单
- [ ] 每条新增禁止项区分错误形式与正确替代写法
- [ ] 已有的 centerX/centerY 等禁止项保留（不回归）
- [ ] 代码 diff 已记录

### Task 6: 扩展「常见场景正确范式」
- [ ] 调研发现的高频失败场景已新增正确范式
- [ ] 每个新场景给出完整可执行代码示例
- [ ] 新示例代码已用 cadquery 独立验证可执行
- [ ] 已有的 4 个场景保留（不回归）
- [ ] 代码 diff 已记录

### Task 7: 扩展少样本示例
- [ ] 调研发现的示例缺口已补充
- [ ] 新示例含完整建模步骤分解 + 参数化代码 + 中文注释
- [ ] 新示例代码已用 cadquery 独立验证可执行（STEP 导出 + volume > 0）
- [ ] 代码 diff 已记录

### Task 8: 强化自检清单
- [ ] 调研发现的新幻觉模式已加入自检清单
- [ ] 已有的 11 项自检保留（不回归）
- [ ] 自检清单总数 ≥ 14 项
- [ ] 代码 diff 已记录

## 阶段 3：测试验证

### Task 9: 回归测试
- [ ] 复用 `_test_task8_followup.py`（3 个原用例）执行完成
- [ ] 复用 `_test_task8_v2_extended.py`（3 个扩展用例）执行完成
- [ ] mode=llm 通过率 ≥ 5/6
- [ ] 无新增的幻觉 API 误用
- [ ] 结果 JSON 已写入 `_test_hallucination_v3_regression_result.json`

### Task 10: 新用例测试（幻觉率下降验证）
- [ ] 复用调研测试脚本（8-10 个新用例）用优化后 prompts.py 重新执行
- [ ] 优化后结果已写入 `_test_hallucination_v3_after_result.json`
- [ ] 优化前/后 pass/fail 对比已完成
- [ ] mode=llm 通过率较优化前提升 ≥ 30%
- [ ] 失败用例的幻觉 API 误用数量减少

## 阶段 4：报告与 Spec 更新

### Task 11: 生成综合对比报告
- [ ] `hallucination_v3_comparison_report.md` 已生成
- [ ] 报告含优化前/后调研用例 pass/fail 对比表
- [ ] 报告含回归测试结果（原 6 用例）
- [ ] 报告含每个失败用例的幻觉 API 与修复后正确代码对比
- [ ] 报告含幻觉率下降百分比统计
- [ ] 报告含八荣八耻合规性自检表
- [ ] 报告如实记录所有结果（不掩饰失败）

### Task 12: 更新 spec 文档
- [ ] `tasks.md` 所有完成项已勾选
- [ ] `checklist.md` 所有验证项已勾选
- [ ] `v2v4_followup_fix_report.md` 追加"修复项 3 进一步优化（v3）"章节

## 八荣八耻合规性自检

- [ ] **以认真查询为荣**：所有幻觉 API 通过实际 `help()` 查询真实签名，非瞎猜
- [ ] **以寻求确认为荣**：spec 已用户审批后再实施
- [ ] **以人类确认为荣**：方案决策点（如优化方向）已在 spec 中说明
- [ ] **以复用现有为荣**：复用 `_test_task8_followup.py` 测试框架与 SYNC-BYPASS 模式
- [ ] **以主动测试为荣**：调研 + 回归 + 新用例测试全部真实执行
- [ ] **以遵循规范为荣**：遵循 spec-driven 模式，仅改 prompts.py
- [ ] **以诚实无知为荣**：调研结果与测试结果如实记录，失败不掩饰
- [ ] **以谨慎重构为荣**：未破坏现有架构，仅新增禁止项/范式/示例/自检项
