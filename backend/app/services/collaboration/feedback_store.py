"""用户反馈存储（SubTask 11.4）。

将用户对审图缺陷的反馈（采纳/误报/修改建议）持久化到文件系统，
后续可被 LLM 推理时检索（作为 few-shot 示例或规则补充）。

存储路径：
    {UPLOAD_DIR}/feedback/{review_task_id}_{defect_index}.json

设计原则：
- 不引入数据库（P0/P1 阶段使用文件系统）
- 单条反馈独立文件，便于增量追加与检索
- 反馈内容完整自包含（含缺陷快照，无需回查 Celery result）
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from app.config import settings
from app.logging import get_logger
from app.schemas.collaboration import FeedbackRecord

log = get_logger(__name__)


def _feedback_dir() -> Path:
    """获取反馈存储根目录。"""
    root = Path(settings.UPLOAD_DIR).resolve() / "feedback"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _feedback_path(review_task_id: str, defect_index: int) -> Path:
    """单条反馈的文件路径。"""
    return _feedback_dir() / f"{review_task_id}_{defect_index}.json"


def save_feedback(record: FeedbackRecord) -> Path:
    """保存用户反馈到文件系统。

    Args:
        record: 反馈记录

    Returns:
        保存的文件路径
    """
    if not record.created_at:
        record.created_at = _dt.datetime.now().isoformat()

    path = _feedback_path(record.review_task_id, record.defect_index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        record.model_dump_json(indent=2),
        encoding="utf-8",
    )
    log.info(
        "collaboration.feedback.saved",
        path=str(path),
        review_task_id=record.review_task_id,
        defect_index=record.defect_index,
        action=record.action,
    )
    return path


def load_feedback(
    review_task_id: str,
    defect_index: int | None = None,
) -> list[FeedbackRecord]:
    """加载用户反馈。

    Args:
        review_task_id: 审图任务 ID
        defect_index: 缺陷索引（None 表示加载该任务所有反馈）

    Returns:
        反馈记录列表（按 defect_index 升序）
    """
    records: list[FeedbackRecord] = []
    if defect_index is not None:
        path = _feedback_path(review_task_id, defect_index)
        if path.is_file():
            try:
                records.append(FeedbackRecord(**json.loads(path.read_text(encoding="utf-8"))))
            except Exception as e:  # noqa: BLE001
                log.warning("collaboration.feedback.load_failed", path=str(path), error=str(e))
        return records

    # 加载该任务所有反馈
    pattern = f"{review_task_id}_*.json"
    for path in sorted(_feedback_dir().glob(pattern)):
        try:
            records.append(FeedbackRecord(**json.loads(path.read_text(encoding="utf-8"))))
        except Exception as e:  # noqa: BLE001
            log.warning("collaboration.feedback.load_failed", path=str(path), error=str(e))
    return records


def list_feedback_by_action(action: str) -> list[FeedbackRecord]:
    """按动作类型列出所有反馈（用于 LLM 检索 few-shot 示例）。

    Args:
        action: accept / reject_as_false_positive / modify_suggestion

    Returns:
        反馈记录列表
    """
    records: list[FeedbackRecord] = []
    for path in sorted(_feedback_dir().glob("*.json")):
        try:
            rec = FeedbackRecord(**json.loads(path.read_text(encoding="utf-8")))
            if rec.action == action:
                records.append(rec)
        except Exception as e:  # noqa: BLE001
            log.warning("collaboration.feedback.load_failed", path=str(path), error=str(e))
    return records


def feedback_stats() -> dict[str, int]:
    """反馈统计（用于仪表盘）。"""
    stats = {
        "total": 0,
        "accept": 0,
        "reject_as_false_positive": 0,
        "modify_suggestion": 0,
    }
    for path in _feedback_dir().glob("*.json"):
        try:
            rec = FeedbackRecord(**json.loads(path.read_text(encoding="utf-8")))
            stats["total"] += 1
            if rec.action in stats:
                stats[rec.action] += 1
        except Exception:  # noqa: BLE001
            pass
    return stats
