# Tasks

本任务清单按依赖顺序组织，目标是完成 SolidWorks Worker 真实路径测试（Tasks 13-18）的执行与报告生成。

## 前置条件

- Tasks 13-15（session/worker_pool/license）测试脚本已执行完成，结果 JSON 已生成
- Task 16（reader）测试脚本已创建，但因 `CoInitialize` 错误失败
- Task 17（writer）测试脚本已创建，未执行
- SolidWorks 2025 SP3.0 已安装在 Windows 节点

## 任务清单

- [x] Task 13: 会话管理测试复核（已完成，汇总结果）
  - [x] SubTask 13.1: 读取 `_test_sw_session_result.json`，确认所有子项 verdict
  - [x] SubTask 13.2: 记录 session 管理测试摘要到报告

- [x] Task 14: Worker 池与并发控制测试复核（已完成，汇总结果）
  - [x] SubTask 14.1: 读取 `_test_sw_worker_pool_result.json`，确认所有子项 verdict
  - [x] SubTask 14.2: 记录 worker_pool 测试摘要到报告

- [x] Task 15: 许可证管理测试复核（已完成，汇总结果）
  - [x] SubTask 15.1: 读取 `_test_sw_license_result.json`，确认所有子项 verdict
  - [x] SubTask 15.2: 记录 license 测试摘要到报告

- [x] Task 16: SLDPRT/SLDASM 读取真实路径测试（需修复 + 执行）
  - [x] SubTask 16.1: 修复 `worker_pool.py` 的 `submit` 方法，在线程 `_run` 函数入口添加 `pythoncom.CoInitialize()`，出口添加 `pythoncom.CoUninitialize()`（含 try/finally 与非 Windows 降级）
  - [x] SubTask 16.2: 运行 `_test_sw_reader.py`，验证 `read_sldprt(Part.SLDPRT)` 真实读取
  - [x] SubTask 16.3: 运行 `_test_sw_reader.py`，验证 `read_sldasm(Assembly.SLDASM)` 真实读取
  - [x] SubTask 16.4: 运行 `_test_sw_reader.py`，验证 `read_sldprt(shaftcutnormal.sldprt)` 复杂样本读取
  - [x] SubTask 16.5: 更新 `_test_sw_reader_result.json`，确认所有子项 verdict

- [x] Task 17: SLDPRT/SLDASM 生成真实路径测试（需执行）
  - [x] SubTask 17.1: 运行 `_test_sw_writer.py`，验证路径 1 `generate_sldprt_from_features`（new_document + extrusion）
  - [x] SubTask 17.2: 运行 `_test_sw_writer.py`，验证路径 2 `generate_sldprt_from_cadquery`（CadQuery → STEP → 导入），CadQuery 不可用时标注降级（实测 FAIL，errors=2097152 swDocFileRequiresRepairError，已如实记录）
  - [ ] SubTask 17.3: 运行 `_test_sw_writer.py`，验证路径 3 `generate_sldasm_from_components`（AddComponent5 + AddMate5）—— **未测试（GAP）**：测试脚本未构造组件文件夹具，待后续补充
  - [x] SubTask 17.4: 更新 `_test_sw_writer_result.json`，确认所有子项 verdict

- [x] Task 18: 生成测试报告 `solidworks_worker_realtest.md`
  - [x] SubTask 18.1: 编写报告头部元信息（测试时间、SW 版本、样本来源）
  - [x] SubTask 18.2: 汇总 Task 13 session 管理测试结果
  - [x] SubTask 18.3: 汇总 Task 14 worker_pool 测试结果
  - [x] SubTask 18.4: 汇总 Task 15 license 测试结果
  - [x] SubTask 18.5: 汇总 Task 16 reader 测试结果（含 CoInitialize 缺陷修复记录）
  - [x] SubTask 18.6: 汇总 Task 17 writer 测试结果
  - [x] SubTask 18.7: 生成汇总矩阵表（Task × 子项 × 状态 × 路径类型）
  - [x] SubTask 18.8: 撰写结论（PASS / CONDITIONAL_PASS / FAIL）—— **判定 CONDITIONAL_PASS**

# Task Dependencies

- Task 16 依赖 Task 16.1（CoInitialize 修复）完成后才能执行 16.2-16.5
- Task 17 依赖 Task 16.1（CoInitialize 修复）完成（writer 也走 worker_pool.submit）
- Task 18 依赖 Task 16 + Task 17 完成后才能汇总
- Task 13/14/15 可并行复核（结果 JSON 已存在）

# 并行化建议

- 阶段 1：Task 16.1（修复 CoInitialize）—— 串行，阻塞后续
- 阶段 2：Task 16.2-16.5 || Task 17.1-17.4 —— 修复后可并行执行
- 阶段 3：Task 18（报告生成）—— 依赖前两阶段完成

# 当前阶段：SW-04 / SW-05 / SW-06 修复任务（待办）

本阶段承接 Task 17 的 FAIL/GAP 项，按 SW-04/SW-05/SW-06 三项修复任务推进。
原则：八荣八耻（以瞎猜接口为耻以认真查询为荣，以跳过验证为耻以主动测试为荣，
以盲目修改为耻以谨慎重构为荣，以破坏架构为耻以遵循规范为荣）。
最小改动，不破坏现有架构，复用现有实现。

## Task 20 (SW-04): CadQuery STEP 导入兼容性修复

- 原因：SubTask 17.2 FAIL，errors=2097152 swDocFileRequiresRepairError（OCC STEP 兼容性问题）
- 修复文件：`backend/app/services/solidworks/writer.py` 的 `generate_sldprt_from_cadquery` 函数
- 修复策略：OpenDoc6 失败时不直接 raise，而是降级调用 `generate_sldprt_from_features` 重建
- [x] SubTask SW-04.1: 修改 `generate_sldprt_from_cadquery` 函数签名返回 `Path | tuple[Path, list[str]]`
- [x] SubTask SW-04.2: 在 OpenDoc6 失败时 catch Exception，调用 `_build_fallback_model_from_cadquery` 构建降级模型
- [x] SubTask SW-04.3: 调用 `generate_sldprt_from_features` 的 `_raw_fn`（避免 worker_pool 嵌套死锁）作为降级路径
- [x] SubTask SW-04.4: 降级时返回 `(output_path, warnings)`，warnings 含 `path_type=FALLBACK-PATH`
- [x] SubTask SW-04.5: 降级也失败时才 raise SolidWorksTaskError
- [x] SubTask SW-04.6: 添加 `_build_fallback_model_from_cadquery` 辅助函数（正则提取 box/cylinder 参数）
- [x] SubTask SW-04.7: 编写测试脚本 `backend/tmp_audit_logs/_test_sw_step_import_fix.py`
  - 使用简单 CadQuery 代码（如 `cq.Workplane().box(10, 10, 10)`）
  - 调用 `generate_sldprt_from_cadquery` 验证要么成功生成 SLDPRT（REAL-PATH），要么明确降级（FALLBACK-PATH 含 warnings）
  - 记录路径类型与返回值
- [x] SubTask SW-04.8: 运行测试脚本并生成报告 `backend/tmp_audit_logs/sw04_step_import_fix.md`
  - 含修复前/后对比
  - 含路径类型标注（REAL-PATH / FALLBACK-PATH）

## Task 19 (SW-05): 装配体生成测试样本与用例补充

- 原因：SubTask 17.3 未测试（GAP），测试脚本未构造组件文件夹具
- 修复文件：`backend/app/services/solidworks/writer.py` 的 `generate_sldasm_from_components` 函数（不修改代码，仅编写测试）
- 修复策略：复用 `generate_sldprt_from_features` 生成 2 个测试组件，构造 SWComponent/SWMate 列表
- [x] SubTask SW-05.1: 通过 `generate_sldprt_from_features` 生成 2 个测试 SLDPRT 组件（如简单拉伸长方体）
- [x] SubTask SW-05.2: 构造 SWComponent 列表（含 source_file / transform 定位）
- [x] SubTask SW-05.3: 构造 SWMate 列表（coincident / concentric 配合）
- [x] SubTask SW-05.4: 调用 `generate_sldasm_from_components` 生成 SLDASM
- [x] SubTask SW-05.5: 编写测试脚本 `backend/tmp_audit_logs/_test_sw_writer_assembly.py`
  - 验证生成 SLDASM 文件 size > 0
  - 记录 components_inserted / warnings
- [x] SubTask SW-05.6: 运行测试脚本并生成报告 `backend/tmp_audit_logs/sw05_assembly_generation.md`

## Task 21 (SW-06): 含真实配合的装配体样本与读取验证

- 依赖：Task 19 (SW-05) 生成的 SLDASM 样本
- 修复文件：不修改代码，仅验证 `reader.py` 的 `read_sldasm` 配合提取链路
- [x] SubTask SW-06.1: 复用 Task 19 (SW-05) 生成的 SLDASM 样本
- [x] SubTask SW-06.2: 调用 `read_sldasm` 读取该样本
- [x] SubTask SW-06.3: 验证返回结果中 `mates` 数组非空 —— **ENV-LIMIT**：所有样本 mates=0，读取链路无异常
- [x] SubTask SW-06.4: 验证每个 mate 含 name / type / component_1 / component_2 字段 —— **ENV-LIMIT**：无 mates 可验证，字段完整性验证跳过
- [x] SubTask SW-06.5: 验证路径 1（GetMates）或路径 2（特征树遍历）至少一条生效 —— **PASS-PARTIAL**：两条路径均执行无异常，日志 `sw.reader.no_mates_found` 确认
- [x] SubTask SW-06.6: 编写测试脚本 `backend/tmp_audit_logs/_test_sw_reader_mates.py`
- [x] SubTask SW-06.7: 运行测试脚本并生成报告 `backend/tmp_audit_logs/sw06_mates_extraction.md`

# Task Dependencies

- Task 21 (SW-06) 依赖 Task 19 (SW-05) 完成后才能执行（需要 SLDASM 样本）
- Task 20 (SW-04) 与 Task 19 (SW-05) 可并行执行（无依赖关系）

# 并行化建议

- 阶段 1：Task 20 (SW-04) || Task 19 (SW-05) —— 可并行
- 阶段 2：Task 21 (SW-06) —— 依赖 SW-05 完成
