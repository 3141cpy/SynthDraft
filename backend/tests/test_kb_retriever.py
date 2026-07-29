"""Task 3 知识库检索单元测试。

覆盖（SubTask 3.5 强制引用原文机制）：
1. test_completeness_complete —— 完整记录返回 completeness=complete
2. test_completeness_incomplete_missing_original_text —— 缺失 original_text 返回 incomplete
3. test_completeness_incomplete_missing_source_file —— 缺失 source_file 返回 incomplete
4. test_completeness_incomplete_blank_original_text —— 空白原文返回 incomplete
5. test_parse_markdown_documents —— 多文档 frontmatter 解析正确
6. test_retriever_returns_incomplete_on_missing_field —— 检索结果缺失字段时标注 incomplete
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.kb import ClauseRecord, ClauseSearchResult
from app.services.kb.indexer import (
    documents_to_clauses,
    parse_markdown_documents,
)

KB_STANDARDS_DIR = (
    Path(__file__).resolve().parents[2] / "kb" / "standards"
)


# ---------------------------------------------------------------------------
# ClauseSearchResult.from_record 完整性校验
# ---------------------------------------------------------------------------


def _make_record(
    original_text: str = "圆度公差带是在同一正截面上半径差为 t 的两同心圆之间的区域。",
    source_file: str = "GBT_1182_2018_形位公差.md",
) -> ClauseRecord:
    return ClauseRecord(
        standard="GB/T 1182-2018",
        clause_id="5.2",
        title="圆度公差",
        category="shape_tolerance",
        keywords=["圆度", "公差"],
        references=["GB/T 1182-2018 §5.1"],
        version="2018",
        is_sample=True,
        original_text=original_text,
        source_file=source_file,
    )


def test_completeness_complete() -> None:
    """完整记录：original_text 与 source_file 均存在 → completeness=complete。"""
    record = _make_record()
    result = ClauseSearchResult.from_record(record, score=0.95)
    assert result.completeness == "complete"
    assert result.original_text == record.original_text
    assert result.source_file == record.source_file
    assert result.score == 0.95


def test_completeness_incomplete_missing_original_text() -> None:
    """缺失 original_text → completeness=incomplete（SubTask 3.5 核心断言）。"""
    record = _make_record(original_text="", source_file="some.md")
    result = ClauseSearchResult.from_record(record, score=0.8)
    assert result.completeness == "incomplete"
    assert result.original_text == ""


def test_completeness_incomplete_missing_source_file() -> None:
    """缺失 source_file → completeness=incomplete。"""
    record = _make_record(original_text="有原文", source_file="")
    result = ClauseSearchResult.from_record(record, score=0.7)
    assert result.completeness == "incomplete"
    assert result.source_file == ""


def test_completeness_incomplete_blank_original_text() -> None:
    """原文仅空白 → completeness=incomplete。"""
    record = _make_record(original_text="   \n  ", source_file="f.md")
    result = ClauseSearchResult.from_record(record, score=0.6)
    assert result.completeness == "incomplete"


# ---------------------------------------------------------------------------
# Markdown 多文档解析
# ---------------------------------------------------------------------------


def test_parse_markdown_documents() -> None:
    """多文档 frontmatter 解析：能从一个文件解析出多条条款。"""
    sample_path = KB_STANDARDS_DIR / "GBT_1182_2018_形位公差.md"
    if not sample_path.is_file():
        pytest.skip(f"样本文件不存在：{sample_path}")

    content = sample_path.read_text(encoding="utf-8")
    docs = parse_markdown_documents(content)
    # 该文件含 8 条条款
    assert len(docs) >= 8, f"期望 ≥8 条，实际 {len(docs)}"

    records = documents_to_clauses(docs, source_file=sample_path.name)
    assert len(records) >= 8
    # 每条记录必含 original_text（强制引用原文）
    for r in records:
        assert r.original_text.strip(), f"条款 {r.clause_id} 缺失 original_text"
        assert r.source_file == sample_path.name
        assert r.standard == "GB/T 1182-2018"


# ---------------------------------------------------------------------------
# 检索结果缺失字段时标注 incomplete（集成层）
# ---------------------------------------------------------------------------


def test_retriever_returns_incomplete_on_missing_field() -> None:
    """构造一条缺失 original_text 的记录，断言 from_result 标注 incomplete。

    此测试不依赖 Qdrant，直接验证 ClauseSearchResult 的完整性校验逻辑
    （即检索层会正确标注 incomplete）。
    """
    record = ClauseRecord(
        standard="GB/T 131-2006",
        clause_id="4.1",
        title="表面结构图形符号",
        category="surface_symbol",
        keywords=["表面结构"],
        references=[],
        version="2006",
        is_sample=True,
        original_text="",  # 缺失原文
        source_file="GBT_131_2006_表面结构表示法.md",
    )
    result = ClauseSearchResult.from_record(record, score=0.42)
    assert result.completeness == "incomplete"
    assert result.standard == "GB/T 131-2006"
    assert result.clause_id == "4.1"
    assert result.score == 0.42
