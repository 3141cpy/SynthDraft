"""Qdrant 向量库封装。

封装 Qdrant 客户端，提供 collection 管理、条款批量写入、向量检索能力。
遵循"以复用现有为荣"原则，使用 qdrant-client 官方包。
"""

from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.config import settings
from app.logging import get_logger
from app.schemas.kb import ClauseRecord, ClauseSearchResult

log = get_logger(__name__)


def _make_client() -> QdrantClient:
    """根据 settings.QDRANT_URL 创建 Qdrant 客户端。"""
    url = settings.QDRANT_URL or "http://localhost:6333"
    return QdrantClient(url=url, timeout=30.0)


class QdrantClauseStore:
    """Qdrant 条款存储封装。

    用法：
        store = QdrantClauseStore()
        store.ensure_collection("gb_clauses", vector_size=1024)
        store.upsert_clauses(clauses_with_vectors)
        results = store.search(query_vec, top_k=5)
    """

    def __init__(self, client: QdrantClient | None = None) -> None:
        self._client = client or _make_client()

    @property
    def client(self) -> QdrantClient:
        return self._client

    def ensure_collection(
        self,
        collection_name: str,
        vector_size: int,
        distance: qmodels.Distance = qmodels.Distance.COSINE,
        recreate: bool = False,
    ) -> None:
        """创建 collection（若不存在）；recreate=True 时先删除再创建。"""
        if recreate:
            try:
                self._client.delete_collection(collection_name=collection_name)
                log.info("kb.qdrant.collection_deleted", name=collection_name)
            except Exception:  # noqa: BLE001
                # collection 不存在时忽略
                pass

        collections = self._client.get_collections().collections
        existing = {c.name for c in collections}
        if collection_name in existing and not recreate:
            log.info(
                "kb.qdrant.collection_exists", name=collection_name, vector_size=vector_size
            )
            return

        self._client.create_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(
                size=vector_size,
                distance=distance,
            ),
        )
        log.info(
            "kb.qdrant.collection_created",
            name=collection_name,
            vector_size=vector_size,
        )

    def upsert_clauses(
        self,
        collection_name: str,
        clauses: list[ClauseRecord],
        vectors: list[list[float]],
    ) -> int:
        """批量写入条款向量与 payload。

        clauses 与 vectors 长度必须一致，按位置对应。
        返回写入条数。
        """
        if len(clauses) != len(vectors):
            raise ValueError(
                f"clauses({len(clauses)}) 与 vectors({len(vectors)}) 长度不一致"
            )
        if not clauses:
            return 0

        points: list[qmodels.PointStruct] = []
        for clause, vec in zip(clauses, vectors, strict=True):
            # 用 clause.point_id 的稳定哈希生成 UUID（同一条款重复写入可覆盖）
            point_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, clause.point_id))
            points.append(
                qmodels.PointStruct(
                    id=point_uuid,
                    vector=vec,
                    payload=clause.to_payload(),
                )
            )

        # 分批 upsert（Qdrant 单批上限约 1000，这里保守用 64）
        batch_size = 64
        upserted = 0
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            self._client.upsert(collection_name=collection_name, points=batch)
            upserted += len(batch)

        log.info(
            "kb.qdrant.upserted",
            collection=collection_name,
            count=upserted,
        )
        return upserted

    def search(
        self,
        collection_name: str,
        query_vector: list[float],
        top_k: int = 5,
        filter_: dict[str, Any] | None = None,
    ) -> list[ClauseSearchResult]:
        """向量检索条款。

        Args:
            collection_name: collection 名
            query_vector: 查询向量
            top_k: 返回条数
            filter_: Qdrant 过滤条件（按 payload 字段过滤）

        Returns:
            list[ClauseSearchResult]，按相似度降序
        """
        query_filter = (
            qmodels.Filter(**filter_) if filter_ else None
        )  # noqa: E731  # 简单封装

        hits = self._client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
        ).points

        results: list[ClauseSearchResult] = []
        for hit in hits:
            payload = hit.payload or {}
            record = ClauseRecord(
                standard=payload.get("standard", ""),
                clause_id=payload.get("clause_id", ""),
                title=payload.get("title", ""),
                category=payload.get("category", "general"),
                keywords=payload.get("keywords", []),
                references=payload.get("references", []),
                version=payload.get("version", ""),
                is_sample=payload.get("is_sample", False),
                original_text=payload.get("original_text", ""),
                source_file=payload.get("source_file", ""),
            )
            results.append(
                ClauseSearchResult.from_record(record, score=float(hit.score or 0.0))
            )
        return results

    def list_standards(self, collection_name: str) -> list[str]:
        """聚合已索引的规范编号列表（从 payload standard 字段）。"""
        try:
            # scroll 遍历 payload，聚合 standard 字段
            seen: set[str] = set()
            offset: str | int | None = None
            while True:
                resp = self._client.scroll(
                    collection_name=collection_name,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                points, next_offset = resp[0], resp[1]
                if not points:
                    break
                for p in points:
                    std = (p.payload or {}).get("standard")
                    if std and std not in seen:
                        seen.add(std)
                offset = next_offset
                if offset is None:
                    break
            return sorted(seen)
        except Exception as e:  # noqa: BLE001
            log.warning("kb.qdrant.list_standards_failed", error=str(e))
            return []

    def count(self, collection_name: str) -> int:
        """返回 collection 中点数（精确计数）。"""
        try:
            resp = self._client.count(collection_name=collection_name, exact=True)
            return resp.count
        except Exception:  # noqa: BLE001
            return 0


def get_store() -> QdrantClauseStore:
    """获取全局 QdrantClauseStore 实例（每次新建客户端，轻量）。"""
    return QdrantClauseStore()
