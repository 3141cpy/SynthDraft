"""协同闭环端点（Task 11）。

端点：
- POST /api/v1/collaboration/optimize-from-review
    基于审图缺陷优化图纸（SubTask 11.1）
- GET /api/v1/collaboration/diff-report/{old_task_id}/{new_task_id}
    修订前后对比报告（SubTask 11.3）
- POST /api/v1/collaboration/feedback
    用户反馈回流（SubTask 11.4）
- GET /api/v1/collaboration/feedback/{review_task_id}
    查询某审图任务的所有反馈
- GET /api/v1/collaboration/feedback-stats
    反馈统计
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUserDep, LoggerDep
from app.celery.task_registry import register_task, task_exists
from app.celery.tasks.collaboration import run_optimize_from_review
from app.celery_app import celery_app
from app.logging import Logger
from app.schemas.collaboration import (
    CollaborativeWorkflowResult,
    DiffReport,
    FeedbackRecord,
    OptimizeFromReviewRequest,
)
from app.schemas.review_detail import DefectItem, ReviewResult
from app.services.collaboration.diff_report import generate_diff_report
from app.services.collaboration.feedback_store import (
    feedback_stats,
    load_feedback,
    save_feedback,
)

router = APIRouter()


@router.post(
    "/optimize-from-review",
    response_model=CollaborativeWorkflowResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="基于审图缺陷优化图纸（SubTask 11.1）",
)
async def optimize_from_review(
    payload: OptimizeFromReviewRequest,
    user_id: str = CurrentUserDep,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """基于审图缺陷自动派发生成任务，实现"审图→生成"协同闭环。

    流程：
    1. 读取原审图任务结果（ReviewResult）
    2. 缺陷列表 → LLM optimization prompt
    3. 派发 run_generation 任务（DXF 输出，自动触发复审）
    4. 返回 CollaborativeWorkflowResult（含 generation_task_id）
    """
    log.info(
        "collaboration.optimize.submitted",
        user=user_id,
        original_review_task_id=payload.review_task_id,
    )

    # 校验原审图任务已完成
    review_async = celery_app.AsyncResult(payload.review_task_id)
    if review_async.state != "SUCCESS":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"原审图任务状态为 {review_async.state}，"
                f"需等待 SUCCESS 后才能派发优化（review_task_id={payload.review_task_id}）"
            ),
        )

    async_result = run_optimize_from_review.apply_async(
        kwargs={
            "review_task_id": payload.review_task_id,
            "user_id": user_id,
            "output_format": payload.output_format,
            "auto_re_review": payload.auto_re_review,
        },
        queue="generations",
    )
    task_id = async_result.id
    register_task(task_id, "collaboration")
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=CollaborativeWorkflowResult(
            original_review_task_id=payload.review_task_id,
            generation_task_id=task_id,
            new_review_task_id=None,
            status="dispatched",
            defects_count=0,
            optimized_prompt="",
            metadata={
                "optimize_task_id": task_id,
                "websocket_url": f"/api/v1/ws/tasks/{task_id}",
            },
        ).model_dump(mode="json"),
    )


@router.get(
    "/optimize-result/{task_id}",
    summary="查询优化任务结果",
)
async def get_optimize_result(
    task_id: str,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """查询 run_optimize_from_review 任务结果。"""
    if not task_exists(task_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务 ID 不存在: {task_id}",
        )
    result = celery_app.AsyncResult(task_id)
    state = result.state
    log.info("collaboration.optimize.result_query", task_id=task_id, state=state)

    if state == "PENDING":
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"task_id": task_id, "status": "pending"},
        )
    if state in ("STARTED", "RETRY"):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"task_id": task_id, "status": "running"},
        )
    if state == "FAILURE":
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"task_id": task_id, "status": "failed", "error": str(result.result)},
        )
    if state == "SUCCESS":
        data = result.result
        if isinstance(data, dict):
            data = {**data, "status": "completed"}
        return JSONResponse(status_code=status.HTTP_200_OK, content=data)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"task_id": task_id, "status": "unknown", "state": state},
    )


@router.get(
    "/diff-report/{old_review_task_id}/{new_review_task_id}",
    response_model=DiffReport,
    summary="修订前后对比报告（SubTask 11.3）",
)
async def get_diff_report(
    old_review_task_id: str,
    new_review_task_id: str,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """生成修订前后两次审图的缺陷对比报告。

    自动从 Celery result backend 读取两次审图结果，对比缺陷列表，
    标注 resolved/unresolved/new 闭环状态。
    """
    log.info(
        "collaboration.diff_report.requested",
        old_review_task_id=old_review_task_id,
        new_review_task_id=new_review_task_id,
    )

    old_result = _fetch_review_result_dict(old_review_task_id)
    new_result = _fetch_review_result_dict(new_review_task_id)

    if old_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"原审图任务结果不可用: {old_review_task_id}",
        )
    if new_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"修订后审图任务结果不可用: {new_review_task_id}",
        )

    old_defects = [DefectItem(**d) for d in old_result.get("defects", [])]
    new_defects = [DefectItem(**d) for d in new_result.get("defects", [])]
    old_score = old_result.get("compliance_score")
    new_score = new_result.get("compliance_score")

    report = generate_diff_report(
        old_review_task_id=old_review_task_id,
        new_review_task_id=new_review_task_id,
        old_defects=old_defects,
        new_defects=new_defects,
        old_score=old_score,
        new_score=new_score,
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=report.model_dump(mode="json"),
    )


@router.post(
    "/feedback",
    response_model=FeedbackRecord,
    status_code=status.HTTP_201_CREATED,
    summary="用户反馈回流（SubTask 11.4）",
)
async def submit_feedback(
    payload: FeedbackRecord,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """提交用户对审图缺陷的反馈（采纳/误报/修改建议）。

    反馈将持久化到文件系统，后续可被 LLM 推理时检索。
    """
    log.info(
        "collaboration.feedback.submitted",
        review_task_id=payload.review_task_id,
        defect_index=payload.defect_index,
        action=payload.action,
    )

    # 自动填充缺陷快照（若未提供）
    if payload.defect_snapshot is None:
        review_result = _fetch_review_result_dict(payload.review_task_id)
        if review_result is not None:
            defects = review_result.get("defects", [])
            if 0 <= payload.defect_index < len(defects):
                payload.defect_snapshot = DefectItem(**defects[payload.defect_index])

    saved_path = save_feedback(payload)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=payload.model_dump(mode="json"),
    )


@router.get(
    "/feedback/{review_task_id}",
    summary="查询某审图任务的所有反馈",
)
async def list_feedback(
    review_task_id: str,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """查询某审图任务的所有用户反馈。"""
    records = load_feedback(review_task_id)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "review_task_id": review_task_id,
            "count": len(records),
            "feedbacks": [r.model_dump(mode="json") for r in records],
        },
    )


@router.get(
    "/feedback-stats",
    summary="反馈统计",
)
async def get_feedback_stats(
    log: Logger = LoggerDep,
) -> JSONResponse:
    """全局反馈统计（用于仪表盘）。"""
    stats = feedback_stats()
    return JSONResponse(status_code=status.HTTP_200_OK, content=stats)


# ===== 辅助函数 =====


def _fetch_review_result_dict(review_task_id: str) -> dict | None:
    """从 Celery result backend 读取审图结果 dict。"""
    result = celery_app.AsyncResult(review_task_id)
    if result.state != "SUCCESS":
        return None
    data = result.result
    if isinstance(data, dict):
        return data
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json")
    return None
