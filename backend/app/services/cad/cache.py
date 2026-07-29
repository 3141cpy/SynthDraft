"""CAD 解析结果缓存（SubTask 17.2）。

设计原则：
- 缓存后端：Redis（复用 settings.REDIS_URL，复用 redis-py）
- 优雅降级：Redis 不可用时直接执行原函数，不抛异常
- 线程安全：Redis 客户端通过连接池管理，thread-safe
- 可配置：CAD_CACHE_ENABLED 开关 + CAD_CACHE_TTL 过期
- 文件 hash：sha256(文件内容) + 文件大小 + 修改时间（修改后自动失效）
- 命中率统计：log.info 记录 cache_hit / cache_miss

缓存 key 格式：f"cad_parse:{file_hash}:{parser_type}"
缓存 value：解析结果 JSON（CADIntermediateModel.model_dump_json）

用法（装饰器）：
    @cached_parse("dxf")
    def parse_dxf_to_intermediate(path: Path) -> CADIntermediateModel:
        ...

    # 或直接调用
    result = get_cached("dxf", path)  # 命中返回 CADIntermediateModel，未命中返回 None
    set_cached("dxf", path, result)
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import threading
import time
from pathlib import Path
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
            log.info("cad.cache.redis_connected", url=settings.REDIS_URL)
            return _redis_client
        except Exception as e:  # noqa: BLE001
            if not _redis_unavailable_logged:
                log.warning(
                    "cad.cache.redis_unavailable",
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


# ===== 文件 hash 计算 =====


def compute_file_hash(file_path: Path) -> str:
    """计算文件 hash：sha256(文件内容) + 文件大小 + 修改时间。

    遵循 spec 要求：文件修改后 hash 变化，缓存自动失效。
    修改时间纳入 hash 避免读取整个大文件也能检测修改（性能优化）。

    Args:
        file_path: 文件路径

    Returns:
        64 字符 hex sha256 + ":size:mtime" 的复合 hash 字符串
    """
    path = Path(file_path)
    stat = path.stat()
    size = stat.st_size
    mtime = int(stat.st_mtime)

    h = hashlib.sha256()
    with open(path, "rb") as f:
        # 分块读取避免大文件内存爆炸
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    content_hash = h.hexdigest()
    return f"{content_hash}:{size}:{mtime}"


def _make_cache_key(parser_type: str, file_hash: str) -> str:
    """构造缓存 key。"""
    return f"cad_parse:{file_hash}:{parser_type}"


# ===== 缓存读写 =====


def get_cached(parser_type: str, file_path: Path) -> Any | None:
    """从缓存读取解析结果。

    Args:
        parser_type: 解析器类型（如 "dxf" / "dwg" / "step"）
        file_path: 文件路径

    Returns:
        命中时返回 CADIntermediateModel.model_dump() 的 dict；未命中返回 None
    """
    if not getattr(settings, "CAD_CACHE_ENABLED", True):
        return None
    client = _get_redis_client()
    if client is None:
        return None
    try:
        file_hash = compute_file_hash(file_path)
        key = _make_cache_key(parser_type, file_hash)
        raw = client.get(key)
        if raw is None:
            log.info("cad.cache.miss", parser=parser_type, key=key, file=str(file_path))
            return None
        log.info("cad.cache.hit", parser=parser_type, key=key, file=str(file_path))
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        log.warning("cad.cache.get_failed", error=str(e), parser=parser_type)
        return None


def set_cached(parser_type: str, file_path: Path, result: Any) -> bool:
    """写入解析结果到缓存。

    Args:
        parser_type: 解析器类型
        file_path: 文件路径
        result: 解析结果（必须 JSON 可序列化，如 CADIntermediateModel.model_dump()）

    Returns:
        True 表示写入成功；False 表示缓存不可用或写入失败
    """
    if not getattr(settings, "CAD_CACHE_ENABLED", True):
        return False
    client = _get_redis_client()
    if client is None:
        return False
    try:
        file_hash = compute_file_hash(file_path)
        key = _make_cache_key(parser_type, file_hash)
        ttl = int(getattr(settings, "CAD_CACHE_TTL", 86400))
        # 若 result 是 pydantic 模型，转 dict
        if hasattr(result, "model_dump"):
            data = result.model_dump(mode="json")
        else:
            data = result
        client.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
        log.info(
            "cad.cache.set",
            parser=parser_type,
            key=key,
            file=str(file_path),
            ttl=ttl,
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("cad.cache.set_failed", error=str(e), parser=parser_type)
        return False


def invalidate_cached(parser_type: str, file_path: Path) -> bool:
    """显式删除缓存条目（修改文件后调用）。

    Args:
        parser_type: 解析器类型
        file_path: 文件路径

    Returns:
        True 表示删除成功；False 表示缓存不可用或删除失败
    """
    if not getattr(settings, "CAD_CACHE_ENABLED", True):
        return False
    client = _get_redis_client()
    if client is None:
        return False
    try:
        file_hash = compute_file_hash(file_path)
        key = _make_cache_key(parser_type, file_hash)
        client.delete(key)
        log.info("cad.cache.invalidated", parser=parser_type, key=key, file=str(file_path))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("cad.cache.invalidate_failed", error=str(e), parser=parser_type)
        return False


# ===== 装饰器 =====


def cached_parse(parser_type: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """装饰器：为 CAD 解析函数添加 Redis 缓存。

    被装饰函数签名要求：第一个位置参数为 Path（文件路径），
    返回值为 pydantic 模型或 JSON 可序列化对象。

    用法：
        @cached_parse("dxf")
        def parse_dxf_to_intermediate(path: Path) -> CADIntermediateModel:
            ...

    行为：
    - CAD_CACHE_ENABLED=False 或 Redis 不可用：直接执行原函数（优雅降级）
    - 命中缓存：返回 CADIntermediateModel.model_validate(cached_dict)
    - 未命中：执行原函数，写入缓存，返回原函数结果

    Args:
        parser_type: 解析器类型标识

    Returns:
        装饰器函数
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        # 预解析返回类型注解（PEP 563 兼容：from __future__ import annotations
        # 会使 inspect.signature().return_annotation 返回字符串，而非类型对象）。
        # 使用 typing.get_type_hints() 解析为真实类型对象，仅解析一次。
        ret_anno: Any = None
        try:
            import typing

            hints = typing.get_type_hints(fn)
            ret_anno = hints.get("return", None)
        except Exception:  # noqa: BLE001
            ret_anno = None

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            if not getattr(settings, "CAD_CACHE_ENABLED", True):
                return fn(*args, **kwargs)
            # 第一个位置参数必须是文件路径
            if not args:
                return fn(*args, **kwargs)
            file_path = args[0]
            if not isinstance(file_path, (str, Path)):
                return fn(*args, **kwargs)
            file_path = Path(file_path)
            if not file_path.is_file():
                return fn(*args, **kwargs)

            # 尝试命中缓存
            cached = get_cached(parser_type, file_path)
            if cached is not None:
                # 尝试构造为原函数返回类型（pydantic 模型）
                if ret_anno is not None and hasattr(ret_anno, "model_validate"):
                    try:
                        return ret_anno.model_validate(cached)  # type: ignore[no-any-return]
                    except Exception as e:  # noqa: BLE001
                        log.warning(
                            "cad.cache.reconstruct_failed",
                            parser=parser_type,
                            error=str(e),
                            error_type=type(e).__name__,
                            file=str(file_path),
                        )
                # 无法构造为模型，返回 dict
                return cached  # type: ignore[no-any-return]

            # 未命中：执行原函数
            t0 = time.perf_counter()
            result = fn(*args, **kwargs)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            log.info(
                "cad.cache.parse_executed",
                parser=parser_type,
                file=str(file_path),
                elapsed_ms=elapsed_ms,
            )
            # 写入缓存（失败不影响主流程）
            set_cached(parser_type, file_path, result)
            return result

        # 暴露原始函数与配置
        wrapper._raw_fn = fn  # type: ignore[attr-defined]
        wrapper._parser_type = parser_type  # type: ignore[attr-defined]
        wrapper._ret_anno = ret_anno  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ===== 离线自检 =====


def _self_test() -> dict[str, Any]:
    """离线自检：验证 CAD 缓存模块完整性与降级路径。

    本测试使用 fakeredis（faithful redis-py 实现）作为 Redis 后端，
    避免依赖真实 Redis 服务。fakeredis 已在 requirements 中（测试用）。

    测试内容：
    1. 模块导入安全
    2. 文件 hash 计算（同文件两次相同 / 修改后不同）
    3. 缓存 key 格式
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
        checks["compute_file_hash_callable"] = callable(compute_file_hash)
        checks["get_cached_callable"] = callable(get_cached)
        checks["set_cached_callable"] = callable(set_cached)
        checks["invalidate_cached_callable"] = callable(invalidate_cached)
        checks["cached_parse_callable"] = callable(cached_parse)
    except Exception as e:  # noqa: BLE001
        checks["module_import"] = False
        errors.append(f"模块导入失败: {e}")

    # 2. 文件 hash 计算
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".dxf", delete=False, encoding="utf-8"
        ) as f:
            f.write("test content for hash")
            tmp_path = Path(f.name)
        try:
            h1 = compute_file_hash(tmp_path)
            h2 = compute_file_hash(tmp_path)
            checks["hash_deterministic"] = h1 == h2 and len(h1) > 0
            # 修改文件后 hash 变化
            time.sleep(0.05)  # 确保 mtime 变化
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write("modified content")
            os.utime(tmp_path, None)  # 强制更新 mtime
            h3 = compute_file_hash(tmp_path)
            checks["hash_changes_on_modify"] = h3 != h1
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001
        checks["hash_compute"] = False
        errors.append(f"文件 hash 计算失败: {e}")

    # 3. 缓存 key 格式
    try:
        key = _make_cache_key("dxf", "abc123:100:1234567890")
        checks["key_format"] = key == "cad_parse:abc123:100:1234567890:dxf"
    except Exception as e:  # noqa: BLE001
        checks["key_format"] = False
        errors.append(f"缓存 key 格式校验失败: {e}")

    # 4. 装饰器命中/未命中（使用 fakeredis）
    try:
        import fakeredis

        # 注入 fakeredis 作为 Redis 客户端
        global _redis_client, _redis_unavailable_logged
        fake = fakeredis.FakeRedis(decode_responses=True)
        with _redis_client_lock:
            _redis_client = fake
            _redis_unavailable_logged = False

        try:
            call_count = 0

            @cached_parse("test_dxf")
            def _parse_fn(path: Path) -> dict:
                nonlocal call_count
                call_count += 1
                return {"parsed": True, "file": str(path), "call_n": call_count}

            import tempfile

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".dxf", delete=False, encoding="utf-8"
            ) as f:
                f.write("test dxf content")
                tmp_path = Path(f.name)
            try:
                # 首次调用：未命中，执行函数
                r1 = _parse_fn(tmp_path)
                checks["first_call_executed"] = call_count == 1
                checks["first_call_result"] = r1.get("parsed") is True

                # 第二次调用：应命中缓存，不执行函数
                r2 = _parse_fn(tmp_path)
                checks["second_call_cached"] = call_count == 1  # 仍为 1，未执行
                checks["second_call_result"] = r2 is not None

                # 修改文件后：hash 变化，未命中，执行函数
                time.sleep(0.05)
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write("modified dxf content")
                os.utime(tmp_path, None)
                r3 = _parse_fn(tmp_path)
                checks["after_modify_re_executed"] = call_count == 2  # 执行了第二次
                checks["after_modify_result"] = r3.get("call_n") == 2
            finally:
                tmp_path.unlink(missing_ok=True)
        finally:
            # 恢复 Redis 客户端
            _reset_redis_client()
    except Exception as e:  # noqa: BLE001
        checks["decorator_cache"] = False
        errors.append(f"装饰器命中/未命中测试失败: {e}")

    # 5. Redis 不可用降级
    try:
        # Monkey-patch _get_redis_client 返回 None，模拟 Redis 不可用
        import app.services.cad.cache as cache_mod

        original_get = cache_mod._get_redis_client
        cache_mod._get_redis_client = lambda: None  # type: ignore
        try:
            call_count2 = 0

            @cached_parse("test_degraded")
            def _parse_fn2(path: Path) -> dict:
                nonlocal call_count2
                call_count2 += 1
                return {"degraded": True}

            import tempfile

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".dxf", delete=False, encoding="utf-8"
            ) as f:
                f.write("degraded test")
                tmp_path = Path(f.name)
            try:
                # Redis 不可用：每次都执行原函数
                _parse_fn2(tmp_path)
                _parse_fn2(tmp_path)
                checks["degraded_executes_original"] = call_count2 == 2
            finally:
                tmp_path.unlink(missing_ok=True)
        finally:
            cache_mod._get_redis_client = original_get  # type: ignore
            _reset_redis_client()
    except Exception as e:  # noqa: BLE001
        checks["degraded_path"] = False
        errors.append(f"Redis 不可用降级测试失败: {e}")

    # 6. 配置项存在
    try:
        checks["config_cad_cache_enabled"] = hasattr(settings, "CAD_CACHE_ENABLED")
        checks["config_cad_cache_ttl"] = hasattr(settings, "CAD_CACHE_TTL")
        checks["config_cad_cache_ttl_default"] = (
            int(getattr(settings, "CAD_CACHE_TTL", 0)) == 86400
        )
    except Exception as e:  # noqa: BLE001
        checks["config"] = False
        errors.append(f"配置项校验失败: {e}")

    ok = all(checks.values()) if checks else False
    return {"ok": ok, "errors": errors, "checks": checks}


__all__ = [
    "compute_file_hash",
    "get_cached",
    "set_cached",
    "invalidate_cached",
    "cached_parse",
    "_self_test",
]
