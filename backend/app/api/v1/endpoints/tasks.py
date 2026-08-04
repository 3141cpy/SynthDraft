"""任务状态查询端点。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.celery.task_registry import task_exists
from app.celery_app import celery_app
from app.schemas.task import TaskStatusResponse

router = APIRouter()


def _map_celery_state(state: str) -> str:
    """将 Celery 原生状态映射为业务状态。

    P2-2 修复：补充 PROGRESS → "running"（原缺失导致执行中任务误报 "queued"）。
    SUCCESS 统一为 "succeeded"（与 ws.py / reviews.py 保持一致）。
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


@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
    summary="查询任务状态",
)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    if not task_exists(task_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务 ID 不存在: {task_id}",
        )
    result = celery_app.AsyncResult(task_id)
    state = _map_celery_state(result.state)
    output: dict | None = None
    error: str | None = None
    # P2-2 修复：progress 从 Celery task info 中读取真实值（PROGRESS 状态下
    # task.info 为 dict，含 progress 字段）；其他状态默认 0。
    progress = 0
    if state == "succeeded":
        output = result.result if isinstance(result.result, dict) else {"value": str(result.result)}
    elif state == "failed":
        error = str(result.result) if result.result else "unknown error"
    elif state == "running":
        if isinstance(result.info, dict):
            progress = result.info.get("progress", 0)
    return TaskStatusResponse(
        task_id=task_id,
        status=state,
        progress=progress,
        result=output,
        error=error,
    )


@router.post(
    "/{task_id}/cancel",
    summary="取消任务",
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_task(task_id: str) -> dict:
    if not task_exists(task_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务 ID 不存在: {task_id}",
        )
    celery_app.control.revoke(task_id, terminate=False)
    return {"task_id": task_id, "status": "canceled"}
