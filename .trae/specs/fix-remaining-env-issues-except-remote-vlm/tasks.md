# Tasks

## 阶段一: 代码层修复(并行)

- [x] Task 1: 草图 VLM 尺寸幻觉修复(prompt + 后处理 + bbox 统一)
  - 依赖: 无(独立可并行)
  - SubTask 1.1: 优化 `_SKETCH_PARSE_PROMPT`
    - 在 prompt 中增加尺寸约束示例,明确要求 `parameters.radius` 必须等于 `dimensions_hint["外径"]/2`
    - 明确要求 `parameters.thickness` 必须等于 `dimensions_hint["厚度"]`(若存在)
    - 增加 few-shot 示例: 输入"外圆 φ100",输出 `{"radius": 50, ...}`, `dimensions_hint: {"外径": 100}`
  - SubTask 1.2: 在 `parse_sketch` 中增加后处理校验函数 `_validate_sketch_dimensions`
    - 比对 `parameters.radius` 与 `dimensions_hint["外径"]/2`(若存在),偏差超 20% 标 warning + confidence 降至 0.3
    - 比对 `parameters.thickness` 与 `dimensions_hint["厚度"]`(若存在),偏差超 20% 标 warning + confidence 降至 0.3
    - 在 `SketchParseResult.warnings` 中追加具体偏差信息
  - SubTask 1.3: 统一 bbox 格式
    - 在 `sketch_parser` 中新增 `_convert_bbox_xyxy_to_xywh(bbox)` 函数
    - 检测 bbox 是否为 `[x1,y1,x2,y2]` 格式(满足 x2>x1, y2>y1 单调性 + x2<=1, y2<=1)
    - 若是,转换为 `[x,y,w,h]` 后再传给 `_normalize_bbox`
    - 或修改 prompt 改为要求 `[x,y,w,h]` 格式(需评估对 VLM 输出准确率影响)
  - SubTask 1.4: 真实测试验证
    - 用 25_sketch_vlm_dimension_retest.md 的草图样本重测
    - 验证: 优化后 VLM 返回 radius 是否更接近 50(可能仍偏差,但 warning 应正确触发)
    - 验证: bbox 转换后 `_normalize_bbox` 输出正确
    - 输出 `tmp_audit_logs/31_sketch_vlm_fix.md`
  - 验证标准: warning 在尺寸偏差超阈值时正确触发;bbox 格式统一后语义正确;不可仅因"VLM 返回非空"即 PASS

- [x] Task 2: WeasyPrint PDF 生成修复
  - 依赖: 无(独立可并行)
  - SubTask 2.1: 审查 `app/services/review/report.py` 的 `generate_pdf_report()` 当前实现
  - SubTask 2.2: 探测可用的 PDF 后端(按优先级):
    - 探测 1: MSYS2 + GTK 是否可安装(`where pacman` / `where gtk3-demo`)
    - 探测 2: `pdfkit` + `wkhtmltopdf`(`pip show pdfkit` + `where wkhtmltopdf`)
    - 探测 3: `playwright`(`pip show playwright` + `python -c "from playwright.sync_api import sync_playwright"`)
  - SubTask 2.3: 基于探测结果实现 PDF 后端:
    - 方案 A (优先): 若 weasyprint 原生可用 → 保持现状,验证真实生成 PDF
    - 方案 B: 若 wkhtmltopdf 可用 → 新增 `_generate_pdf_via_wkhtmltopdf(html_path, output_path)` 函数
    - 方案 C: 若 playwright 可用 → 新增 `_generate_pdf_via_playwright(html_path, output_path)` 函数
    - 方案 D: 全部不可用 → 正式声明延后(含探测证据)
  - SubTask 2.4: 修改 `generate_pdf_report()` 支持多后端:
    - 读取 `settings.PDF_BACKEND`(新增配置,默认 "weasyprint")
    - 按配置调用对应后端;失败时降级到下一个可用后端
    - 全部失败时返回 None + warning(保持现有降级语义)
  - SubTask 2.5: 在 `app/config.py` 新增 `PDF_BACKEND` 字段(值域: weasyprint/wkhtmltopdf/playwright)
  - SubTask 2.6: 真实测试验证
    - 用 26_html_vlm_ocr_render.md 的 HTML 报告作为输入
    - 调用 `generate_pdf_report()` 真实生成 PDF
    - 验证: PDF 文件存在 + size > 0 + 可被 `PyPDF2` 或 `pdfplumber` 读取(非损坏)
    - 输出 `tmp_audit_logs/32_weasyprint_pdf_fix.md`
  - 验证标准: 必须真实生成 PDF 文件,不可仅返回 None 降级

- [x] Task 3: embedding bge-m3 加载修复
  - 依赖: 无(独立可并行)
  - SubTask 3.1: 在 `app/services/kb/embedder.py` 的 `_load_model()` 中,加载 bge-m3 前设置 `HF_ENDPOINT`
    - `os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")`
    - 或在 `app/config.py` 新增 `HF_ENDPOINT` 字段(默认 "https://hf-mirror.com")
  - SubTask 3.2: 真实测试 bge-m3 加载
    - 设置 `HF_ENDPOINT=https://hf-mirror.com`
    - 调用 `BGEM3Embedder()` 加载 bge-m3
    - 记录: 加载成功/失败 + 耗时 + backend + vector_size
    - 若成功: 与 nomic-embed-text 对比 5 条查询的 top-5 重叠度
    - 若失败: 尝试 modelscope 镜像(`pip install modelscope` + `modelscope download BAAI/bge-m3`)
  - SubTask 3.3: 输出 `tmp_audit_logs/33_embedding_bge_m3_fix.md`
  - 验证标准: bge-m3 加载成功并完成对比,或正式声明延后(含 HF_ENDPOINT 配置证据 + 失败日志)

## 阶段二: DWG 路径进一步尝试(独立可并行)

- [x] Task 4: DWG 路径进一步尝试
  - 依赖: 无(独立可并行)
  - SubTask 4.1: 探测 LibreCAD dwg2dxf
    - `where dwg2dxf` / `where.exe dwg2dxf`
    - 若 NOT FOUND: 尝试 `winget install LibreCAD` 或 `choco install librecad`
    - 记录命令与结果
  - SubTask 4.2: 探测 ODA File Converter 在线下载
    - WebFetch https://www.opendesign.com/guestfiles/oda_file_converter 获取下载链接
    - 若可下载: 下载并安装到默认路径
    - 记录 URL / 文件大小 / 安装结果
  - SubTask 4.3: 探测 Python 包 `dxfgrabber` / `python-dxf` / `aspose-cad`
    - `pip install aspose-cad`(若可用,支持 DWG 原生解析)
    - `pip install dxfgrabber`(仅 DXF,跳过)
  - SubTask 4.4: 若任一 alternative 可用:
    - 准备真实 DWG 样本(若无样本,用 ezdxf 生成 DXF 后改后缀为 .dwg 作为最小测试样本)
    - 调用 `dwg_to_dxf()` 或 alternative 转换
    - 验证产出 DXF 可被 ezdxf 读取
  - SubTask 4.5: 若所有 alternative 均失败:
    - 在 audit_report.md 12.2 item 1 正式声明"DWG 路径延后"
    - 含每项 alternative 的尝试命令与失败日志
  - SubTask 4.6: 输出 `tmp_audit_logs/34_dwg_path_further.md`
  - 验证标准: 必须有进一步尝试的证据(命令输出/错误日志),不可直接复用上一轮结论

## 阶段三: audit_report.md 同步修正

- [x] Task 5: 修正 audit_report.md 12.2 环境限制清单
  - 依赖: Task 1-4 全部完成
  - SubTask 5.1: 基于 Task 1 结果修正 item 8(草图 VLM 尺寸识别): FAIL → 已修复(含 warning 触发证据) 或 保持 FAIL(含优化后仍偏差的证据)
  - SubTask 5.2: 基于 Task 2 结果修正 WeasyPrint 限制: 新增 item 或修改现有 item,标注 PDF 后端已修复/延后
  - SubTask 5.3: 基于 Task 3 结果修正 item 2(embedding): 未对比 → 已对比(bge-m3 vs nomic 重叠率) 或 保持未对比(含 HF mirror 失败证据)
  - SubTask 5.4: 基于 Task 4 结果修正 item 1(DWG): 未测试 → 已测试(含真实转换证据) 或 保持延后(含新的尝试证据)
  - SubTask 5.5: 补登"第三轮环境问题修复对照表"章节
  - SubTask 5.6: 修正最终验收结论
  - 验证标准: 不可继续使用"待补"等模糊表述

## 阶段四: checklist.md 与 tasks.md 同步

- [x] Task 6: 创建 checklist.md 并逐项验证
  - 依赖: Task 5 完成
  - SubTask 6.1: 创建 checklist.md 覆盖本 spec 所有 Requirement
  - SubTask 6.2: 逐项验证 checkpoint,基于真实证据打勾
  - SubTask 6.3: 未真正通过的 checkpoint 必须改为未打勾并标注原因
  - 验证标准: 每个打勾项必须有真实证据(日志+产出文件)支撑
  - 完成证据: checklist.md 已更新,51 项 checkpoint 中 46 项 [x] + 5 项 [ ](N/A,条件未触发) + 0 项证据不足;每项 [x] 附"证据:"行引用具体文件路径+行号+测试输出

## Task Dependencies

- Task 1 独立(可并行)
- Task 2 独立(可并行)
- Task 3 独立(可并行)
- Task 4 独立(可并行)
- Task 5 依赖 Task 1-4 全部完成
- Task 6 依赖 Task 5 完成

## 并行执行建议

阶段一+二(Task 1-4)可并行启动 3 个 sub-agent:
- Sub-Agent A: Task 1(草图 VLM 尺寸修复) + Task 4(DWG 路径)
- Sub-Agent B: Task 2(WeasyPrint PDF 修复)
- Sub-Agent C: Task 3(embedding bge-m3 修复)

阶段三+四(Task 5-6)必须在阶段一+二全部完成后串行执行。
