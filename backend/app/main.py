"""FastAPI 应用入口。

职责：
1. 创建 FastAPI 实例与 OpenAPI 元信息
2. 配置 CORS、日志、tracing
3. 挂载 v1 路由
4. 注册 lifespan 事件

启动：uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings
from app.database import async_session_factory, init_db
from app.logging import configure_logging, get_logger
from app.services.ai.base import refresh_active_config_cache
from app.services.ai.config_store import migrate_from_env
from app.tracing import configure_tracing, instrument_fastapi

# 初始化日志（最早执行，确保后续日志可用）
configure_logging()
log = get_logger(__name__)

# 初始化 tracing（OTEL_ENABLED=false 时为空操作）
configure_tracing()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动与关闭钩子。"""
    log.info(
        "app.starting",
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.APP_ENV,
    )
    # 建表 + .env 旧配置迁移（失败不阻断启动，避免数据库不可用时服务无法启动）
    try:
        await init_db()
        log.info("app.init_db.done")
    except Exception as e:  # noqa: BLE001
        log.warning("app.init_db.failed", error=str(e))
    try:
        async with async_session_factory() as session:
            migrated = await migrate_from_env(session)
            log.info("app.migrate_from_env.done", migrated=migrated)
    except Exception as e:  # noqa: BLE001
        log.warning("app.migrate_from_env.failed", error=str(e))
    # 预填激活配置同步缓存，使后续 sync get_llm_provider() / healthz 能立即读到
    # DB 激活配置，而非走 legacy settings fallback（避免重启后首次 healthz 显示旧 provider）。
    try:
        await refresh_active_config_cache()
        log.info("app.refresh_active_config_cache.done")
    except Exception as e:  # noqa: BLE001
        log.warning("app.refresh_active_config_cache.failed", error=str(e))
    yield
    log.info("app.stopping", name=settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "AI 驱动工程设计辅助系统后端 —— 提供智能审图、智能生成、"
        "工程规范知识库检索能力。当前为 P0 阶段骨架。"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenTelemetry 自动埋点（已配置时生效）
instrument_fastapi(app)

# 挂载 v1 路由
app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["root"])
async def root() -> dict:
    """根路径：返回服务基本信息与文档入口。"""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/api/v1/healthz",
        "ready": "/api/v1/readyz",
    }


log.info("app.initialized", routes_count=len(app.routes))
