"""AI Provider 配置存取服务（Task 1.4 + split-llm-vlm-config）。

提供配置 CRUD、按 role 过滤、独立激活切换、连接测试、``.env`` 迁移能力。
所有函数均为 async，接受 ``AsyncSession``。API key 经 ``app.security`` 的
Fernet 加解密。

split-llm-vlm-config：
- ``list_configs(role=None)`` 支持按 role 过滤
- ``get_active_config(role)`` 返回指定 role 的激活配置
- ``create_config`` 按 role 自动激活同 role 首条（不影响另一 role）
- ``activate_config`` 在目标配置所属 role 范围内激活，不影响另一 role
- ``test_config`` 按 role 探测对应模型字段（llm 探测 model，vlm 探测 vlm_model）

设计说明（与 Task 2 的关系）：
当前 provider 类（``OllamaProvider`` 等）尚未适配从 ``AIProviderConfig`` 读取
配置（Task 2.3-2.6 才适配），其构造函数不接受 config。因此 ``test_config``
采用按 ``provider_type`` 的直接 HTTP 探测实现，自洽地测试"指定配置"的连通性，
不依赖 provider 类的适配进度。Task 2 完成后可重构为复用 provider 实例。
"""

from __future__ import annotations

import time
from typing import Any, Literal

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logging import get_logger
from app.models.ai_provider_config import AIProviderConfig
from app.schemas.ai_config import (
    AIConfigTestResult,
    AIProviderConfigCreate,
    AIProviderConfigUpdate,
)
from app.security import decrypt_value, encrypt_value

log = get_logger(__name__)

# Ollama 视觉模型关键字（与 ollama_provider.py 保持一致，复刻以保持本模块自洽）
_OLLAMA_VLM_KEYWORDS = (
    "minicpm-v",
    "llava",
    "qwen2.5-vl",
    "qwen2-vl",
    "llama3.2-vision",
    "moondream",
)

Role = Literal["llm", "vlm"]


# ===== CRUD =====


async def list_configs(
    db: AsyncSession, role: Role | None = None
) -> list[AIProviderConfig]:
    """列出 provider 配置，按 id 升序。

    ``role`` 不传时返回所有配置；传 ``"llm"`` / ``"vlm"`` 时仅返回对应 role。
    """
    stmt = select(AIProviderConfig)
    if role is not None:
        stmt = stmt.where(AIProviderConfig.role == role)
    stmt = stmt.order_by(AIProviderConfig.id.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_config(db: AsyncSession, config_id: int) -> AIProviderConfig | None:
    """按 id 获取单个配置。"""
    result = await db.execute(
        select(AIProviderConfig).where(AIProviderConfig.id == config_id)
    )
    return result.scalars().one_or_none()


async def get_active_config(
    db: AsyncSession, role: Role = "llm"
) -> AIProviderConfig | None:
    """获取指定 role 当前激活的配置（同一 role 内最多一条）。

    ``role="llm"`` 返回 LLM 激活配置；``role="vlm"`` 返回 VLM 激活配置。
    未传 role 时默认查 LLM（向后兼容旧调用方）。
    """
    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.role == role,
            AIProviderConfig.is_active.is_(True),
        )
    )
    return result.scalars().one_or_none()


async def create_config(db: AsyncSession, data: AIProviderConfigCreate) -> AIProviderConfig:
    """新增 provider 配置。

    新建记录默认 ``is_active=False``；若此前该 role 下无任何配置，则自动激活
    首条（不影响另一 role 的激活状态），避免空 role 时无可用 provider。
    """
    role: Role = data.role
    existing_in_role = await list_configs(db, role=role)
    config = AIProviderConfig(
        name=data.name,
        provider_type=data.provider_type,
        base_url=data.base_url,
        api_key_encrypted=encrypt_value(data.api_key),
        model=data.model,
        vlm_model=data.vlm_model,
        role=role,
        is_active=(len(existing_in_role) == 0),
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    log.info(
        "ai.config.created",
        config_id=config.id,
        name=config.name,
        provider_type=config.provider_type,
        role=config.role,
        auto_activated=config.is_active,
    )
    return config


async def update_config(
    db: AsyncSession, config_id: int, data: AIProviderConfigUpdate
) -> AIProviderConfig | None:
    """更新指定配置。``api_key=None`` 表示不修改密钥。

    ``role`` 字段一般不修改（创建后即固定）；如传入新 role，将触发 role 切换
    并清空另一 role 的字段（model/vlm_model 之一）。建议调用方不暴露 role 修改。
    """
    config = await get_config(db, config_id)
    if config is None:
        return None
    changes = data.model_dump(exclude_unset=True)
    # api_key 单独处理：None 表示不修改，显式传入（含空串）则加密覆盖
    if "api_key" in changes:
        new_key = changes.pop("api_key")
        if new_key is not None:
            config.api_key_encrypted = encrypt_value(new_key) if new_key else ""
    # role 切换时清空无关字段，避免脏数据
    new_role = changes.get("role")
    if new_role is not None and new_role != config.role:
        if new_role == "llm":
            config.vlm_model = ""
        elif new_role == "vlm":
            config.model = ""
        # 切换 role 后激活状态可能不一致：若新 role 下已有激活配置，则此配置降级为未激活
        if config.is_active:
            existing_active = await get_active_config(db, role=new_role)
            if existing_active is not None and existing_active.id != config.id:
                config.is_active = False
    for field, value in changes.items():
        if field == "role":
            continue  # 已在上面处理
        setattr(config, field, value)
    await db.commit()
    await db.refresh(config)
    log.info("ai.config.updated", config_id=config_id, fields=list(changes.keys()))
    if config.is_active:
        # 失效对应 role 的 provider 单例缓存（仅激活配置变更才需失效）
        try:
            from app.services.ai.base import (
                refresh_active_config_cache,
                reset_llm_provider_cache,
                reset_vlm_provider_cache,
            )

            if config.role == "llm":
                reset_llm_provider_cache()
            else:
                reset_vlm_provider_cache()
            await refresh_active_config_cache()
        except Exception as e:  # noqa: BLE001
            log.warning("ai.config.update.reset_cache_failed", error=str(e))
    return config


async def delete_config(db: AsyncSession, config_id: int) -> bool:
    """删除指定配置。返回是否实际删除了记录。"""
    config = await get_config(db, config_id)
    if config is None:
        return False
    was_active = config.is_active
    role = config.role
    await db.delete(config)
    await db.commit()
    log.info(
        "ai.config.deleted",
        config_id=config_id,
        was_active=was_active,
        role=role,
    )
    return True


async def activate_config(
    db: AsyncSession, config_id: int
) -> AIProviderConfig | None:
    """激活指定配置：在目标配置所属 role 范围内互斥激活，不影响另一 role。

    流程：
    1. 读取目标配置，获取其 ``role``。
    2. 将该 role 下所有 ``is_active=True`` 的记录置为 False。
    3. 将目标配置置为 ``is_active=True``。
    4. 失效对应 role 的 provider 单例缓存（LLM 走 ``reset_llm_provider_cache``，
       VLM 走 ``reset_vlm_provider_cache``），并预填同步缓存。

    另一 role 的激活状态完全不受影响。
    """
    config = await get_config(db, config_id)
    if config is None:
        return None
    role: Role = config.role  # type: ignore[assignment]
    # 仅取消同 role 内其他配置的激活
    await db.execute(
        update(AIProviderConfig)
        .where(
            AIProviderConfig.role == role,
            AIProviderConfig.is_active.is_(True),
        )
        .values(is_active=False)
    )
    config.is_active = True
    await db.commit()
    await db.refresh(config)
    log.info(
        "ai.config.activated",
        config_id=config_id,
        name=config.name,
        role=role,
    )

    # 失效对应 role 的 provider 单例缓存
    try:
        from app.services.ai.base import (
            refresh_active_config_cache,
            reset_llm_provider_cache,
            reset_vlm_provider_cache,
        )

        if role == "llm":
            reset_llm_provider_cache()
        else:
            reset_vlm_provider_cache()
        # 刷新同步配置缓存（两个 role 都刷新，避免遗漏）
        await refresh_active_config_cache()
    except Exception as e:  # noqa: BLE001
        log.warning("ai.config.activate.reset_cache_failed", error=str(e))
    return config


# ===== 连接测试 =====


def _model_matches(target: str, available: list[str]) -> bool:
    """宽松匹配模型名（兼容 ``:latest`` 后缀与前缀匹配，与 ollama_provider 一致）。"""
    if not target:
        return False
    variants = {target, f"{target}:latest"}
    return any(n in variants or n.startswith(target) for n in available)


async def test_config(
    db: AsyncSession, config_id: int
) -> AIConfigTestResult:
    """测试指定配置的连通性。

    按 ``provider_type`` 发起直接 HTTP 探测，返回 ``available`` / ``vlm_available``
    / ``latency_ms`` / ``error``。探测失败时 ``available=False`` 且填充 ``error``。

    split-llm-vlm-config：按 ``role`` 探测对应模型字段：
    - ``role="llm"``：探测 ``model`` 字段是否可用，``vlm_available`` 恒为 False
    - ``role="vlm"``：探测 ``vlm_model`` 字段是否可用，``available`` 与
      ``vlm_available`` 同值（VLM 配置中 ``model`` 留空不探测）
    """
    config = await get_config(db, config_id)
    if config is None:
        return AIConfigTestResult(
            available=False, vlm_available=False, latency_ms=0, error="配置不存在"
        )
    api_key = decrypt_value(config.api_key_encrypted)
    start = time.perf_counter()

    # 按 role 选择探测目标模型字段
    if config.role == "vlm":
        probe_model = config.vlm_model
    else:
        probe_model = config.model

    try:
        if config.provider_type == "ollama":
            res = await _probe_ollama(
                config.base_url,
                probe_model,
                config.vlm_model,
                role=config.role,  # type: ignore[arg-type]
            )
        elif config.provider_type == "openai_compatible":
            res = await _probe_openai_compatible(
                config.base_url,
                api_key,
                probe_model,
                config.vlm_model,
                role=config.role,  # type: ignore[arg-type]
            )
        elif config.provider_type == "anthropic":
            res = await _probe_anthropic(
                config.base_url,
                api_key,
                probe_model,
                config.vlm_model,
                role=config.role,  # type: ignore[arg-type]
            )
        else:
            return AIConfigTestResult(
                available=False,
                vlm_available=False,
                latency_ms=0,
                error=f"不支持的 provider_type: {config.provider_type!r}",
            )
    except Exception as e:  # noqa: BLE001
        latency = int((time.perf_counter() - start) * 1000)
        log.warning("ai.config.test.failed", config_id=config_id, error=str(e))
        return AIConfigTestResult(
            available=False, vlm_available=False, latency_ms=latency, error=str(e)
        )
    latency = int((time.perf_counter() - start) * 1000)
    log.info(
        "ai.config.test.done",
        config_id=config_id,
        role=config.role,
        available=res["available"],
        vlm_available=res["vlm_available"],
        latency_ms=latency,
    )
    return AIConfigTestResult(
        available=res["available"],
        vlm_available=res["vlm_available"],
        latency_ms=latency,
        error=res.get("error", ""),
    )


async def _probe_ollama(
    base_url: str,
    model: str,
    vlm_model: str,
    role: Role = "llm",
) -> dict[str, Any]:
    """Ollama 探测：GET /api/tags 获取已安装模型列表。

    - ``role="llm"``：检查 ``model`` 是否已拉取，``vlm_available`` 恒为 False
    - ``role="vlm"``：检查 ``vlm_model`` 是否已拉取，``available=vlm_available``
    """
    url = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{url}/api/tags")
        resp.raise_for_status()
        data = resp.json()
    models = [
        m.get("name", "") or m.get("model", "") for m in data.get("models", [])
    ]

    if role == "vlm":
        # VLM 配置：探测 vlm_model 字段
        target = vlm_model
        available = _model_matches(target, models)
        if not available:
            return {
                "available": False,
                "vlm_available": False,
                "error": f"视觉模型 {target!r} 未在 Ollama 中拉取，已安装: {models}",
            }
        return {"available": True, "vlm_available": True}

    # role == "llm"：探测 model 字段
    available = _model_matches(model, models)
    if not available:
        return {
            "available": False,
            "vlm_available": False,
            "error": f"模型 {model!r} 未在 Ollama 中拉取，已安装: {models}",
        }
    # LLM 配置不再探测 VLM（VLM 由独立的 vlm role 配置负责）
    return {"available": True, "vlm_available": False}


async def _probe_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    vlm_model: str,
    role: Role = "llm",
) -> dict[str, Any]:
    """OpenAI 兼容探测：GET {base_url}/models（带 Bearer 鉴权）。"""
    url = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{url}/models", headers=headers)
        resp.raise_for_status()
        data = resp.json()
    # 兼容 {"data":[{"id":...}]} 与 {"models":[{"id":...}]} 两种形态
    items = data.get("data") or data.get("models") or []
    ids = [str(it.get("id") or it.get("name") or "") for it in items]
    # 部分兼容端点不返回完整列表；列表为空时仅凭连通性判定 available

    if role == "vlm":
        target = vlm_model
        available = bool(target) and ((not ids) or _model_matches(target, ids))
        error = "" if available else f"视觉模型 {target!r} 不在可用列表: {ids}"
        return {"available": available, "vlm_available": available, "error": error}

    # role == "llm"
    available = (not ids) or _model_matches(model, ids)
    error = "" if available else f"模型 {model!r} 不在可用列表: {ids}"
    return {"available": available, "vlm_available": False, "error": error}


async def _probe_anthropic(
    base_url: str,
    api_key: str,
    model: str,
    vlm_model: str,
    role: Role = "llm",
) -> dict[str, Any]:
    """Anthropic 探测：POST /v1/messages 发送最小 ping 消息。"""
    if not api_key:
        return {
            "available": False,
            "vlm_available": False,
            "error": "Anthropic provider 缺少 api_key",
        }
    url = base_url.rstrip("/")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    # 按 role 选择 ping 用的模型名
    ping_model = vlm_model if role == "vlm" else model
    if not ping_model:
        return {
            "available": False,
            "vlm_available": False,
            "error": f"role={role} 时对应模型字段为空",
        }
    payload = {
        "model": ping_model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{url}/v1/messages", headers=headers, json=payload)
    # 200 表示模型可用；400/404 通常是模型名错误，401 鉴权失败
    if resp.status_code == 200:
        if role == "vlm":
            return {"available": True, "vlm_available": True}
        return {"available": True, "vlm_available": False}
    return {
        "available": False,
        "vlm_available": False,
        "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
    }


# ===== .env 迁移 =====


def _build_env_migration_configs() -> list[AIProviderConfigCreate]:
    """根据 settings 中的旧 LLM_PROVIDER 字段构造初始配置列表。

    split-llm-vlm-config：从旧 .env 同时迁出 LLM 与 VLM（若旧配置含 vlm_model）：
    - 始终迁出一条 ``role="llm"`` 配置（使用 ``LLM_MODEL`` / ``OPENAI_MODEL`` 等）
    - 若旧配置的 vlm_model 非空，额外迁出一条 ``role="vlm"`` 配置（使用 vlm_model）
    - 两条配置均 ``is_active=True``（迁移逻辑会按 role 独立激活首条）

    返回空列表表示旧 provider 类型无法识别。
    """
    provider = (settings.LLM_PROVIDER or "").lower().strip()
    configs: list[AIProviderConfigCreate] = []

    if provider == "ollama":
        configs.append(
            AIProviderConfigCreate(
                name="Ollama 文本模型（.env 迁移）",
                provider_type="ollama",
                base_url=settings.OLLAMA_HOST_URL,
                api_key="",
                model=settings.LLM_MODEL,
                vlm_model="",
                role="llm",
            )
        )
        # Ollama 旧版自动探测 VLM，无显式 vlm_model 字段，不迁出 vlm 配置
        return configs

    if provider == "openai":
        if settings.OPENAI_VLM_MODEL:
            configs.append(
                AIProviderConfigCreate(
                    name="OpenAI 视觉模型（.env 迁移）",
                    provider_type="openai_compatible",
                    base_url=settings.OPENAI_BASE_URL,
                    api_key=settings.OPENAI_API_KEY,
                    model="",
                    vlm_model=settings.OPENAI_VLM_MODEL,
                    role="vlm",
                )
            )
        configs.append(
            AIProviderConfigCreate(
                name="OpenAI 文本模型（.env 迁移）",
                provider_type="openai_compatible",
                base_url=settings.OPENAI_BASE_URL,
                api_key=settings.OPENAI_API_KEY,
                model=settings.OPENAI_MODEL,
                vlm_model="",
                role="llm",
            )
        )
        return configs

    if provider == "anthropic":
        if settings.ANTHROPIC_VLM_MODEL:
            configs.append(
                AIProviderConfigCreate(
                    name="Anthropic 视觉模型（.env 迁移）",
                    provider_type="anthropic",
                    base_url=settings.ANTHROPIC_BASE_URL,
                    api_key=settings.ANTHROPIC_API_KEY,
                    model="",
                    vlm_model=settings.ANTHROPIC_VLM_MODEL,
                    role="vlm",
                )
            )
        configs.append(
            AIProviderConfigCreate(
                name="Anthropic 文本模型（.env 迁移）",
                provider_type="anthropic",
                base_url=settings.ANTHROPIC_BASE_URL,
                api_key=settings.ANTHROPIC_API_KEY,
                model=settings.ANTHROPIC_MODEL,
                vlm_model="",
                role="llm",
            )
        )
        return configs

    if provider == "vllm":
        # vLLM 暴露 OpenAI 兼容 API，统一归为 openai_compatible
        vllm_vlm = getattr(settings, "VLLM_VLM_MODEL", "")
        if vllm_vlm:
            configs.append(
                AIProviderConfigCreate(
                    name="vLLM 视觉模型（.env 迁移）",
                    provider_type="openai_compatible",
                    base_url=settings.VLLM_BASE_URL,
                    api_key=settings.OPENAI_API_KEY,
                    model="",
                    vlm_model=vllm_vlm,
                    role="vlm",
                )
            )
        configs.append(
            AIProviderConfigCreate(
                name="vLLM 文本模型（.env 迁移）",
                provider_type="openai_compatible",
                base_url=settings.VLLM_BASE_URL,
                api_key=settings.OPENAI_API_KEY,
                model=settings.VLLM_MODEL,
                vlm_model="",
                role="llm",
            )
        )
        return configs

    return configs


async def migrate_from_env(db: AsyncSession) -> int:
    """首次启动迁移：数据库为空时将 ``.env`` 旧配置迁入为激活配置。

    split-llm-vlm-config：同时迁出 LLM 与 VLM 配置（若旧 .env 含 vlm_model），
    每个 role 内首条自动激活。

    Returns:
        迁移的记录数（0 表示数据库非空或无可迁移配置）。
    """
    existing = await list_configs(db)
    if existing:
        log.info("ai.config.migrate.skip", reason="db_not_empty", count=len(existing))
        return 0
    configs_data = _build_env_migration_configs()
    if not configs_data:
        log.warning(
            "ai.config.migrate.skip",
            reason="unknown_provider",
            llm_provider=settings.LLM_PROVIDER,
        )
        return 0

    migrated = 0
    # 按 role 分组：每个 role 内首条激活
    seen_roles: set[str] = set()
    for data in configs_data:
        is_first_in_role = data.role not in seen_roles
        seen_roles.add(data.role)
        config = AIProviderConfig(
            name=data.name,
            provider_type=data.provider_type,
            base_url=data.base_url,
            api_key_encrypted=encrypt_value(data.api_key),
            model=data.model,
            vlm_model=data.vlm_model,
            role=data.role,
            is_active=is_first_in_role,
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)
        migrated += 1
        log.info(
            "ai.config.migrated",
            config_id=config.id,
            name=config.name,
            provider_type=config.provider_type,
            role=config.role,
            source_provider=settings.LLM_PROVIDER,
        )
    return migrated
