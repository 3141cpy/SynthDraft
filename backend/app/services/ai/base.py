"""AI Provider 抽象基类与 schema（SubTask 3.1）。

设计原则：
- 统一 ChatMessage / ChatResponse schema，屏蔽不同厂商差异
- BaseLLMProvider 定义最小可用接口：is_available / is_vlm_available / chat / chat_with_image
- get_llm_provider() 工厂根据 settings.LLM_PROVIDER 路由到具体实现
- 所有 Provider 必须实现降级路径：API Key 未配置或调用失败时返回空 ChatResponse，不抛异常
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    """统一对话消息 schema。"""

    role: Literal["system", "user", "assistant"]
    content: str
    images: list[str] | None = None  # base64 编码图片列表（部分 provider 直接使用）


class ChatResponse(BaseModel):
    """统一对话响应 schema。"""

    content: str = ""
    model: str = ""
    usage: dict[str, int] | None = None
    raw: dict[str, Any] | None = None


class BaseLLMProvider(ABC):
    """LLM Provider 抽象基类。

    所有具体 Provider（Ollama / OpenAI / Anthropic）必须实现以下四个方法。
    实现方需保证降级路径：API Key 未配置或调用失败时返回空 ChatResponse + warning 日志，
    不向上抛出异常，以保障 review / generation pipeline 的鲁棒性。
    """

    @abstractmethod
    def is_available(self) -> bool:
        """文本模型是否可用（实测发起 ping 消息验证）。"""
        ...

    @abstractmethod
    def is_vlm_available(self) -> bool:
        """视觉模型是否可用（检查 VLM 模型配置 + 端点可达）。"""
        ...

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """文本对话。"""
        ...

    @abstractmethod
    def chat_with_image(
        self,
        messages: list[ChatMessage],
        image_b64: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """多模态对话：附带一张 base64 编码图片。"""
        ...


_provider_instance: BaseLLMProvider | None = None


def get_llm_provider() -> BaseLLMProvider:
    """单例工厂：根据 settings.LLM_PROVIDER 返回具体 Provider 实例。

    支持：ollama / openai / anthropic / vllm。
    SubTask 13.1 降级路径：LLM_PROVIDER=vllm 但 VLLM_ENABLED=False 时回退到 Ollama。
    路由失败时抛 ValueError（配置错误属致命问题，不应降级）。
    """
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance
    from app.config import settings

    provider_name = (settings.LLM_PROVIDER or "").lower().strip()
    if provider_name == "ollama":
        from app.services.ai.providers.ollama_provider import OllamaProvider

        _provider_instance = OllamaProvider()
    elif provider_name == "openai":
        from app.services.ai.providers.openai_provider import OpenAIProvider

        _provider_instance = OpenAIProvider()
    elif provider_name == "anthropic":
        from app.services.ai.providers.anthropic_provider import AnthropicProvider

        _provider_instance = AnthropicProvider()
    elif provider_name == "vllm":
        # SubTask 13.1 降级路径：VLLM_ENABLED=False 时回退到 Ollama
        if not settings.VLLM_ENABLED:
            from app.logging import get_logger

            log = get_logger(__name__)
            log.warning(
                "ai.provider.vllm_fallback_to_ollama",
                reason="VLLM_ENABLED_false",
            )
            from app.services.ai.providers.ollama_provider import OllamaProvider

            _provider_instance = OllamaProvider()
        else:
            from app.services.ai.providers.vllm_provider import VLLMProvider

            _provider_instance = VLLMProvider()
    else:
        raise ValueError(f"不支持的 LLM_PROVIDER: {provider_name!r}")
    return _provider_instance


def reset_provider_cache() -> None:
    """重置单例缓存（测试用）。"""
    global _provider_instance
    _provider_instance = None
