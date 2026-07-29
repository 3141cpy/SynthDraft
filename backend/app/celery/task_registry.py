"""任务 ID 注册表。

在 Redis 中维护任务 ID，用于区分"排队中"与"ID 不存在"。
Celery 的 AsyncResult 对不存在的 task_id 默认返回 PENDING，
无法区分"排队中"与"ID 不存在"。本模块通过 Redis key 解决此问题。
"""

from __future__ import annotations

from app.celery_app import celery_app
from app.logging import get_logger

log = get_logger(__name__)

# Redis key 前缀
_TASK_KEY_PREFIX = "synthdraft:task:"
# 默认 TTL：24 小时
_DEFAULT_TTL = 86400


def _get_redis_client():
    """获取 Redis 客户端（复用 Celery result backend 的连接）。"""
    backend = celery_app.backend
    # Celery Redis backend 暴露 client 属性
    if hasattr(backend, "client"):
        return backend.client
    # 兜底：直接创建 Redis 连接
    import redis
    from app.config import settings
    return redis.from_url(settings.CELERY_RESULT_BACKEND)


def register_task(task_id: str, task_type: str, ttl: int = _DEFAULT_TTL) -> None:
    """注册任务 ID 到 Redis。

    Args:
        task_id: Celery 任务 ID
        task_type: 任务类型（如 "review" / "generation" / "sketch" / "collaboration"）
        ttl: Redis key TTL（秒），默认 24 小时
    """
    try:
        client = _get_redis_client()
        key = f"{_TASK_KEY_PREFIX}{task_id}"
        client.setex(key, ttl, task_type)
        log.debug("task_registry.registered", task_id=task_id, task_type=task_type)
    except Exception as e:
        # 注册失败不应阻塞主流程，仅记录 warning
        log.warning("task_registry.register_failed", task_id=task_id, error=str(e))


def task_exists(task_id: str) -> bool:
    """检查任务 ID 是否存在于注册表。

    Args:
        task_id: Celery 任务 ID

    Returns:
        True 表示任务曾被提交（排队中/运行中/已完成）
        False 表示任务 ID 不存在
    """
    try:
        client = _get_redis_client()
        key = f"{_TASK_KEY_PREFIX}{task_id}"
        return bool(client.exists(key))
    except Exception as e:
        # 查询失败时返回 True（保守策略，不阻断查询）
        log.warning("task_registry.exists_check_failed", task_id=task_id, error=str(e))
        return True
