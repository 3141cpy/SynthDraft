"""审计日志增强（SubTask 13.4）。

等保三级 8.1.4.3 要求审计日志覆盖：
1. **用户操作**：登录/登出/数据查询/数据修改
2. **数据访问**：文件读取/下载/导出
3. **管理员操作**：配置变更/权限授予/系统启停

设计原则（八荣八耻）：
- 复用现有 ``observability/llm_metrics.py`` 的 JSONL 持久化模式（避免重复实现）
- 复用 structlog（``app.logging``）做结构化日志
- 不引入新依赖（elasticsearch / loki 等留待运维侧采集）
- 实事求是：本模块仅做日志记录与查询，不做实时告警（属于 OBS 模块职责）

日志格式：JSONL，每行一条审计事件，写入 ``settings.AUDIT_LOG_PATH``。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from app.config import settings
from app.logging import get_logger

log = get_logger(__name__)

_WRITE_LOCK = threading.Lock()

# 审计事件类型
AuditEventType = Literal[
    "user_login",          # 用户登录
    "user_logout",         # 用户登出
    "user_query",          # 数据查询
    "user_modify",         # 数据修改
    "data_access",         # 文件读取/下载
    "data_export",         # 数据导出
    "data_delete",         # 数据删除
    "admin_config_change", # 管理员配置变更
    "admin_permission",    # 权限授予/撤销
    "admin_system",        # 系统启停
]

# 高风险事件类型（应重点监控）
HIGH_RISK_EVENTS: set[str] = {
    "user_modify",
    "data_delete",
    "data_export",
    "admin_config_change",
    "admin_permission",
    "admin_system",
}


def _audit_log_path() -> Path:
    return Path(settings.AUDIT_LOG_PATH)


def _ensure_log_dir() -> None:
    p = _audit_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)


def record_audit_event(
    *,
    event_type: AuditEventType | str,
    actor: str = "",  # 用户名 / 系统组件名
    actor_ip: str = "",
    target: str = "",  # 操作对象（如文件路径 / API 路径 / 配置项）
    action: str = "",  # 动作描述
    result: Literal["success", "failure", "denied"] = "success",
    detail: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """记录一条审计事件到 JSONL 文件。

    Args:
        event_type: 事件类型（见 AuditEventType）
        actor: 操作者（用户名 / 系统组件名）
        actor_ip: 操作者 IP（如可获取）
        target: 操作对象
        action: 动作描述（自由文本）
        result: 结果（success / failure / denied）
        detail: 详细信息（dict）
        extra: 额外元数据

    Returns:
        实际写入的事件字典

    环境限制说明（实事求是标注）：
    - 若 AUDIT_LOG_ENABLED=false，仅记录到 structlog，不写文件
    """
    event: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": str(event_type),
        "actor": str(actor),
        "actor_ip": str(actor_ip),
        "target": str(target),
        "action": str(action),
        "result": str(result),
        "is_high_risk": str(event_type) in HIGH_RISK_EVENTS,
    }
    if detail:
        event["detail"] = detail
    if extra:
        event["extra"] = extra

    # 始终记录到 structlog（即使文件写入关闭）
    log_level = "warning" if event["is_high_risk"] or result != "success" else "info"
    log_fn = getattr(log, log_level, log.info)
    log_fn("audit.event", **{k: v for k, v in event.items() if v})

    if not settings.AUDIT_LOG_ENABLED:
        return event

    # 写入 JSONL 文件
    try:
        _ensure_log_dir()
        with _WRITE_LOCK:
            with _audit_log_path().open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        log.error("audit_log.write_failed", error=str(e))

    return event


def load_audit_events(
    *,
    event_type: str | None = None,
    actor: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    high_risk_only: bool = False,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """查询审计日志。

    Args:
        event_type: 按事件类型过滤
        actor: 按操作者过滤
        since: 起始时间（含）
        until: 结束时间（不含）
        high_risk_only: 仅返回高风险事件
        limit: 最多返回条数（默认 1000）

    Returns:
        审计事件列表（按时间倒序）
    """
    p = _audit_log_path()
    if not p.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception as e:  # noqa: BLE001
                    log.warning("audit_log.load.line_skipped", lineno=lineno, error=str(e))
                    continue
                # 过滤
                if event_type and ev.get("event_type") != event_type:
                    continue
                if actor and ev.get("actor") != actor:
                    continue
                if high_risk_only and not ev.get("is_high_risk"):
                    continue
                if since or until:
                    try:
                        ts = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
                        if since and ts < since:
                            continue
                        if until and ts >= until:
                            continue
                    except Exception:  # noqa: BLE001
                        pass
                events.append(ev)
    except Exception as e:  # noqa: BLE001
        log.warning("audit_log.load_failed", error=str(e))
    # 按时间倒序排序后再取前 limit 条（避免 break 后排序返回最旧事件）
    events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return events[:limit]


def cleanup_expired_logs(retention_days: int | None = None) -> int:
    """清理过期审计日志。

    Args:
        retention_days: 保留天数（None 时读 settings.AUDIT_LOG_RETENTION_DAYS）

    Returns:
        已删除的日志条数
    """
    if retention_days is None:
        retention_days = settings.AUDIT_LOG_RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    p = _audit_log_path()
    if not p.is_file():
        return 0
    kept: list[str] = []
    deleted = 0
    try:
        # 持有写锁贯穿读+写全过程，避免与 record_audit_event 竞态丢失审计记录
        with _WRITE_LOCK:
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                        ts = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
                        if ts < cutoff:
                            deleted += 1
                            continue
                    except Exception:  # noqa: BLE001
                        pass  # 解析失败的行保留，避免误删
                    kept.append(line)
            # 写回保留的日志
            with p.open("w", encoding="utf-8") as f:
                for line in kept:
                    f.write(line + "\n")
    except Exception as e:  # noqa: BLE001
        log.warning("audit_log.cleanup_failed", error=str(e))
        return 0
    log.info("audit_log.cleanup_done", deleted=deleted, kept=len(kept), retention_days=retention_days)
    return deleted


def self_test() -> dict[str, Any]:
    """self_test：写入审计事件 + 查询 + 清理。"""
    import tempfile
    orig_path = settings.AUDIT_LOG_PATH
    orig_enabled = settings.AUDIT_LOG_ENABLED
    tmpdir = tempfile.mkdtemp(prefix="audit_log_selftest_")
    test_path = str(Path(tmpdir) / "audit.jsonl")
    settings.AUDIT_LOG_PATH = test_path  # type: ignore[assignment]
    settings.AUDIT_LOG_ENABLED = True  # type: ignore[assignment]
    try:
        # 1. 写入 3 类事件
        ev1 = record_audit_event(
            event_type="user_login",
            actor="alice",
            action="用户登录",
            result="success",
        )
        ev2 = record_audit_event(
            event_type="data_export",
            actor="bob",
            target="/api/v1/generations/123/export",
            action="导出生成结果",
            result="success",
        )
        ev3 = record_audit_event(
            event_type="admin_config_change",
            actor="admin",
            target="VLLM_QUANTIZATION",
            action="修改 vLLM 量化配置",
            result="success",
            detail={"old": "", "new": "awq"},
        )

        # 2. 查询：全部
        all_events = load_audit_events(limit=100)
        # 3. 查询：高风险
        high_risk = load_audit_events(high_risk_only=True)
        # 4. 查询：按 actor
        bob_events = load_audit_events(actor="bob")

        # 5. 清理过期（cutoff 设为未来时间，应删 0 条）
        deleted_none = cleanup_expired_logs(retention_days=36500)
        # 6. 清理过期（cutoff 设为过去，应删 3 条）
        deleted_all = cleanup_expired_logs(retention_days=-1)

        return {
            "wrote_count": 3,
            "loaded_count": len(all_events),
            "high_risk_count": len(high_risk),
            "bob_events_count": len(bob_events),
            "cleanup_future_deleted": deleted_none,
            "cleanup_past_deleted": deleted_all,
            "ev1_is_high_risk": ev1["is_high_risk"],
            "ev2_is_high_risk": ev2["is_high_risk"],
            "ev3_is_high_risk": ev3["is_high_risk"],
            "audit_path": test_path,
            "ok": (
                len(all_events) == 3
                and len(high_risk) == 2  # data_export + admin_config_change
                and len(bob_events) == 1
                and deleted_none == 0
                and deleted_all == 3
                and ev1["is_high_risk"] is False
                and ev2["is_high_risk"] is True
                and ev3["is_high_risk"] is True
            ),
        }
    finally:
        settings.AUDIT_LOG_PATH = orig_path  # type: ignore[assignment]
        settings.AUDIT_LOG_ENABLED = orig_enabled  # type: ignore[assignment]


if __name__ == "__main__":
    print(json.dumps(self_test(), indent=2, ensure_ascii=False, default=str))
