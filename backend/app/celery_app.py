"""Celery 应用实例。

遵循"以复用现有为荣"原则，使用 Celery 5.x 标准 API。
broker/result backend 均指向 Redis（见 .env.example）。
"""

from __future__ import annotations

from celery import Celery

from app.config import settings
from app.logging import configure_logging, get_logger

# 在 Celery worker 启动时即配置日志
configure_logging()
log = get_logger(__name__)

celery_app = Celery(
    "synthdraft",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.celery.tasks.reviews",
        "app.celery.tasks.generations",
        "app.celery.tasks.solidworks",  # SubTask 7.5：SolidWorks Worker 队列
        "app.celery.tasks.sketch",  # Task 12：草图转 CAD
        "app.celery.tasks.assembly",  # Task 10：装配体生成（AssemCAD 范式）
        "app.celery.tasks.collaboration",  # Task 11：审图→生成协同闭环
    ],
)

celery_app.conf.update(
    # 序列化
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 任务路由（按队列分流）
    # - reviews/generations：Linux AI 服务消费
    # - solidworks：Windows SolidWorks Worker 消费（装有 SolidWorks 许可证的机器）
    task_routes={
        "app.celery.tasks.reviews.*": {"queue": "reviews"},
        "app.celery.tasks.generations.*": {"queue": "generations"},
        "app.celery.tasks.solidworks.*": {"queue": "solidworks"},
        "app.celery.tasks.sketch.*": {"queue": "sketch"},
        "app.celery.tasks.assembly.*": {"queue": "assembly"},
        "app.celery.tasks.collaboration.*": {"queue": "collaboration"},
    },
    # 默认队列
    task_default_queue="default",
    # 可见性超时（长任务需要更长）
    broker_visibility_timeout=3600,
    # 结果过期（7 天）
    result_expires=60 * 60 * 24 * 7,
    # 任务执行前预取 1 条（避免长任务饿死后继）
    worker_prefetch_multiplier=1,
    # 启用 STARTED 状态上报（配合任务内 update_state PROGRESS 进度上报）
    task_track_started=True,
    # 不发送默认事件以降低 broker 压力（如需监控可开启）
    task_send_sent_event=False,
    worker_send_task_events=False,
)

log.info(
    "celery.configured",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)


# 可选：在 worker 启动时注入 tracing
def _on_worker_ready(sender, **kwargs):  # noqa: ANN001
    """worker 就绪钩子，注入 OpenTelemetry 埋点。"""
    try:
        from app.tracing import configure_tracing, instrument_celery

        configure_tracing()
        instrument_celery()
    except Exception as e:  # noqa: BLE001
        log.warning("celery.tracing_init_failed", error=str(e))

    # 预热 LLM/VLM 配置缓存（Celery worker 进程不导入 main.py，需主动预热）
    try:
        import asyncio

        from app.services.ai.base import refresh_active_config_cache

        asyncio.run(refresh_active_config_cache())
        log.info("celery.worker_ready.cache_preheated")
    except Exception as e:  # noqa: BLE001
        log.warning("celery.worker_ready.preheat_cache_failed", error=str(e))


try:
    from celery.signals import worker_ready

    worker_ready.connect(_on_worker_ready)
except ImportError:
    pass
