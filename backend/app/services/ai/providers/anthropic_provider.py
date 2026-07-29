"""Anthropic Claude LLM Provider（SubTask 3.4）。

官方文档：
- Messages API: https://docs.anthropic.com/en/api/messages
- Vision 指南: https://docs.anthropic.com/en/docs/build-with-claude/vision

关键 API 参数（已查阅官方文档与 2026 年社区文档确认）：
- 端点: POST https://api.anthropic.com/v1/messages
- Headers:
    x-api-key: <ANTHROPIC_API_KEY>
    anthropic-version: 2023-06-01
    content-type: application/json
- 请求体（system 是顶级参数，不在 messages 数组中）:
    {
      "model": "claude-3-5-sonnet-latest",
      "max_tokens": 1024,        # 必填
      "system": "...",            # 可选
      "messages": [{"role":"user","content":"..."}],
      "temperature": 0.2
    }
- Vision content block（与 text block 共存于 user message content 数组）:
    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "<b64>"}}
    {"type": "text", "text": "..."}
- 响应:
    {
      "content": [{"type": "text", "text": "..."}],
      "model": "claude-...",
      "usage": {"input_tokens": N, "output_tokens": M}
    }

实现策略：
- 优先用 anthropic 官方 SDK（>=0.20）：`from anthropic import Anthropic` + `client.messages.create`
- SDK 未安装时用 httpx 直接调 REST API 兜底（venv 当前未装 anthropic，走此路径）

配置项（SubTask 3.6 将在 settings 中正式添加，本 subtask 暂用环境变量兜底）：
- ANTHROPIC_API_KEY
- ANTHROPIC_BASE_URL（默认 https://api.anthropic.com）
- ANTHROPIC_MODEL（默认 claude-3-5-sonnet-latest）
- ANTHROPIC_VLM_MODEL（默认空，决定 is_vlm_available）

降级路径：API Key 未配置或调用失败时返回空 ChatResponse + warning，不抛异常。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.logging import get_logger
from app.services.ai.base import BaseLLMProvider, ChatMessage, ChatResponse

log = get_logger(__name__)

# 默认值
_DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
_DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-latest"
_ANTHROPIC_VERSION = "2023-06-01"


def _get_env(key: str, default: str = "") -> str:
    """从环境变量读取配置（SubTask 3.6 后改读 settings）。"""
    try:
        from app.config import settings

        val = getattr(settings, key, None)
        if val:
            return str(val)
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get(key, default)


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude Provider。

    优先用官方 SDK；未安装时用 httpx 直接调 REST API。
    API Key 未配置或调用失败时返回空 ChatResponse。
    """

    def __init__(self) -> None:
        self._api_key: str = _get_env("ANTHROPIC_API_KEY")
        self._base_url: str = _get_env("ANTHROPIC_BASE_URL", _DEFAULT_ANTHROPIC_BASE_URL)
        self._base_url = self._base_url.rstrip("/")
        self._model: str = _get_env("ANTHROPIC_MODEL", _DEFAULT_ANTHROPIC_MODEL) or _DEFAULT_ANTHROPIC_MODEL
        self._vlm_model: str = _get_env("ANTHROPIC_VLM_MODEL")
        self._client: Any | None = None
        self._use_sdk: bool = False
        self._init_error: str | None = None
        self._init_client()

    def _init_client(self) -> None:
        """初始化 Anthropic client：优先 SDK，回退 httpx。"""
        if not self._api_key:
            self._init_error = "ANTHROPIC_API_KEY 未配置"
            log.warning("ai.anthropic.init_skipped", reason="no_api_key")
            return
        try:
            import anthropic  # type: ignore[import-untyped]

            self._client = anthropic.Anthropic(api_key=self._api_key, base_url=self._base_url)
            self._use_sdk = True
            log.info(
                "ai.anthropic.init_ok_sdk",
                base_url=self._base_url,
                model=self._model,
                vlm_model=self._vlm_model or "",
                sdk_version=getattr(anthropic, "__version__", "unknown"),
            )
        except ImportError:
            # SDK 未安装，走 httpx 兜底
            self._client = "httpx"  # 占位标记，表示走 httpx 路径
            log.info(
                "ai.anthropic.init_ok_httpx",
                base_url=self._base_url,
                model=self._model,
                vlm_model=self._vlm_model or "",
                reason="anthropic_sdk_not_installed",
            )
        except Exception as e:  # noqa: BLE001
            self._init_error = f"Anthropic client 初始化失败: {e}"
            log.warning("ai.anthropic.init_failed", error=str(e))

    # ===== 可用性检测 =====

    def is_available(self) -> bool:
        """实测发起 ping 消息验证 API Key 与端点可达。"""
        if self._client is None:
            return False
        try:
            resp = self._invoke_messages(
                model=self._model,
                system=None,
                messages=[{"role": "user", "content": "ping"}],
                temperature=0.0,
                max_tokens=1,
            )
            return bool(resp)
        except Exception as e:  # noqa: BLE001
            log.warning("ai.anthropic.ping_failed", error=str(e))
            return False

    def is_vlm_available(self) -> bool:
        """视觉模型是否可用：检查 ANTHROPIC_VLM_MODEL 是否非空。"""
        return bool(self._vlm_model)

    # ===== 文本对话 =====

    def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """文本对话。system role 提取为顶级 system 参数。调用失败时返回空 ChatResponse。

        SubTask 13.3：商业 API 脱敏模式启用时，先对 messages 脱敏再调用。
        """
        if self._client is None:
            log.warning("ai.anthropic.chat.skipped", reason="no_client", error=self._init_error or "")
            return ChatResponse()

        # SubTask 13.3: 商业 API 脱敏（off/optional/strict）
        try:
            from app.services.ai.desensitize import sanitize_messages

            messages = sanitize_messages(messages)  # type: ignore[assignment]
        except ValueError as e:
            log.warning("ai.anthropic.chat.desensitize_rejected", error=str(e))
            return ChatResponse()
        except Exception as e:  # noqa: BLE001
            # strict 模式下脱敏异常必须 fail-closed，避免泄露未脱敏内容
            from app.config import settings

            log.warning("ai.anthropic.chat.desensitize_failed", error=str(e), strict=settings.commercial_api_strict)
            if settings.commercial_api_strict:
                return ChatResponse()

        system_msg, payload_messages = self._split_system(messages)
        try:
            resp = self._invoke_messages(
                model=self._model,
                system=system_msg,
                messages=payload_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("ai.anthropic.chat.failed", model=self._model, error=str(e))
            return ChatResponse()

        return self._convert_dict(resp)

    # ===== 多模态对话 =====

    def chat_with_image(
        self,
        messages: list[ChatMessage],
        image_b64: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """多模态对话：将最后一条 user message 的 content 改为 [image, text] 数组。

        调用失败时返回空 ChatResponse + warning。
        """
        if self._client is None:
            log.warning("ai.anthropic.chat_image.skipped", reason="no_client", error=self._init_error or "")
            return ChatResponse()
        if not self._vlm_model:
            log.warning("ai.anthropic.chat_image.skipped", reason="no_vlm_model")
            return ChatResponse()

        # SubTask 13.3: 商业 API 脱敏（与 chat() 一致，多模态也需脱敏文本内容）
        try:
            from app.services.ai.desensitize import sanitize_messages

            messages = sanitize_messages(messages)  # type: ignore[assignment]
        except ValueError as e:
            log.warning("ai.anthropic.chat_image.desensitize_rejected", error=str(e))
            return ChatResponse()
        except Exception as e:  # noqa: BLE001
            # strict 模式下脱敏异常必须 fail-closed，避免泄露未脱敏内容
            from app.config import settings

            log.warning("ai.anthropic.chat_image.desensitize_failed", error=str(e), strict=settings.commercial_api_strict)
            if settings.commercial_api_strict:
                return ChatResponse()

        system_msg, payload_messages = self._split_system(messages)
        payload_messages = self._inject_image_to_last_user(payload_messages, image_b64)
        try:
            resp = self._invoke_messages(
                model=self._vlm_model,
                system=system_msg,
                messages=payload_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("ai.anthropic.chat_image.failed", model=self._vlm_model, error=str(e))
            return ChatResponse()

        return self._convert_dict(resp)

    # ===== 内部工具：消息构造 =====

    @staticmethod
    def _split_system(
        messages: list[ChatMessage],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """从 messages 中提取 system role，剩余只保留 user/assistant。

        Anthropic 的 system 是顶级参数，不能放在 messages 数组中。
        多条 system 用 "\n\n" 拼接。
        """
        system_parts: list[str] = []
        payload: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                if m.content:
                    system_parts.append(m.content)
            else:
                payload.append({"role": m.role, "content": m.content})
        system_msg = "\n\n".join(system_parts) if system_parts else None
        return system_msg, payload

    @staticmethod
    def _inject_image_to_last_user(
        payload: list[dict[str, Any]],
        image_b64: str,
    ) -> list[dict[str, Any]]:
        """将最后一条 user message 的 content 替换为 [image, text] 数组。

        若不存在 user message，则追加一条含图片的 user message。
        Anthropic 要求 image block 在 text block 之前（部分客户端对此敏感，按官方示例顺序排列）。
        """
        last_user_idx = -1
        for i in range(len(payload) - 1, -1, -1):
            if payload[i].get("role") == "user":
                last_user_idx = i
                break
        text_content = str(payload[last_user_idx].get("content", "")) if last_user_idx >= 0 else ""
        vision_content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_b64,
                },
            },
            {"type": "text", "text": text_content},
        ]
        if last_user_idx >= 0:
            payload[last_user_idx]["content"] = vision_content
        else:
            payload.append({"role": "user", "content": vision_content})
        return payload

    # ===== 内部工具：HTTP 调用 =====

    def _invoke_messages(
        self,
        model: str,
        system: str | None,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """统一调用入口：SDK 路径返回 model_dump() dict，httpx 路径返回 resp.json()。

        异常向上抛出，由 chat / chat_with_image / is_available 捕获并降级。
        """
        if self._use_sdk and self._client is not None and self._client != "httpx":
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
                "temperature": temperature,
            }
            # system 为空时不传 system 参数（Anthropic SDK 不接受 None）
            if system:
                kwargs["system"] = system
            resp = self._client.messages.create(**kwargs)
            if hasattr(resp, "model_dump"):
                return resp.model_dump()
            return dict(resp)  # 兜底
        # httpx 兜底
        return self._invoke_httpx(model, system, messages, temperature, max_tokens)

    def _invoke_httpx(
        self,
        model: str,
        system: str | None,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """直接调 REST API: POST {base_url}/v1/messages。"""
        url = f"{self._base_url}/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
        }
        if system:
            body["system"] = system
        # 超时：text 60s，vision 可能更慢但调用方应已设大 max_tokens
        resp = httpx.post(url, headers=headers, json=body, timeout=120.0)
        resp.raise_for_status()
        return resp.json()

    # ===== 内部工具：响应转换 =====

    @staticmethod
    def _convert_dict(data: dict[str, Any]) -> ChatResponse:
        """将 Anthropic 响应 dict 转换为统一 ChatResponse。

        响应结构:
          {"content": [{"type":"text","text":"..."}, ...],
           "model": "...", "usage": {"input_tokens": N, "output_tokens": M}}
        """
        content = ""
        try:
            for block in data.get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    content += str(block.get("text", ""))
        except Exception as e:  # noqa: BLE001
            log.warning("ai.anthropic.convert_content_failed", error=str(e))

        model = str(data.get("model", "") or "")
        usage: dict[str, int] | None = None
        u = data.get("usage")
        if isinstance(u, dict):
            usage = {
                "input_tokens": int(u.get("input_tokens", 0) or 0),
                "output_tokens": int(u.get("output_tokens", 0) or 0),
            }

        return ChatResponse(content=content, model=model, usage=usage, raw=data)
