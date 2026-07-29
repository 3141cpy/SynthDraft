"""用户反馈分析（SubTask 16.3）。

基于 ``feedback_store`` 持久化的反馈记录计算统计指标：
- 总反馈数 / 误报率 / 采纳率 / 修改建议率
- 按缺陷类别分组统计
- 按时间趋势统计（日 / 周 / 月）
- 常见缺陷 Top-N

遵循"以复用现有为荣"原则：直接读 ``feedback_store.load_all_feedback()``，
不重复实现持久化。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Literal

from app.services.review.feedback_store import FeedbackRecord, load_all_feedback

TrendGranularity = Literal["day", "week", "month"]


def _to_dt(ts: str) -> datetime | None:
    """ISO 时间戳转 datetime（兼容带/不带时区）。"""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt
    except Exception:  # noqa: BLE001
        return None


def _trend_key(dt: datetime, granularity: TrendGranularity) -> str:
    if granularity == "day":
        return dt.strftime("%Y-%m-%d")
    if granularity == "month":
        return dt.strftime("%Y-%m")
    # week：ISO 周一作为周起始
    iso_year, iso_week, _ = dt.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def compute_summary(records: list[FeedbackRecord] | None = None) -> dict[str, Any]:
    """计算总体统计指标。

    Args:
        records: 已加载的反馈记录；None 时从存储加载。

    Returns:
        dict 含 total / accept_count / reject_count / modify_count /
        accept_rate / false_positive_rate / modify_rate
    """
    if records is None:
        records = load_all_feedback()
    total = len(records)
    if total == 0:
        return {
            "total": 0,
            "accept_count": 0,
            "reject_as_false_positive_count": 0,
            "modify_suggestion_count": 0,
            "accept_rate": 0.0,
            "false_positive_rate": 0.0,
            "modify_rate": 0.0,
        }
    accept = sum(1 for r in records if r.action == "accept")
    reject = sum(1 for r in records if r.action == "reject_as_false_positive")
    modify = sum(1 for r in records if r.action == "modify_suggestion")
    return {
        "total": total,
        "accept_count": accept,
        "reject_as_false_positive_count": reject,
        "modify_suggestion_count": modify,
        "accept_rate": round(accept * 100.0 / total, 2),
        "false_positive_rate": round(reject * 100.0 / total, 2),
        "modify_rate": round(modify * 100.0 / total, 2),
    }


def compute_by_category(records: list[FeedbackRecord] | None = None) -> dict[str, Any]:
    """按缺陷类别分组统计。

    Returns:
        dict 含 categories 列表，每项含 category / total / 各 action 计数与占比。
    """
    if records is None:
        records = load_all_feedback()
    grouped: dict[str, list[FeedbackRecord]] = defaultdict(list)
    for r in records:
        cat = r.category or "unknown"
        grouped[cat].append(r)

    categories: list[dict[str, Any]] = []
    for cat, recs in sorted(grouped.items()):
        n = len(recs)
        accept = sum(1 for r in recs if r.action == "accept")
        reject = sum(1 for r in recs if r.action == "reject_as_false_positive")
        modify = sum(1 for r in recs if r.action == "modify_suggestion")
        categories.append(
            {
                "category": cat,
                "total": n,
                "accept_count": accept,
                "reject_as_false_positive_count": reject,
                "modify_suggestion_count": modify,
                "false_positive_rate": round(reject * 100.0 / n, 2) if n else 0.0,
                "accept_rate": round(accept * 100.0 / n, 2) if n else 0.0,
            }
        )
    return {"categories": categories, "category_count": len(categories)}


def compute_trend(
    granularity: TrendGranularity = "day",
    records: list[FeedbackRecord] | None = None,
) -> dict[str, Any]:
    """按时间趋势统计。

    Args:
        granularity: "day" / "week" / "month"
        records: 已加载记录；None 时从存储加载。

    Returns:
        dict 含 trend 列表，每项含 bucket / total / 各 action 计数。
    """
    if records is None:
        records = load_all_feedback()
    buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total": 0,
            "accept": 0,
            "reject_as_false_positive": 0,
            "modify_suggestion": 0,
        }
    )
    skipped = 0
    for r in records:
        dt = _to_dt(r.timestamp)
        if dt is None:
            skipped += 1
            continue
        # 统一转 UTC 比较
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        key = _trend_key(dt, granularity)
        b = buckets[key]
        b["total"] += 1
        b[r.action] += 1

    trend = [
        {"bucket": k, **buckets[k]} for k in sorted(buckets.keys())
    ]
    return {
        "granularity": granularity,
        "bucket_count": len(trend),
        "skipped_records": skipped,
        "trend": trend,
    }


def compute_top_defects(
    top_n: int = 10,
    records: list[FeedbackRecord] | None = None,
) -> dict[str, Any]:
    """常见缺陷 Top-N（按 defect_id 出现次数）。

    Returns:
        dict 含 top_defects 列表，每项含 defect_id / count / 主类别。
    """
    if records is None:
        records = load_all_feedback()
    counter: Counter[str] = Counter()
    cat_map: dict[str, Counter[str]] = defaultdict(Counter)
    for r in records:
        counter[r.defect_id] += 1
        cat_map[r.defect_id][r.category or "unknown"] += 1

    top = []
    for defect_id, count in counter.most_common(top_n):
        cat = cat_map[defect_id].most_common(1)[0][0]
        top.append({"defect_id": defect_id, "count": count, "primary_category": cat})
    return {"top_n": top_n, "top_defects": top}


def self_test() -> dict[str, Any]:
    """self_test：用内存样本数据验证四个统计函数。"""
    from app.services.review.feedback_store import FeedbackRecord

    # 构造 5 条样本：2 accept / 2 reject / 1 modify，跨 2 个类别与 2 天
    base = "2026-07-2"
    records = [
        FeedbackRecord(
            task_id="t1",
            defect_id="d1",
            category="dimension",
            severity="major",
            action="accept",
            timestamp=f"{base}5T10:00:00+00:00",
        ),
        FeedbackRecord(
            task_id="t1",
            defect_id="d2",
            category="annotation",
            severity="minor",
            action="reject_as_false_positive",
            timestamp=f"{base}5T11:00:00+00:00",
        ),
        FeedbackRecord(
            task_id="t2",
            defect_id="d3",
            category="dimension",
            severity="critical",
            action="modify_suggestion",
            timestamp=f"{base}6T09:00:00+00:00",
        ),
        FeedbackRecord(
            task_id="t2",
            defect_id="d1",
            category="dimension",
            severity="major",
            action="accept",
            timestamp=f"{base}6T10:00:00+00:00",
        ),
        FeedbackRecord(
            task_id="t3",
            defect_id="d4",
            category="tolerance",
            severity="major",
            action="reject_as_false_positive",
            timestamp=f"{base}6T12:00:00+00:00",
        ),
    ]

    summary = compute_summary(records)
    by_cat = compute_by_category(records)
    trend_day = compute_trend("day", records)
    top = compute_top_defects(5, records)

    return {
        "summary": summary,
        "by_category": by_cat,
        "trend_day": trend_day,
        "top_defects": top,
        "ok": (
            summary["total"] == 5
            and summary["accept_count"] == 2
            and summary["false_positive_rate"] == 40.0
            and by_cat["category_count"] == 3
            and trend_day["bucket_count"] == 2
            and top["top_defects"][0]["defect_id"] == "d1"
            and top["top_defects"][0]["count"] == 2
        ),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(self_test(), indent=2, ensure_ascii=False, default=str))
