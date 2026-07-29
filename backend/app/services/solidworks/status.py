"""SolidWorks Worker 健康状态枚举（SubTask 7.4）。

用于 SolidWorksWorkerPool.health_status 属性，描述 Worker Pool 当前健康状态。
与 exceptions.py 分离：exceptions 描述错误，status 描述运行态。

状态转移：
    STOPPED → (start) → HEALTHY
    HEALTHY → (ping 失败但会话对象存在) → DEGRADED → (软重启) → HEALTHY
    HEALTHY/DEGRADED → (会话对象为 None / 连续 3 次失败) → UNHEALTHY
    UNHEALTHY → (restart) → RESTARTING → (成功) → HEALTHY
    RESTARTING → (失败超 max_retries) → UNHEALTHY
    任意状态 → (shutdown) → STOPPED
"""

from __future__ import annotations

from enum import Enum


class HealthStatus(str, Enum):
    """Worker Pool 健康状态。

    继承 str 便于 JSON 序列化与日志结构化字段输出。
    """

    HEALTHY = "healthy"
    """健康：ping 成功，可接受任务。"""

    DEGRADED = "degraded"
    """降级：ping 失败但会话对象仍存在，尝试软重启可恢复。"""

    UNHEALTHY = "unhealthy"
    """不健康：会话对象为 None 或连续多次失败，需硬重启。"""

    RESTARTING = "restarting"
    """重启中：正在执行 restart 流程，拒绝新任务。"""

    STOPPED = "stopped"
    """已停止：Worker Pool 已 shutdown 或尚未 start。"""


__all__ = ["HealthStatus"]
