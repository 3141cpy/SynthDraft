"""协同闭环服务模块（Task 11）。

实现"审图→生成→复审"协同闭环：
- defect_to_prompt：缺陷列表 → LLM prompt（SubTask 11.1）
- diff_report：修订前后缺陷对比报告（SubTask 11.3）
- feedback_store：用户反馈存储（SubTask 11.4）

SubTask 11.2（修订后自动复审）在 app/celery/tasks/collaboration.py 中实现。
"""

from app.services.collaboration.defect_to_prompt import (
    defects_to_optimization_prompt,
    extract_file_hint_from_review_result,
)
from app.services.collaboration.diff_report import generate_diff_report
from app.services.collaboration.feedback_store import (
    save_feedback,
    load_feedback,
    list_feedback_by_action,
    feedback_stats,
)

__all__ = [
    "defects_to_optimization_prompt",
    "extract_file_hint_from_review_result",
    "generate_diff_report",
    "save_feedback",
    "load_feedback",
    "list_feedback_by_action",
    "feedback_stats",
]
