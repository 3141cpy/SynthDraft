"""从 Markdown 样本构建向量索引。

读取 kb/standards/ 下所有 Markdown 文件（多文档格式：每条条款一个
YAML frontmatter + Markdown body），生成 embedding，写入 Qdrant。

遵循"以复用现有为荣"原则：
- YAML 解析用 PyYAML
- 多文档解析自实现（python-frontmatter 仅支持单文档）
- 向量化用 BGEM3Embedder
- 存储用 QdrantClauseStore
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from app.logging import get_logger
from app.schemas.kb import ClauseRecord
from app.services.kb.embedder import BGEM3Embedder, get_embedder
from app.services.kb.qdrant_store import QdrantClauseStore, get_store

log = get_logger(__name__)

# 默认 collection 名
DEFAULT_COLLECTION = "gb_clauses"

# 匹配文档分隔符：行首的 --- （前后允许空白行）
_DOC_SEPARATOR = re.compile(r"^---\s*$", re.MULTILINE)


def parse_markdown_documents(content: str) -> list[dict[str, Any]]:
    """解析多文档 Markdown 文件。

    每个文档格式：
        ---
        <yaml frontmatter>
        ---

        <markdown body>

    返回 list[dict]，每个 dict 含 frontmatter(dict) 与 body(str)。
    若整个文件无 frontmatter，返回空列表。
    """
    # 找到所有 --- 分隔符位置
    separators = list(_DOC_SEPARATOR.finditer(content))
    if len(separators) < 2:
        return []

    documents: list[dict[str, Any]] = []
    # 第一个 --- 之前的内容视为前言（通常为空），跳过
    i = 0
    while i + 1 < len(separators):
        fm_start = separators[i].end()
        fm_end = separators[i + 1].start()
        frontmatter_text = content[fm_start:fm_end].strip()

        # body：从当前闭合 --- 到下一个 ---（或文件末尾）
        body_start = separators[i + 1].end()
        if i + 2 < len(separators):
            body_end = separators[i + 2].start()
        else:
            body_end = len(content)
        body_text = content[body_start:body_end].strip()

        if frontmatter_text:
            try:
                fm = yaml.safe_load(frontmatter_text)
                if isinstance(fm, dict):
                    documents.append({"frontmatter": fm, "body": body_text})
            except yaml.YAMLError as e:
                log.warning(
                    "kb.indexer.yaml_parse_failed",
                    error=str(e),
                    snippet=frontmatter_text[:80],
                )

        # 跳两步：一个文档 = 2 个分隔符（开 + 闭）
        i += 2

    return documents


def documents_to_clauses(
    documents: list[dict[str, Any]], source_file: str
) -> list[ClauseRecord]:
    """将解析出的文档转换为 ClauseRecord 列表。

    用 body 作为 original_text（强制引用原文）。
    """
    records: list[ClauseRecord] = []
    for doc in documents:
        fm = doc["frontmatter"]
        body = doc["body"]
        # 去掉 markdown 标题行后的纯文本作为 original_text
        original_text = _strip_markdown_headings(body)
        if not original_text.strip():
            continue

        record = ClauseRecord(
            standard=fm.get("standard", ""),
            clause_id=str(fm.get("clause_id", "")),
            title=fm.get("title", ""),
            category=fm.get("category", "general"),
            keywords=fm.get("keywords", []) or [],
            references=fm.get("references", []) or [],
            version=str(fm.get("version", "")),
            is_sample=bool(fm.get("is_sample", False)),
            original_text=original_text,
            source_file=source_file,
        )
        records.append(record)
    return records


def _strip_markdown_headings(body: str) -> str:
    """去掉 markdown 标题行（# 开头），保留正文文本。"""
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def load_clauses_from_dir(md_dir: Path) -> list[ClauseRecord]:
    """从目录加载所有 Markdown 文件中的条款。

    支持多文档格式（一个文件含多条条款）。
    """
    if not md_dir.is_dir():
        raise FileNotFoundError(f"Markdown 目录不存在: {md_dir}")

    all_records: list[ClauseRecord] = []
    md_files = sorted(md_dir.glob("*.md"))
    log.info("kb.indexer.loading_dir", dir=str(md_dir), file_count=len(md_files))

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("kb.indexer.read_failed", file=str(md_file), error=str(e))
            continue

        docs = parse_markdown_documents(content)
        records = documents_to_clauses(docs, source_file=md_file.name)
        log.info(
            "kb.indexer.parsed_file",
            file=md_file.name,
            clauses=len(records),
        )
        all_records.extend(records)

    log.info("kb.indexer.loaded_total", total=len(all_records))
    return all_records


def build_index_from_markdown(
    md_dir: Path,
    collection_name: str = DEFAULT_COLLECTION,
    embedder: BGEM3Embedder | None = None,
    store: QdrantClauseStore | None = None,
    batch_size: int = 32,
    recreate: bool = False,
) -> int:
    """读取 Markdown 文件，生成 embedding，写入 Qdrant。

    Args:
        md_dir: Markdown 目录
        collection_name: Qdrant collection 名
        embedder: 向量化器（None 则用全局单例）
        store: Qdrant 存储（None 则新建）
        batch_size: 向量化批大小
        recreate: 是否销毁并重建 collection。默认 False(增量 upsert)，
            仅在显式请求全量重建时设为 True，避免误删已有向量数据。

    Returns:
        已索引条款数
    """
    embedder = embedder or get_embedder()
    store = store or get_store()

    records = load_clauses_from_dir(md_dir)
    if not records:
        log.warning("kb.indexer.no_records", dir=str(md_dir))
        return 0

    # 确保 collection（按实际向量维度创建）
    vector_size = embedder.vector_size
    store.ensure_collection(
        collection_name=collection_name,
        vector_size=vector_size,
        recreate=recreate,
    )

    # 分批向量化并写入
    total_upserted = 0
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        texts = [
            f"{r.title}。{r.original_text}。关键词：{','.join(r.keywords)}"
            for r in batch
        ]
        vectors = embedder.embed(texts)
        upserted = store.upsert_clauses(collection_name, batch, vectors)
        total_upserted += upserted
        log.info(
            "kb.indexer.batch_indexed",
            batch=i // batch_size + 1,
            batch_count=len(batch),
            total=total_upserted,
        )

    log.info(
        "kb.indexer.build_complete",
        collection=collection_name,
        indexed=total_upserted,
        backend=embedder.backend,
        vector_size=vector_size,
    )
    return total_upserted
