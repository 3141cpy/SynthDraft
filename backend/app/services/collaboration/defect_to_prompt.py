"""缺陷列表 → LLM prompt 转换（SubTask 11.1）。

将审图缺陷列表 + 原图元信息转换为生成模块可消费的 LLM prompt，
让生成模块基于缺陷生成修订版 CadQuery 代码。

设计原则：
- 不重复造轮子：复用 generation.code_generator.generate_cadquery_code
- 缺陷信息结构化注入：按 category 分组，突出 critical/major
- prompt 长度可控：单条缺陷摘要 < 200 字符，总长度 < 4000 字符
- 优雅降级：缺陷列表为空时返回通用优化 prompt
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.logging import get_logger
from app.schemas.review_detail import DefectItem

log = get_logger(__name__)

# 单条缺陷摘要的最大长度（避免 prompt 过长）
_DEFECT_SUMMARY_MAX_LEN = 200
# 最多注入的缺陷数量（按 severity 优先级截断）
_MAX_DEFECTS_IN_PROMPT = 15

# 严重等级优先级（数字越小越优先）
_SEVERITY_PRIORITY = {
    "critical": 0,
    "major": 1,
    "minor": 2,
    "warning": 3,
}

# 缺陷类别中文映射
_CATEGORY_CN = {
    "title_block": "标题栏",
    "layer_naming": "图层命名",
    "dimensioning": "尺寸标注",
    "tolerance": "形位公差",
    "surface_roughness": "表面粗糙度",
    "line_type": "线型",
    "view_layout": "视图布局",
    "text_annotation": "文字标注",
    "other": "其他",
}


def _summarize_defect(defect: DefectItem) -> str:
    """将单条缺陷转为简洁文本摘要。"""
    cat_cn = _CATEGORY_CN.get(defect.category, defect.category)
    sev_cn = {"critical": "严重", "major": "重要", "minor": "一般", "warning": "提示"}.get(
        defect.severity, defect.severity
    )
    coord_str = ""
    if defect.coordinate:
        x = defect.coordinate.get("x", 0)
        y = defect.coordinate.get("y", 0)
        coord_str = f"（位置 x={x:.1f}, y={y:.1f}）"

    suggestion = defect.suggestion
    if len(suggestion) > _DEFECT_SUMMARY_MAX_LEN:
        suggestion = suggestion[: _DEFECT_SUMMARY_MAX_LEN - 3] + "..."

    return (
        f"[{sev_cn}][{cat_cn}] {defect.evidence}{coord_str}；"
        f"规范：{defect.standard_ref}；建议：{suggestion}"
    )


def defects_to_optimization_prompt(
    defects: list[DefectItem],
    original_file_hint: str = "",
) -> str:
    """将审图缺陷列表转换为生成模块的 LLM prompt。

    Args:
        defects: 审图输出的缺陷列表
        original_file_hint: 原文件提示信息（如 "原文件: bolt.dxf"）

    Returns:
        优化 prompt 字符串，可直接传给 generate_cadquery_code()
    """
    if not defects:
        return (
            "生成一个符合 GB/T 18229-2023 CAD 工程制图通用规范的零件图，"
            "包含完整的标题栏、尺寸标注、图层规范。"
        )

    # 按 severity 优先级排序，截断到 _MAX_DEFECTS_IN_PROMPT
    sorted_defects = sorted(
        defects,
        key=lambda d: _SEVERITY_PRIORITY.get(d.severity, 99),
    )
    truncated = sorted_defects[:_MAX_DEFECTS_IN_PROMPT]

    # 按 category 分组
    by_category: dict[str, list[DefectItem]] = defaultdict(list)
    for d in truncated:
        by_category[d.category].append(d)

    # 统计
    severity_counts = defaultdict(int)
    for d in truncated:
        severity_counts[d.severity] += 1

    severity_summary = "、".join(
        f"{sev}: {cnt} 条"
        for sev, cnt in sorted(severity_counts.items(), key=lambda x: _SEVERITY_PRIORITY.get(x[0], 99))
    )

    # 构造 prompt
    lines: list[str] = []
    lines.append(
        "你是 CAD 工程制图专家。根据以下审图缺陷列表，生成修订版 CadQuery 代码，"
        "输出符合国标规范的 DXF 工程图。"
    )
    if original_file_hint:
        lines.append(f"原文件：{original_file_hint}")
    lines.append(f"审图发现 {len(truncated)} 条缺陷（{severity_summary}）：")
    lines.append("")

    for cat, items in by_category.items():
        cat_cn = _CATEGORY_CN.get(cat, cat)
        lines.append(f"## {cat_cn}（{len(items)} 条）")
        for i, d in enumerate(items, 1):
            lines.append(f"{i}. {_summarize_defect(d)}")
        lines.append("")

    lines.append("## 修订要求")
    lines.append("1. 必须修复上述所有 critical 和 major 缺陷")
    lines.append("2. 输出 DXF 格式，包含完整的标题栏/图层/尺寸标注")
    lines.append("3. 使用 GB/T 18229-2023 规范的图层命名（粗实线/细实线/中心线/剖面线等）")
    lines.append("4. 尺寸标注使用 GB/T 4458.4 规范")
    lines.append("5. 仅输出 CadQuery Python 代码（含 import cadquery as cq），不要其他文字")

    prompt = "\n".join(lines)
    log.info(
        "collaboration.prompt.generated",
        defects_count=len(defects),
        truncated_count=len(truncated),
        prompt_len=len(prompt),
    )
    return prompt


def extract_file_hint_from_review_result(
    review_result_dict: dict[str, Any],
) -> str:
    """从 ReviewResult dict 中提取文件提示信息。"""
    file_key = review_result_dict.get("file_key", "")
    if not file_key:
        return ""
    # 取 basename
    from pathlib import Path

    try:
        return f"原文件: {Path(file_key).name}"
    except Exception:  # noqa: BLE001
        return f"原文件: {file_key}"
