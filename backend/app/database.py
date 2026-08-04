"""SQLAlchemy 异步引擎、会话工厂与 ORM Base。

P0 阶段建立连接与会话基础；Task 1 起落地 ORM 模型（``ai_provider_configs`` 表）。
遵循"以复用现有为荣"原则，使用 SQLAlchemy 2.0 标准异步 API。

建表策略：项目尚未配置 Alembic 迁移环境，沿用 ``Base.metadata.create_all``
在应用启动时自动建表（与现有 P0 模式一致）。后续若引入 Alembic，可替换为
迁移脚本驱动，``Base`` 仍作为所有模型的声明基类复用。
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

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


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类。

    各模型模块 import ``Base`` 后定义映射类，``Base.metadata`` 自动收集表定义。
    ``init_db()`` 调用 ``Base.metadata.create_all`` 一次性建表。
    """


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


async def init_db() -> None:
    """创建所有已注册的 ORM 表。

    项目尚未配置 Alembic 迁移环境，沿用 ``Base.metadata.create_all`` 在应用
    启动时自动建表（与现有 P0 模式一致）。仅在表不存在时创建，已存在的表
    不受影响。

    注意：必须先 import ``app.models`` 包以触发模型模块加载，使其映射类注册
    到 ``Base.metadata``。

    split-llm-vlm-config：``ai_provider_configs`` 表新增 ``role`` 字段。
    ``create_all`` 不会修改已存在的表结构，因此对已有库需要手动检测并 ALTER
    TABLE 补列。所有后端支持的方言（PostgreSQL / SQLite）均使用 ADD COLUMN。
    """
    # 懒导入模型包，触发模型模块加载并注册到 Base.metadata
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # split-llm-vlm-config: 自动给旧库补 role 列。
        # 失败时记录 warning 不阻断启动（例如某些方言不支持 introspection）。
        try:
            await _ensure_role_column(conn)
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning(
                "init_db.ensure_role_column_failed", error=str(e)
            )


async def _ensure_role_column(conn: AsyncConnection) -> None:
    """检测 ``ai_provider_configs`` 表是否已有 ``role`` 列，无则添加。

    兼容 PostgreSQL / SQLite：使用 ``inspect()`` 反射列信息。新增列时
    SQLite 需要 ``DEFAULT 'llm'`` 以填充已有行；PostgreSQL 同样支持。
    """
    from sqlalchemy import inspect, text

    def _has_role(sync_conn) -> bool:
        insp = inspect(sync_conn)
        if "ai_provider_configs" not in insp.get_table_names():
            return True  # 表尚未创建，create_all 会带 role 列一起建
        cols = {c["name"] for c in insp.get_columns("ai_provider_configs")}
        return "role" in cols

    already = await conn.run_sync(_has_role)
    if already:
        return
    # 旧库无 role 列：添加并默认 'llm'，确保现有配置归类为 LLM
    await conn.execute(
        text(
            "ALTER TABLE ai_provider_configs ADD COLUMN role VARCHAR(10) "
            "NOT NULL DEFAULT 'llm'"
        )
    )
