"""可观测性端点（Task 16）。

端点：
- GET /api/v1/observability/queue-status：Celery 队列状态
- GET /api/v1/observability/feedback-summary：反馈总体统计
- GET /api/v1/observability/feedback-by-category：按类别统计
- GET /api/v1/observability/feedback-trend：时间趋势
- GET /api/v1/observability/llm-cost-summary：LLM 成本汇总
- GET /api/v1/observability/llm-latency：LLM 延迟分布
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.api.deps import LoggerDep
from app.logging import Logger
from app.observability import llm_metrics, queue_monitor
from app.services.review import feedback_analytics

router = APIRouter()


@router.get(
    "/observability/queue-status",
    summary="Celery 队列状态",
    description="采集各 Celery 队列的活跃/排队/失败任务数与 worker 状态，触发阈值告警。",
)
async def get_queue_status(log: Logger = LoggerDep) -> JSONResponse:
    status = queue_monitor.collect_queue_status()
    log.info(
        "observability.queue_status",
        worker_count=status["worker_count"],
        queue_count=len(status["queues"]),
        alert_count=len(status["alerts"]),
    )
    return JSONResponse(status_code=200, content=status)


@router.get(
    "/observability/feedback-summary",
    summary="反馈总体统计",
    description="统计总反馈数 / 误报率 / 采纳率 / 修改建议率。",
)
async def get_feedback_summary(log: Logger = LoggerDep) -> JSONResponse:
    summary = feedback_analytics.compute_summary()
    log.info("observability.feedback_summary", total=summary["total"])
    return JSONResponse(status_code=200, content=summary)


@router.get(
    "/observability/feedback-by-category",
    summary="按缺陷类别分组统计反馈",
)
async def get_feedback_by_category(log: Logger = LoggerDep) -> JSONResponse:
    result = feedback_analytics.compute_by_category()
    log.info(
        "observability.feedback_by_category",
        category_count=result["category_count"],
    )
    return JSONResponse(status_code=200, content=result)


@router.get(
    "/observability/feedback-trend",
    summary="反馈时间趋势",
)
async def get_feedback_trend(
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    log: Logger = LoggerDep,
) -> JSONResponse:
    result = feedback_analytics.compute_trend(granularity)  # type: ignore[arg-type]
    log.info(
        "observability.feedback_trend",
        granularity=granularity,
        bucket_count=result["bucket_count"],
    )
    return JSONResponse(status_code=200, content=result)


@router.get(
    "/observability/llm-cost-summary",
    summary="LLM 推理成本汇总（按模型）",
)
async def get_llm_cost_summary(log: Logger = LoggerDep) -> JSONResponse:
    summary = llm_metrics.compute_cost_summary()
    log.info(
        "observability.llm_cost_summary",
        total_calls=summary["total_calls"],
        total_cost_usd=summary["total_cost_usd"],
    )
    return JSONResponse(status_code=200, content=summary)


@router.get(
    "/observability/llm-latency",
    summary="LLM 推理延迟分布",
)
async def get_llm_latency(log: Logger = LoggerDep) -> JSONResponse:
    result = llm_metrics.compute_latency_distribution()
    log.info(
        "observability.llm_latency",
        count=result["overall"]["count"],
        p95_ms=result["overall"]["p95_ms"],
    )
    return JSONResponse(status_code=200, content=result)
