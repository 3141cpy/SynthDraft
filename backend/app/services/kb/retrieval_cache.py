"""RAG 检索结果缓存（SubTask 17.3）。

设计原则：
- 缓存后端：Redis（复用 settings.REDIS_URL，复用 redis-py）
- 优雅降级：Redis 不可用时直接执行原函数，不抛异常
- 线程安全：Redis 客户端通过连接池管理，thread-safe
- 可配置：RAG_CACHE_ENABLED 开关 + RAG_CACHE_TTL 过期
- 缓存 key：基于查询文本 hash + top_k + 过滤条件 hash（语义相同的查询命中缓存）
- 命中率统计：log.info 记录 cache_hit / cache_miss

缓存 key 格式：f"rag_retrieve:{query_hash}:{filter_hash}:{top_k}"
缓存 value：检索结果列表 JSON（[ClauseSearchResult.model_dump(), ...]）

用法（装饰器）：
    @cached_retrieve
    def retrieve(self, query, top_k=5, ...):
        ...

    # 或直接调用
    cached = get_cached_retrieve(query, top_k, filters)  # 命中返回 list[dict]，未命中返回 None
    set_cached_retrieve(query, top_k, filters, results)
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import threading
import time
from typing import Any, Callable, TypeVar

from app.config import settings
from app.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")

# ===== Redis 客户端单例（线程安全）=====

_redis_client: Any = None
_redis_client_lock = threading.Lock()
_redis_unavailable_logged = False


def _get_redis_client() -> Any:
    """获取 Redis 客户端单例。

    遵循"以复用现有为荣"原则，使用 redis-py from_url + 连接池。
    Redis 不可用时返回 None（仅首次记录 warning，避免日志噪声）。
    """
    global _redis_client, _redis_unavailable_logged
    if _redis_client is not None:
        return _redis_client
    with _redis_client_lock:
        if _redis_client is not None:
            return _redis_client
        try:
            import redis as redis_lib

            client = redis_lib.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,  # 返回 str 而非 bytes
            )
            client.ping()  # 探活
            _redis_client = client
            log.info("rag.cache.redis_connected", url=settings.REDIS_URL)
            return _redis_client
        except Exception as e:  # noqa: BLE001
            if not _redis_unavailable_logged:
                log.warning(
                    "rag.cache.redis_unavailable",
                    error=str(e),
                    error_type=type(e).__name__,
                    degraded="直接执行原函数，不缓存",
                )
                _redis_unavailable_logged = True
            return None


def _reset_redis_client() -> None:
    """重置 Redis 客户端缓存（测试用，允许注入 fakeredis 后重连）。"""
    global _redis_client, _redis_unavailable_logged
    with _redis_client_lock:
        _redis_client = None
        _redis_unavailable_logged = False


# ===== 缓存 key 计算 =====


def _hash_query(query: str) -> str:
    """对查询文本做 sha256 hash（归一化：去首尾空白 + 小写）。"""
    normalized = (query or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _hash_filters(
    standard_filter: list[str] | None,
    category_filter: list[str] | None,
    keyword_filter: list[str] | None,
    clause_id_filter: str | None = None,
) -> str:
    """对过滤条件做 hash（排序后哈希，保证集合相同即 hash 相同）。"""
    payload: dict[str, Any] = {
        "standard": sorted(standard_filter) if standard_filter else [],
        "category": sorted(category_filter) if category_filter else [],
        "keyword": sorted(keyword_filter) if keyword_filter else [],
        "clause_id": clause_id_filter or "",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _make_cache_key(
    query: str,
    top_k: int,
    standard_filter: list[str] | None,
    category_filter: list[str] | None,
    keyword_filter: list[str] | None,
    clause_id_filter: str | None = None,
) -> str:
    """构造缓存 key。

    语义相同的查询（归一化后）+ 相同过滤条件（含 clause_id）+ 相同 top_k → 命中同一缓存。
    """
    qh = _hash_query(query)
    fh = _hash_filters(
        standard_filter, category_filter, keyword_filter, clause_id_filter
    )
    return f"rag_retrieve:{qh}:{fh}:{top_k}"


# ===== 缓存读写 =====


def get_cached_retrieve(
    query: str,
    top_k: int,
    standard_filter: list[str] | None,
    category_filter: list[str] | None,
    keyword_filter: list[str] | None,
    clause_id_filter: str | None = None,
) -> list[dict[str, Any]] | None:
    """从缓存读取检索结果。

    Returns:
        命中时返回 list[dict]；未命中返回 None
    """
    if not getattr(settings, "RAG_CACHE_ENABLED", True):
        return None
    client = _get_redis_client()
    if client is None:
        return None
    try:
        key = _make_cache_key(
            query,
            top_k,
            standard_filter,
            category_filter,
            keyword_filter,
            clause_id_filter,
        )
        raw = client.get(key)
        if raw is None:
            log.info("rag.cache.miss", key=key, query=query[:40], top_k=top_k)
            return None
        log.info("rag.cache.hit", key=key, query=query[:40], top_k=top_k)
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        log.warning("rag.cache.get_failed", error=str(e))
        return None


def set_cached_retrieve(
    query: str,
    top_k: int,
    standard_filter: list[str] | None,
    category_filter: list[str] | None,
    keyword_filter: list[str] | None,
    results: list[Any],
    clause_id_filter: str | None = None,
) -> bool:
    """写入检索结果到缓存。

    Args:
        results: ClauseSearchResult 列表（pydantic 模型）或 dict 列表

    Returns:
        True 表示写入成功；False 表示缓存不可用或写入失败
    """
    if not getattr(settings, "RAG_CACHE_ENABLED", True):
        return False
    client = _get_redis_client()
    if client is None:
        return False
    try:
        key = _make_cache_key(
            query,
            top_k,
            standard_filter,
            category_filter,
            keyword_filter,
            clause_id_filter,
        )
        ttl = int(getattr(settings, "RAG_CACHE_TTL", 3600))
        # 序列化：若元素是 pydantic 模型，转 dict
        data: list[dict[str, Any]] = []
        for r in results:
            if hasattr(r, "model_dump"):
                data.append(r.model_dump(mode="json"))
            else:
                data.append(r)  # type: ignore[arg-type]
        client.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
        log.info(
            "rag.cache.set",
            key=key,
            query=query[:40],
            top_k=top_k,
            results_count=len(data),
            ttl=ttl,
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("rag.cache.set_failed", error=str(e))
        return False


def invalidate_cached_retrieve(
    query: str,
    top_k: int,
    standard_filter: list[str] | None,
    category_filter: list[str] | None,
    keyword_filter: list[str] | None,
    clause_id_filter: str | None = None,
) -> bool:
    """显式删除缓存条目（知识库更新后调用）。

    Returns:
        True 表示删除成功；False 表示缓存不可用或删除失败
    """
    if not getattr(settings, "RAG_CACHE_ENABLED", True):
        return False
    client = _get_redis_client()
    if client is None:
        return False
    try:
        key = _make_cache_key(
            query,
            top_k,
            standard_filter,
            category_filter,
            keyword_filter,
            clause_id_filter,
        )
        client.delete(key)
        log.info("rag.cache.invalidated", key=key, query=query[:40])
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("rag.cache.invalidate_failed", error=str(e))
        return False


def invalidate_all_retrieve_cache() -> int:
    """清除所有 RAG 检索缓存（知识库全量重建索引后调用）。

    使用 SCAN + DEL 模式避免阻塞 Redis（KEYS 命令在大库上会阻塞）。

    Returns:
        删除的 key 数量
    """
    if not getattr(settings, "RAG_CACHE_ENABLED", True):
        return 0
    client = _get_redis_client()
    if client is None:
        return 0
    deleted = 0
    try:
        # SCAN 遍历所有 rag_retrieve: 前缀的 key
        for key in client.scan_iter(match="rag_retrieve:*", count=100):
            client.delete(key)
            deleted += 1
        log.info("rag.cache.invalidated_all", deleted=deleted)
    except Exception as e:  # noqa: BLE001
        log.warning("rag.cache.invalidate_all_failed", error=str(e))
    return deleted


# ===== 装饰器 =====


def cached_retrieve(fn: Callable[..., T]) -> Callable[..., T]:
    """装饰器：为 RAG 检索函数添加 Redis 缓存。

    被装饰函数签名要求（HybridClauseRetriever.retrieve 约定）：
        retrieve(self, query, top_k=5, standard_filter=None,
                 category_filter=None, keyword_filter=None,
                 clause_id_filter=None)

    行为：
    - RAG_CACHE_ENABLED=False 或 Redis 不可用：直接执行原函数（优雅降级）
    - 命中缓存：返回 [ClauseSearchResult.model_validate(d) for d in cached]
    - 未命中：执行原函数，写入缓存，返回原函数结果

    Returns:
        装饰器函数
    """

    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        if not getattr(settings, "RAG_CACHE_ENABLED", True):
            return fn(*args, **kwargs)

        # 参数提取：用 inspect 绑定位置 + 关键字参数，
        # 兼容 (self, query, top_k, ...) 位置参数调用与关键字参数调用。
        # 仅从 kwargs 读取会忽略位置参数，导致缓存键错误；
        # 同时纳入 clause_id_filter 避免跨 clause 缓存污染。
        try:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            query = bound.arguments.get("query")
            top_k = bound.arguments.get("top_k", 5)
            standard_filter = bound.arguments.get("standard_filter")
            category_filter = bound.arguments.get("category_filter")
            keyword_filter = bound.arguments.get("keyword_filter")
            clause_id_filter = bound.arguments.get("clause_id_filter")
        except TypeError:
            # 签名绑定失败（参数不匹配），回退到直接执行原函数，不缓存
            return fn(*args, **kwargs)

        if not query or not str(query).strip():
            return fn(*args, **kwargs)

        # 尝试命中缓存
        cached = get_cached_retrieve(
            query,
            top_k,
            standard_filter,
            category_filter,
            keyword_filter,
            clause_id_filter,
        )
        if cached is not None:
            # 重构为 ClauseSearchResult 列表
            try:
                from app.schemas.kb import ClauseSearchResult

                return [
                    ClauseSearchResult.model_validate(item) for item in cached
                ]  # type: ignore[no-any-return]
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "rag.cache.reconstruct_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # 重构失败，回退到执行原函数
                return fn(*args, **kwargs)

        # 未命中：执行原函数
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "rag.cache.retrieve_executed",
            query=str(query)[:40],
            top_k=top_k,
            elapsed_ms=elapsed_ms,
            results_count=len(result) if hasattr(result, "__len__") else 0,
        )
        # 写入缓存（失败不影响主流程）
        if hasattr(result, "__iter__"):
            set_cached_retrieve(
                query,
                top_k,
                standard_filter,
                category_filter,
                keyword_filter,
                list(result),
                clause_id_filter,
            )
        return result

    # 暴露原始函数
    wrapper._raw_fn = fn  # type: ignore[attr-defined]
    return wrapper


# ===== 离线自检 =====


def _self_test() -> dict[str, Any]:
    """离线自检：验证 RAG 检索缓存模块完整性与降级路径。

    本测试使用 fakeredis（faithful redis-py 实现）作为 Redis 后端，
    避免依赖真实 Redis 服务与 Qdrant。

    测试内容：
    1. 模块导入安全
    2. 缓存 key 计算（同查询命中 / 不同查询分离）
    3. 过滤条件 hash（顺序无关）
    4. 装饰器命中/未命中
    5. Redis 不可用降级
    6. 配置开关

    Returns:
        {"ok": bool, "errors": list[str], "checks": dict[str, bool]}
    """
    checks: dict[str, bool] = {}
    errors: list[str] = []

    # 1. 模块导入与函数存在
    try:
        checks["get_cached_retrieve_callable"] = callable(get_cached_retrieve)
        checks["set_cached_retrieve_callable"] = callable(set_cached_retrieve)
        checks[
            "invalidate_cached_retrieve_callable"
        ] = callable(invalidate_cached_retrieve)
        checks["invalidate_all_retrieve_cache_callable"] = callable(
            invalidate_all_retrieve_cache
        )
        checks["cached_retrieve_callable"] = callable(cached_retrieve)
    except Exception as e:  # noqa: BLE001
        checks["module_import"] = False
        errors.append(f"模块导入失败: {e}")

    # 2. 缓存 key 计算
    try:
        k1 = _make_cache_key("圆度公差", 5, None, None, None)
        k2 = _make_cache_key("圆度公差", 5, None, None, None)
        checks["key_deterministic"] = k1 == k2 and k1.startswith("rag_retrieve:")

        # 不同 top_k → 不同 key
        k3 = _make_cache_key("圆度公差", 10, None, None, None)
        checks["key_differs_by_top_k"] = k3 != k1

        # 查询归一化：首尾空白 + 大小写不敏感
        k4 = _make_cache_key("  圆度公差  ", 5, None, None, None)
        checks["key_normalizes_query"] = k4 == k1

        # 不同查询 → 不同 key
        k5 = _make_cache_key("圆柱度", 5, None, None, None)
        checks["key_differs_by_query"] = k5 != k1
    except Exception as e:  # noqa: BLE001
        checks["key_compute"] = False
        errors.append(f"缓存 key 计算失败: {e}")

    # 3. 过滤条件 hash 顺序无关
    try:
        k_a = _make_cache_key("q", 5, ["GB/T 1182", "GB/T 1804"], None, None)
        k_b = _make_cache_key("q", 5, ["GB/T 1804", "GB/T 1182"], None, None)
        checks["filter_order_invariant"] = k_a == k_b

        # 不同过滤 → 不同 key
        k_c = _make_cache_key("q", 5, ["GB/T 1182"], None, None)
        checks["filter_differs"] = k_c != k_a
    except Exception as e:  # noqa: BLE001
        checks["filter_hash"] = False
        errors.append(f"过滤条件 hash 测试失败: {e}")

    # 4. 装饰器命中/未命中（使用 fakeredis）
    try:
        import fakeredis

        global _redis_client, _redis_unavailable_logged
        fake = fakeredis.FakeRedis(decode_responses=True)
        with _redis_client_lock:
            _redis_client = fake
            _redis_unavailable_logged = False

        try:
            call_count = 0

            class _FakeRetriever:
                @cached_retrieve
                def retrieve(
                    self,
                    query: str,
                    top_k: int = 5,
                    standard_filter: list[str] | None = None,
                    category_filter: list[str] | None = None,
                    keyword_filter: list[str] | None = None,
                ) -> list:
                    nonlocal call_count
                    call_count += 1
                    from app.schemas.kb import ClauseSearchResult

                    return [
                        ClauseSearchResult(
                            standard="GB/T 1182-2018",
                            clause_id=f"5.{call_count}",
                            title="圆度",
                            original_text="圆度公差...",
                            score=0.9,
                            source_file="gb1182.md",
                            category="form",
                            keywords=["圆度"],
                            completeness="complete",
                        )
                    ]

            r = _FakeRetriever()

            # 首次调用：未命中，执行函数
            res1 = r.retrieve("圆度公差", top_k=5)
            checks["first_call_executed"] = call_count == 1
            checks["first_call_result_count"] = len(res1) == 1

            # 第二次调用：应命中缓存，不执行函数
            res2 = r.retrieve("圆度公差", top_k=5)
            checks["second_call_cached"] = call_count == 1  # 仍为 1，未执行
            checks["second_call_result_count"] = len(res2) == 1
            checks["second_call_is_clause_search_result"] = (
                type(res2[0]).__name__ == "ClauseSearchResult"
            )

            # 不同 top_k：未命中，执行函数
            res3 = r.retrieve("圆度公差", top_k=10)
            checks["different_top_k_re_executed"] = call_count == 2

            # 不同查询：未命中，执行函数
            res4 = r.retrieve("圆柱度", top_k=5)
            checks["different_query_re_executed"] = call_count == 3
        finally:
            _reset_redis_client()
    except Exception as e:  # noqa: BLE001
        checks["decorator_cache"] = False
        errors.append(f"装饰器命中/未命中测试失败: {e}")

    # 5. Redis 不可用降级
    try:
        import app.services.kb.retrieval_cache as cache_mod

        original_get = cache_mod._get_redis_client
        cache_mod._get_redis_client = lambda: None  # type: ignore
        try:
            call_count2 = 0

            class _FakeRetriever2:
                @cached_retrieve
                def retrieve(
                    self,
                    query: str,
                    top_k: int = 5,
                    standard_filter: list[str] | None = None,
                    category_filter: list[str] | None = None,
                    keyword_filter: list[str] | None = None,
                ) -> list:
                    nonlocal call_count2
                    call_count2 += 1
                    return [{"degraded": True, "call_n": call_count2}]

            r2 = _FakeRetriever2()
            # Redis 不可用：每次都执行原函数
            r2.retrieve("test", top_k=5)
            r2.retrieve("test", top_k=5)
            checks["degraded_executes_original"] = call_count2 == 2
        finally:
            cache_mod._get_redis_client = original_get  # type: ignore
            _reset_redis_client()
    except Exception as e:  # noqa: BLE001
        checks["degraded_path"] = False
        errors.append(f"Redis 不可用降级测试失败: {e}")

    # 6. 配置项存在
    try:
        checks["config_rag_cache_enabled"] = hasattr(settings, "RAG_CACHE_ENABLED")
        checks["config_rag_cache_ttl"] = hasattr(settings, "RAG_CACHE_TTL")
        checks["config_rag_cache_ttl_default"] = (
            int(getattr(settings, "RAG_CACHE_TTL", 0)) == 3600
        )
    except Exception as e:  # noqa: BLE001
        checks["config"] = False
        errors.append(f"配置项校验失败: {e}")

    ok = all(checks.values()) if checks else False
    return {"ok": ok, "errors": errors, "checks": checks}


__all__ = [
    "get_cached_retrieve",
    "set_cached_retrieve",
    "invalidate_cached_retrieve",
    "invalidate_all_retrieve_cache",
    "cached_retrieve",
    "_self_test",
]
