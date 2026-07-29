# Checklist

本 checklist 对照 spec.md 与 tasks.md 的阶段门控要求，列出所有验证检查点。每个检查点必须基于真实证据（命令输出/文件存在/日志记录），不得仅凭代码改动或主观断言。

## 阶段一：实际状态确认

- [x] `backend/tmp_audit_logs/missing_deps_audit.md` 存在且包含全代码库 `import` grep 结果
- [x] MISSING 包清单与 `requirements.txt` 对比结果记录在案
- [x] 每个 MISSING 包的 `python -c "import X"` 实测输出记录在案

## 阶段二：主动安装缺失依赖

### ultralytics
- [x] `pip install ultralytics` 命令输出记录（成功/失败 + 完整日志）
- [x] `from ultralytics import YOLO` 导入成功
- [x] `YOLO("yolo11n.pt")` 实例化成功（自动下载权重日志可见）
- [x] `backend/requirements.txt` 新增 `ultralytics==<version>` 行
- [x] 若安装失败，根因记录完整（命令输出 + 异常堆栈），且尝试过至少 2 种安装方式（如 `--only-binary` / `--pre` / conda）

### playwright
- [x] `pip install playwright` 命令输出记录
- [x] `python -m playwright install chromium` 命令输出记录（浏览器下载日志可见）
- [x] `from playwright.sync_api import sync_playwright` 导入成功
- [x] `p.chromium.launch()` 启动 headless 浏览器成功
- [x] `backend/requirements.txt` 新增 `playwright==<version>` 行
- [x] 若安装失败，根因记录完整

### 其他 MISSING 包
- [x] 每个 MISSING 包的安装命令输出记录
- [x] 导入验证成功
- [x] `requirements.txt` 已补充（或确认已在列）
- [x] 失败项有完整根因记录

## 阶段三：修复被降级掩盖的代码 bug

### version_manager._convert_dsn
- [x] 原代码 `u.lstrip('/')` 误用已确认（grep 输出 + 行号）
- [x] 修复后代码使用 `u.path.lstrip('/')` 且有类型注释
- [x] `StandardVersionManager().backend_name == "postgres"` 实测通过
- [x] `register_version` 真实写入 PostgreSQL（`SELECT * FROM standard_versions` 查询结果）
- [x] `list_versions` 真实读取 PostgreSQL
- [x] `get_latest_version` 真实读取 PostgreSQL
- [x] `notify_subscribers` 真实写入 `standard_notifications` 表
- [x] `backend/tmp_audit_logs/version_manager_bugfix.md` 包含修复前后对比与重测证据

### 类似 bug 扫描
- [x] grep 全代码库 `except.*RuntimeError` / `except.*ImportError` 降级模式输出记录
- [x] 每个降级点的审查结论记录在案（真实环境缺失 / 代码 bug / 误降级）
- [x] 发现的 bug 逐个修复并有重测证据

## 阶段四：重新验证所有曾降级的真实路径

### YOLOv11 区域检测
- [x] 测试图片路径与文件存在性记录
- [x] `is_detector_available()` 返回 True
- [x] `detect_regions(image_path)` 返回非空 `list[Region]`
- [x] 至少一个 Region 的 `source == "yolov11"`
- [x] `backend/tmp_audit_logs/yolov11_realpath_test.md` 包含测试结果

### HTML→PDF（playwright 后端）
- [x] 测试 HTML 文件路径与文件存在性记录
- [x] `generate_pdf_report(html_path)` 显式 `PDF_BACKEND=playwright` 调用成功
- [x] 返回的 PDF 文件路径存在且 size > 0
- [x] PDF 内容可读（`pdfplumber.open()` 或 `PyPDF2.PdfReader()` 验证）
- [x] `backend/tmp_audit_logs/pdf_playwright_realpath_test.md` 包含测试结果

### 版本管理器 PostgreSQL
- [x] `StandardVersionManager` 与 `UpdateNotifier` 的 `backend_name == "postgres"`
- [x] KB API 端点 `/api/v1/kb/standards/{id}/versions` 真实调用返回 200
- [x] KB API 端点 `/api/v1/kb/standards/{id}/notifications` 真实调用返回 200
- [x] `backend/tmp_audit_logs/version_manager_pg_realpath_test.md` 包含端到端测试结果

### 其他降级路径复核
- [x] `report.py` 的 weasyprint/wkhtmltopdf/xhtml2pdf 至少一路实测通过（非 playwright）
- [x] `vlm_ocr.py` 的 VLM 调用至少一次真实成功（非降级到空 dict）
- [x] `region_detector.py` 在 ultralytics 已安装但权重缺失时优雅降级到 VLM（日志可见）
- [x] `backend/tmp_audit_logs/other_realpath_recheck.md` 包含复核结果

## 阶段五：如实更新交付报告

### dependency_check.md
- [x] 末尾追加"二次复核与主动修复"章节
- [x] 如实列出之前误标 INSTALLED/PASS 但实际未实测的项
- [x] 如实列出本次主动安装的包与版本（含安装命令输出引用）
- [x] 如实列出本次修复的代码 bug 与重测结果（含 file:line 引用）

### final_acceptance_report.md
- [x] "环境限制清单"中移除被本次修复推翻的 ENV-LIMIT 项
- [x] "已修复问题"中追加本次修复的 bug 与重测证据
- [x] "特别提醒用户"章节如实说明之前的敷衍标注已纠正
- [x] 结论 PASS/CONDITIONAL_PASS 经复核仍成立（或实事求是降级）

### spec 回填
- [x] `complete-final-acceptance-and-fix/checklist.md` 中标注复核纠正项（不删除原勾选）
- [x] `fix-remaining-issues-and-upgrade-to-pass/checklist.md` 中标注复核纠正项（不删除原勾选）
- [x] 每个纠正项有"原勾选依据 → 复核发现 → 纠正结论"三段式记录

## 总体门控

- [x] 所有检查点均有真实证据（命令输出/文件存在/日志记录），无主观断言
- [x] 所有"已修复"项均有重测证据，无仅凭代码改动即标注
- [x] 所有"ENV-LIMIT"项均有可复现的失败证据，无误降级掩盖
- [x] 报告中如实承认之前的敷衍标注，不掩饰
- [x] 用户原始诉求"主动安装缺失依赖"已实质性完成（ultralytics / playwright 等已真实可用）
