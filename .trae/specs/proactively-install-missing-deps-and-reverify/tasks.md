# Tasks

本任务清单对照 spec.md 拆解"主动安装缺失依赖并重新完整验证"工作。任务按"先确认实际状态 → 主动安装/修复 → 重新验证真实路径 → 如实更新报告"的串行依赖链组织。

## 阶段一：实际状态确认（前置门控）

- [x] Task 1: 全面盘点代码中实际使用但未在 requirements.txt 的依赖
  - [x] SubTask 1.1: grep 全代码库 `import` 语句，列出所有第三方包
  - [x] SubTask 1.2: 对比 `backend/requirements.txt`，标记 MISSING（代码用但未列）与 UNUSED（列出但代码未用）
  - [x] SubTask 1.3: 对每个 MISSING 包，`python -c "import X"` 验证当前是否实际可导入
  - [x] SubTask 1.4: 记录结果到 `backend/tmp_audit_logs/missing_deps_audit.md`

## 阶段二：主动安装缺失依赖

- [x] Task 2: 主动安装 ultralytics（YOLOv11 区域检测真实路径）
  - [x] SubTask 2.1: `pip install ultralytics`（Windows + Python 3.13 兼容性确认）
  - [x] SubTask 2.2: 验证 `from ultralytics import YOLO` 可导入
  - [x] SubTask 2.3: 验证 `YOLO("yolo11n.pt")` 可加载（自动下载预训练权重）
  - [x] SubTask 2.4: 将 `ultralytics` 加入 `backend/requirements.txt`，版本号用 `pip show` 获取
  - [x] SubTask 2.5: 若安装失败，记录根因（命令输出 + 异常堆栈），不得仅标 ENV-LIMIT

- [x] Task 3: 主动安装 playwright（HTML→PDF 真实路径）
  - [x] SubTask 3.1: `pip install playwright`（Windows + Python 3.13 兼容性确认）
  - [x] SubTask 3.2: `python -m playwright install chromium` 拉取浏览器
  - [x] SubTask 3.3: 验证 `from playwright.sync_api import sync_playwright` 可导入
  - [x] SubTask 3.4: 验证 `p.chromium.launch()` 可启动 headless 浏览器
  - [x] SubTask 3.5: 将 `playwright` 加入 `backend/requirements.txt`
  - [x] SubTask 3.6: 若安装失败，记录根因，不得仅标 ENV-LIMIT

- [x] Task 4: 复核其他 MISSING 包（如 psycopg2-binary / Pillow 等基础包）
  - [x] SubTask 4.1: 对 Task 1.4 列出的每个 MISSING 包，主动 `pip install`
  - [x] SubTask 4.2: 验证导入成功
  - [x] SubTask 4.3: 加入 `requirements.txt`（若未列）
  - [x] SubTask 4.4: 若某包安装失败，记录根因后可标注 ENV-LIMIT（需附命令输出）

## 阶段三：修复被降级掩盖的代码 bug

- [x] Task 5: 修复 `version_manager.py:_convert_dsn` bug
  - [x] SubTask 5.1: 阅读现有 `_convert_dsn` 实现，确认 `u.lstrip('/')` 误用
  - [x] SubTask 5.2: 修正为 `u.path.lstrip('/')`，并增加类型注释与单元测试用例
  - [x] SubTask 5.3: 验证修复后 `StandardVersionManager().backend_name == "postgres"`（不再降级到 JSON）
  - [x] SubTask 5.4: 验证 `register_version` / `list_versions` / `get_latest_version` 真实写入 PostgreSQL（查表 `standard_versions`）
  - [x] SubTask 5.5: 验证 `notify_subscribers` 真实写入 PostgreSQL（查表 `standard_notifications`）
  - [x] SubTask 5.6: 记录修复过程与重测结果到 `backend/tmp_audit_logs/version_manager_bugfix.md`

- [x] Task 6: 全代码库扫描类似的"误降级"bug
  - [x] SubTask 6.1: grep 所有 `except.*RuntimeError` / `except.*ImportError` 后立即降级的模式
  - [x] SubTask 6.2: 逐个审查降级触发条件是否包含代码 bug（而非真实环境缺失）
  - [x] SubTask 6.3: 发现的 bug 逐个修复并记录

## 阶段四：重新验证所有曾降级的真实路径

- [x] Task 7: YOLOv11 区域检测真实路径验证
  - [x] SubTask 7.1: 准备测试图片（使用 backend/tmp_test_images/ 下的工程图样本）
  - [x] SubTask 7.2: 调用 `region_detector.detect_regions(image_path)` 验证返回非空 `list[Region]` 且 `source == "yolov11"`
  - [x] SubTask 7.3: 验证 `is_detector_available()` 返回 True
  - [x] SubTask 7.4: 记录到 `backend/tmp_audit_logs/yolov11_realpath_test.md`

- [x] Task 8: HTML→PDF 真实路径验证（playwright 后端）
  - [x] SubTask 8.1: 准备测试 HTML（复用 `_build_report_data` 生成的样本）
  - [x] SubTask 8.2: 调用 `generate_pdf_report(html_path)` 显式 `PDF_BACKEND=playwright`
  - [x] SubTask 8.3: 验证返回非 None 且 PDF 文件 size > 0
  - [x] SubTask 8.4: 用 `PyPDF2` 或 `pdfplumber` 验证 PDF 内容可读
  - [x] SubTask 8.5: 记录到 `backend/tmp_audit_logs/pdf_playwright_realpath_test.md`

- [x] Task 9: 版本管理器 PostgreSQL 真实路径验证
  - [x] SubTask 9.1: 复用 Task 5 的修复后代码
  - [x] SubTask 9.2: 验证 `StandardVersionManager` / `UpdateNotifier` 全部走 PostgreSQL 后端
  - [x] SubTask 9.3: 调用 KB API 端点验证端到端可用
  - [x] SubTask 9.4: 记录到 `backend/tmp_audit_logs/version_manager_pg_realpath_test.md`

- [x] Task 10: 其他降级路径复核
  - [x] SubTask 10.1: 复核 `report.py` 的 weasyprint/wkhtmltopdf/xhtml2pdf 后端是否真实可用（至少实测一路）
  - [x] SubTask 10.2: 复核 `vlm_ocr.py` 的 VLM 调用是否真实成功（非降级到空 dict）
  - [x] SubTask 10.3: 复核 `region_detector.py` 在 ultralytics 已安装但权重缺失时仍能优雅降级到 VLM
  - [x] SubTask 10.4: 记录到 `backend/tmp_audit_logs/other_realpath_recheck.md`

## 阶段五：如实更新交付报告

- [x] Task 11: 更新 `dependency_check.md`
  - [x] SubTask 11.1: 在原报告末尾追加"二次复核与主动修复"章节
  - [x] SubTask 11.2: 如实列出之前误标 INSTALLED/PASS 但实际未实测的项
  - [x] SubTask 11.3: 如实列出本次主动安装的包与版本
  - [x] SubTask 11.4: 如实列出本次修复的代码 bug 与重测结果

- [x] Task 12: 更新 `final_acceptance_report.md`
  - [x] SubTask 12.1: 在"环境限制清单"中移除被本次修复推翻的 ENV-LIMIT 项（如版本管理器 PostgreSQL 降级）
  - [x] SubTask 12.2: 在"已修复问题"中追加本次修复的 bug 与重测证据
  - [x] SubTask 12.3: 在"特别提醒用户"章节如实说明之前的敷衍标注已纠正
  - [x] SubTask 12.4: 复核结论 PASS 是否仍成立（若新增 bug 影响判定，实事求是降级）

- [x] Task 13: 回填相关 spec 的 checklist 复核结论
  - [x] SubTask 13.1: 在 `complete-final-acceptance-and-fix/checklist.md` 中标注哪些项因本次复核而"实质未完成 → 已纠正"
  - [x] SubTask 13.2: 在 `fix-remaining-issues-and-upgrade-to-pass/checklist.md` 中同上标注
  - [x] SubTask 13.3: 不删除原勾选记录，追加"复核纠正"备注以保留追溯

# Task Dependencies

- Task 1（盘点）→ 所有后续 Task
- Task 2/3/4（主动安装）可并行，依赖 Task 1 完成
- Task 5（修复 bug）独立于 Task 2-4，可并行
- Task 6（扫描类似 bug）依赖 Task 5 完成（参考修复模式）
- Task 7/8/9/10（真实路径验证）依赖对应 Task 2/3/4/5 完成
- Task 11/12（报告更新）依赖 Task 7-10 全部完成
- Task 13（spec 回填）依赖 Task 11/12 完成

# 并行化建议

- 第一波（并行）：Task 1（盘点）
- 第二波（并行）：Task 2（ultralytics）|| Task 3（playwright）|| Task 4（其他包）|| Task 5（修复 bug）
- 第三波（串行）：Task 6（扫描类似 bug）
- 第四波（并行）：Task 7（YOLOv11 验证）|| Task 8（PDF 验证）|| Task 9（版本管理验证）|| Task 10（其他复核）
- 第五波（串行）：Task 11 → Task 12 → Task 13

# 阶段门控

1. Task 1 盘点必须基于 `grep` 实测，不得仅凭记忆
2. Task 2-4 安装必须实测执行 `pip install`，失败时记录命令输出，不得仅标 ENV-LIMIT
3. Task 5 修复必须遵循"谨慎重构"原则，最小改动，不破坏架构
4. Task 7-10 真实路径验证必须真实调用，不得仅单元测试
5. Task 11-12 报告更新必须实事求是，不可将"代码 bug 掩盖的降级"误标为 ENV-LIMIT
6. Task 13 spec 回填必须保留追溯，不删除原勾选记录
