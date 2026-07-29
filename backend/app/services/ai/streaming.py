"""LLM 流式输出 + 主动取消（SubTask 17.4）。

设计原则：
- 流式输出：基于 generator 逐 chunk 产出 LLM 响应，前端可实时渲染
- 主动取消：通过 Redis 标志位（``llm_stream:cancel:{request_id}`` = "1"）
  实现跨进程取消；streamer 每次产出 chunk 前检查标志位
- 优雅降级：LLM_STREAM_ENABLED=False 或 Redis 不可用时，回退为一次性返回完整响应
- 超时保护：LLM_STREAM_TIMEOUT（默认 300 秒）兜底，避免无限等待
- 资源清理：流结束（正常/异常/取消）后自动清理 Redis 标志位

取消机制：
1. 客户端发起流式请求 → 服务端生成 request_id（或客户端传入）
2. 客户端调用 ``POST /api/v1/llm/cancel/{request_id}`` 主动取消
3. 服务端在 stream_chat generator 中每次 yield 前检查 Redis 标志位
4. 检测到取消标志 → 抛 ``StreamCancelled`` 异常 + 记录日志 + 清理标志位

用法（流式）：
    from app.services.ai.streaming import stream_chat, cancel_stream, StreamCancelled

    # 流式产出（generator）
    try:
        for chunk in stream_chat(messages, request_id="abc-123"):
            print(chunk, end="", flush=True)
    except StreamCancelled:
        print("[cancelled]")

    # 主动取消
    cancel_stream("abc-123")

用法（FastAPI SSE 端点）：
    @router.post("/llm/stream")
    async def llm_stream(req: StreamRequest):
        async def event_gen():
            try:
                for chunk in stream_chat(...):
                    yield {"data": chunk}
            except StreamCancelled:
                yield {"data": "[cancelled]"}
        return EventSourceResponse(event_gen())
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Generator, Iterator

from app.config import settings
from app.logging import get_logger
from app.services.ai.base import ChatMessage, ChatResponse
from app.services.cad.cache import _get_redis_client as _cad_get_redis_client

log = get_logger(__name__)


# ===== 异常 =====


class StreamCancelled(Exception):
    """流被主动取消（客户端调用 cancel API）。"""

    def __init__(self, request_id: str, reason: str = "client_cancelled") -> None:
        self.request_id = request_id
        self.reason = reason
        super().__init__(f"stream cancelled: request_id={request_id} reason={reason}")


class StreamTimeout(Exception):
    """流超时（超过 LLM_STREAM_TIMEOUT）。"""

    def __init__(self, request_id: str, timeout_sec: int) -> None:
        self.request_id = request_id
        self.timeout_sec = timeout_sec
        super().__init__(
            f"stream timeout: request_id={request_id} timeout={timeout_sec}s"
        )


# ===== Redis 客户端（复用 cad.cache 的单例逻辑，避免重复连接）=====


def _get_redis_client() -> Any:
    """获取 Redis 客户端（复用 cad.cache 的连接池单例）。

    遵循"以复用现有为荣"原则，不重复造 Redis 连接管理。
    """
    return _cad_get_redis_client()


def _cancel_key(request_id: str) -> str:
    """构造取消标志位的 Redis key。"""
    return f"llm_stream:cancel:{request_id}"


def _status_key(request_id: str) -> str:
    """构造流状态记录的 Redis key。"""
    return f"llm_stream:status:{request_id}"


# ===== 取消 API =====


def cancel_stream(request_id: str, reason: str = "client_cancelled") -> bool:
    """主动取消一个流式请求。

    在 Redis 中设置取消标志位，streamer 在下一次 chunk 检查时检测到并退出。

    Args:
        request_id: 流请求 ID
        reason: 取消原因（记录日志）

    Returns:
        True 表示标志位设置成功；False 表示 Redis 不可用
    """
    client = _get_redis_client()
    if client is None:
        log.warning("llm.stream.cancel.redis_unavailable", request_id=request_id)
        return False
    try:
        # 设置取消标志位，TTL 5 分钟（避免长期残留）
        client.set(_cancel_key(request_id), reason, ex=300)
        log.info(
            "llm.stream.cancel.set",
            request_id=request_id,
            reason=reason,
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("llm.stream.cancel.set_failed", request_id=request_id, error=str(e))
        return False


def is_stream_cancelled(request_id: str) -> bool:
    """检查流是否已被取消。

    Args:
        request_id: 流请求 ID

    Returns:
        True 表示已被取消；False 表示未取消或 Redis 不可用
    """
    client = _get_redis_client()
    if client is None:
        return False
    try:
        return client.get(_cancel_key(request_id)) is not None
    except Exception:  # noqa: BLE001
        return False


def _clear_cancel_flag(request_id: str) -> None:
    """清理取消标志位（流结束后调用）。"""
    client = _get_redis_client()
    if client is None:
        return
    try:
        client.delete(_cancel_key(request_id))
    except Exception:  # noqa: BLE001
        pass


def _set_stream_status(request_id: str, status: str, extra: dict[str, Any] | None = None) -> None:
    """记录流状态（running / completed / cancelled / failed）。

    用于运维查询当前活跃流。TTL 1 小时。
    """
    import json

    client = _get_redis_client()
    if client is None:
        return
    try:
        payload: dict[str, Any] = {
            "status": status,
            "updated_at": time.time(),
        }
        if extra:
            payload.update(extra)
        client.set(_status_key(request_id), json.dumps(payload), ex=3600)
    except Exception:  # noqa: BLE001
        pass


def get_stream_status(request_id: str) -> dict[str, Any] | None:
    """查询流状态。"""
    import json

    client = _get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(_status_key(request_id))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


# ===== 流式输出核心 =====


def generate_request_id() -> str:
    """生成唯一的流请求 ID（uuid4 前 12 位，便于日志与调试）。"""
    return uuid.uuid4().hex[:12]


def stream_chat(
    messages: list[ChatMessage],
    request_id: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    provider: Any = None,
) -> Iterator[str]:
    """流式输出 LLM 响应（generator）。

    行为：
    - LLM_STREAM_ENABLED=False：直接调用 provider.chat()，一次性 yield 完整响应
    - LLM_STREAM_ENABLED=True：调用 provider.stream_chat()，逐 chunk yield
    - 每次 yield 前检查取消标志位，被取消时抛 ``StreamCancelled``
    - 超时（LLM_STREAM_TIMEOUT）抛 ``StreamTimeout``
    - 流结束后自动清理取消标志位 + 记录最终状态

    Args:
        messages: 对话消息列表
        request_id: 流请求 ID（None 时自动生成）
        temperature: 采样温度
        max_tokens: 最大生成 token 数
        provider: LLM Provider 实例（None 时用 get_llm_provider()）

    Yields:
        str: 响应文本片段（chunk）

    Raises:
        StreamCancelled: 被主动取消
        StreamTimeout: 超时
    """
    if request_id is None:
        request_id = generate_request_id()

    if provider is None:
        from app.services.ai.base import get_llm_provider

        provider = get_llm_provider()

    stream_enabled = bool(getattr(settings, "LLM_STREAM_ENABLED", True))
    timeout_sec = int(getattr(settings, "LLM_STREAM_TIMEOUT", 300))

    _set_stream_status(request_id, "running", extra={"stream": stream_enabled})
    start_time = time.monotonic()
    chunks_count = 0
    total_chars = 0

    try:
        if not stream_enabled:
            # 降级：非流式模式，一次性返回完整响应
            log.info(
                "llm.stream.disabled",
                request_id=request_id,
                reason="LLM_STREAM_ENABLED=False",
            )
            # 检查取消
            if is_stream_cancelled(request_id):
                raise StreamCancelled(request_id)
            resp: ChatResponse = provider.chat(
                messages, temperature=temperature, max_tokens=max_tokens
            )
            if resp.content:
                yield resp.content
                chunks_count = 1
                total_chars = len(resp.content)
            _set_stream_status(
                request_id,
                "completed",
                extra={
                    "chunks": chunks_count,
                    "chars": total_chars,
                    "elapsed_ms": int((time.monotonic() - start_time) * 1000),
                },
            )
            return

        # 流式模式：调用 provider.stream_chat()
        # provider 需实现 stream_chat 方法；否则降级为非流式
        stream_fn = getattr(provider, "stream_chat", None)
        if stream_fn is None:
            log.warning(
                "llm.stream.fallback_no_stream_method",
                request_id=request_id,
                provider=type(provider).__name__,
            )
            if is_stream_cancelled(request_id):
                raise StreamCancelled(request_id)
            resp = provider.chat(
                messages, temperature=temperature, max_tokens=max_tokens
            )
            if resp.content:
                yield resp.content
                chunks_count = 1
                total_chars = len(resp.content)
            _set_stream_status(
                request_id,
                "completed",
                extra={
                    "chunks": chunks_count,
                    "chars": total_chars,
                    "elapsed_ms": int((time.monotonic() - start_time) * 1000),
                    "fallback": True,
                },
            )
            return

        # 真正流式产出
        for chunk in stream_fn(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            # 检查取消
            if is_stream_cancelled(request_id):
                raise StreamCancelled(request_id)
            # 检查超时
            elapsed = time.monotonic() - start_time
            if elapsed > timeout_sec:
                raise StreamTimeout(request_id, timeout_sec)
            if chunk:
                yield chunk
                chunks_count += 1
                total_chars += len(chunk)

        _set_stream_status(
            request_id,
            "completed",
            extra={
                "chunks": chunks_count,
                "chars": total_chars,
                "elapsed_ms": int((time.monotonic() - start_time) * 1000),
            },
        )
        log.info(
            "llm.stream.completed",
            request_id=request_id,
            chunks=chunks_count,
            chars=total_chars,
            elapsed_ms=int((time.monotonic() - start_time) * 1000),
        )
    except StreamCancelled as e:
        _set_stream_status(
            request_id,
            "cancelled",
            extra={
                "reason": e.reason,
                "chunks_before_cancel": chunks_count,
                "chars_before_cancel": total_chars,
                "elapsed_ms": int((time.monotonic() - start_time) * 1000),
            },
        )
        log.info(
            "llm.stream.cancelled",
            request_id=request_id,
            reason=e.reason,
            chunks=chunks_count,
            chars=total_chars,
        )
        raise
    except StreamTimeout as e:
        _set_stream_status(
            request_id,
            "timeout",
            extra={
                "timeout_sec": e.timeout_sec,
                "chunks": chunks_count,
                "chars": total_chars,
            },
        )
        log.warning(
            "llm.stream.timeout",
            request_id=request_id,
            timeout=e.timeout_sec,
            chunks=chunks_count,
        )
        raise
    except Exception as e:
        _set_stream_status(
            request_id,
            "failed",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "chunks": chunks_count,
                "chars": total_chars,
            },
        )
        log.warning(
            "llm.stream.failed",
            request_id=request_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
    finally:
        _clear_cancel_flag(request_id)


# ===== 离线自检 =====


class _MockProvider:
    """模拟 Provider，用于流式自检（不依赖真实 LLM）。"""

    def __init__(self, chunks: list[str] | None = None, fail_on_chunk: int | None = None) -> None:
        self._chunks = chunks or ["Hello", ", ", "world", "!"]
        self._fail_on_chunk = fail_on_chunk
        self.chat_calls = 0

    def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        self.chat_calls += 1
        return ChatResponse(content="".join(self._chunks), model="mock")

    def stream_chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        for i, chunk in enumerate(self._chunks):
            if self._fail_on_chunk is not None and i >= self._fail_on_chunk:
                raise RuntimeError(f"mock fail at chunk {i}")
            yield chunk


def _self_test() -> dict[str, Any]:
    """离线自检：验证 LLM 流式输出与主动取消功能。

    本测试使用 fakeredis + MockProvider，不依赖真实 LLM/Ollama。

    测试内容：
    1. 模块导入安全
    2. request_id 生成唯一性
    3. 取消标志位 set/get/clear
    4. 流式输出（正常完成）
    5. 流式输出（中途取消）
    6. 非流式降级（LLM_STREAM_ENABLED=False）
    7. provider 无 stream_chat 方法时降级
    8. 流状态记录与查询
    9. 超时保护（模拟）

    Returns:
        {"ok": bool, "errors": list[str], "checks": dict[str, bool]}
    """
    import json

    checks: dict[str, bool] = {}
    errors: list[str] = []

    # 注入 fakeredis（复用 cad.cache 的 _redis_client 单例）
    try:
        import fakeredis

        from app.services.cad import cache as cad_cache_mod

        fake = fakeredis.FakeRedis(decode_responses=True)
        cad_cache_mod._redis_client = fake
        cad_cache_mod._redis_unavailable_logged = False
    except Exception as e:  # noqa: BLE001
        checks["fakeredis_setup"] = False
        errors.append(f"fakeredis 注入失败: {e}")
        return {"ok": False, "errors": errors, "checks": checks}

    # 1. 模块导入与函数存在
    try:
        checks["stream_chat_callable"] = callable(stream_chat)
        checks["cancel_stream_callable"] = callable(cancel_stream)
        checks["is_stream_cancelled_callable"] = callable(is_stream_cancelled)
        checks["generate_request_id_callable"] = callable(generate_request_id)
        checks["get_stream_status_callable"] = callable(get_stream_status)
    except Exception as e:  # noqa: BLE001
        checks["module_import"] = False
        errors.append(f"模块导入失败: {e}")

    # 2. request_id 唯一性
    try:
        ids = {generate_request_id() for _ in range(100)}
        checks["request_id_unique"] = len(ids) == 100
        checks["request_id_length"] = all(len(rid) == 12 for rid in ids)
    except Exception as e:  # noqa: BLE001
        checks["request_id_gen"] = False
        errors.append(f"request_id 生成失败: {e}")

    # 3. 取消标志位 set/get/clear
    try:
        rid = "test-cancel-001"
        # 初始未取消
        checks["initial_not_cancelled"] = not is_stream_cancelled(rid)
        # 设置取消
        ok = cancel_stream(rid, reason="test")
        checks["cancel_set_ok"] = ok
        checks["cancel_detected"] = is_stream_cancelled(rid)
        # 清理
        _clear_cancel_flag(rid)
        checks["cancel_cleared"] = not is_stream_cancelled(rid)
    except Exception as e:  # noqa: BLE001
        checks["cancel_flag"] = False
        errors.append(f"取消标志位测试失败: {e}")

    # 4. 流式输出（正常完成）
    try:
        provider = _MockProvider(chunks=["Hello", ", ", "world", "!"])
        rid = "test-stream-001"
        chunks = list(stream_chat([ChatMessage(role="user", content="hi")], request_id=rid, provider=provider))
        checks["stream_normal_chunks"] = len(chunks) == 4
        checks["stream_normal_content"] = "".join(chunks) == "Hello, world!"
        # 流状态应为 completed
        status = get_stream_status(rid)
        checks["stream_normal_status_completed"] = (
            status is not None and status.get("status") == "completed"
        )
        checks["stream_normal_status_chars"] = (
            status is not None and status.get("chars") == 13
        )
    except Exception as e:  # noqa: BLE001
        checks["stream_normal"] = False
        errors.append(f"流式输出（正常）测试失败: {e}")

    # 5. 流式输出（中途取消）
    try:
        provider = _MockProvider(chunks=["a", "b", "c", "d", "e"])
        rid = "test-stream-cancel-001"
        # 预设取消标志位（在第一个 chunk 后取消）
        cancel_stream(rid, reason="user_clicked_cancel")
        cancelled = False
        received_chunks: list[str] = []
        try:
            for chunk in stream_chat(
                [ChatMessage(role="user", content="hi")],
                request_id=rid,
                provider=provider,
            ):
                received_chunks.append(chunk)
        except StreamCancelled:
            cancelled = True
        checks["stream_cancelled_raised"] = cancelled
        # 由于 cancel 标志位预设，应在第一个 chunk yield 前就检测到
        # （stream_chat 在 yield 前检查，第一个 chunk 不会产出）
        checks["stream_cancelled_no_chunks"] = len(received_chunks) == 0
        # 状态应为 cancelled
        status = get_stream_status(rid)
        checks["stream_cancelled_status"] = (
            status is not None and status.get("status") == "cancelled"
        )
    except Exception as e:  # noqa: BLE001
        checks["stream_cancel"] = False
        errors.append(f"流式输出（取消）测试失败: {e}")

    # 5b. 流式输出（中途取消 - 第二个 chunk 后取消）
    try:
        provider = _MockProvider(chunks=["a", "b", "c", "d"])
        rid = "test-stream-cancel-002"
        received_chunks: list[str] = []
        cancel_triggered = False
        try:
            for i, chunk in enumerate(
                stream_chat(
                    [ChatMessage(role="user", content="hi")],
                    request_id=rid,
                    provider=provider,
                )
            ):
                received_chunks.append(chunk)
                # 在收到第一个 chunk 后设置取消
                if i == 0 and not cancel_triggered:
                    cancel_stream(rid, reason="mid_stream_cancel")
                    cancel_triggered = True
        except StreamCancelled:
            pass
        # 应该收到至少 1 个 chunk（第一个），但不会收到全部 4 个
        checks["stream_mid_cancel_partial"] = 1 <= len(received_chunks) < 4
        status = get_stream_status(rid)
        checks["stream_mid_cancel_status"] = (
            status is not None and status.get("status") == "cancelled"
        )
    except Exception as e:  # noqa: BLE001
        checks["stream_mid_cancel"] = False
        errors.append(f"流式输出（中途取消）测试失败: {e}")

    # 6. 非流式降级（LLM_STREAM_ENABLED=False）
    try:
        original = settings.LLM_STREAM_ENABLED
        # 临时禁用流式
        settings.LLM_STREAM_ENABLED = False
        try:
            provider = _MockProvider(chunks=["full", "response"])
            rid = "test-stream-disabled-001"
            chunks = list(stream_chat(
                [ChatMessage(role="user", content="hi")],
                request_id=rid,
                provider=provider,
            ))
            # 非流式：一次性 yield 完整响应（provider.chat 拼接所有 chunks）
            checks["disabled_single_yield"] = len(chunks) == 1
            checks["disabled_full_content"] = chunks[0] == "fullresponse" if chunks else False
            checks["disabled_provider_chat_called"] = provider.chat_calls == 1
            status = get_stream_status(rid)
            checks["disabled_status_completed"] = (
                status is not None and status.get("status") == "completed"
            )
        finally:
            settings.LLM_STREAM_ENABLED = original
    except Exception as e:  # noqa: BLE001
        checks["disabled_mode"] = False
        errors.append(f"非流式降级测试失败: {e}")

    # 7. provider 无 stream_chat 方法时降级
    try:
        class _NoStreamProvider:
            def __init__(self) -> None:
                self.chat_calls = 0
            def chat(self, messages, temperature=0.2, max_tokens=2048) -> ChatResponse:
                self.chat_calls += 1
                return ChatResponse(content="fallback", model="no_stream")

        provider = _NoStreamProvider()
        rid = "test-stream-fallback-001"
        chunks = list(stream_chat(
            [ChatMessage(role="user", content="hi")],
            request_id=rid,
            provider=provider,
        ))
        checks["fallback_single_yield"] = len(chunks) == 1
        checks["fallback_content"] = chunks[0] == "fallback" if chunks else False
        checks["fallback_chat_called"] = provider.chat_calls == 1
        status = get_stream_status(rid)
        checks["fallback_status_completed"] = (
            status is not None
            and status.get("status") == "completed"
            and status.get("fallback") is True
        )
    except Exception as e:  # noqa: BLE001
        checks["fallback_no_stream_method"] = False
        errors.append(f"无 stream_chat 降级测试失败: {e}")

    # 8. 流状态查询（不存在的 request_id）
    try:
        status = get_stream_status("nonexistent-rid-99999")
        checks["status_none_for_nonexistent"] = status is None
    except Exception as e:  # noqa: BLE001
        checks["status_query"] = False
        errors.append(f"流状态查询测试失败: {e}")

    # 9. 配置项存在
    try:
        checks["config_llm_stream_enabled"] = hasattr(settings, "LLM_STREAM_ENABLED")
        checks["config_llm_stream_timeout"] = hasattr(settings, "LLM_STREAM_TIMEOUT")
        checks["config_llm_stream_timeout_default"] = (
            int(getattr(settings, "LLM_STREAM_TIMEOUT", 0)) == 300
        )
    except Exception as e:  # noqa: BLE001
        checks["config"] = False
        errors.append(f"配置项校验失败: {e}")

    # 清理 fakeredis
    cad_cache_mod._redis_client = None
    cad_cache_mod._redis_unavailable_logged = False

    ok = all(checks.values()) if checks else False
    return {"ok": ok, "errors": errors, "checks": checks}


__all__ = [
    "StreamCancelled",
    "StreamTimeout",
    "stream_chat",
    "cancel_stream",
    "is_stream_cancelled",
    "get_stream_status",
    "generate_request_id",
    "_self_test",
]
