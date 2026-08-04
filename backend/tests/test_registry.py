"""Task 7.3: Provider 注册表 + 工厂 + 热切换测试。

覆盖 registry.py（注册表）、base.py（工厂 + 缓存重置 + legacy fallback）。

测试用例（7 个）：
1. test_register_provider — 装饰器注册成功
2. test_get_provider_class — 查找已注册 provider
3. test_get_provider_class_not_found — 查找未注册类型返回 None
4. test_list_provider_types — 列出所有已注册类型
5. test_get_llm_provider_legacy_fallback — DB 无配置时 legacy fallback
6. test_reset_provider_cache — 重置后下次调用重新解析
7. test_providers_registered — 验证 ollama / openai_compatible / anthropic 已注册
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 backend/ 在 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 导入 providers 包以触发 @register_provider 注册
import app.services.ai.providers  # noqa: F401
from app.services.ai.base import (
    BaseLLMProvider,
    ChatMessage,
    ChatResponse,
    get_llm_provider,
    reset_provider_cache,
)
from app.services.ai.providers.ollama_provider import OllamaProvider
from app.services.ai.registry import (
    _PROVIDERS,
    get_provider_class,
    list_provider_types,
    register_provider,
)


# ===== Fixtures =====


@pytest.fixture(autouse=True)
def _reset_base_cache() -> None:
    """每个测试前后清理 base 模块全局缓存，确保隔离。"""
    reset_provider_cache()
    yield
    reset_provider_cache()


@pytest.fixture(autouse=True)
def _mock_refresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """防止 legacy fallback 路径触发真实 PostgreSQL 连接。

    get_llm_provider 的 legacy fallback 不访问 DB（_instantiate_legacy 不调 DB），
    但 _load_active_config_sync 在无事件循环时会 asyncio.run(_fetch_active_config_from_db)。
    此处 mock 确保即使无运行事件循环也不连 PostgreSQL。
    """

    async def _noop() -> None:
        pass

    monkeypatch.setattr(
        "app.services.ai.base.refresh_active_config_cache", _noop
    )


# ===== 注册表测试 =====


def test_register_provider() -> None:
    """装饰器注册成功。"""
    test_type = "test-dummy-provider"

    @register_provider(test_type)
    class DummyProvider(BaseLLMProvider):
        def is_available(self) -> bool:
            return False

        def is_vlm_available(self) -> bool:
            return False

        def chat(
            self,
            messages: list[ChatMessage],
            temperature: float = 0.2,
            max_tokens: int = 2048,
        ) -> ChatResponse:
            return ChatResponse()

        def chat_with_image(
            self,
            messages: list[ChatMessage],
            image_b64: str,
            temperature: float = 0.2,
            max_tokens: int = 2048,
        ) -> ChatResponse:
            return ChatResponse()

    try:
        assert test_type in list_provider_types()
        assert get_provider_class(test_type) is DummyProvider
    finally:
        # 清理：移除测试专用 provider，避免污染其他测试
        _PROVIDERS.pop(test_type, None)


def test_get_provider_class() -> None:
    """查找已注册 provider。"""
    cls = get_provider_class("ollama")
    assert cls is not None
    assert cls is OllamaProvider


def test_get_provider_class_not_found() -> None:
    """查找未注册类型返回 None。"""
    cls = get_provider_class("nonexistent-provider-type")
    assert cls is None


def test_list_provider_types() -> None:
    """列出所有已注册类型。"""
    types = list_provider_types()
    assert "ollama" in types
    assert "openai_compatible" in types
    assert "anthropic" in types


def test_providers_registered() -> None:
    """验证 ollama / openai_compatible / anthropic 三个 provider 已注册。"""
    assert get_provider_class("ollama") is not None
    assert get_provider_class("openai_compatible") is not None
    assert get_provider_class("anthropic") is not None

    types = set(list_provider_types())
    assert {"ollama", "openai_compatible", "anthropic"}.issubset(types)


# ===== 工厂 + 热切换测试 =====


@pytest.mark.asyncio
async def test_get_llm_provider_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB 无配置时 legacy fallback（mock settings.LLM_PROVIDER）。

    async 测试中存在运行事件循环，_load_active_config_sync 检测到循环后
    直接返回 None（不访问 DB），从而走 legacy fallback 路径。
    """
    from app.config import settings

    # mock LLM_PROVIDER 为 ollama（OllamaProvider 构造函数不触发网络调用）
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    # 确保 VLLM_ENABLED 为 False（避免 vllm 分支干扰）
    monkeypatch.setattr(settings, "VLLM_ENABLED", False)

    reset_provider_cache()
    provider = get_llm_provider()
    assert provider is not None
    assert isinstance(provider, BaseLLMProvider)
    assert isinstance(provider, OllamaProvider)


def test_reset_provider_cache() -> None:
    """重置后下次调用重新解析。"""
    import app.services.ai.base as base_module

    # 手动填充缓存状态
    base_module._provider_instance = "dummy-instance"  # type: ignore[assignment]
    base_module._active_config_cache = "dummy-config"  # type: ignore[assignment]
    base_module._config_cache_loaded = True

    # 重置
    reset_provider_cache()

    # 全局缓存已清空
    assert base_module._provider_instance is None
    assert base_module._active_config_cache is None
    assert base_module._config_cache_loaded is False
