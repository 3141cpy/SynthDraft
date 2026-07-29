# SolidWorks Worker 真实路径测试执行 Spec

## Why

SynthDraft 项目的 SolidWorks Worker 模块（session/worker_pool/license/reader/writer）已完成开发与离线自检，但缺少一份**基于真实 SolidWorks 实例的端到端真实路径测试报告**。现有测试脚本（`backend/tmp_audit_logs/_test_sw_*.py`）已覆盖 Tasks 13-15（session/worker_pool/license），但 Task 16（reader）因 `CoInitialize` 错误失败，Task 17（writer）脚本已创建但未执行，Task 18（测试报告）尚未生成。

根本原因：`worker_pool.py` 的 `submit` 方法在新线程中执行任务，但未在该线程调用 `pythoncom.CoInitialize()`，导致 SolidWorks COM STA 调用报"尚未调用 CoInitialize"。

本 spec 旨在：
1. 修复 `CoInitialize` 缺陷，使 reader/writer 真实路径测试可执行
2. 执行 Task 16（SLDPRT/SLDASM 读取）+ Task 17（SLDPRT/SLDASM 生成）真实路径测试
3. 生成 Task 18 测试报告 `solidworks_worker_realtest.md`

遵循"以跳过验证为耻，以主动测试为荣；以瞎猜接口为耻，以查阅文档为荣"原则。

## What Changes

- **修复缺陷**：`backend/app/services/solidworks/worker_pool.py` 的 `submit` 方法内部线程 `_run` 增加 `pythoncom.CoInitialize()` / `CoUninitialize()` 调用
- **执行 Task 16**：运行 `_test_sw_reader.py`，验证 `read_sldprt` / `read_sldasm` 真实读取 SolidWorks 自带样本文件（Part.SLDPRT / Assembly.SLDASM / shaftcutnormal.sldprt），提取特征树/尺寸/形位公差/表面粗糙度/技术要求/自定义属性/组件/配合/BOM/质量属性
- **执行 Task 17**：运行 `_test_sw_writer.py`，验证三条生成路径：
  - 路径 1：`generate_sldprt_from_features`（new_document + 特征重建）
  - 路径 2：`generate_sldprt_from_cadquery`（CadQuery → STEP → 导入）
  - 路径 3：`generate_sldasm_from_components`（AddComponent5 + AddMate5）
- **生成 Task 18**：测试报告 `backend/tmp_audit_logs/solidworks_worker_realtest.md`，汇总 Tasks 13-18 全部测试结果

## Impact

- Affected specs: 无（本 spec 是测试执行性 spec，仅修复一个阻塞缺陷）
- Affected code: `backend/app/services/solidworks/worker_pool.py`（仅 `submit` 方法内部 `_run` 函数增加 COM 初始化）
- Affected docs: 新增 `backend/tmp_audit_logs/solidworks_worker_realtest.md`
- 测试样本: SolidWorks 自带样本（Part.SLDPRT / Assembly.SLDASM / shaftcutnormal.sldprt）

## ADDED Requirements

### Requirement: Worker 线程 COM 公寓初始化

`SolidWorksWorkerPool.submit` 在新线程中执行任务时 SHALL 在线程入口调用 `pythoncom.CoInitialize()`，在线程退出前调用 `pythoncom.CoUninitialize()`，确保 SolidWorks COM STA 调用可用。

#### Scenario: 任务线程 COM 初始化

- **WHEN** 调用 `pool.submit(task_fn, ...)` 在新线程执行任务
- **THEN** 线程入口 SHALL 调用 `pythoncom.CoInitialize()`
- **AND** 线程退出前 SHALL 调用 `pythoncom.CoUninitialize()`
- **AND** 任务函数内 `session.open_document()` / `session.new_document()` 等 COM 调用不再报"尚未调用 CoInitialize"

#### Scenario: 非 Windows 平台降级

- **WHEN** `pythoncom` 不可用（Linux/无 pywin32）
- **THEN** SHALL 跳过 CoInitialize 调用，不影响降级路径
- **AND** 不抛异常

### Requirement: Task 16 SLDPRT/SLDASM 读取真实路径测试

系统 SHALL 对 `reader.py` 的 `read_sldprt` / `read_sldasm` 执行真实路径测试，使用 SolidWorks 自带样本文件验证提取项完整性。

#### Scenario: read_sldprt 真实读取

- **WHEN** 调用 `read_sldprt(session, Part.SLDPRT)`
- **THEN** SHALL 返回 `SolidWorksModel`（doc_type="part"）
- **AND** `features` 数组非空（含特征树遍历结果）
- **AND** `dimensions` / `geometric_tolerances` / `surface_finishes` / `custom_properties` / `mass_properties` 字段已填充（可为空数组但字段存在）
- **AND** 不可仅因函数返回即 PASS，需验证提取内容非空

#### Scenario: read_sldasm 真实读取

- **WHEN** 调用 `read_sldasm(session, Assembly.SLDASM)`
- **THEN** SHALL 返回 `SolidWorksModel`（doc_type="assembly"）
- **AND** `components` 数组非空（含组件树）
- **AND** `mates` / `bom_items` 字段已填充

### Requirement: Task 17 SLDPRT/SLDASM 生成真实路径测试

系统 SHALL 对 `writer.py` 的三条生成路径执行真实路径测试，验证生成文件真实存在且非空。

#### Scenario: 路径 1 new_document + 特征重建

- **WHEN** 调用 `generate_sldprt_from_features(session, model, output_path)`，model 含一个 extrusion 特征
- **THEN** SHALL 返回生成的 SLDPRT 文件路径
- **AND** 文件真实存在且 size > 0
- **AND** 记录生成耗时

#### Scenario: 路径 2 CadQuery → STEP → 导入

- **WHEN** 调用 `generate_sldprt_from_cadquery(session, code, output_path)`，code 为简单长方体 CadQuery 代码
- **THEN** SHALL 返回生成的 SLDPRT 文件路径
- **AND** 文件真实存在且 size > 0
- **AND** 若 CadQuery 沙箱不可用需明确标注降级

#### Scenario: 路径 3 装配体生成

- **WHEN** 调用 `generate_sldasm_from_components(session, components, output_path, mates)`
- **THEN** SHALL 返回生成的 SLDASM 文件路径
- **AND** 文件真实存在且 size > 0

### Requirement: Task 18 测试报告

报告 `solidworks_worker_realtest.md` SHALL 包含以下结构：

1. **头部元信息**：测试时间、SolidWorks 版本、样本文件来源
2. **逐 Task 测试记录**（Tasks 13-18）：
   - Task 13：session 管理（已完成的 `_test_sw_session_result.json` 汇总）
   - Task 14：worker_pool 并发控制（已完成的 `_test_sw_worker_pool_result.json` 汇总）
   - Task 15：license 管理（已完成的 `_test_sw_license_result.json` 汇总）
   - Task 16：reader 真实路径测试（本次执行）
   - Task 17：writer 真实路径测试（本次执行）
   - Task 18：本报告本身
3. **汇总表**：Task × 子项 × 状态 × 路径类型 矩阵
4. **缺陷修复记录**：CoInitialize 缺陷的根因与修复
5. **结论**：总体 PASS / CONDITIONAL_PASS / FAIL

## MODIFIED Requirements

无

## REMOVED Requirements

无
