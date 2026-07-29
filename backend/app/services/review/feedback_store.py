"""用户反馈存储（SubTask 16.3）。

记录审图缺陷条目的用户反馈：
- accept：用户认可该缺陷
- reject_as_false_positive：用户标记为误报
- modify_suggestion：用户修改了修改建议

存储方式：JSONL 文件追加写（与 ``llm_metrics`` 持久化风格一致）。
每条记录含：feedback_id / task_id / defect_id / category / severity /
action / user_id / timestamp / note。

遵循"以复用现有为荣"原则：复用 structlog + settings 配置，
不引入数据库依赖（P2 阶段最小可用）。
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import settings
from app.logging import get_logger

log = get_logger(__name__)

FeedbackAction = Literal["accept", "reject_as_false_positive", "modify_suggestion"]

_WRITE_LOCK = threading.Lock()


class FeedbackRecord(BaseModel):
    """单条反馈记录。"""

    feedback_id: str = Field(default_factory=lambda: f"fb_{uuid.uuid4().hex[:12]}")
    task_id: str
    defect_id: str
    category: str = ""  # 缺陷类别（如 "dimension" / "tolerance" / "annotation"）
    severity: str = ""  # 严重等级（如 "critical" / "major" / "minor"）
    action: FeedbackAction
    user_id: str = "anonymous"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    note: str = ""  # 修改建议文本或备注
    original_suggestion: str = ""  # 原始修改建议（modify_suggestion 时有意义）


def _store_path() -> Path:
    return Path(settings.OBS_FEEDBACK_STORE_PATH)


def _ensure_store_dir() -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)


def record_feedback(record: FeedbackRecord) -> FeedbackRecord:
    """追加一条反馈记录到 JSONL 文件。

    线程安全：通过模块级锁串行化文件写入。
    """
    _ensure_store_dir()
    with _WRITE_LOCK:
        with _store_path().open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")
    log.info(
        "feedback.recorded",
        feedback_id=record.feedback_id,
        task_id=record.task_id,
        action=record.action,
        category=record.category,
    )
    return record


def accept(
    task_id: str,
    defect_id: str,
    *,
    category: str = "",
    severity: str = "",
    user_id: str = "anonymous",
    note: str = "",
) -> FeedbackRecord:
    """用户认可缺陷条目。"""
    return record_feedback(
        FeedbackRecord(
            task_id=task_id,
            defect_id=defect_id,
            category=category,
            severity=severity,
            action="accept",
            user_id=user_id,
            note=note,
        )
    )


def reject_as_false_positive(
    task_id: str,
    defect_id: str,
    *,
    category: str = "",
    severity: str = "",
    user_id: str = "anonymous",
    note: str = "",
) -> FeedbackRecord:
    """用户标记缺陷为误报。"""
    return record_feedback(
        FeedbackRecord(
            task_id=task_id,
            defect_id=defect_id,
            category=category,
            severity=severity,
            action="reject_as_false_positive",
            user_id=user_id,
            note=note,
        )
    )


def modify_suggestion(
    task_id: str,
    defect_id: str,
    *,
    category: str = "",
    severity: str = "",
    user_id: str = "anonymous",
    note: str = "",
    original_suggestion: str = "",
) -> FeedbackRecord:
    """用户修改了修改建议。"""
    return record_feedback(
        FeedbackRecord(
            task_id=task_id,
            defect_id=defect_id,
            category=category,
            severity=severity,
            action="modify_suggestion",
            user_id=user_id,
            note=note,
            original_suggestion=original_suggestion,
        )
    )


def load_all_feedback() -> list[FeedbackRecord]:
    """加载全部反馈记录（按时间顺序）。

    文件不存在或解析失败的行跳过，不抛异常。
    """
    p = _store_path()
    if not p.is_file():
        return []
    records: list[FeedbackRecord] = []
    with p.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(FeedbackRecord.model_validate_json(line))
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "feedback.load.line_skipped",
                    lineno=lineno,
                    error=str(e),
                )
    return records


def clear_all_feedback() -> int:
    """清空反馈存储（仅测试用）。返回删除的记录数。"""
    p = _store_path()
    if not p.is_file():
        return 0
    n = len(load_all_feedback())
    p.unlink()
    return n


def self_test() -> dict[str, Any]:
    """self_test：写入 3 条样本反馈并读回验证。"""
    # 隔离测试：用临时路径
    import tempfile

    orig = settings.OBS_FEEDBACK_STORE_PATH
    tmpdir = tempfile.mkdtemp(prefix="feedback_selftest_")
    test_path = str(Path(tmpdir) / "feedback.jsonl")
    settings.OBS_FEEDBACK_STORE_PATH = test_path  # type: ignore[assignment]
    try:
        r1 = accept("t1", "d1", category="dimension", severity="major", user_id="u1")
        r2 = reject_as_false_positive(
            "t1", "d2", category="annotation", severity="minor", user_id="u1"
        )
        r3 = modify_suggestion(
            "t2",
            "d3",
            category="tolerance",
            severity="critical",
            user_id="u2",
            note="改用 IT7",
            original_suggestion="改用 IT8",
        )

        loaded = load_all_feedback()
        return {
            "wrote_count": 3,
            "loaded_count": len(loaded),
            "actions": [r.action for r in loaded],
            "categories": [r.category for r in loaded],
            "store_path": test_path,
            "ok": len(loaded) == 3
            and [r.feedback_id for r in loaded] == [r1.feedback_id, r2.feedback_id, r3.feedback_id],
        }
    finally:
        settings.OBS_FEEDBACK_STORE_PATH = orig  # type: ignore[assignment]


if __name__ == "__main__":
    import json as _json

    print(_json.dumps(self_test(), indent=2, ensure_ascii=False, default=str))
