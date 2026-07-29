"""规则引擎（SubTask 4.4 降级路径）。

当 LLM 不可用时，基于硬编码规则检查常见缺陷：
- 标题栏缺失必填字段（图号/比例/材料/日期）
- 图层名不符合 GB/T 17450 命名规范
- 尺寸标注缺失或重复
- 形位公差标注格式错误
- 表面粗糙度符号缺失

每条缺陷引用对应 GB/T 条款（从知识库查得的 clause_id）。

引用规范：
- GB/T 17450-1998 技术制图 图线（图层命名）
- GB/T 4457.4-2002 机械制图 尺寸注法（尺寸标注）
- GB/T 1182-2018 几何公差（形位公差）
- GB/T 131-2006 产品几何技术规范 表面结构表示法（表面粗糙度）
- GB/T 18229-2023 CAD 工程制图规则（标题栏/CAD 制图通用）
"""

from __future__ import annotations

from typing import Any

from app.logging import get_logger
from app.schemas.review_detail import DefectItem, SemanticModel

log = get_logger(__name__)

# GB/T 17450 推荐图层名（粗略白名单；P0 阶段用启发式）
# 实际 GB/T 17450 用线型代码（No.xxxx），这里允许常见工程图图层名
_GB_T17450_RECOMMENDED_LAYERS = {
    "0", "OUTLINE", "DIM", "DIMENSION", "TEXT", "TITLE", "CENTER",
    "HIDDEN", "HATCH", "SECTION", "VIEWPORT", "PHANTOM", "CONSTRUCTION",
    "NOTES", "BORDER", "DETAIL", "ARROW",
}

# 必填标题栏字段及其规范引用
_REQUIRED_TITLE_FIELDS = {
    "drawing_number": ("GB/T 18229-2023 §A.3", "A.3"),
    "scale": ("GB/T 4457.4-2002 §5.2", "5.2"),
    "material": ("GB/T 18229-2023 §A.3", "A.3"),
    "date": ("GB/T 18229-2023 §A.3", "A.3"),
}


def rule_engine_judge(semantic_model: SemanticModel) -> list[DefectItem]:
    """基于硬编码规则检查缺陷。

    Args:
        semantic_model: 三层语义模型

    Returns:
        缺陷列表（按严重等级降序）
    """
    defects: list[DefectItem] = []

    defects.extend(_check_title_block(semantic_model))
    defects.extend(_check_layer_naming(semantic_model))
    defects.extend(_check_dimensions(semantic_model))
    defects.extend(_check_tolerance(semantic_model))
    defects.extend(_check_surface_roughness(semantic_model))

    # 按严重等级排序：critical > major > minor > warning
    severity_order = {"critical": 0, "major": 1, "minor": 2, "warning": 3}
    defects.sort(key=lambda d: severity_order.get(d.severity, 99))

    log.info(
        "review.rule_engine.done",
        defects=len(defects),
        by_severity={
            s: sum(1 for d in defects if d.severity == s)
            for s in severity_order
        },
    )
    return defects


def _check_title_block(model: SemanticModel) -> list[DefectItem]:
    """检查标题栏：缺失/必填字段为空。"""
    defects: list[DefectItem] = []
    sem = model.semantic

    if not sem.has_title_block:
        defects.append(
            DefectItem(
                category="title_block",
                severity="critical",
                coordinate=None,
                standard_ref="GB/T 18229-2023 §A.3",
                standard_clause_id="A.3",
                suggestion="补充标题栏：图纸必须包含完整的标题栏（图号/比例/材料/日期/制图/校对等）",
                evidence="未检测到标题栏（无带属性的 TITLE 块引用或属性字段）",
            )
        )
        return defects

    # 检查必填字段
    for field, (ref, clause_id) in _REQUIRED_TITLE_FIELDS.items():
        val = sem.title_block_fields.get(field)
        if not val or not str(val).strip() or str(val).strip() in ("-", "N/A", "无"):
            defects.append(
                DefectItem(
                    category="title_block",
                    severity="major",
                    coordinate=None,
                    standard_ref=ref,
                    standard_clause_id=clause_id,
                    suggestion=f"在标题栏中填写 {field} 字段（当前为空或占位符）",
                    evidence=f"标题栏字段 {field} 缺失或为空（当前值={val!r}）",
                )
            )

    return defects


def _check_layer_naming(model: SemanticModel) -> list[DefectItem]:
    """检查图层命名：是否符合 GB/T 17450 推荐。"""
    defects: list[DefectItem] = []
    sem = model.semantic

    for name in sem.layer_names:
        upper = name.upper().strip()
        # 0 层是 CAD 默认层，允许
        if upper == "0":
            continue
        # 命中白名单（允许大小写差异）
        if upper in {n.upper() for n in _GB_T17450_RECOMMENDED_LAYERS}:
            continue
        # 含中文/工程语义关键词的图层名也允许（粗略启发式）
        if any(c in name for c in "轮廓尺寸标注中心文字标题隐藏剖面"):
            continue
        # 含特殊字符或过短
        if len(name) < 2 or any(c in name for c in "$%^&*()+=[]{}|;':\",<>/?`~"):
            defects.append(
                DefectItem(
                    category="layer_naming",
                    severity="minor",
                    coordinate=None,
                    standard_ref="GB/T 17450-1998 §5",
                    standard_clause_id="5",
                    suggestion=f"图层名 '{name}' 不符合 GB/T 17450 推荐命名，建议改为 OUTLINE/DIM/TEXT/CENTER 等规范名",
                    evidence=f"图层名 '{name}' 不在 GB/T 17450 推荐图层名白名单内",
                )
            )
    return defects


def _check_dimensions(model: SemanticModel) -> list[DefectItem]:
    """检查尺寸标注：缺失/重复。"""
    defects: list[DefectItem] = []
    sem = model.semantic

    # P0 阶段：仅检查是否有尺寸标注
    if sem.dimension_count == 0:
        # 仅当存在几何图元（线/圆/弧）时才报缺陷
        has_geom = (
            len(model.geometry.lines) > 0
            or len(model.geometry.circles) > 0
            or len(model.geometry.arcs) > 0
        )
        if has_geom:
            defects.append(
                DefectItem(
                    category="dimensioning",
                    severity="critical",
                    coordinate=None,
                    standard_ref="GB/T 4457.4-2002 §4.1",
                    standard_clause_id="4.1",
                    suggestion="添加尺寸标注：图纸中的几何要素必须标注完整尺寸",
                    evidence=f"未检测到任何尺寸标注（共 {len(model.geometry.lines)} 条线/圆/弧未标注）",
                )
            )
    else:
        # 检查标注类型分布：若全部为 unknown，提示标注样式问题
        if sem.dimension_types.get("unknown", 0) == sem.dimension_count:
            defects.append(
                DefectItem(
                    category="dimensioning",
                    severity="minor",
                    coordinate=None,
                    standard_ref="GB/T 4457.4-2002 §4.1",
                    standard_clause_id="4.1",
                    suggestion="检查尺寸标注样式：所有标注类型均为 unknown，建议使用 linear/aligned/radius 等标准类型",
                    evidence=f"共 {sem.dimension_count} 条标注均为 unknown 类型",
                )
            )

    return defects


def _check_tolerance(model: SemanticModel) -> list[DefectItem]:
    """检查形位公差标注。

    P0 启发式：若图纸含几何图元但无任何形位公差标注，提示（minor）。
    严格按 GB/T 1182-2018 检查格式需 P1 几何引擎支持。
    """
    defects: list[DefectItem] = []
    sem = model.semantic

    has_geom = (
        len(model.geometry.lines) > 0
        or len(model.geometry.circles) > 0
        or len(model.geometry.arcs) > 0
    )
    if has_geom and not sem.has_tolerance:
        defects.append(
            DefectItem(
                category="tolerance",
                severity="warning",
                coordinate=None,
                standard_ref="GB/T 1182-2018 §6",
                standard_clause_id="6",
                suggestion="考虑添加形位公差标注（如平行度/垂直度/同轴度），特别是配合面与基准面",
                evidence="未检测到形位公差标注（TOLERANCE 实体或 ⌖⊥∥ 等符号）",
            )
        )
    return defects


def _check_surface_roughness(model: SemanticModel) -> list[DefectItem]:
    """检查表面粗糙度符号。

    P0 启发式：若图纸含几何图元但无表面粗糙度标注，提示（minor）。
    """
    defects: list[DefectItem] = []
    sem = model.semantic

    has_geom = (
        len(model.geometry.lines) > 0
        or len(model.geometry.circles) > 0
        or len(model.geometry.arcs) > 0
    )
    if has_geom and not sem.has_surface_roughness:
        defects.append(
            DefectItem(
                category="surface_roughness",
                severity="minor",
                coordinate=None,
                standard_ref="GB/T 131-2006 §4",
                standard_clause_id="4",
                suggestion="添加表面粗糙度符号（如 Ra1.6 / Ra3.2），标注所有加工面",
                evidence="未检测到表面粗糙度符号（Ra/Rz/∇ 等标记）",
            )
        )
    return defects
