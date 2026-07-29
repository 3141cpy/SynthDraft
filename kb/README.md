# 工程规范知识库（kb/）

本目录托管 SynthDraft 项目 P0 阶段的工程规范知识库样本数据与提取工具。

## 目录结构

```
kb/
├── README.md                  # 本文件
├── standards/                 # 规范条款结构化样本数据（Markdown，YAML frontmatter）
│   ├── GBT_1182_2018_形位公差.md
│   ├── GBT_4457.4_2002_尺寸注法.md
│   ├── GBT_17450_1998_技术制图图线.md
│   ├── GBT_1804_2000_一般公差.md
│   ├── GBT_131_2006_表面结构表示法.md
│   └── GBT_18229_2023_CAD工程制图规则.md
└── tools/                     # PDF→结构化条文提取工具
    ├── README.md
    └── extract_clauses.py
```

## 样本数据说明

**重要**：`standards/` 目录下的 Markdown 文件是**开发样本数据**，仅用于 P0 阶段管线开发与测试，**非规范原文**。

- 每条条款均标注 `is_sample: true`，内容基于公开技术常识编写。
- 涵盖 6 部规范：GB/T 1182-2018、GB/T 4457.4-2002、GB/T 17450-1998、GB/T 1804-2000、GB/T 131-2006、GB/T 18229-2023。
- 合计 42 条条款样本（≥ 6 部规范 × 5 条/部），满足 P0 向量索引测试要求（≥30 条）。

## 版权与合规

GB/T 规范 PDF 受版权保护，**不可擅自下载或复制**。本仓库不包含任何规范原文。

生产部署时：
1. 由企业提供正版规范 PDF（或正版电子版授权）。
2. 使用 `kb/tools/extract_clauses.py` 自动提取结构化条文，替换 `standards/` 目录下的样本数据。
3. 替换后应将 `is_sample` 字段改为 `false`，并记录提取来源与版本。

## 文件格式约定

每个 Markdown 文件可包含多条条款，采用多文档（multi-document）格式：

```
---
standard: GB/T 1182-2018
clause_id: "5.2"
title: 圆度公差
category: shape_tolerance
keywords: [圆度, 公差, 形状]
references: ["GB/T 1182-2018 §5.1"]
version: "2018"
is_sample: true
---

# 圆度公差（§5.2）

圆度公差带是在同一正截面上，半径差为公差值 t 的两同心圆之间的区域。

## 备注
本条款为开发样本，非规范原文。

---
standard: GB/T 1182-2018
clause_id: "5.3"
...
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| standard | string | 规范编号，如 `GB/T 1182-2018` |
| clause_id | string | 条款号，如 `5.2` |
| title | string | 条款标题 |
| category | string | 分类，如 `shape_tolerance` / `dimension_basic` |
| keywords | list[string] | 关键词 |
| references | list[string] | 引用关系 |
| version | string | 规范版本年份 |
| is_sample | bool | 是否为开发样本 |

## 与后端集成

后端通过 `backend/app/services/kb/indexer.py` 的 `build_index_from_markdown()` 读取本目录文件，生成 embedding 并写入 Qdrant 向量库。详见 `backend/app/services/kb/`。
