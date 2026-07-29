"""LLM 流式输出 + 主动取消 API 端点（SubTask 17.4）。

端点：
- ``POST /api/v1/llm/stream``：流式输出 LLM 响应（SSE）
- ``POST /api/v1/llm/cancel/{request_id}``：主动取消流式请求
- ``GET /api/v1/llm/stream/{request_id}/status``：查询流式请求状态

设计原则：
- SSE（Server-Sent Events）：标准协议，浏览器原生支持 EventSource
- 主动取消：通过 Redis 标志位实现跨进程取消
- 优雅降级：LLM_STREAM_ENABLED=False 时回退为普通 JSON 响应
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import SettingsDep, get_current_user_id
from app.config import Settings
from app.logging import get_logger
from app.services.ai.base import ChatMessage, get_llm_provider
from app.services.ai.streaming import (
    StreamCancelled,
    StreamTimeout,
    cancel_stream,
    generate_request_id,
    get_stream_status,
    is_stream_cancelled,
    stream_chat,
)

router = APIRouter()
log = get_logger(__name__)


# ===== Schemas =====


class StreamChatRequest(BaseModel):
    """流式对话请求。"""

    messages: list[ChatMessage] = Field(..., description="对话消息列表")
    request_id: str | None = Field(
        default=None,
        description="流请求 ID（None 时自动生成）；客户端可传入以便主动取消",
    )
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=32768)


class StreamCancelRequest(BaseModel):
    """取消流式请求。"""

    reason: str = Field(default="client_cancelled", description="取消原因")


class StreamCancelResponse(BaseModel):
    """取消流式请求响应。"""

    request_id: str
    cancelled: bool
    message: str = ""


class StreamStatusResponse(BaseModel):
    """流式请求状态。"""

    request_id: str
    found: bool
    status: dict[str, Any] | None = None


# ===== 端点 =====


@router.post(
    "/llm/stream",
    response_model=None,
    summary="LLM 流式输出（SSE）",
    description=(
        "以 Server-Sent Events 形式流式输出 LLM 响应。"
        "客户端可通过 ``POST /api/v1/llm/cancel/{request_id}`` 主动取消。"
        "LLM_STREAM_ENABLED=False 时回退为普通 JSON 响应（一次性返回完整内容）。"
    ),
)
async def llm_stream(
    req: StreamChatRequest,
    settings: Settings = SettingsDep,
    user_id: str = Depends(get_current_user_id),
) -> StreamingResponse | JSONResponse:
    """流式输出 LLM 响应。

    SSE 事件格式：
    - ``data: {"chunk": "..."}``：文本片段
    - ``data: {"done": true, "request_id": "..."}``：流正常结束（JSON 对象，向后兼容）
    - ``data: {"cancelled": true, "request_id": "..."}``：被取消（JSON 对象）
    - ``data: {"error": "...", "request_id": "..."}``：错误（JSON 对象）
    - ``data: [DONE]``：OpenAI 风格的流终止标记，**所有终止分支**（done / cancelled / error）末尾均追加此行

    终止标记遵循 OpenAI SSE 规范：客户端在收到 ``data: [DONE]`` 行后必须关闭连接，
    不应继续解析后续内容。``[DONE]`` 行不是 JSON 对象，客户端解析时应单独处理。
    """
    request_id = f"{user_id}-{req.request_id or generate_request_id()}"
    log.info(
        "llm.stream.api.received",
        request_id=request_id,
        user_id=user_id,
        messages_count=len(req.messages),
        stream_enabled=settings.LLM_STREAM_ENABLED,
    )

    # 非流式降级：直接返回完整响应
    if not settings.LLM_STREAM_ENABLED:
        try:
            provider = get_llm_provider()
            resp = provider.chat(
                req.messages,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            )
            return JSONResponse(
                {
                    "request_id": request_id,
                    "content": resp.content,
                    "model": resp.model,
                    "streamed": False,
                }
            )
        except Exception as e:  # noqa: BLE001
            log.warning("llm.stream.api.fallback_failed", error=str(e))
            return JSONResponse(
                {"request_id": request_id, "content": "", "error": str(e)},
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # 流式 SSE
    def event_gen():
        try:
            for chunk in stream_chat(
                req.messages,
                request_id=request_id,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            ):
                yield f"data: {json.dumps({'chunk': chunk, 'request_id': request_id}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'request_id': request_id}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except StreamCancelled:
            yield f"data: {json.dumps({'cancelled': True, 'request_id': request_id}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except StreamTimeout as e:
            yield f"data: {json.dumps({'error': f'stream timeout: {e.timeout_sec}s', 'request_id': request_id}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:  # noqa: BLE001
            log.warning("llm.stream.api.error", request_id=request_id, error=str(e))
            yield f"data: {json.dumps({'error': str(e), 'request_id': request_id}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
            "X-Request-Id": request_id,
        },
    )


@router.post(
    "/llm/cancel/{request_id}",
    response_model=StreamCancelResponse,
    summary="主动取消流式请求",
    description="设置 Redis 取消标志位，streamer 在下一次 chunk 检查时退出。",
)
async def llm_cancel(
    request_id: str,
    req: StreamCancelRequest | None = None,
) -> StreamCancelResponse:
    """主动取消一个流式请求。"""
    reason = req.reason if req else "client_cancelled"
    # 先检查是否还在运行
    stream_status = get_stream_status(request_id)
    if stream_status is None:
        return StreamCancelResponse(
            request_id=request_id,
            cancelled=False,
            message="stream not found (already completed or never started)",
        )
    if stream_status.get("status") in ("completed", "cancelled", "failed", "timeout"):
        return StreamCancelResponse(
            request_id=request_id,
            cancelled=False,
            message=f"stream already in terminal state: {stream_status.get('status')}",
        )
    ok = cancel_stream(request_id, reason=reason)
    return StreamCancelResponse(
        request_id=request_id,
        cancelled=ok,
        message="cancel flag set" if ok else "redis unavailable, cancel flag not set",
    )


@router.get(
    "/llm/stream/{request_id}/status",
    response_model=StreamStatusResponse,
    summary="查询流式请求状态",
    description="查询流式请求的当前状态（running/completed/cancelled/failed/timeout）。",
)
async def llm_stream_status(request_id: str) -> StreamStatusResponse:
    """查询流式请求状态。"""
    s = get_stream_status(request_id)
    return StreamStatusResponse(
        request_id=request_id,
        found=s is not None,
        status=s,
    )
