"""模板匹配降级生成（SubTask 5.2 降级路径）。

当 Ollama ``qwen2.5-coder:7b`` 不可用时，基于关键词匹配选择预定义模板，
并通过正则从用户 prompt 中提取参数填充模板。

支持的零件族：
- flange  法兰盘（外径/内径/孔数/孔径/分度圆/厚度）
- shaft   阶梯轴（左段直径/长度 + 右段直径/长度）
- plate   矩形板（长/宽/厚/孔径/边距）
- holed_plate  孔板（plate 别名）

设计原则：
- 参数提取容错：解析失败时回退到该模板的安全默认值
- 输出代码风格与 prompts.py 少样本对齐，便于沙箱统一执行
"""

from __future__ import annotations

import re

__all__ = ["TEMPLATE_KEYWORDS", "template_match_generate"]


# ===== 模板定义 =====
# 每个模板含：关键词列表（用于匹配）、代码模板（含 {占位符}）

_FLANGE_TEMPLATE = """\
import cadquery as cq

# 法兰盘参数（模板匹配生成）
outer_diameter = {outer_diameter}        # 外径 mm
inner_diameter = {inner_diameter}        # 内径 mm
hole_diameter = {hole_diameter}          # 均布孔直径 mm
hole_count = {hole_count}                # 均布孔数量
bolt_circle_diameter = {bolt_circle_diameter}  # 孔分度圆直径 mm
thickness = {thickness}                  # 厚度 mm

# 1. 创建底盘圆环并拉伸
result = (
    cq.Workplane("XY")
    .circle(outer_diameter / 2)
    .circle(inner_diameter / 2)
    .extrude(thickness)
)

# 2. 在分度圆上极坐标阵列均布孔
result = (
    result.faces(">Z")
    .workplane()
    .polarArray(bolt_circle_diameter / 2, 0, 360, hole_count)
    .hole(hole_diameter)
)
"""

_SHAFT_TEMPLATE = """\
import cadquery as cq

# 阶梯轴参数（模板匹配生成）
seg1_diameter = {seg1_diameter}  # 左段直径 mm
seg1_length = {seg1_length}      # 左段长度 mm
seg2_diameter = {seg2_diameter}  # 右段直径 mm
seg2_length = {seg2_length}      # 右段长度 mm

# 1. 创建左段
result = (
    cq.Workplane("XY")
    .circle(seg1_diameter / 2)
    .extrude(seg1_length)
)

# 2. 在端面叠加右段
result = (
    result.faces(">Z")
    .workplane()
    .circle(seg2_diameter / 2)
    .extrude(seg2_length)
)
"""

_PLATE_TEMPLATE = """\
import cadquery as cq

# 矩形板参数（模板匹配生成）
length = {length}     # 长 mm
width = {width}       # 宽 mm
thickness = {thickness}  # 厚 mm
hole_diameter = {hole_diameter}     # 安装孔直径 mm
edge_offset = {edge_offset}         # 孔距边缘距离 mm

# 1. 创建矩形板
result = (
    cq.Workplane("XY")
    .box(length, width, thickness)
)

# 2. 在顶面四角打孔
result = (
    result.faces(">Z")
    .workplane()
    .rarray(length - 2 * edge_offset, width - 2 * edge_offset, 2, 2)
    .hole(hole_diameter)
)
"""

_CUBE_TEMPLATE = """\
import cadquery as cq

# 立方体参数（模板匹配生成）
size = {size}  # 边长 mm

# 创建立方体
result = cq.Workplane("XY").box(size, size, size)
"""


# 关键词 → 模板映射（顺序敏感：第一个匹配的胜出）
TEMPLATE_KEYWORDS: list[tuple[list[str], str]] = [
    (["法兰", "flange"], "flange"),
    (["轴", "shaft", "阶梯轴"], "shaft"),
    (["孔板", "holed", "孔的板"], "plate"),
    (["板", "plate", "矩形板"], "plate"),
    (["立方体", "cube", "正方体", "块"], "cube"),
]


# ===== 参数提取工具 =====


def _find_number_after(prompt: str, keywords: list[str]) -> float | None:
    """在 prompt 中查找关键词后紧跟的数字（支持 '外径100' / '外径 100' / '外径为100mm'）。"""
    for kw in keywords:
        # 关键词后允许空格/"为"/":"/"="，然后是数字（含小数）
        pattern = rf"{re.escape(kw)}\s*[为是:=]?\s*(\d+(?:\.\d+)?)"
        m = re.search(pattern, prompt)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def _find_int_after(prompt: str, keywords: list[str]) -> int | None:
    """查找关键词后紧跟的整数。"""
    for kw in keywords:
        pattern = rf"{re.escape(kw)}\s*[为是:=]?\s*(\d+)"
        m = re.search(pattern, prompt)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


# ===== 各模板参数提取 =====


def _extract_flange_params(prompt: str) -> dict[str, float | int]:
    p = prompt.lower() if isinstance(prompt, str) else ""
    # 中英文混合查找
    outer = _find_number_after(p, ["外径", "外直径", "outer diameter", "outer_diameter"])
    inner = _find_number_after(p, ["内径", "内直径", "inner diameter", "inner_diameter"])
    hole_d = _find_number_after(p, ["孔径", "孔直径", "hole diameter", "hole_diameter"])
    hole_n = _find_int_after(p, ["孔数", "均布孔", "个孔", "holes", "hole count"])
    bcd = _find_number_after(
        p, ["分度圆", "节圆", "bolt circle", "bolt_circle", "pcd"]
    )
    thickness = _find_number_after(p, ["厚度", "厚", "thickness", "高", "高度"])

    # 安全默认值（保证几何可生成）
    return {
        "outer_diameter": outer if outer and outer > 0 else 100.0,
        "inner_diameter": inner if inner and inner > 0 else 50.0,
        "hole_diameter": hole_d if hole_d and hole_d > 0 else 10.0,
        "hole_count": hole_n if hole_n and hole_n > 0 else 6,
        "bolt_circle_diameter": bcd if bcd and bcd > 0 else 80.0,
        "thickness": thickness if thickness and thickness > 0 else 10.0,
    }


def _extract_shaft_params(prompt: str) -> dict[str, float]:
    p = prompt.lower() if isinstance(prompt, str) else ""
    d1 = _find_number_after(p, ["左段直径", "左段", "小径", "seg1", "seg1_diameter"])
    l1 = _find_number_after(p, ["左段长", "左段长度", "seg1_length", "左段长"])
    d2 = _find_number_after(p, ["右段直径", "右段", "大径", "seg2", "seg2_diameter"])
    l2 = _find_number_after(p, ["右段长", "右段长度", "seg2_length", "右段长"])
    total = _find_number_after(p, ["总长", "total length", "total_length"])

    # 默认阶梯轴：左 20x40 + 右 30x60
    seg1_d = d1 if d1 and d1 > 0 else 20.0
    seg1_l = l1 if l1 and l1 > 0 else 40.0
    seg2_d = d2 if d2 and d2 > 0 else 30.0
    # 若只给了总长，右段长度 = 总长 - 左段长度
    if l2 and l2 > 0:
        seg2_l = l2
    elif total and total > seg1_l:
        seg2_l = total - seg1_l
    else:
        seg2_l = 60.0
    return {
        "seg1_diameter": seg1_d,
        "seg1_length": seg1_l,
        "seg2_diameter": seg2_d,
        "seg2_length": seg2_l,
    }


def _extract_plate_params(prompt: str) -> dict[str, float]:
    p = prompt.lower() if isinstance(prompt, str) else ""
    length = _find_number_after(p, ["长", "长度", "length"])
    width = _find_number_after(p, ["宽", "宽度", "width"])
    thickness = _find_number_after(p, ["厚度", "厚", "thickness"])
    hole_d = _find_number_after(p, ["孔径", "孔直径", "hole diameter", "hole_diameter"])
    edge_offset = _find_number_after(p, ["边距", "距边缘", "edge offset", "edge_offset"])

    return {
        "length": length if length and length > 0 else 100.0,
        "width": width if width and width > 0 else 60.0,
        "thickness": thickness if thickness and thickness > 0 else 5.0,
        "hole_diameter": hole_d if hole_d and hole_d > 0 else 8.0,
        "edge_offset": edge_offset if edge_offset and edge_offset > 0 else 10.0,
    }


def _extract_cube_params(prompt: str) -> dict[str, float]:
    p = prompt.lower() if isinstance(prompt, str) else ""
    size = _find_number_after(p, ["边长", "size", "尺寸"])
    return {"size": size if size and size > 0 else 10.0}


# ===== 主入口 =====


def template_match_generate(prompt: str) -> str:
    """关键词匹配选择模板 + 参数填充，返回 CadQuery Python 代码。

    Args:
        prompt: 用户自然语言零件描述

    Returns:
        可执行的 CadQuery Python 代码字符串（含 ``result`` 变量）

    Raises:
        ValueError: prompt 为空
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt 不能为空")

    p_lower = prompt.lower()

    # 选择模板
    selected = "cube"  # 兜底
    for keywords, name in TEMPLATE_KEYWORDS:
        if any(kw in p_lower or kw in prompt for kw in keywords):
            selected = name
            break

    if selected == "flange":
        params = _extract_flange_params(prompt)
        return _FLANGE_TEMPLATE.format(**params)
    if selected == "shaft":
        params = _extract_shaft_params(prompt)
        return _SHAFT_TEMPLATE.format(**params)
    if selected == "plate":
        params = _extract_plate_params(prompt)
        return _PLATE_TEMPLATE.format(**params)
    # 兜底：cube
    params = _extract_cube_params(prompt)
    return _CUBE_TEMPLATE.format(**params)


def detect_template(prompt: str) -> str:
    """仅返回检测到的模板名（不生成代码），便于上层标记 mode。"""
    if not prompt:
        return "cube"
    p_lower = prompt.lower()
    for keywords, name in TEMPLATE_KEYWORDS:
        if any(kw in p_lower or kw in prompt for kw in keywords):
            return name
    return "cube"
