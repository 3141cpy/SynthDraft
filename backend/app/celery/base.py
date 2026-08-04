"""Celery 任务基类。

提供统一的结构化日志、异常捕获与状态回写。
所有业务任务应继承 BaseTask 而非直接使用 @app.task。
"""

from __future__ import annotations

from typing import Any

from celery import Task

from app.logging import get_logger

log = get_logger(__name__)


class BaseTask(Task):
    """项目统一任务基类。

    - before_start：执行前刷新 AI 配置缓存（LLM/VLM）
    - on_failure：记录失败日志，将异常信息写入 result
    - on_success：记录成功日志
    """

    name = "app.celery.base.BaseTask"
    abstract = True

    def before_start(self, task_id: str, args: tuple, kwargs: dict) -> None:
        """任务执行前刷新 AI 配置缓存（LLM/VLM）。

        使用 psycopg2 同步直连 DB，避免 Celery --pool=threads 下 asyncio.run
        与 asyncpg 事件循环冲突。失败仅记 warning 日志，不阻断任务执行。
        """
        from app.services.ai.base import refresh_active_config_cache_sync

        try:
            refresh_active_config_cache_sync()
            log.info(
                "task.before_start.cache_refreshed",
                task_id=task_id,
                task_name=self.name,
            )
        except Exception as exc:
            log.warning(
                "task.before_start.refresh_failed",
                task_id=task_id,
                task_name=self.name,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        traceback: Any,
    ) -> None:
        log.error(
            "task.failed",
            task_id=task_id,
            task_name=self.name,
            args=args,
            kwargs=kwargs,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        super().on_failure(exc, task_id, args, kwargs, traceback)

    def on_success(
        self,
        retval: Any,
        task_id: str,
        args: tuple,
        kwargs: dict,
    ) -> None:
        log.info(
            "task.succeeded",
            task_id=task_id,
            task_name=self.name,
        )
        super().on_success(retval, task_id, args, kwargs)

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ) -> None:
        log.warning(
            "task.retry",
            task_id=task_id,
            task_name=self.name,
            error=str(exc),
        )
        super().on_retry(exc, task_id, args, kwargs, einfo)
