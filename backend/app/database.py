"""SQLAlchemy 异步引擎与会话工厂。

P0 阶段仅建立连接与会话基础；ORM 模型在 Task 2+ 落地。
遵循"以复用现有为荣"原则，使用 SQLAlchemy 2.0 标准异步 API。
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# 模块级引擎与会话工厂（懒初始化，便于测试覆盖）
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_DEBUG and not settings.is_production,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：提供一个异步会话并在请求结束时关闭。"""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_db_connected() -> bool:
    """探活数据库连接。供 /readyz 使用。"""
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
