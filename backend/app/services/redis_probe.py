"""Redis 探活工具。

P0 阶段使用同步 redis-py；/readyz 通过 asyncio.to_thread 调用避免阻塞事件循环。
遵循"以复用现有为荣"原则，复用 requirements 中的 redis 包。
"""

from __future__ import annotations

import redis as redis_lib

from app.config import settings


def check_redis_connected() -> bool:
    """同步探测 Redis 连通性。"""
    try:
        client = redis_lib.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        return bool(client.ping())
    except Exception:
        return False
