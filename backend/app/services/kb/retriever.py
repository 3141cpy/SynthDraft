"""混合检索：向量检索（Qdrant）+ 元数据过滤（LlamaIndex MetadataFilters）。

遵循"以复用现有为荣"原则：
- 向量检索：复用 QdrantClauseStore（封装 qdrant-client）
- 元数据过滤：复用 LlamaIndex 的 MetadataFilters / MetadataFilter 抽象
- 强制引用原文（SubTask 3.5）：检索结果必含 original_text，缺失则 completeness=incomplete

SubTask 17.3：在 retrieve 上叠加 @cached_retrieve 装饰器，
同一查询文本 + 过滤条件 + top_k 第二次检索直接返回缓存（Redis 后端）。
RAG_CACHE_ENABLED=False 或 Redis 不可用时透明降级为直接检索。
"""

from __future__ import annotations

from typing import Any

from app.logging import get_logger
from app.schemas.kb import ClauseSearchResult
from app.services.kb.embedder import BGEM3Embedder, get_embedder
from app.services.kb.qdrant_store import QdrantClauseStore, get_store
from app.services.kb.retrieval_cache import cached_retrieve

log = get_logger(__name__)

# 默认 collection
DEFAULT_COLLECTION = "gb_clauses"


def _build_qdrant_filter(
    standard_filter: list[str] | None,
    category_filter: list[str] | None,
    keyword_filter: list[str] | None = None,
    clause_id_filter: str | None = None,
) -> dict[str, Any] | None:
    """将多值过滤条件转换为 Qdrant Filter 字典。

    使用 Qdrant 的 must 语义（must 中多个 FieldCondition 之间是 AND）：
    - clause_id: 精确匹配（must，MatchValue）
    - standard: 维度内多值任一匹配（must，MatchAny）
    - category: 维度内多值任一匹配（must，MatchAny）
    - keywords: 维度内任一关键词命中（must，MatchAny）
    - 不同维度之间是 AND

    返回 None 表示无过滤。
    """
    from qdrant_client.http import models as qmodels

    must_clauses: list[qmodels.FieldCondition] = []

    if clause_id_filter:
        must_clauses.append(
            qmodels.FieldCondition(
                key="clause_id",
                match=qmodels.MatchValue(value=clause_id_filter),
            )
        )

    if standard_filter:
        must_clauses.append(
            qmodels.FieldCondition(
                key="standard",
                match=qmodels.MatchAny(any=standard_filter),
            )
        )
    if category_filter:
        must_clauses.append(
            qmodels.FieldCondition(
                key="category",
                match=qmodels.MatchAny(any=category_filter),
            )
        )
    if keyword_filter:
        must_clauses.append(
            qmodels.FieldCondition(
                key="keywords",
                match=qmodels.MatchAny(any=keyword_filter),
            )
        )

    if not must_clauses:
        return None

    # Qdrant 语义：must 中多个 FieldCondition 之间是 AND；
    # 每个 FieldCondition 内部用 MatchAny 实现维度内的 OR。
    return {"must": must_clauses}


def _build_llamaindex_metadata_filters(
    standard_filter: list[str] | None,
    category_filter: list[str] | None,
) -> Any:
    """用 LlamaIndex 的 MetadataFilters 抽象构建过滤条件。

    集成 LlamaIndex（SubTask 3.4 要求）：使用其过滤抽象表达业务意图，
    随后在 retrieve() 中转换为 Qdrant 原生过滤执行。
    """
    try:
        from llama_index.core.vector_stores import (
            FilterOperator,
            MetadataFilter,
            MetadataFilters,
        )
    except ImportError:
        log.warning("kb.retriever.llamaindex_unavailable")
        return None

    filters: list[MetadataFilter] = []
    if standard_filter:
        # MatchAny 语义：OR
        filters.append(
            MetadataFilter(
                key="standard",
                value=standard_filter,
                operator=FilterOperator.IN,
            )
        )
    if category_filter:
        filters.append(
            MetadataFilter(
                key="category",
                value=category_filter,
                operator=FilterOperator.IN,
            )
        )

    if not filters:
        return None

    return MetadataFilters(filters=filters, condition="and")


class HybridClauseRetriever:
    """混合检索器：向量相似度 + 元数据过滤。

    用法：
        r = HybridClauseRetriever()
        results = r.retrieve("圆度公差标注要求", top_k=3,
                             standard_filter=["GB/T 1182-2018"])
    """

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION,
        embedder: BGEM3Embedder | None = None,
        store: QdrantClauseStore | None = None,
    ) -> None:
        self.collection_name = collection_name
        self._embedder = embedder
        self._store = store

    @property
    def embedder(self) -> BGEM3Embedder:
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    @property
    def store(self) -> QdrantClauseStore:
        if self._store is None:
            self._store = get_store()
        return self._store

    @cached_retrieve
    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        standard_filter: list[str] | None = None,
        category_filter: list[str] | None = None,
        keyword_filter: list[str] | None = None,
        clause_id_filter: str | None = None,
    ) -> list[ClauseSearchResult]:
        """混合检索：向量相似度 + 元数据过滤。

        SubTask 17.3: ``@cached_retrieve`` 装饰器自动缓存检索结果，
        同一查询文本 + 过滤条件 + top_k 第二次检索直接返回缓存（Redis 后端）。
        RAG_CACHE_ENABLED=False 或 Redis 不可用时透明降级为直接检索。

        Args:
            query: 查询文本
            top_k: 返回条数
            standard_filter: 规范编号过滤（OR）
            category_filter: 分类过滤（OR）
            keyword_filter: 关键词过滤（OR）
            clause_id_filter: 条款号精确匹配（AND）

        Returns:
            list[ClauseSearchResult]，按相似度降序。
            每条结果经完整性校验（SubTask 3.5）。
        """
        if not query or not query.strip():
            return []

        # 1) 构建过滤条件（用 LlamaIndex 抽象表达意图，转换为 Qdrant 原生过滤执行）
        _build_llamaindex_metadata_filters(standard_filter, category_filter)
        qdrant_filter = _build_qdrant_filter(
            standard_filter, category_filter, keyword_filter, clause_id_filter
        )

        # 2) 查询向量化
        query_vec = self.embedder.embed_one(query)

        # 3) Qdrant 向量检索 + 过滤
        results = self.store.search(
            collection_name=self.collection_name,
            query_vector=query_vec,
            top_k=top_k,
            filter_=qdrant_filter,
        )

        # 4) 强制引用原文机制（SubTask 3.5）：记录 incomplete 警告
        # 注意：列表推导式变量在 Python 3 中不泄漏到外层作用域，
        # 因此遍历 incomplete 列表收集缺失字段，避免引用未定义的 r。
        incomplete = [r for r in results if r.completeness == "incomplete"]
        if incomplete:
            missing_fields: list[str] = []
            for item in incomplete:
                if not item.original_text:
                    missing_fields.append("original_text")
                if not item.source_file:
                    missing_fields.append("source_file")
            log.warning(
                "kb.retriever.incomplete_results",
                count=len(incomplete),
                total=len(results),
                missing_fields=missing_fields,
            )

        log.info(
            "kb.retriever.retrieved",
            query=query[:40],
            top_k=top_k,
            returned=len(results),
            filtered=bool(qdrant_filter),
        )
        return results


def get_retriever() -> HybridClauseRetriever:
    """获取默认 HybridClauseRetriever 实例。"""
    return HybridClauseRetriever()
