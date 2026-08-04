"""WebSocket 端点：推送任务进度。

P0 阶段采用轮询 Celery AsyncResult 的轻量实现（避免引入额外 pubsub 复杂度）。
Task 6 落地前端时再升级为 Redis pubsub 实时推送。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.celery_app import celery_app
from app.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


def _map_state(state: str) -> str:
    """将 Celery 原生状态映射为业务状态。

    P2-2 修复：补充 PROGRESS → "running"（与 tasks.py _map_celery_state 对齐）。
    """
    mapping = {
        "PENDING": "queued",
        "RECEIVED": "queued",
        "STARTED": "running",
        "PROGRESS": "running",
        "RETRY": "running",
        "SUCCESS": "succeeded",
        "FAILURE": "failed",
        "REVOKED": "canceled",
    }
    return mapping.get(state, "queued")


@router.websocket("/ws/tasks/{task_id}")
async def task_progress_ws(websocket: WebSocket, task_id: str) -> None:
    """订阅指定任务的进度更新，每秒推送一次状态。"""
    await websocket.accept()
    log.info("ws.connected", task_id=task_id)
    try:
        while True:
            result = celery_app.AsyncResult(task_id)
            state = _map_state(result.state)
            # P2-2 修复：progress 从 task.info 读取真实值（PROGRESS 状态下
            # task.info 为 dict 含 progress 字段）；其他状态默认 0。
            progress = 0
            if state == "running" and isinstance(result.info, dict):
                progress = result.info.get("progress", 0)
            payload: dict = {"task_id": task_id, "status": state, "progress": progress}
            if state == "succeeded":
                payload["result"] = (
                    result.result if isinstance(result.result, dict)
                    else {"value": str(result.result)}
                )
            elif state == "failed":
                payload["error"] = str(result.result) if result.result else "unknown"
            await websocket.send_json(payload)
            if state in ("succeeded", "failed", "canceled"):
                break
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        log.info("ws.disconnected", task_id=task_id)
    except Exception as e:  # noqa: BLE001
        log.error("ws.error", task_id=task_id, error=str(e))
        try:
            await websocket.close()
        except Exception:
            pass
