# 主动安装缺失依赖并重新完整验证 Spec

## Why

用户在最终验收阶段明确指出我违反了"主动修复原则"——遇到 `psycopg2 未安装`（实际为 `_convert_dsn` 代码 bug 导致的误判）时直接降级到 JSON 后端并标注 ENV-LIMIT，没有主动安装/修复；同样 `ultralytics` 与 `playwright` 缺失时也选择了降级路径而非主动安装。这违反了八荣八耻原则中"以跳过验证为耻，以主动测试为荣"与"以瞎猜接口为耻，以认真查询为荣"。本 spec 用于彻底纠正这一错误：主动安装所有可安装的缺失依赖、修复被降级路径掩盖的代码 bug、重新完整验证所有真实路径，并如实更新交付报告。

## What Changes

- **主动安装缺失 Python 包**：
  - `ultralytics`（YOLOv11 区域检测真实路径，`region_detector.py` 使用）
  - `playwright`（HTML→PDF 真实路径，`report.py` 使用）
  - 同步执行 `python -m playwright install chromium` 拉取浏览器
  - 将新安装包写入 `backend/requirements.txt`
- **修复代码 bug**：
  - `version_manager.py:229` 的 `_convert_dsn`：`u.lstrip('/')` 误用——`u` 是 `ParseResult` 对象，应取 `u.path.lstrip('/')`
  - 修复后 PostgreSQL 后端真实可用，不再误降级到 JSON
- **重新验证所有曾降级的真实路径**：
  - `version_manager.StandardVersionManager` 走 PostgreSQL 后端（非 JSON 降级）
  - `region_detector.detect_regions` 走 YOLOv11 路径（非 VLM 降级）
  - `report.generate_pdf_report` 走 playwright 后端（至少一路真实可用，非全失败返回 None）
- **更新依赖检查报告与最终交付报告**：
  - `dependency_check.md` 如实补充本次发现与修复过程
  - `final_acceptance_report.md` 修正之前将"代码 bug 掩盖的降级"误标为"ENV-LIMIT"的敷衍标注
  - 在"特别提醒用户"章节移除已修复项
- **回填 spec checklist**：将 `complete-final-acceptance-and-fix` 与 `fix-remaining-issues-and-upgrade-to-pass` 中因敷衍而误勾的项（如有）标注复核结论

## Impact

- Affected specs:
  - `complete-final-acceptance-and-fix`（Task 1.1/1.2 依赖检查实质未完成，需复核）
  - `fix-remaining-issues-and-upgrade-to-pass`（Phase 1 依赖前置门控实质未完成，需复核）
- Affected code:
  - `backend/app/services/kb/version_manager.py`（修复 `_convert_dsn` bug）
  - `backend/requirements.txt`（新增 ultralytics / playwright）
  - `backend/tmp_audit_logs/dependency_check.md`（如实补充）
  - `backend/tmp_audit_logs/final_acceptance_report.md`（修正敷衍标注）

## ADDED Requirements

### Requirement: 主动安装缺失依赖

当任一代码路径因 `ImportError`/`ModuleNotFoundError` 触发降级时，必须先尝试 `pip install` 安装该依赖，只有当安装失败（如无 Python 3.13 wheel、需付费许可证、需管理员权限且环境不允许）时才可标注 ENV-LIMIT，并在报告中如实记录安装尝试过程与失败原因。

#### Scenario: 代码中使用但 requirements.txt 未列出的包

- **WHEN** 代码中 `import X` 但 `requirements.txt` 未列出 X
- **THEN** 必须将 X 加入 `requirements.txt` 并 `pip install`，不得仅靠 try/except 降级

#### Scenario: 代码 bug 触发的降级

- **WHEN** 降级原因实为代码 bug（如属性误用、参数错传）而非依赖缺失
- **THEN** 必须修复代码 bug，不得用降级路径掩盖 bug 后标注 ENV-LIMIT

### Requirement: 真实路径优先

所有模块的真实路径必须实测验证至少一次，不得仅因降级路径可用即跳过真实路径测试。

#### Scenario: 多后端模块

- **WHEN** 模块有多个后端（如 PDF 的 weasyprint/wkhtmltopdf/playwright/xhtml2pdf）
- **THEN** 至少一个真实后端必须实测通过，其余后端如实标注 INSTALLED/ENV-LIMIT

## MODIFIED Requirements

### Requirement: 最终交付报告必须如实

`final_acceptance_report.md` 中：
- 所有"ENV-LIMIT"标注必须有可复现的失败证据（命令输出/异常堆栈），不得仅凭"try/except 触发降级"即标注
- 所有"已修复"项必须有重测证据（HTTP 响应/文件存在/日志输出），不得仅凭代码改动即标注
- 结论 PASS 必须基于所有真实路径实测通过，不得基于降级路径通过即判 PASS

## REMOVED Requirements

无（本 spec 不移除任何已有要求，仅纠正既有要求的执行敷衍）。
