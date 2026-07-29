"""修订前后缺陷对比报告（SubTask 11.3）。

对比两次审图的缺陷列表，生成闭环状态：
- resolved：原缺陷在修订后已修复
- unresolved：原缺陷在修订后仍存在
- new：修订后新增的缺陷

匹配策略（基于八荣八耻 §"以瞎猜接口为耻"，先实测再实现）：
1. 严格匹配：category + standard_ref 完全相同
2. 模糊匹配：suggestion 关键词重合度 ≥ 0.6
3. 未匹配的原缺陷 → unresolved
4. 未匹配的新缺陷 → new
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from app.logging import get_logger
from app.schemas.collaboration import DefectDiffItem, DiffReport
from app.schemas.review_detail import DefectItem

log = get_logger(__name__)

# 模糊匹配的关键词重合度阈值
_FUZZY_MATCH_THRESHOLD = 0.6


def _tokenize(text: str) -> set[str]:
    """简单分词：按空格/标点切分，过滤单字。"""
    import re

    tokens = set(re.split(r"[\s,，。；;:：()（）/\\\-]+", text.lower()))
    tokens.discard("")
    # 过滤单字（无语义价值）
    return {t for t in tokens if len(t) >= 2}


def _similarity(defect_a: DefectItem, defect_b: DefectItem) -> float:
    """计算两条缺陷的相似度（0-1）。

    匹配维度：
    - category 完全相同：+0.4
    - standard_ref 完全相同：+0.3
    - suggestion 关键词重合度：×0.3
    """
    score = 0.0
    if defect_a.category == defect_b.category:
        score += 0.4
    if defect_a.standard_ref and defect_a.standard_ref == defect_b.standard_ref:
        score += 0.3
    if defect_a.suggestion and defect_b.suggestion:
        tokens_a = _tokenize(defect_a.suggestion)
        tokens_b = _tokenize(defect_b.suggestion)
        if tokens_a and tokens_b:
            intersection = tokens_a & tokens_b
            union = tokens_a | tokens_b
            jaccard = len(intersection) / len(union) if union else 0.0
            score += jaccard * 0.3
    return min(score, 1.0)


def _find_best_match(
    defect: DefectItem,
    candidates: list[tuple[int, DefectItem]],
    used_indices: set[int],
) -> tuple[int | None, float]:
    """在候选缺陷中找到最佳匹配（未被使用过的）。"""
    best_idx: int | None = None
    best_score = 0.0
    for idx, cand in candidates:
        if idx in used_indices:
            continue
        score = _similarity(defect, cand)
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx, best_score


def generate_diff_report(
    old_review_task_id: str,
    new_review_task_id: str,
    old_defects: list[DefectItem],
    new_defects: list[DefectItem],
    old_score: float | None = None,
    new_score: float | None = None,
    generation_task_id: str | None = None,
) -> DiffReport:
    """生成修订前后的缺陷对比报告。

    Args:
        old_review_task_id: 原审图任务 ID
        new_review_task_id: 修订后审图任务 ID
        old_defects: 原审图缺陷列表
        new_defects: 修订后审图缺陷列表
        old_score: 原合规性评分
        new_score: 修订后合规性评分
        generation_task_id: 关联的生成任务 ID

    Returns:
        DiffReport 对象
    """
    old_indexed = list(enumerate(old_defects))
    used_old_indices: set[int] = set()
    diffs: list[DefectDiffItem] = []

    # ===== 阶段 1：新缺陷匹配原缺陷（resolved） =====
    for new_defect in new_defects:
        match_idx, score = _find_best_match(
            new_defect, old_indexed, used_old_indices
        )
        if match_idx is not None and score >= _FUZZY_MATCH_THRESHOLD:
            # 匹配成功：原缺陷在修订后仍存在（unresolved）
            # 注意：新缺陷匹配到原缺陷，说明该缺陷未被修复
            used_old_indices.add(match_idx)
            diffs.append(
                DefectDiffItem(
                    diff_status="unresolved",
                    defect=new_defect,
                    matched_defect_index=match_idx,
                    similarity_score=score,
                )
            )
        else:
            # 未匹配：新增缺陷
            diffs.append(
                DefectDiffItem(
                    diff_status="new",
                    defect=new_defect,
                    matched_defect_index=None,
                    similarity_score=score if match_idx is not None else None,
                )
            )

    # ===== 阶段 2：未被匹配的原缺陷 → resolved =====
    for idx, old_defect in old_indexed:
        if idx not in used_old_indices:
            diffs.append(
                DefectDiffItem(
                    diff_status="resolved",
                    defect=old_defect,
                    matched_defect_index=idx,
                    similarity_score=None,
                )
            )

    # 统计
    resolved_count = sum(1 for d in diffs if d.diff_status == "resolved")
    unresolved_count = sum(1 for d in diffs if d.diff_status == "unresolved")
    new_count = sum(1 for d in diffs if d.diff_status == "new")

    closure_rate = (
        resolved_count / len(old_defects) if old_defects else 1.0
    )

    score_improvement = None
    if old_score is not None and new_score is not None:
        score_improvement = new_score - old_score

    report = DiffReport(
        original_review_task_id=old_review_task_id,
        new_review_task_id=new_review_task_id,
        generation_task_id=generation_task_id,
        old_defects_count=len(old_defects),
        new_defects_count=len(new_defects),
        resolved_count=resolved_count,
        unresolved_count=unresolved_count,
        new_count=new_count,
        old_compliance_score=old_score,
        new_compliance_score=new_score,
        score_improvement=score_improvement,
        diffs=diffs,
        closure_rate=closure_rate,
        generated_at=_dt.datetime.now().isoformat(),
    )

    log.info(
        "collaboration.diff_report.generated",
        old_task=old_review_task_id,
        new_task=new_review_task_id,
        old_count=len(old_defects),
        new_count=len(new_defects),
        resolved=resolved_count,
        unresolved=unresolved_count,
        new=new_count,
        closure_rate=f"{closure_rate*100:.1f}%",
    )
    return report
