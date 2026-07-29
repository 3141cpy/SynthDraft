"""v1 路由聚合：将各端点子路由挂载到 /api/v1 前缀下。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    collaboration,
    generations,
    health,
    kb,
    llm,
    observability,
    reviews,
    sketch,
    tasks,
    uploads,
    ws,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(
    generations.router, prefix="/generations", tags=["generations"]
)
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(kb.router, prefix="/kb", tags=["knowledge-base"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(
    collaboration.router, prefix="/collaboration", tags=["collaboration"]
)
api_router.include_router(sketch.router, prefix="/sketches", tags=["sketch"])
api_router.include_router(observability.router, tags=["observability"])
api_router.include_router(llm.router, tags=["llm"])
api_router.include_router(ws.router, tags=["websocket"])
