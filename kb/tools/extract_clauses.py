"""PDF→结构化条文提取工具。

将工程规范 PDF（如 GB/T 系列国标）提取为结构化条文 Markdown 文件，
输出格式与 kb/standards/ 下的样本一致（YAML frontmatter + Markdown body），
便于后续由 indexer.py 建立向量索引。

遵循"以复用现有为荣"原则：
- 文本与表格提取：使用 pdfplumber（PyPI 0.11.10）
- YAML 序列化：使用 PyYAML（6.0.2）
- LLM 后处理（可选）：调用 Ollama，可禁用

命令行接口：
    python extract_clauses.py --input <pdf> --output <md_dir> --standard "GB/T XXXX-YYYY"

注意：GB/T 规范 PDF 受版权保护。本工具仅用于处理企业自有正版 PDF，
不内置任何规范 PDF，也不会从公开网络下载受版权保护的规范原文。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    import pdfplumber
except ImportError as e:  # pragma: no cover
    sys.stderr.write(
        "[extract_clauses] pdfplumber 未安装，请运行：pip install pdfplumber==0.11.10\n"
    )
    raise e


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class ExtractedClause:
    """从 PDF 提取的一条结构化条款。"""

    standard: str
    clause_id: str
    title: str
    body: str
    tables: list[list[list[str]]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    version: str = ""
    is_sample: bool = False  # 由 PDF 提取的视为非样本

    def to_markdown(self, source_file: str = "") -> str:
        """序列化为 YAML frontmatter + Markdown body 文本。"""
        frontmatter: dict[str, Any] = {
            "standard": self.standard,
            "clause_id": self.clause_id,
            "title": self.title,
            "category": _guess_category(self.title, self.body),
            "keywords": self.keywords or _auto_keywords(self.title),
            "references": self.references,
            "version": self.version or _extract_version(self.standard),
            "is_sample": self.is_sample,
        }
        if source_file:
            frontmatter["source_file"] = source_file

        body = self.body.strip()
        if self.tables:
            for idx, table in enumerate(self.tables, start=1):
                body += f"\n\n## 表 {idx}\n\n" + _table_to_markdown(table)

        fm_yaml = yaml.safe_dump(
            frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False
        ).strip()
        return f"---\n{fm_yaml}\n---\n\n# {self.title}（§{self.clause_id}）\n\n{body}\n"


# ---------------------------------------------------------------------------
# PDF 提取核心
# ---------------------------------------------------------------------------


# 匹配条款标题：行首数字编号 + 空格 + 标题文本，如 "5.2 圆度公差" / "4.1.1 尺寸界线"
_CLAUSE_PATTERN = re.compile(
    r"^(?P<id>\d+(?:\.\d+){0,3})\s+(?P<title>[^\n]{2,80})\s*$",
    re.MULTILINE,
)


def extract_text_and_tables(pdf_path: Path) -> tuple[str, list[list[list[str]]]]:
    """用 pdfplumber 提取 PDF 全文与表格。

    返回 (full_text, all_tables)。all_tables 为页内表格的扁平列表。
    """
    full_text_parts: list[str] = []
    all_tables: list[list[list[str]]] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            full_text_parts.append(page_text)
            try:
                page_tables = page.extract_tables() or []
            except Exception:  # noqa: BLE001
                page_tables = []
            for tbl in page_tables:
                if tbl and len(tbl) >= 1:
                    all_tables.append(
                        [[(cell or "").strip() for cell in row] for row in tbl]
                    )

    return "\n".join(full_text_parts), all_tables


def split_into_clauses(
    full_text: str, standard: str, llm_postprocess: bool = False
) -> list[ExtractedClause]:
    """按正则识别条款标题，切分正文为条款列表。

    LLM 后处理为可选项；当 llm_postprocess=True 且 Ollama 可达时，
    可对条款做进一步归一化（本 P0 实现保留接口，默认走纯正则）。
    """
    matches = list(_CLAUSE_PATTERN.finditer(full_text))
    if not matches:
        # 未识别到条款，整体作为单条条款返回，clause_id 置 "0"
        return [
            ExtractedClause(
                standard=standard,
                clause_id="0",
                title=f"{standard} 提取内容",
                body=full_text.strip()[:2000],
            )
        ]

    clauses: list[ExtractedClause] = []
    for i, m in enumerate(matches):
        clause_id = m.group("id")
        title = m.group("title").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        body = full_text[start:end].strip()
        if not body:
            continue
        clauses.append(
            ExtractedClause(
                standard=standard,
                clause_id=clause_id,
                title=title,
                body=body,
                keywords=_auto_keywords(title),
                references=_extract_references(body, standard),
            )
        )

    if llm_postprocess:
        _llm_postprocess_clauses(clauses, standard)

    return clauses


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


_CATEGORY_KEYWORDS = {
    "shape_tolerance": ["圆度", "圆柱度", "平面度", "直线度", "形状公差"],
    "orientation_tolerance": ["平行度", "垂直度", "倾斜度", "方向公差"],
    "location_tolerance": ["位置度", "同轴度", "对称度", "位置公差"],
    "runout_tolerance": ["圆跳动", "全跳动", "跳动公差"],
    "dimension_basic": ["尺寸", "标注", "基本规则"],
    "dimension_line": ["尺寸界线", "尺寸线", "箭头"],
    "surface_parameter": ["表面结构", "Ra", "Rz", "粗糙度"],
    "surface_symbol": ["图形符号", "表面结构符号"],
    "line_type": ["实线", "虚线", "点画线", "图线"],
    "general_tolerance": ["一般公差", "未注公差"],
    "cad_layer": ["图层", "CAD"],
    "cad_dimension": ["CAD", "尺寸标注"],
}


def _guess_category(title: str, body: str) -> str:
    text = (title + " " + body).lower()
    for cat, kws in _CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return cat
    return "general"


def _auto_keywords(title: str) -> list[str]:
    # 简单分词：按中文标点与空格切分，取长度≥2 的非数字片段
    parts = re.split(r"[\s、，,。/（）()]+", title)
    return [p for p in parts if len(p) >= 2 and not p.replace(".", "").isdigit()][:5]


def _extract_version(standard: str) -> str:
    m = re.search(r"(\d{4})$", standard)
    return m.group(1) if m else ""


_REF_PATTERN = re.compile(r"(GB/T\s*\d+(?:\.\d+)?(?:[-—]\d{4})?|ISO\s*\d+(?:[-—]\d{4})?)")


def _extract_references(body: str, self_standard: str) -> list[str]:
    refs: list[str] = []
    for m in _REF_PATTERN.finditer(body):
        ref = m.group(1).replace("—", "-").replace("  ", " ")
        ref = re.sub(r"\s+", " ", ref).strip()
        if ref and ref not in refs and ref not in self_standard:
            refs.append(ref)
    return refs[:5]


def _table_to_markdown(table: list[list[str]]) -> str:
    if not table:
        return ""
    header = table[0]
    rows = table[1:] if len(table) > 1 else []
    md = "| " + " | ".join(header) + " |\n"
    md += "|" + "---|" * len(header) + "\n"
    for row in rows:
        # 补齐列数
        row = row + [""] * (len(header) - len(row))
        md += "| " + " | ".join(row[: len(header)]) + " |\n"
    return md


def _llm_postprocess_clauses(clauses: list[ExtractedClause], standard: str) -> None:
    """可选：调用 Ollama 对条款做后处理（P0 阶段保留接口，不强制）。

    实现策略：尝试调用本地 Ollama；若不可达则静默跳过。
    """
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return

    ollama_url = os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{ollama_url}/api/tags")
            if resp.status_code != 200:
                return
    except Exception:  # noqa: BLE001
        return

    # 此处仅做关键字归一化示例；完整 LLM 后处理在 P1 增强
    for c in clauses:
        if not c.keywords:
            c.keywords = _auto_keywords(c.title)


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def write_clauses_to_dir(
    clauses: list[ExtractedClause],
    output_dir: Path,
    source_file: str,
) -> list[Path]:
    """将条款以多文档形式写入单个 Markdown 文件（一个输入 PDF 一个输出文件）。

    返回写入的文件路径列表（通常为 1 个）。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if not clauses:
        return []

    # 文件名：标准号规范化
    safe_name = re.sub(r"[^\w.\-]", "_", clauses[0].standard).replace("/", "_")
    out_path = output_dir / f"{safe_name}.md"

    parts = [c.to_markdown(source_file=source_file) for c in clauses]
    out_path.write_text("\n".join(parts), encoding="utf-8")
    return [out_path]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从工程规范 PDF 提取结构化条文，输出 Markdown 文件（YAML frontmatter + body）。"
    )
    parser.add_argument("--input", required=True, help="输入 PDF 文件路径")
    parser.add_argument(
        "--output", required=True, help="输出 Markdown 目录路径（自动创建）"
    )
    parser.add_argument(
        "--standard", required=True, help='规范编号，如 "GB/T 1182-2018"'
    )
    parser.add_argument(
        "--llm-postprocess",
        action="store_true",
        help="启用 LLM 后处理（需 Ollama 可达，默认关闭）",
    )
    args = parser.parse_args(argv)

    pdf_path = Path(args.input)
    if not pdf_path.is_file():
        sys.stderr.write(f"[extract_clauses] 输入文件不存在: {pdf_path}\n")
        return 2

    output_dir = Path(args.output)
    print(f"[extract_clauses] 提取 PDF: {pdf_path}")
    print(f"[extract_clauses] 规范编号: {args.standard}")

    full_text, tables = extract_text_and_tables(pdf_path)
    print(f"[extract_clauses] 提取文本长度: {len(full_text)} 字符")
    print(f"[extract_clauses] 提取表格数: {len(tables)}")

    clauses = split_into_clauses(full_text, args.standard, args.llm_postprocess)
    print(f"[extract_clauses] 识别条款数: {len(clauses)}")

    # 把表格按顺序分配给条款（简单策略：每个条款最多挂 1 张表）
    if tables:
        for i, clause in enumerate(clauses):
            if i < len(tables):
                clause.tables = [tables[i]]

    written = write_clauses_to_dir(clauses, output_dir, source_file=pdf_path.name)
    for p in written:
        print(f"[extract_clauses] 已写入: {p}")

    # 输出提取时间戳
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[extract_clauses] 完成 @ {ts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
