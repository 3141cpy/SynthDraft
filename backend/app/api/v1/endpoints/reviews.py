"""审图端点（Task 4 真实实现）。

端点：
- POST /api/v1/reviews：提交审图任务 → 入 Celery reviews 队列 → 返回 task_id
- GET /api/v1/reviews/{task_id}/result：查询审图结果（从 Celery result backend 读）
- GET /api/v1/reviews/{task_id}/report：下载 HTML 报告（FileResponse）
"""

from __future__ import annotations

from pathlib import Path

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse

from app.api.deps import CurrentUserDep, LoggerDep
from app.celery.task_registry import register_task, task_exists
from app.celery.tasks.reviews import run_review
from app.celery_app import celery_app
from app.logging import Logger
from app.schemas.review import ReviewCreateRequest, ReviewTaskAccepted

router = APIRouter()


@router.post(
    "",
    response_model=ReviewTaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交审图任务",
)
async def create_review(
    payload: ReviewCreateRequest,
    user_id: str = CurrentUserDep,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """提交审图任务到 Celery reviews 队列。"""
    log.info(
        "review.submitted",
        user=user_id,
        file_type=payload.file_type,
        file_key=payload.file_key,
    )
    async_result = run_review.apply_async(
        kwargs={
            "file_key": payload.file_key,
            "file_type": payload.file_type,
            "standard_set": payload.standard_set,
            "user_id": user_id,
        },
        queue="reviews",
    )
    task_id = async_result.id
    register_task(task_id, "review")
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=ReviewTaskAccepted(
            task_id=task_id,
            websocket_url=f"/api/v1/ws/tasks/{task_id}",
        ).model_dump(),
    )


@router.get(
    "/{task_id}/result",
    summary="查询审图结果",
)
async def get_review_result(
    task_id: str,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """查询审图任务结果。

    从 Celery result backend 读取任务状态与返回值。
    状态：
    - PENDING：任务排队中或不存在
    - STARTED/RETRY：执行中
    - PROGRESS：执行中（携带 step/progress 进度元数据）
    - SUCCESS：返回 ReviewResult
    - FAILURE：返回错误信息
    """
    if not task_exists(task_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务 ID 不存在: {task_id}",
        )
    result: AsyncResult = celery_app.AsyncResult(task_id)
    state = result.state

    log.info("review.result.query", task_id=task_id, state=state)

    if state == "PENDING":
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "task_id": task_id,
                "status": "pending",
                "message": "任务排队中或任务 ID 不存在",
            },
        )
    if state in ("STARTED", "RETRY", "PROGRESS"):
        content = {
            "task_id": task_id,
            "status": "running",
            "message": f"任务执行中（state={state}）",
        }
        if state == "PROGRESS" and isinstance(result.info, dict):
            content["step"] = result.info.get("step", "")
            content["progress"] = result.info.get("progress", 0)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=content,
        )
    if state == "FAILURE":
        exc = result.result
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "task_id": task_id,
                "status": "failed",
                "error": str(exc) if exc else "任务执行失败",
            },
        )
    if state == "SUCCESS":
        data = result.result
        if isinstance(data, dict):
            data = {**data, "status": "completed"}
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=data,
        )
    # 兜底
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "task_id": task_id,
            "status": "unknown",
            "state": state,
        },
    )


@router.get(
    "/{task_id}/report",
    summary="下载审图报告",
)
async def get_review_report(
    task_id: str,
    format: str = "html",
    log: Logger = LoggerDep,
) -> FileResponse:
    """下载审图报告文件。

    Args:
        task_id: 任务 ID
        format: 报告格式（html / pdf）；pdf 不可用时回退到 html
    """
    result: AsyncResult = celery_app.AsyncResult(task_id)
    if result.state != "SUCCESS":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务结果不可用（state={result.state}）；请先调用 /result 确认任务完成",
        )

    data = result.result
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="任务结果格式异常",
        )

    report_path = data.get("report_path")
    pdf_path = data.get("pdf_report_path")

    if not report_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务结果中未包含报告路径",
        )

    target = Path(report_path)
    if format.lower() == "pdf" and pdf_path:
        target = Path(pdf_path)
    elif format.lower() == "pdf":
        log.warning("review.report.pdf_unavailable", task_id=task_id, fallback="html")

    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"报告文件不存在: {target}",
        )

    media_type = "application/pdf" if target.suffix.lower() == ".pdf" else "text/html"
    log.info("review.report.served", task_id=task_id, path=str(target), format=format)

    return FileResponse(
        path=str(target),
        media_type=media_type,
        filename=target.name,
    )
