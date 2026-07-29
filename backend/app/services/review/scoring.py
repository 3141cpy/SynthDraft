"""合规性评分算法（SubTask 4.6）。

基础分 100，按缺陷严重等级扣分：
- critical：扣 15/条
- major：扣 8/条
- minor：扣 3/条
- warning：扣 1/条

最低 0 分（不允许负分）。
"""

from __future__ import annotations

from app.schemas.review_detail import DefectItem

# 严重等级 → 扣分
_SEVERITY_PENALTY: dict[str, int] = {
    "critical": 15,
    "major": 8,
    "minor": 3,
    "warning": 1,
}

_BASE_SCORE = 100.0
_MIN_SCORE = 0.0


def compute_compliance_score(defects: list[DefectItem]) -> float:
    """计算合规性评分。

    Args:
        defects: 缺陷列表

    Returns:
        0-100 浮点数（向下取整到 0，不四舍五入小数）
    """
    total_penalty = 0
    for d in defects:
        penalty = _SEVERITY_PENALTY.get(d.severity, 0)
        total_penalty += penalty

    score = _BASE_SCORE - total_penalty
    if score < _MIN_SCORE:
        score = _MIN_SCORE
    return float(score)


def severity_counts(defects: list[DefectItem]) -> dict[str, int]:
    """按严重等级统计缺陷数。"""
    counts: dict[str, int] = {"critical": 0, "major": 0, "minor": 0, "warning": 0}
    for d in defects:
        if d.severity in counts:
            counts[d.severity] += 1
    return counts
