"""AI Provider 配置管理端点（Task 3 + split-llm-vlm-config）。

端点（挂载于 /api/v1/ai/config 前缀下）：
- GET    ""                     — 列出所有 provider 配置（api_key 脱敏，支持 role 过滤）
- POST   ""                     — 新增 provider 配置（api_key 加密存储）
- PUT    "/{config_id}"         — 更新指定配置
- DELETE "/{config_id}"         — 删除指定配置
- POST   "/{config_id}/activate"— 激活指定配置（运行时热切换，role 内互斥）
- POST   "/{config_id}/test"    — 测试连接（按 role 探测对应模型字段）

split-llm-vlm-config：
- GET ``?role=llm`` / ``?role=vlm`` 支持按角色过滤配置列表
- 响应体新增 ``role`` 字段（``"llm"`` / ``"vlm"``），便于前端分 Tab 展示
- activate / test 内部已按 role 互斥与探测，端点无需改动

设计原则：
- 复用 ``config_store`` 服务层（CRUD + activate + test），端点仅做 HTTP 适配
- api_key 脱敏：GET 始终返回 ``"***"`` 或 ``""``；POST/PUT 接受明文，由
  ``config_store`` 经 Fernet 加密后存储
- 遵循现有端点模式（``DbDep`` / ``CurrentUserDep`` / ``HTTPException`` / structlog）
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDep, DbDep
from app.logging import get_logger
from app.models.ai_provider_config import AIProviderConfig
from app.schemas.ai_config import (
    AIConfigTestResult,
    AIProviderConfigCreate,
    AIProviderConfigResponse,
    AIProviderConfigUpdate,
)
from app.services.ai import config_store

router = APIRouter()
log = get_logger(__name__)


def _to_response(config: AIProviderConfig) -> AIProviderConfigResponse:
    """ORM → Response 转换，api_key 脱敏。

    有加密密文返回 ``"***"``，无密文（本地模型）返回空串。
    """
    return AIProviderConfigResponse(
        id=config.id,
        name=config.name,
        provider_type=config.provider_type,  # type: ignore[arg-type]
        base_url=config.base_url,
        api_key="***" if config.api_key_encrypted else "",
        model=config.model,
        vlm_model=config.vlm_model,
        role=config.role,  # type: ignore[arg-type]
        is_active=config.is_active,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.get(
    "",
    response_model=list[AIProviderConfigResponse],
    summary="列出所有 AI provider 配置",
    description=(
        "返回所有 provider 配置，按 id 升序。"
        "api_key 字段脱敏：有 key 返回 '***'，无 key 返回空串。"
        "可通过 ``role`` 查询参数过滤：``?role=llm`` 仅返回文本模型配置，"
        "``?role=vlm`` 仅返回视觉模型配置。"
    ),
)
async def list_configs(
    role: Literal["llm", "vlm"] | None = Query(
        default=None,
        description="按角色过滤：llm=文本模型 / vlm=视觉模型；不传则返回全部",
    ),
    db: AsyncSession = DbDep,
    user_id: str = CurrentUserDep,
) -> list[AIProviderConfigResponse]:
    configs = await config_store.list_configs(db, role=role)
    log.info("ai.config.list", user=user_id, count=len(configs), role=role)
    return [_to_response(c) for c in configs]


@router.post(
    "",
    response_model=AIProviderConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增 AI provider 配置",
    description=(
        "新增 provider 配置；首条记录自动激活。"
        "api_key 由服务层经 Fernet 加密后存储。"
    ),
)
async def create_config(
    payload: AIProviderConfigCreate,
    db: AsyncSession = DbDep,
    user_id: str = CurrentUserDep,
) -> AIProviderConfigResponse:
    log.info(
        "ai.config.create.received",
        user=user_id,
        name=payload.name,
        provider_type=payload.provider_type,
    )
    config = await config_store.create_config(db, payload)
    return _to_response(config)


@router.put(
    "/{config_id}",
    response_model=AIProviderConfigResponse,
    summary="更新 AI provider 配置",
    description=(
        "更新指定配置；api_key=None 表示不修改密钥，"
        "显式传值（含空串）则加密覆盖。不存在返回 404。"
    ),
)
async def update_config(
    config_id: int,
    payload: AIProviderConfigUpdate,
    db: AsyncSession = DbDep,
    user_id: str = CurrentUserDep,
) -> AIProviderConfigResponse:
    log.info(
        "ai.config.update.received",
        user=user_id,
        config_id=config_id,
        fields=list(payload.model_dump(exclude_unset=True).keys()),
    )
    config = await config_store.update_config(db, config_id, payload)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AI 配置不存在: id={config_id}",
        )
    return _to_response(config)


@router.delete(
    "/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除 AI provider 配置",
    description="删除指定配置；不存在返回 404。",
)
async def delete_config(
    config_id: int,
    db: AsyncSession = DbDep,
    user_id: str = CurrentUserDep,
) -> None:
    log.info("ai.config.delete.received", user=user_id, config_id=config_id)
    ok = await config_store.delete_config(db, config_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AI 配置不存在: id={config_id}",
        )


@router.post(
    "/{config_id}/activate",
    response_model=AIProviderConfigResponse,
    summary="激活 AI provider 配置",
    description=(
        "激活指定配置（运行时热切换，无需重启）。"
        "内部已失效 provider 单例缓存并刷新激活配置缓存。不存在返回 404。"
    ),
)
async def activate_config(
    config_id: int,
    db: AsyncSession = DbDep,
    user_id: str = CurrentUserDep,
) -> AIProviderConfigResponse:
    log.info("ai.config.activate.received", user=user_id, config_id=config_id)
    config = await config_store.activate_config(db, config_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AI 配置不存在: id={config_id}",
        )
    return _to_response(config)


@router.post(
    "/{config_id}/test",
    response_model=AIConfigTestResult,
    summary="测试 AI provider 配置连接",
    description=(
        "探测指定配置的连通性（文本模型 + 视觉模型），返回可用性、"
        "视觉模型可用性与往返延迟。不存在返回 404。"
    ),
)
async def test_config(
    config_id: int,
    db: AsyncSession = DbDep,
    user_id: str = CurrentUserDep,
) -> AIConfigTestResult:
    log.info("ai.config.test.received", user=user_id, config_id=config_id)
    # config_store.test_config 对不存在的配置返回 available=False 的结果对象
    # 而非 None；此处先校验存在性以符合 RESTful 404 语义。
    existing = await config_store.get_config(db, config_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AI 配置不存在: id={config_id}",
        )
    return await config_store.test_config(db, config_id)
