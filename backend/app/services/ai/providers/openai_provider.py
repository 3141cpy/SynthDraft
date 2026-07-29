"""OpenAI 兼容 LLM Provider（SubTask 3.3）。

支持厂商：OpenAI 官方 / vLLM / DeepSeek / 通义千问 / 智谱 GLM 等 OpenAI 兼容端点。
通过 OPENAI_BASE_URL 切换端点，OPENAI_API_KEY 鉴权。

官方文档：
- Chat Completions API: https://platform.openai.com/docs/api-reference/chat
- Vision 指南: https://platform.openai.com/docs/guides/vision

关键 API 参数（已查阅官方文档确认）：
- client.chat.completions.create(model, messages, temperature, max_tokens)
- messages: [{"role": "system|user|assistant", "content": "..."}]
- Vision content block:
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,<b64>"}}
  与 {"type": "text", "text": "..."} 共存于 user message 的 content 数组中
- 响应: resp.choices[0].message.content / resp.usage.{prompt,completion,total}_tokens

配置项（SubTask 3.6 将在 settings 中正式添加，本 subtask 暂用环境变量兜底）：
- OPENAI_API_KEY：API Key
- OPENAI_BASE_URL：兼容端点 URL（默认 https://api.openai.com/v1）
- OPENAI_MODEL：文本模型（默认 gpt-4o-mini）
- OPENAI_VLM_MODEL：视觉模型（默认空，决定 is_vlm_available）

降级路径：API Key 未配置或调用失败时返回空 ChatResponse + warning，不抛异常。
"""

from __future__ import annotations

import os
from typing import Any

from app.logging import get_logger
from app.services.ai.base import BaseLLMProvider, ChatMessage, ChatResponse

log = get_logger(__name__)

# 默认模型与端点
_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _get_env(key: str, default: str = "") -> str:
    """从环境变量读取配置（SubTask 3.6 后改读 settings）。

    优先尝试 settings 字段（若已添加），失败则回退环境变量。
    """
    # 3.6 添加 settings 字段后，此处可平滑切换；当前先用环境变量
    try:
        from app.config import settings

        val = getattr(settings, key, None)
        if val:
            return str(val)
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get(key, default)


class OpenAIProvider(BaseLLMProvider):
    """OpenAI 兼容 Provider。

    使用官方 openai SDK（>=1.0）。若 SDK 未安装或 API Key 未配置，
    is_available() 返回 False，chat*() 返回空 ChatResponse。
    """

    def __init__(self) -> None:
        self._api_key: str = _get_env("OPENAI_API_KEY")
        self._base_url: str = _get_env("OPENAI_BASE_URL", _DEFAULT_OPENAI_BASE_URL)
        self._model: str = _get_env("OPENAI_MODEL", _DEFAULT_OPENAI_MODEL) or _DEFAULT_OPENAI_MODEL
        self._vlm_model: str = _get_env("OPENAI_VLM_MODEL")
        self._client: Any | None = None
        self._init_error: str | None = None
        self._init_client()

    def _init_client(self) -> None:
        """惰性初始化 OpenAI client。

        SDK 未安装或 API Key 缺失时记录错误，不抛异常。
        """
        if not self._api_key:
            self._init_error = "OPENAI_API_KEY 未配置"
            log.warning("ai.openai.init_skipped", reason="no_api_key")
            return
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError as e:
            self._init_error = f"openai SDK 未安装: {e}"
            log.warning("ai.openai.init_skipped", reason="no_sdk", error=str(e))
            return
        try:
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
            log.info(
                "ai.openai.init_ok",
                base_url=self._base_url,
                model=self._model,
                vlm_model=self._vlm_model or "",
            )
        except Exception as e:  # noqa: BLE001
            self._init_error = f"OpenAI client 初始化失败: {e}"
            log.warning("ai.openai.init_failed", error=str(e))

    # ===== 可用性检测 =====

    def is_available(self) -> bool:
        """实测发起 ping 消息验证 API Key 与端点可达。"""
        if self._client is None:
            return False
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0.0,
            )
            return bool(resp)
        except Exception as e:  # noqa: BLE001
            log.warning("ai.openai.ping_failed", error=str(e))
            return False

    def is_vlm_available(self) -> bool:
        """视觉模型是否可用：检查 OPENAI_VLM_MODEL 是否非空。

        为避免每次都发请求消耗配额，仅做配置检查。
        实际调用 chat_with_image() 时若端点不支持视觉会降级返回空响应。
        """
        return bool(self._vlm_model)

    # ===== 文本对话 =====

    def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """文本对话。调用失败时返回空 ChatResponse + warning。

        SubTask 13.3：商业 API 脱敏模式启用时，先对 messages 脱敏再调用。
        """
        if self._client is None:
            log.warning("ai.openai.chat.skipped", reason="no_client", error=self._init_error or "")
            return ChatResponse()
        # SubTask 13.3: 商业 API 脱敏（off/optional/strict）
        try:
            from app.services.ai.desensitize import sanitize_messages

            messages = sanitize_messages(messages)  # type: ignore[assignment]
        except ValueError as e:
            # strict 模式拒绝调用
            log.warning("ai.openai.chat.desensitize_rejected", error=str(e))
            return ChatResponse()
        except Exception as e:  # noqa: BLE001
            # strict 模式下脱敏异常必须 fail-closed，避免泄露未脱敏内容
            from app.config import settings

            log.warning("ai.openai.chat.desensitize_failed", error=str(e), strict=settings.commercial_api_strict)
            if settings.commercial_api_strict:
                return ChatResponse()
            # optional/off 模式：脱敏失败不阻断调用（降级策略：宁可发原文不可中断业务）
        payload_messages = [{"role": m.role, "content": m.content} for m in messages]
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=payload_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:  # noqa: BLE001
            log.warning(
                "ai.openai.chat.failed",
                model=self._model,
                error=str(e),
            )
            return ChatResponse()

        return self._convert_response(resp)

    # ===== 多模态对话 =====

    def chat_with_image(
        self,
        messages: list[ChatMessage],
        image_b64: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """多模态对话：将最后一条 user message 的 content 改为 [text, image_url] 数组。

        调用失败时返回空 ChatResponse + warning。
        """
        if self._client is None:
            log.warning("ai.openai.chat_image.skipped", reason="no_client", error=self._init_error or "")
            return ChatResponse()
        if not self._vlm_model:
            log.warning("ai.openai.chat_image.skipped", reason="no_vlm_model")
            return ChatResponse()

        # SubTask 13.3: 商业 API 脱敏（与 chat() 一致，多模态也需脱敏文本内容）
        try:
            from app.services.ai.desensitize import sanitize_messages

            messages = sanitize_messages(messages)  # type: ignore[assignment]
        except ValueError as e:
            # strict 模式拒绝调用
            log.warning("ai.openai.chat_image.desensitize_rejected", error=str(e))
            return ChatResponse()
        except Exception as e:  # noqa: BLE001
            # strict 模式下脱敏异常必须 fail-closed，避免泄露未脱敏内容
            from app.config import settings

            log.warning("ai.openai.chat_image.desensitize_failed", error=str(e), strict=settings.commercial_api_strict)
            if settings.commercial_api_strict:
                return ChatResponse()
            # optional/off 模式：脱敏失败不阻断调用（降级策略：宁可发原文不可中断业务）

        # 构造多模态 messages：替换最后一条 user message 的 content
        payload_messages = self._build_vision_messages(messages, image_b64)
        try:
            resp = self._client.chat.completions.create(
                model=self._vlm_model,
                messages=payload_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:  # noqa: BLE001
            log.warning(
                "ai.openai.chat_image.failed",
                model=self._vlm_model,
                error=str(e),
            )
            return ChatResponse()

        return self._convert_response(resp)

    # ===== 内部工具 =====

    @staticmethod
    def _build_vision_messages(
        messages: list[ChatMessage],
        image_b64: str,
    ) -> list[dict[str, Any]]:
        """将 messages 中最后一条 user message 的 content 替换为多模态数组。

        若不存在 user message，则在末尾追加一条含图片的 user message。
        """
        payload: list[dict[str, Any]] = [
            {"role": m.role, "content": m.content} for m in messages
        ]
        # 找到最后一个 user message 的索引
        last_user_idx = -1
        for i in range(len(payload) - 1, -1, -1):
            if payload[i]["role"] == "user":
                last_user_idx = i
                break
        vision_content = [
            {"type": "text", "text": str(payload[last_user_idx]["content"]) if last_user_idx >= 0 else ""},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]
        if last_user_idx >= 0:
            payload[last_user_idx]["content"] = vision_content
        else:
            payload.append({"role": "user", "content": vision_content})
        return payload

    @staticmethod
    def _convert_response(resp: Any) -> ChatResponse:
        """将 openai SDK 响应对象转换为统一 ChatResponse。"""
        content = ""
        model = ""
        usage: dict[str, int] | None = None
        raw: dict[str, Any] | None = None
        try:
            choices = getattr(resp, "choices", None) or []
            if choices:
                msg = getattr(choices[0], "message", None)
                if msg is not None:
                    content = getattr(msg, "content", "") or ""
            model = getattr(resp, "model", "") or ""
            u = getattr(resp, "usage", None)
            if u is not None:
                usage = {
                    "prompt_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(u, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(u, "total_tokens", 0) or 0),
                }
            # 尝试转 dict 保留 raw（model_dump 适用于 pydantic 模型）
            if hasattr(resp, "model_dump"):
                try:
                    raw = resp.model_dump()
                except Exception:  # noqa: BLE001
                    raw = None
        except Exception as e:  # noqa: BLE001
            log.warning("ai.openai.convert_failed", error=str(e))

        return ChatResponse(content=content, model=model, usage=usage, raw=raw)
