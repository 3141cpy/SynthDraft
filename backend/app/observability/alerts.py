"""告警规则与通知渠道（SubTask 16.2）。

告警规则：
- 队列堆积：某队列排队任务数 > 阈值
- 任务失败率：失败率 > 阈值（基于反馈的失败计数）
- Worker 离线：在线 worker 数 == 0
- 任务长期 reserved 不执行：某队列 reserved > 0 且 active == 0 且 worker_count > 0（疑似卡死）

通知渠道：
- log（始终记录）
- webhook（可选，``settings.OBS_ALERT_WEBHOOK_URL`` 配置时 POST）

遵循"以复用现有为荣"原则：不引入邮件/Slack SDK，webhook 用 httpx 直接 POST。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.logging import get_logger

log = get_logger(__name__)


def evaluate_queue_alerts(
    *,
    queues: dict[str, dict[str, int]],
    worker_count: int,
    backlog_threshold: int,
    failure_rate_threshold: float,
) -> list[dict[str, Any]]:
    """评估队列相关告警。

    Args:
        queues: ``queue_monitor.collect_queue_status`` 返回的 queues 字段
        worker_count: 在线 worker 数
        backlog_threshold: 排队堆积阈值
        failure_rate_threshold: 失败率阈值（百分比）

    Returns:
        触发的告警列表，每项含 level / rule / queue / value / threshold / message。
    """
    alerts: list[dict[str, Any]] = []

    # 1) Worker 离线
    if worker_count == 0:
        alerts.append(
            {
                "level": "critical",
                "rule": "worker_offline",
                "queue": "*",
                "value": 0,
                "threshold": 1,
                "message": "无在线 Celery worker",
            }
        )

    # 2) 队列堆积（active + reserved + scheduled 排队中）
    for q, counts in queues.items():
        backlog = counts.get("active", 0) + counts.get("reserved", 0) + counts.get("scheduled", 0)
        if backlog > backlog_threshold:
            alerts.append(
                {
                    "level": "warning",
                    "rule": "queue_backlog",
                    "queue": q,
                    "value": backlog,
                    "threshold": backlog_threshold,
                    "message": f"队列 {q} 排队任务数 {backlog} 超过阈值 {backlog_threshold}",
                }
            )

        # 3) 任务长期 reserved 不执行（worker 在线但不消费，疑似卡死）
        reserved = counts.get("reserved", 0)
        active = counts.get("active", 0)
        if reserved > 0 and active == 0 and worker_count > 0:
            alerts.append(
                {
                    "level": "critical",
                    "rule": "task_stale_reserved",
                    "queue": q,
                    "value": reserved,
                    "threshold": 0,
                    "message": (
                        f"队列 {q} 有 {reserved} 个任务 reserved 但 active=0，"
                        f"worker_count={worker_count}，疑似 worker 在线但不消费"
                    ),
                }
            )

        # 4) 失败率（基于 failed 计数；当前实时探测无法获取历史失败率，仅当 failed > 0 时触发）
        failed = counts.get("failed", 0)
        total = backlog + failed
        if total > 0 and failed > 0:
            failure_rate = failed * 100.0 / total
            if failure_rate > failure_rate_threshold:
                alerts.append(
                    {
                        "level": "warning",
                        "rule": "queue_failure_rate",
                        "queue": q,
                        "value": round(failure_rate, 2),
                        "threshold": failure_rate_threshold,
                        "message": f"队列 {q} 失败率 {failure_rate:.2f}% 超过阈值 {failure_rate_threshold}%",
                    }
                )

    # 记录告警日志
    for a in alerts:
        if a["level"] == "critical":
            log.error("alert.triggered", **a)
        else:
            log.warning("alert.triggered", **a)

    # 异步触发 webhook（不阻塞调用方，失败仅记录）
    if alerts and settings.OBS_ALERT_WEBHOOK_URL:
        _fire_webhook(alerts)

    return alerts


def _fire_webhook(alerts: list[dict[str, Any]]) -> None:
    """向 webhook POST 告警列表（fire-and-forget，失败仅记录 warning）。"""
    payload = {
        "source": settings.OTEL_SERVICE_NAME,
        "fired_at": datetime.now(timezone.utc).isoformat(),
        "alerts": alerts,
    }
    try:
        resp = httpx.post(
            settings.OBS_ALERT_WEBHOOK_URL,
            json=payload,
            timeout=5.0,
        )
        log.info(
            "alert.webhook.sent",
            status_code=resp.status_code,
            alert_count=len(alerts),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("alert.webhook.failed", error=str(e), alert_count=len(alerts))


def self_test() -> dict[str, Any]:
    """self_test：构造告警场景验证规则触发。"""
    # 1) Worker 离线
    a1 = evaluate_queue_alerts(
        queues={"default": {"active": 0, "reserved": 0, "scheduled": 0, "failed": 0}},
        worker_count=0,
        backlog_threshold=50,
        failure_rate_threshold=10.0,
    )
    # 2) 队列堆积
    a2 = evaluate_queue_alerts(
        queues={"reviews": {"active": 30, "reserved": 30, "scheduled": 0, "failed": 0}},
        worker_count=1,
        backlog_threshold=50,
        failure_rate_threshold=10.0,
    )
    # 3) 失败率
    a3 = evaluate_queue_alerts(
        queues={"generations": {"active": 0, "reserved": 0, "scheduled": 0, "failed": 5}},
        worker_count=1,
        backlog_threshold=50,
        failure_rate_threshold=10.0,
    )
    # 4) 无告警
    a4 = evaluate_queue_alerts(
        queues={"default": {"active": 1, "reserved": 0, "scheduled": 0, "failed": 0}},
        worker_count=1,
        backlog_threshold=50,
        failure_rate_threshold=10.0,
    )
    # 5) task_stale_reserved 触发：reserved>0 且 active==0 且 worker_count>0
    a5 = evaluate_queue_alerts(
        queues={"default": {"active": 0, "reserved": 5, "scheduled": 0, "failed": 0}},
        worker_count=1,
        backlog_threshold=50,
        failure_rate_threshold=10.0,
    )
    # 6) task_stale_reserved 不触发：reserved>0 且 active>0（正在消费）
    a6 = evaluate_queue_alerts(
        queues={"default": {"active": 2, "reserved": 5, "scheduled": 0, "failed": 0}},
        worker_count=1,
        backlog_threshold=50,
        failure_rate_threshold=10.0,
    )

    rules_triggered = {a["rule"] for a in a1 + a2 + a3 + a5}
    a5_rules = {a["rule"] for a in a5}
    a6_rules = {a["rule"] for a in a6}
    return {
        "worker_offline_alerts": len(a1),
        "backlog_alerts": len(a2),
        "failure_rate_alerts": len(a3),
        "no_alerts_when_healthy": len(a4) == 0,
        "stale_reserved_alerts": len(a5),
        "stale_reserved_rules": sorted(a5_rules),
        "stale_reserved_no_alert_when_consuming": len(a6) == 0,
        "rules_triggered": sorted(rules_triggered),
        "ok": (
            len(a1) == 1
            and "worker_offline" in rules_triggered
            and len(a2) == 1
            and "queue_backlog" in rules_triggered
            and "queue_failure_rate" in rules_triggered
            and len(a4) == 0
            and len(a5) == 1
            and "task_stale_reserved" in a5_rules
            and len(a6) == 0
        ),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(self_test(), indent=2, ensure_ascii=False, default=str))
