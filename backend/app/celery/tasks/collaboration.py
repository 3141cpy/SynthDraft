"""协同闭环 Celery 任务（Task 11）。

实现"审图→生成→复审"完整闭环：
1. run_optimize_from_review：基于审图缺陷自动派发生成任务（SubTask 11.1）
2. （修订后自动复审由 run_generation 内部已实现，SubTask 11.2 复用）

任务编排：
    原审图任务（run_review）→ run_optimize_from_review
        ↓ 读取 ReviewResult.defects
        ↓ defects_to_optimization_prompt() 转换为 LLM prompt
        ↓ run_generation.apply_async() 派发生成任务
        ↓ （run_generation 内部自动派发 run_review 做复审，SubTask 11.2）
        ↓ 返回 CollaborativeWorkflowResult（含所有关联任务 ID）

依赖：
- app.celery_app.celery_app
- app.celery.tasks.reviews.run_review（读取原审图结果）
- app.celery.tasks.generations.run_generation（派发生成任务）
- app.services.collaboration.defect_to_prompt
- app.schemas.collaboration.CollaborativeWorkflowResult
"""

from __future__ import annotations

import time
from typing import Any

from app.celery.base import BaseTask
from app.celery_app import celery_app
from app.logging import get_logger
from app.schemas.collaboration import CollaborativeWorkflowResult
from app.schemas.review_detail import DefectItem, ReviewResult
from app.services.collaboration.defect_to_prompt import (
    defects_to_optimization_prompt,
    extract_file_hint_from_review_result,
)

log = get_logger(__name__)


@celery_app.task(
    name="app.celery.tasks.collaboration.run_optimize_from_review",
    bind=True,
    base=BaseTask,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    time_limit=120,        # 硬超时 2 分钟（仅派发，实际生成异步）
    soft_time_limit=100,   # 软超时 100 秒
)
def run_optimize_from_review(
    self: BaseTask,
    review_task_id: str,
    user_id: str = "anonymous",
    output_format: str = "dxf",
    auto_re_review: bool = True,
) -> dict[str, Any]:
    """基于审图缺陷优化图纸（SubTask 11.1）。

    流程：
    1. 从 Celery result backend 读取原审图结果（ReviewResult）
    2. 提取缺陷列表，转换为 LLM optimization prompt
    3. 派发 run_generation 任务（output_format=dxf，确保能触发复审）
    4. 返回 CollaborativeWorkflowResult（含 generation_task_id）

    Args:
        review_task_id: 原审图任务 ID
        user_id: 提交用户 ID
        output_format: 期望输出格式（默认 dxf，便于复审闭环）
        auto_re_review: 是否自动触发复审（由 run_generation 内部实现）

    Returns:
        CollaborativeWorkflowResult dict
    """
    task_id = self.request.id or "unknown"
    t_start = time.perf_counter()
    log.info(
        "collaboration.optimize.start",
        task_id=task_id,
        original_review_task_id=review_task_id,
        user=user_id,
        output_format=output_format,
    )

    # ===== 1. 读取原审图结果 =====
    review_result_dict = _fetch_review_result(review_task_id)
    if review_result_dict is None:
        raise FileNotFoundError(
            f"原审图任务结果不可用（可能已过期或不存在）: {review_task_id}"
        )

    # 构造 ReviewResult 对象
    try:
        review_result = ReviewResult(**review_result_dict)
    except Exception as e:  # noqa: BLE001
        log.error(
            "collaboration.optimize.parse_review_failed",
            task_id=task_id,
            error=str(e),
        )
        raise ValueError(f"原审图结果解析失败: {e}") from e

    defects = review_result.defects
    defects_count = len(defects)
    log.info(
        "collaboration.optimize.review_loaded",
        task_id=task_id,
        original_review_task_id=review_task_id,
        defects_count=defects_count,
        compliance_score=review_result.compliance_score,
    )

    # ===== 2. 缺陷 → LLM prompt =====
    file_hint = extract_file_hint_from_review_result(review_result_dict)
    prompt = defects_to_optimization_prompt(defects, file_hint)

    # 截断存储（避免 metadata 过大）
    prompt_preview = prompt[:500]

    # ===== 3. 派发 run_generation 任务 =====
    from app.celery.tasks.generations import run_generation

    gen_args = [
        "text",           # input_type
        prompt,           # prompt
        None,             # sketch_key
        output_format,    # output_format
        user_id,          # user_id
    ]

    try:
        async_result = run_generation.apply_async(args=gen_args)
        generation_task_id = async_result.id
        log.info(
            "collaboration.optimize.generation_dispatched",
            task_id=task_id,
            generation_task_id=generation_task_id,
            output_format=output_format,
        )
    except Exception as e:  # noqa: BLE001
        log.error(
            "collaboration.optimize.dispatch_failed",
            task_id=task_id,
            error=str(e),
        )
        # 返回 failed 状态
        result = CollaborativeWorkflowResult(
            original_review_task_id=review_task_id,
            generation_task_id="",
            new_review_task_id=None,
            status="failed",
            defects_count=defects_count,
            optimized_prompt=prompt_preview,
            metadata={
                "error": str(e),
                "user_id": user_id,
                "auto_re_review": auto_re_review,
                "elapsed_ms": int((time.perf_counter() - t_start) * 1000),
            },
        )
        return result.model_dump(mode="json")

    # ===== 4. 构造闭环结果 =====
    # 注意：new_review_task_id 在 run_generation 完成后才会写入其 metadata
    # 调用方需稍后查询 generation_task_id 的结果以获取 new_review_task_id
    result = CollaborativeWorkflowResult(
        original_review_task_id=review_task_id,
        generation_task_id=generation_task_id,
        new_review_task_id=None,  # 异步，由 run_generation 内部派发后填充
        status="dispatched",
        defects_count=defects_count,
        optimized_prompt=prompt_preview,
        metadata={
            "user_id": user_id,
            "output_format": output_format,
            "auto_re_review": auto_re_review,
            "original_compliance_score": review_result.compliance_score,
            "original_review_mode": review_result.review_mode,
            "elapsed_ms": int((time.perf_counter() - t_start) * 1000),
        },
    )

    log.info(
        "collaboration.optimize.done",
        task_id=task_id,
        generation_task_id=generation_task_id,
        defects_count=defects_count,
        elapsed_ms=result.metadata["elapsed_ms"],
    )
    return result.model_dump(mode="json")


def _fetch_review_result(review_task_id: str) -> dict[str, Any] | None:
    """从 Celery result backend 读取审图任务结果。

    Args:
        review_task_id: 审图任务 ID

    Returns:
        ReviewResult dict，或 None（任务不存在/未完成/已过期）
    """
    from app.celery_app import celery_app

    try:
        async_result = celery_app.AsyncResult(review_task_id)
        if async_result.state != "SUCCESS":
            log.warning(
                "collaboration.review_result.not_ready",
                review_task_id=review_task_id,
                state=async_result.state,
            )
            return None
        result = async_result.result
        if isinstance(result, dict):
            return result
        # 某些情况下 result 可能是 ReviewResult 对象（未序列化）
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        log.warning(
            "collaboration.review_result.unexpected_type",
            review_task_id=review_task_id,
            type=type(result).__name__,
        )
        return None
    except Exception as e:  # noqa: BLE001
        log.warning(
            "collaboration.review_result.fetch_failed",
            review_task_id=review_task_id,
            error=str(e),
        )
        return None
