"""结构化日志：基于 structlog，开发态人类可读、生产态 JSON。

遵循"以复用现有为荣"原则，不重复实现日志格式化。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config import settings

# structlog 的 BoundLogger 在绑定前是 LazyProxy；统一用 Any 避免类型噪声
Logger = Any


def configure_logging() -> None:
    """初始化 structlog 与标准 logging 桥接。

    开发环境（APP_ENV != production）：人类可读的控制台输出。
    生产环境：JSON 格式，便于 ELK/Loki 采集。
    """
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.DEBUG)

    # 标准库 logging 配置（structlog 内部会调用）
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    # 共享的处理器链
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_production:
        # 生产：JSON
        renderer = structlog.processors.JSONRenderer()
    else:
        # 开发：彩色控制台
        renderer = structlog.dev.ConsoleRenderer(colors=not settings.is_production)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 降低三方库噪声
    for noisy in ("uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取一个结构化 logger。"""
    return structlog.get_logger(name)
