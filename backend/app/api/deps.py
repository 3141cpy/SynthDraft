"""FastAPI 依赖注入：settings、db session、logger 等。

遵循"以复用现有为荣"原则，使用 FastAPI 标准依赖模式。
"""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session
from app.logging import Logger, get_logger
from app.security import decode_access_token


def get_app_settings() -> Settings:
    """注入全局 Settings。"""
    return get_settings()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """注入异步数据库会话。"""
    async for session in get_session():
        yield session


def get_logger_dep():
    """注入结构化 logger。"""
    return get_logger("api")


def get_current_user_id(
    authorization: str | None = Header(default=None),
) -> str:
    """从 Authorization: Bearer <jwt> 解析当前用户 ID。

    未提供 token 时：
    - 开发环境（APP_ENV=development）返回 "anonymous"，便于调试；
    - 其他环境（含生产/staging/未显式配置）抛 401，强制鉴权（fail closed）。
    """
    if not authorization:
        s = get_settings()
        if s.is_development:
            return "anonymous"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required",
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )
    try:
        payload = decode_access_token(parts[1])
        return str(payload.get("sub", "anonymous"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        ) from e


SettingsDep = Depends(get_app_settings)
DbDep = Depends(get_db)
LoggerDep = Depends(get_logger_dep)
CurrentUserDep = Depends(get_current_user_id)
