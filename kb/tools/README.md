# kb/tools/ —— 规范条文提取工具

## extract_clauses.py

从工程规范 PDF 提取结构化条文，输出与 `kb/standards/` 样本格式一致的 Markdown 文件（YAML frontmatter + Markdown body）。

### 依赖

```
pdfplumber==0.11.10
pyyaml==6.0.2
httpx（可选，用于 LLM 后处理调用 Ollama）
```

安装：

```powershell
d:\SynthDraft\backend\.venv\Scripts\python.exe -m pip install pdfplumber==0.11.10 pyyaml==6.0.2
```

### 用法

```powershell
cd d:\SynthDraft

d:\SynthDraft\backend\.venv\Scripts\python.exe kb\tools\extract_clauses.py `
    --input <正版PDF路径> `
    --output kb\standards_extracted `
    --standard "GB/T 1182-2018"
```

参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--input` | 是 | 输入 PDF 文件路径 |
| `--output` | 是 | 输出 Markdown 目录（自动创建） |
| `--standard` | 是 | 规范编号，如 `GB/T 1182-2018` |
| `--llm-postprocess` | 否 | 启用 LLM 后处理（需 Ollama 可达，默认关闭） |

### 输出格式

每个输入 PDF 生成一个 Markdown 文件，采用多文档格式（每条条款一个 YAML frontmatter 块）：

```
---
standard: GB/T 1182-2018
clause_id: "5.2"
title: 圆度公差
category: shape_tolerance
keywords: [圆度, 公差]
references: ["GB/T 1182-2018 §5.1"]
version: "2018"
is_sample: false
source_file: GBT_1182_2018.pdf
---

# 圆度公差（§5.2）

圆度公差带是在同一正截面上...

---
standard: GB/T 1182-2018
clause_id: "5.3"
...
```

### 工作原理

1. **文本与表格提取**：用 `pdfplumber` 逐页提取文本与表格（`extract_text()` + `extract_tables()`）。
2. **条款切分**：用正则 `^\d+(\.\d+){0,3}\s+标题` 识别条款标题（如 "5.2 圆度公差"），按条款切分正文。
3. **元数据补全**：
   - `category`：基于标题与正文关键词匹配（圆度→shape_tolerance 等）。
   - `keywords`：从标题自动分词。
   - `references`：用正则扫描正文中的 `GB/T xxxx` / `ISO xxxx` 引用。
   - `version`：从规范编号尾部年份提取。
4. **LLM 后处理（可选）**：当 `--llm-postprocess` 启用且 Ollama 可达时，对条款做归一化（P0 阶段仅做关键字补全，完整实现在 P1）。

### 版权合规

**重要**：GB/T 规范 PDF 受版权保护。本工具仅用于处理企业自有正版 PDF，不内置任何规范 PDF，也不会从公开网络下载受版权保护的规范原文。

生产部署时，由企业提供正版规范 PDF（或正版电子版授权），用本工具提取后替换 `kb/standards/` 下的样本数据，并将 `is_sample` 字段改为 `false`。
