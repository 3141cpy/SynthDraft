# 修复剩余环境问题(除远程 VLM API 外)Spec

## Why

上一轮 `complete-remaining-test-gaps` spec 已诚实标注 4 项剩余环境/代码问题,但仅"标注"未"修复"。用户要求针对这些仍存在问题的部分进行优化完善(除远程 VLM API 之外,因无 API Key 已正式声明延后),并特别提到 WeasyPrint 可能也存在问题需要审查完善,最后必须进行实际测试确保问题都已解决。这违反了"以跳过验证为耻,以主动测试为荣"原则——仅声明问题不修复等同于敷衍。

## 待修复问题清单(基于 audit_report.md 12.2 环境限制)

### 问题 1: 草图 VLM 尺寸幻觉(FAIL,代码层可优化)

- 现状: VLM=minicpm-v:latest 对草图尺寸识别存在严重幻觉(radius 期望 50.0 实际 10 偏差 5x, thickness 期望 10.0 实际 2 偏差 5x)
- 根因 1: `_SKETCH_PARSE_PROMPT` 缺乏尺寸约束示例,VLM 返回值与图示标注脱节
- 根因 2: `sketch_parser.parse_sketch` 无后处理校验,未比对 `dimensions_hint` 与 `parameters` 一致性
- 根因 3: bbox 格式约定不一致——`_SKETCH_PARSE_PROMPT` 要求 `[x1,y1,x2,y2]`,但 `vlm_ocr._normalize_bbox` 按 `[x,y,w,h]` 处理,导致语义错误
- 修复方向: 优化 prompt + 后处理校验 + bbox 格式统一

### 问题 2: DWG 路径未测试(环境限制,需进一步尝试)

- 现状: ODA File Converter 未安装 + pyautocad 需 AutoCAD + ezdxf 1.4.4 不支持原生 DWG
- 修复方向: 尝试 LibreCAD dwg2dxf / 在线转换 / 或正式声明延后(若所有 alternative 均失败)

### 问题 3: embedding bge-m3 不可用(环境限制,需修复 SSL/HF mirror)

- 现状: FlagEmbedding 1.4.0 安装但 bge-m3 模型加载失败(SSL + HF mirror 401)
- 修复方向: 配置 HF_ENDPOINT=https://hf-mirror.com 重试 / 或使用 modelscope 镜像 / 或本地下载权重离线加载

### 问题 4: WeasyPrint 缺少 GTK 运行时(PDF 降级到 HTML)

- 现状: `app/services/review/report.py` 中 `generate_pdf_report()` 因 weasyprint 不可用返回 None,PDF 报告功能完全失效
- 根因: WeasyPrint 在 Windows 依赖 GTK 运行时库(pango/cairo/gdk-pixbuf),MSYS2 未安装
- 修复方向: 安装 GTK for Windows (MSYS2) / 或寻找 alternative PDF 生成方案(pdfkit+wkhtmltopdf / playwright headless chromium)

## What Changes

- **修复草图 VLM 尺寸幻觉**:
  - 优化 `_SKETCH_PARSE_PROMPT`: 增加尺寸约束示例,明确要求 `parameters.radius` 必须与 `dimensions_hint` 中"外径"字段一致(外径/2 = 半径)
  - 在 `parse_sketch` 中增加后处理校验: 比对 `parameters` 与 `dimensions_hint`,偏差超 20% 时标记低置信度并附 warning
  - 统一 bbox 格式: 在 `sketch_parser` 中将 `[x1,y1,x2,y2]` 转换为 `[x,y,w,h]` 后再传给 `_normalize_bbox`,或在 prompt 中改为要求 `[x,y,w,h]` 格式
- **DWG 路径进一步尝试**:
  - 尝试下载 LibreCAD 的 dwg2dxf 命令行工具
  - 或尝试 ODA File Converter 在线下载(若网络可达)
  - 若所有 alternative 均失败,正式声明延后(含尝试证据)
- **修复 embedding bge-m3 加载**:
  - 设置 `HF_ENDPOINT=https://hf-mirror.com` 环境变量重试 bge-m3 加载
  - 或尝试 modelscope 镜像(`modelscope` SDK 下载 `BAAI/bge-m3`)
  - 验证: bge-m3 加载成功后,与 nomic-embed-text 对比 top-5 重叠度
- **修复 WeasyPrint PDF 生成**:
  - 优先方案: 安装 MSYS2 + GTK for Windows,使 weasyprint 原生可用
  - 备选方案 1: 改用 `pdfkit` + `wkhtmltopdf`(Windows 原生支持,无需 GTK)
  - 备选方案 2: 改用 `playwright` headless chromium 打印 PDF(已安装 playwright)
  - 验证: 真实生成 PDF 文件,文件大小 > 0,可被 PDF 阅读器打开

## Impact

- Affected specs: `complete-remaining-test-gaps`(环境限制清单更新) / `audit-p0p1-and-extend-ai-providers`(audit_report.md 12.2 修正)
- Affected code:
  - `app/services/generation/sketch_parser.py`(prompt 优化 + 后处理校验 + bbox 格式统一)
  - `app/services/review/vlm_ocr.py`(`_normalize_bbox` 可能需支持 `[x1,y1,x2,y2]` 输入)
  - `app/services/kb/embedder.py`(HF_ENDPOINT 配置 + bge-m3 重试逻辑)
  - `app/services/review/report.py`(`generate_pdf_report` 可能改用 alternative 方案)
  - `app/config.py`(可能新增 PDF_BACKEND / HF_ENDPOINT 配置)
- Affected docs: `audit_report.md` 12.2 环境限制清单(已修复项移除,新增 PASS 证据)

## ADDED Requirements

### Requirement: 草图 VLM 尺寸语义校验与后处理

系统 SHALL 在 `parse_sketch` 返回前增加尺寸语义校验,比对 `parameters` 与 `dimensions_hint`,偏差超阈值时标记低置信度并附 warning。

#### Scenario: VLM 返回尺寸与 dimensions_hint 偏差超 20%

- **WHEN** VLM 返回 `parameters={'radius': 10, 'thickness': 2}`
- **AND** `dimensions_hint={'外径': 100, '厚度': 10}`(期望 radius=50, thickness=10)
- **THEN** 系统 SHALL 检测到 radius 偏差 5x(>20%),thickness 偏差 5x(>20%)
- **AND** 在 `SketchParseResult.warnings` 中追加 `"VLM 尺寸识别偏差超阈值: radius 期望 50.0 实际 10 偏差 5.00x"`
- **AND** 将该 feature 的 `confidence` 降至 0.3 以下
- **AND** 不可仅因"VLM 返回非空"即视为成功

### Requirement: 草图 bbox 格式统一

系统 SHALL 统一 `sketch_parser` 与 `vlm_ocr._normalize_bbox` 的 bbox 格式约定,避免 `[x1,y1,x2,y2]` 被错误地按 `[x,y,w,h]` 处理。

#### Scenario: VLM 返回 [x1,y1,x2,y2] 格式 bbox

- **WHEN** VLM 返回 bbox=`[0.5, 0.49, 0.78, 0.6]`(满足 x2>x1, y2>y1 单调性,判为 [x1,y1,x2,y2])
- **THEN** 系统 SHALL 转换为 `[x, y, w, h]` 格式:`[0.5, 0.49, 0.28, 0.11]`
- **AND** 再传给 `_normalize_bbox` 做钳制
- **AND** 不可直接将 `[x1,y1,x2,y2]` 传给按 `[x,y,w,h]` 处理的函数

### Requirement: WeasyPrint PDF 生成可用性

系统 SHALL 确保 `generate_pdf_report()` 在 Windows 环境下能真实生成 PDF 文件,不可仅返回 None 降级到 HTML。

#### Scenario: WeasyPrint 原生可用

- **WHEN** MSYS2 + GTK 已安装,`from weasyprint import HTML` 不抛异常
- **THEN** `generate_pdf_report()` SHALL 调用 `HTML.write_pdf()` 生成 PDF
- **AND** PDF 文件大小 > 0
- **AND** log.info 记录 `review.report.pdf_done`

#### Scenario: WeasyPrint 不可用时使用 alternative PDF 后端

- **WHEN** WeasyPrint 不可用(缺 GTK)
- **AND** 已配置 `PDF_BACKEND=pdfkit` 或 `PDF_BACKEND=playwright`
- **THEN** 系统 SHALL 调用对应的 alternative 后端生成 PDF
- **AND** 不可仅返回 None 降级到 HTML

### Requirement: embedding bge-m3 加载修复

系统 SHALL 通过配置 `HF_ENDPOINT=https://hf-mirror.com` 或 modelscope 镜像修复 bge-m3 加载失败问题。

#### Scenario: 通过 HF mirror 加载 bge-m3

- **WHEN** 设置 `HF_ENDPOINT=https://hf-mirror.com`
- **AND** 调用 `BGEM3Embedder()` 加载 bge-m3
- **THEN** 加载 SHALL 成功,`backend="bge-m3"`,`vector_size=1024`
- **AND** 与 nomic-embed-text 对比 top-5 重叠度已记录

### Requirement: DWG 路径进一步尝试

系统 SHALL 尝试 LibreCAD dwg2dxf 或 ODA File Converter 下载,若所有 alternative 均失败则正式声明延后(含尝试证据)。

#### Scenario: dwg2dxf 可用

- **WHEN** `where dwg2dxf` 返回有效路径
- **THEN** 系统 SHALL 调用 dwg2dxf 转换真实 DWG 文件为 DXF
- **AND** 验证产出 DXF 可被 ezdxf 读取

#### Scenario: 所有 alternative 均失败

- **WHEN** ODA File Converter / dwg2dxf / pyautocad 均不可用
- **THEN** audit_report.md SHALL 正式声明"DWG 路径延后,原因:所有 alternative 均失败"
- **AND** 含每项 alternative 的尝试命令与失败日志

## MODIFIED Requirements

### Requirement: audit_report.md 环境限制清单更新

[原要求] audit_report.md 12.2 列出 8 项环境限制,标注为"未测试/未对比/待补"

[修改为] 本轮修复完成后,audit_report.md 12.2 SHALL 基于真实测试结果更新:
- 已修复项移至"已修复"区块,附 PASS 证据
- 仍受限项保留,附新的尝试证据
- 不可继续使用"待补"等模糊表述

## REMOVED Requirements

### Requirement: 仅声明问题不修复

**Reason**: 上一轮 `complete-remaining-test-gaps` spec 仅诚实标注 4 项环境限制,未做修复尝试。这等同于"以诚实无知为荣"但放弃了"以主动测试为荣"——诚实标注是底线,主动修复才是目标。

**Migration**: 所有可修复项 SHALL 在本 spec 中完成修复并验证;确无法修复项(如远程 VLM API 无 Key)才正式声明延后。
