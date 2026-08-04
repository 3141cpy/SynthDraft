"""AI Provider 抽象基类与 schema（SubTask 3.1 + Task 2.2 + split-llm-vlm-config）。

设计原则：
- 统一 ChatMessage / ChatResponse schema，屏蔽不同厂商差异
- BaseLLMProvider 定义最小可用接口：is_available / is_vlm_available / chat / chat_with_image
- ``get_llm_provider()`` 工厂从数据库读取 ``role="llm" AND is_active=True`` 的配置，
  经 registry 查找类并实例化（Task 2.2：替代旧的 settings.LLM_PROVIDER if/elif 链）
- ``get_vlm_provider()`` 工厂从数据库读取 ``role="vlm" AND is_active=True`` 的配置，
  独立缓存（split-llm-vlm-config）。VLM provider 实例化时将 ``config.vlm_model``
  作为 ``config.model`` 注入，使 provider 的 ``chat_with_image()`` 使用正确的视觉模型
- 配置变更时通过 ``reset_llm_provider_cache()`` / ``reset_vlm_provider_cache()`` 失效
  对应 role 的单例缓存，实现运行时热切换
- 所有 Provider 必须实现降级路径：API Key 未配置或调用失败时返回空 ChatResponse，不抛异常

sync/async 取舍（Task 2.2 决策）：
现有调用点约半数为 sync 函数（code_generator / vlm_ocr / llm_judge /
conflict_detector 的 is_*_available 包装器），改 async 会引发 ``await`` 语法
错误并迫使这些 sync 包装器全部改 async——属 Task 4 范畴。故保留 sync 接口：
- ``get_llm_provider()`` / ``get_vlm_provider()``（sync）：优先返回缓存实例；缓存未
  命中时尝试同步读 DB（无运行中事件循环时用 ``asyncio.run``），读不到则回退
  legacy ``settings`` 路由（兼容纯 .env 部署与既有测试）。
- ``get_llm_provider_async()`` / ``get_vlm_provider_async()``（async）：DB 直读的
  正规路径，供 Task 4 迁移后的 async 调用方使用。
- ``refresh_active_config_cache()``（async）：刷新两个 role 的同步缓存，供应用启动
  与 ``config_store.activate_config`` 在激活后调用，使后续 sync 调用立即生效。
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

    split-llm-vlm-config：VLM provider 实例化时由 ``_instantiate_from_config``
    自动把 ``config.vlm_model`` 注入 ``config.model``（构造一个临时 view），
    使 provider 的 ``is_available`` / ``chat`` / ``chat_with_image`` 都基于
    ``vlm_model`` 工作，无需修改各 provider 实现。
    """

    @abstractmethod
    def is_available(self) -> bool:
        """文本模型是否可用（实测发起 ping 消息验证）。

        对于 VLM role 的 provider，``model`` 字段已被替换为 ``vlm_model``，
        ``is_available`` 实际探测的是视觉模型可用性。
        """
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


from app.logging import get_logger

log = get_logger(__name__)

# ===== 单例缓存（LLM 与 VLM 独立）=====
# _llm_provider_instance / _vlm_provider_instance: 已实例化的 provider（单例）
# _active_llm_config_cache / _active_vlm_config_cache: 最近一次从 DB 读取的激活配置
# _llm_config_cache_loaded / _vlm_config_cache_loaded: 是否已尝试加载过配置
_llm_provider_instance: BaseLLMProvider | None = None
_vlm_provider_instance: BaseLLMProvider | None = None
_active_llm_config_cache: Any = None
_active_vlm_config_cache: Any = None
_llm_config_cache_loaded: bool = False
_vlm_config_cache_loaded: bool = False


def _ensure_providers_imported() -> None:
    """确保 provider 模块已加载，触发 ``@register_provider`` 注册。

    导入 ``app.services.ai.providers`` 包会执行其 ``__init__.py``，预导入所有
    provider 模块。重复 import 是无副作用的幂等操作（Python 模块缓存）。
    """
    import app.services.ai.providers  # noqa: F401


async def _fetch_active_config_from_db(role: Literal["llm", "vlm"]) -> Any:
    """从数据库读取指定 role 的激活 provider 配置（async）。

    返回 ``AIProviderConfig`` ORM 实例或 None。DB 异常向上抛出由调用方降级。
    """
    from app.database import async_session_factory
    from app.services.ai.config_store import get_active_config

    async with async_session_factory() as db:
        return await get_active_config(db, role=role)


async def refresh_active_config_cache() -> None:
    """刷新两个 role 的激活配置同步缓存（async）。

    供应用启动与 ``config_store.activate_config`` 在激活后调用，使后续 sync
    ``get_llm_provider()`` / ``get_vlm_provider()`` 能立即读到新配置。DB 不可达
    时清空缓存并记录 warning，不抛异常（降级到 legacy 路径）。
    """
    global _active_llm_config_cache, _active_vlm_config_cache
    global _llm_config_cache_loaded, _vlm_config_cache_loaded
    try:
        _active_llm_config_cache = await _fetch_active_config_from_db("llm")
    except Exception as e:  # noqa: BLE001
        # 刷新失败时保留已有缓存（如 worker 启动预热的有效配置），避免 None 覆盖
        # 导致 get_llm_provider() 误回退 legacy fallback（Celery threads 池中
        # asyncio.run 与 asyncpg 连接池事件循环不匹配会触发此路径）
        log.warning("ai.provider.refresh_llm_config_failed", error=str(e))
    _llm_config_cache_loaded = True
    try:
        _active_vlm_config_cache = await _fetch_active_config_from_db("vlm")
    except Exception as e:  # noqa: BLE001
        log.warning("ai.provider.refresh_vlm_config_failed", error=str(e))
    _vlm_config_cache_loaded = True


def refresh_active_config_cache_sync() -> None:
    """同步刷新两个 role 的激活配置缓存（使用 psycopg2 直连）。

    供 Celery ``before_start`` 钩子在 ``--pool=threads`` 下调用，避免
    ``asyncio.run`` 与 asyncpg 事件循环冲突。DB 不可达时记 warning，
    保留已有缓存，不抛异常。
    """
    global _active_llm_config_cache, _active_vlm_config_cache
    global _llm_config_cache_loaded, _vlm_config_cache_loaded

    from urllib.parse import urlparse, unquote

    import psycopg2

    from app.config import settings

    # 从 asyncpg URL 派生 psycopg2 连接参数
    parsed = urlparse(settings.DATABASE_URL.replace("+asyncpg", ""))
    conn_params = {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": unquote(parsed.username) if parsed.username else "",
        "password": unquote(parsed.password) if parsed.password else "",
        "dbname": parsed.path.lstrip("/") if parsed.path else "",
    }

    from app.models.ai_provider_config import AIProviderConfig

    try:
        with psycopg2.connect(**conn_params) as conn:
            for role, cache_attr, loaded_attr in [
                ("llm", "_active_llm_config_cache", "_llm_config_cache_loaded"),
                ("vlm", "_active_vlm_config_cache", "_vlm_config_cache_loaded"),
            ]:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name, provider_type, base_url, api_key_encrypted, "
                        "model, vlm_model, role, is_active, created_at, updated_at "
                        "FROM ai_provider_configs WHERE is_active = true AND role = %s",
                        (role,),
                    )
                    row = cur.fetchone()
                    if row:
                        config = AIProviderConfig(
                            id=row[0],
                            name=row[1],
                            provider_type=row[2],
                            base_url=row[3],
                            api_key_encrypted=row[4],
                            model=row[5],
                            vlm_model=row[6],
                            role=row[7],
                            is_active=row[8],
                            created_at=row[9],
                            updated_at=row[10],
                        )
                    else:
                        config = None
                    # 更新缓存
                    if role == "llm":
                        _active_llm_config_cache = config
                        _llm_config_cache_loaded = True
                    else:
                        _active_vlm_config_cache = config
                        _vlm_config_cache_loaded = True
        log.info(
            "ai.provider.sync_cache_refreshed",
            llm_config=_active_llm_config_cache.name if _active_llm_config_cache else None,
            vlm_config=_active_vlm_config_cache.name if _active_vlm_config_cache else None,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("ai.provider.sync_refresh_failed", error=str(e))


def _load_active_config_sync(role: Literal["llm", "vlm"]) -> Any:
    """同步获取指定 role 的激活配置：优先用已加载缓存，否则尝试同步读 DB。

    - 已加载缓存：直接返回（含 None，表示 DB 中无该 role 的激活配置）。
    - 未加载且无运行中事件循环：用 ``asyncio.run`` 同步读 DB 并缓存。
    - 未加载但有运行中事件循环（async 上下文）：无法阻塞读 DB，返回 None
      并由调用方走 legacy fallback（此时应通过 ``refresh_active_config_cache``
      在启动/激活时预填缓存以避免频繁 fallback）。
    """
    global _active_llm_config_cache, _active_vlm_config_cache
    global _llm_config_cache_loaded, _vlm_config_cache_loaded
    if role == "llm":
        if _llm_config_cache_loaded:
            return _active_llm_config_cache
    else:
        if _vlm_config_cache_loaded:
            return _active_vlm_config_cache

    import asyncio

    try:
        asyncio.get_running_loop()
        # 存在运行中的事件循环，sync 路径不能阻塞读 DB
        return None
    except RuntimeError:
        # 无运行中事件循环，安全同步执行 async 读
        pass

    try:
        cfg = asyncio.run(_fetch_active_config_from_db(role))
        # DB 读取成功（包括明确返回 None=无激活配置），缓存并标记 loaded
        if role == "llm":
            _active_llm_config_cache = cfg
            _llm_config_cache_loaded = True
        else:
            _active_vlm_config_cache = cfg
            _vlm_config_cache_loaded = True
        return cfg
    except Exception as e:  # noqa: BLE001
        log.warning("ai.provider.load_config_sync_failed", role=role, error=str(e))
        # DB 读取异常，不缓存，不标记 loaded，下次重试
        return None


class _VLMConfigView:
    """VLM 配置视图：将 ``config.vlm_model`` 注入 ``config.model`` 字段。

    provider 类（OllamaProvider / OpenAICompatibleProvider / AnthropicProvider）
    在构造时通过 ``getattr(config, "model", ...)`` / ``getattr(config, "vlm_model", ...)``
    读取字段。对于 role="vlm" 的配置，``model`` 字段为空、``vlm_model`` 字段为视觉
    模型名。但 provider 实例化后会用 ``self._model`` 调用 ``chat()``、用 ``self._vlm_model``
    调用 ``chat_with_image()``——这会导致 VLM provider 调 ``chat()`` 时使用空 model。

    本视图将 ``vlm_model`` 同时暴露为 ``model`` 与 ``vlm_model``，使 provider 的
    ``self._model`` 与 ``self._vlm_model`` 都指向视觉模型名，从而：
    - ``is_available()`` 探测视觉模型可用性
    - ``chat_with_image()`` 用视觉模型名调用 API

    复用现有 provider 实现，无需修改任一 provider 类。
    """

    def __init__(self, config: Any) -> None:
        # 把所有原字段复制过来
        self.id = getattr(config, "id", None)
        self.name = getattr(config, "name", "")
        self.provider_type = getattr(config, "provider_type", "")
        self.base_url = getattr(config, "base_url", "")
        self.api_key_encrypted = getattr(config, "api_key_encrypted", "")
        self.role = getattr(config, "role", "vlm")
        self.is_active = getattr(config, "is_active", True)
        self.created_at = getattr(config, "created_at", None)
        self.updated_at = getattr(config, "updated_at", None)
        # 关键：把 vlm_model 注入 model 字段
        vlm = getattr(config, "vlm_model", "") or ""
        self.vlm_model = vlm
        self.model = vlm  # 使 provider 的 self._model 指向视觉模型


def _instantiate_from_config(config: Any, role: Literal["llm", "vlm"]) -> BaseLLMProvider:
    """根据 ``AIProviderConfig`` 实例化 provider（经 registry 查找类）。

    对于 ``role="vlm"`` 的配置，使用 ``_VLMConfigView`` 包装，使 provider 的
    ``self._model`` 与 ``self._vlm_model`` 都指向视觉模型名，无需修改任一 provider。
    """
    _ensure_providers_imported()
    from app.services.ai.registry import get_provider_class

    effective_config: Any = config
    if role == "vlm":
        effective_config = _VLMConfigView(config)

    cls = get_provider_class(config.provider_type)
    if cls is None:
        raise ValueError(f"不支持的 provider_type: {config.provider_type!r}")
    return cls(effective_config)


def _build_legacy_config(provider_name: str, ptype: str) -> Any:
    """从 ``settings`` 旧字段构造临时 ``AIProviderConfig``（不持久化）。

    供 legacy fallback 路径使用：纯 .env 部署（DB 无配置）或测试环境下，按
    ``LLM_PROVIDER`` 旧值构造等价配置，保持向后兼容。vllm 已合并到
    openai_compatible，VLLM_ENABLED=False 时调用方应已回退到 ollama。
    """
    from app.config import settings
    from app.models.ai_provider_config import AIProviderConfig
    from app.security import encrypt_value

    if ptype == "ollama":
        return AIProviderConfig(
            name="legacy-ollama",
            provider_type="ollama",
            base_url=settings.OLLAMA_HOST_URL,
            api_key_encrypted="",
            model=settings.LLM_MODEL,
            vlm_model="",
            role="llm",
        )
    if ptype == "openai_compatible":
        if provider_name == "vllm":
            return AIProviderConfig(
                name="legacy-vllm",
                provider_type="openai_compatible",
                base_url=settings.VLLM_BASE_URL,
                api_key_encrypted=encrypt_value(settings.OPENAI_API_KEY),
                model=settings.VLLM_MODEL,
                vlm_model=getattr(settings, "VLLM_VLM_MODEL", ""),
                role="llm",
            )
        return AIProviderConfig(
            name="legacy-openai",
            provider_type="openai_compatible",
            base_url=settings.OPENAI_BASE_URL,
            api_key_encrypted=encrypt_value(settings.OPENAI_API_KEY),
            model=settings.OPENAI_MODEL,
            vlm_model=settings.OPENAI_VLM_MODEL,
            role="llm",
        )
    if ptype == "anthropic":
        return AIProviderConfig(
            name="legacy-anthropic",
            provider_type="anthropic",
            base_url=settings.ANTHROPIC_BASE_URL,
            api_key_encrypted=encrypt_value(settings.ANTHROPIC_API_KEY),
            model=settings.ANTHROPIC_MODEL,
            vlm_model=settings.ANTHROPIC_VLM_MODEL,
            role="llm",
        )
    raise ValueError(f"无法为 provider_name={provider_name!r} 构造 legacy 配置")


def _build_legacy_vlm_config() -> Any | None:
    """构造 VLM 的 legacy fallback 配置。

    若旧 .env 中 ``OPENAI_VLM_MODEL`` / ``ANTHROPIC_VLM_MODEL`` 非空，则构造
    等价 VLM 配置（role="vlm"）；否则返回 None（无 VLM 降级路径）。

    Ollama 旧版无显式 vlm_model 字段，返回 None（由调用方自行判断是否走 Ollama
    自动探测——但本项目策略是 VLM 必须显式配置，无配置则视为不可用）。
    """
    from app.config import settings
    from app.models.ai_provider_config import AIProviderConfig
    from app.security import encrypt_value

    provider = (settings.LLM_PROVIDER or "").lower().strip()
    if provider == "openai" and settings.OPENAI_VLM_MODEL:
        return AIProviderConfig(
            name="legacy-openai-vlm",
            provider_type="openai_compatible",
            base_url=settings.OPENAI_BASE_URL,
            api_key_encrypted=encrypt_value(settings.OPENAI_API_KEY),
            model="",
            vlm_model=settings.OPENAI_VLM_MODEL,
            role="vlm",
        )
    if provider == "anthropic" and settings.ANTHROPIC_VLM_MODEL:
        return AIProviderConfig(
            name="legacy-anthropic-vlm",
            provider_type="anthropic",
            base_url=settings.ANTHROPIC_BASE_URL,
            api_key_encrypted=encrypt_value(settings.ANTHROPIC_API_KEY),
            model="",
            vlm_model=settings.ANTHROPIC_VLM_MODEL,
            role="vlm",
        )
    if provider == "vllm" and getattr(settings, "VLLM_VLM_MODEL", ""):
        return AIProviderConfig(
            name="legacy-vllm-vlm",
            provider_type="openai_compatible",
            base_url=settings.VLLM_BASE_URL,
            api_key_encrypted=encrypt_value(settings.OPENAI_API_KEY),
            model="",
            vlm_model=getattr(settings, "VLLM_VLM_MODEL", ""),
            role="vlm",
        )
    return None


def _instantiate_legacy() -> BaseLLMProvider:
    """legacy fallback：根据 ``settings.LLM_PROVIDER`` 路由（兼容旧 .env / 测试）。

    vllm 已合并到 openai_compatible；保留旧降级：LLM_PROVIDER=vllm 但
    VLLM_ENABLED=False 时回退 ollama（避免调用未启动的 vLLM 端点）。
    """
    _ensure_providers_imported()
    from app.config import settings
    from app.services.ai.registry import get_provider_class

    provider_name = (settings.LLM_PROVIDER or "").lower().strip()
    if provider_name == "vllm" and not settings.VLLM_ENABLED:
        log.warning("ai.provider.vllm_fallback_to_ollama", reason="VLLM_ENABLED_false")
        provider_name = "ollama"

    type_map = {
        "ollama": "ollama",
        "openai": "openai_compatible",
        "anthropic": "anthropic",
        "vllm": "openai_compatible",
    }
    ptype = type_map.get(provider_name)
    if ptype is None:
        raise ValueError(f"不支持的 LLM_PROVIDER: {provider_name!r}")
    cls = get_provider_class(ptype)
    if cls is None:
        raise ValueError(f"provider_type {ptype!r} 未注册")
    config = _build_legacy_config(provider_name, ptype)
    return cls(config)


def _instantiate_legacy_vlm() -> BaseLLMProvider | None:
    """VLM legacy fallback：根据 ``settings.LLM_PROVIDER`` 构造 VLM provider。

    若旧 .env 中无 vlm_model，返回 None（VLM 不可用）。
    """
    config = _build_legacy_vlm_config()
    if config is None:
        return None
    _ensure_providers_imported()
    from app.services.ai.registry import get_provider_class

    cls = get_provider_class(config.provider_type)
    if cls is None:
        raise ValueError(f"provider_type {config.provider_type!r} 未注册")
    # VLM legacy 配置同样需要 _VLMConfigView 包装
    view = _VLMConfigView(config)
    return cls(view)


def get_llm_provider() -> BaseLLMProvider:
    """LLM 单例工厂（sync）：返回当前激活的文本模型 Provider 实例。

    解析顺序：
    1. 已缓存实例 → 直接返回。
    2. 同步读 DB ``role="llm" AND is_active=True`` 配置 → 经 registry 实例化并缓存。
    3. DB 无配置或不可达 → legacy fallback（按 ``settings.LLM_PROVIDER`` 路由）。

    配置变更时由 ``config_store.activate_config`` 调用 ``reset_llm_provider_cache``
    失效缓存，下次调用即重新解析。路由失败抛 ValueError（配置错误属致命问题）。
    """
    global _llm_provider_instance
    if _llm_provider_instance is not None:
        return _llm_provider_instance

    config = _load_active_config_sync("llm")
    if config is not None:
        _llm_provider_instance = _instantiate_from_config(config, "llm")
        return _llm_provider_instance

    # DB 无激活配置或不可达 → legacy fallback
    _llm_provider_instance = _instantiate_legacy()
    return _llm_provider_instance


async def get_llm_provider_async() -> BaseLLMProvider:
    """LLM 单例工厂（async）：DB 直读正规路径，供 async 调用方使用。

    与 sync ``get_llm_provider`` 共享同一 ``_llm_provider_instance`` 缓存。
    缓存未命中时直接 async 读 DB；DB 无配置则回退 legacy 路径。读取成功后
    顺带刷新同步缓存，使后续 sync 调用无需再访问 DB。
    """
    global _llm_provider_instance, _active_llm_config_cache, _llm_config_cache_loaded
    if _llm_provider_instance is not None:
        return _llm_provider_instance

    try:
        config = await _fetch_active_config_from_db("llm")
    except Exception as e:  # noqa: BLE001
        log.warning("ai.provider.async_load_llm_failed", error=str(e))
        config = None

    if config is not None:
        _active_llm_config_cache = config
        _llm_config_cache_loaded = True
        _llm_provider_instance = _instantiate_from_config(config, "llm")
        return _llm_provider_instance

    # legacy fallback（同步实现，async 调用方在此处不会阻塞事件循环，因 fallback 不访问 DB）
    _llm_provider_instance = _instantiate_legacy()
    return _llm_provider_instance


def get_vlm_provider() -> BaseLLMProvider | None:
    """VLM 单例工厂（sync）：返回当前激活的视觉模型 Provider 实例。

    split-llm-vlm-config：与 LLM 工厂完全独立，缓存分离。

    解析顺序：
    1. 已缓存实例 → 直接返回。
    2. 同步读 DB ``role="vlm" AND is_active=True`` 配置 → 经 _VLMConfigView 包装
       后实例化并缓存（将 ``vlm_model`` 注入 ``model`` 字段）。
    3. DB 无配置或不可达 → legacy fallback（按 ``settings`` 中 vlm_model 字段构造）。
       若 legacy 也无 vlm_model，返回 None（VLM 不可用）。

    返回 None 表示 VLM 未配置；调用方应通过 ``is_vlm_available()`` 二次确认。
    """
    global _vlm_provider_instance
    if _vlm_provider_instance is not None:
        return _vlm_provider_instance

    config = _load_active_config_sync("vlm")
    if config is not None:
        _vlm_provider_instance = _instantiate_from_config(config, "vlm")
        return _vlm_provider_instance

    # DB 无激活配置或不可达 → legacy fallback
    _vlm_provider_instance = _instantiate_legacy_vlm()
    return _vlm_provider_instance


async def get_vlm_provider_async() -> BaseLLMProvider | None:
    """VLM 单例工厂（async）：DB 直读正规路径。

    与 sync ``get_vlm_provider`` 共享同一 ``_vlm_provider_instance`` 缓存。
    """
    global _vlm_provider_instance, _active_vlm_config_cache, _vlm_config_cache_loaded
    if _vlm_provider_instance is not None:
        return _vlm_provider_instance

    try:
        config = await _fetch_active_config_from_db("vlm")
    except Exception as e:  # noqa: BLE001
        log.warning("ai.provider.async_load_vlm_failed", error=str(e))
        config = None

    if config is not None:
        _active_vlm_config_cache = config
        _vlm_config_cache_loaded = True
        _vlm_provider_instance = _instantiate_from_config(config, "vlm")
        return _vlm_provider_instance

    _vlm_provider_instance = _instantiate_legacy_vlm()
    return _vlm_provider_instance


def reset_llm_provider_cache() -> None:
    """重置 LLM 单例缓存与配置缓存（测试用 + LLM 激活切换时由 config_store 调用）。

    清空 ``_llm_provider_instance`` / ``_active_llm_config_cache`` /
    ``_llm_config_cache_loaded``，使下次 ``get_llm_provider`` 重新解析。
    """
    global _llm_provider_instance, _active_llm_config_cache, _llm_config_cache_loaded
    _llm_provider_instance = None
    _active_llm_config_cache = None
    _llm_config_cache_loaded = False


def reset_vlm_provider_cache() -> None:
    """重置 VLM 单例缓存与配置缓存（split-llm-vlm-config）。

    清空 ``_vlm_provider_instance`` / ``_active_vlm_config_cache`` /
    ``_vlm_config_cache_loaded``，使下次 ``get_vlm_provider`` 重新解析。
    """
    global _vlm_provider_instance, _active_vlm_config_cache, _vlm_config_cache_loaded
    _vlm_provider_instance = None
    _active_vlm_config_cache = None
    _vlm_config_cache_loaded = False


# ===== 向后兼容别名 =====
# 旧调用方（code_generator / conflict_detector 等）仍在使用 reset_provider_cache，
# 保持别名指向 reset_llm_provider_cache（旧调用方均为 LLM 上下文）。
def reset_provider_cache() -> None:
    """[已弃用] 重置 LLM provider 缓存的别名。

    split-llm-vlm-config 后请改用 ``reset_llm_provider_cache`` /
    ``reset_vlm_provider_cache`` 精确控制。本别名仅重置 LLM 缓存以保持
    向后兼容（旧测试与 config_store.legacy 路径仍可能调用）。
    """
    reset_llm_provider_cache()


def get_active_provider_type(role: Literal["llm", "vlm"] = "llm") -> str:
    """返回指定 role 当前激活配置的 provider_type（sync，从缓存读取）。

    供 healthz 等需要展示 provider 名称的同步场景使用。
    - 缓存已加载：直接返回 ``config.provider_type``（缓存为 None 表示 DB 无激活配置）。
    - 缓存未加载：尝试同步加载（无运行中事件循环时）；async 上下文下无法阻塞读 DB。
    - DB 无配置或不可达：回退到 ``settings.LLM_PROVIDER``（legacy 兼容）。

    注意：应用启动时 ``main.py`` lifespan 已调用 ``refresh_active_config_cache``
    预填缓存，确保 async 上下文下也能读到正确值。
    """
    config = _load_active_config_sync(role)
    if config is not None:
        return config.provider_type
    from app.config import settings

    return settings.LLM_PROVIDER
