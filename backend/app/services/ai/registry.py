"""Provider 注册表（Task 2.1）。

替代 ``base.py`` 中的 if/elif 工厂链：provider 通过 ``@register_provider`` 装饰器
自注册到全局注册表，工厂通过 ``get_provider_class()`` 按 ``provider_type`` 查找。

注册时机：provider 模块被 import 时装饰器执行。``app.services.ai.providers`` 包的
``__init__.py`` 会预导入所有 provider 模块以触发注册；``base._ensure_providers_imported``
亦会在工厂首次调用前兜底触发，确保 ``get_provider_class`` 能找到已注册的类。

设计原则（八荣八耻）：
- 以复用现有为荣：沿用 Python 装饰器注册表模式，不引入插件框架
- 以谨慎重构为荣：注册表仅维护 ``provider_type -> class`` 映射，不耦合实例化逻辑
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.ai.base import BaseLLMProvider

# 全局注册表：provider_type -> provider 类
_PROVIDERS: dict[str, type["BaseLLMProvider"]] = {}


def register_provider(provider_type: str):
    """装饰器：注册 provider 类到注册表。

    用法::

        @register_provider("ollama")
        class OllamaProvider(BaseLLMProvider): ...
    """

    def decorator(cls: type["BaseLLMProvider"]) -> type["BaseLLMProvider"]:
        _PROVIDERS[provider_type] = cls
        return cls

    return decorator


def get_provider_class(
    provider_type: str,
) -> type["BaseLLMProvider"] | None:
    """按 ``provider_type`` 查找已注册的 provider 类，未注册返回 None。"""
    return _PROVIDERS.get(provider_type)


def list_provider_types() -> list[str]:
    """返回所有已注册的 provider_type 列表（顺序与注册顺序一致）。"""
    return list(_PROVIDERS.keys())
