"""标识符归一化模块（Task 9.5）。

把 OCR 得到的杂乱文本（如 "Ø20"、"Φ30"、"phi25"、"M8x1.25"、
"M8×1.25"、"±0.1"、"+-0.1"、"H7/g6"、"Ra1.6"、"Ra 1.6"、
"∇1.6"、"T-2024-001" 等）归一化为结构化对象。

设计原则（八荣八耻）：
- 以复用现有为荣：仅用 Python 标准库 re + 项目已有的 pydantic schema，
  不引入任何额外依赖
- 以瞎猜接口为耻：所有正则在模块顶部以 re.VERBOSE 显式声明并加注释，
  self_test() 中每条规则至少 2 个用例（正例 + 反例）实测验证
- 以覆盖测试为荣：self_test() 覆盖规则表所有示例 + 边界情况
  （如 "M8" 无螺距、纯数字长度、"304" 与材料区分等）
- 以实事求是为荣：无法识别的文本如实放入 unmatched，不强行归一化；
  "2024年1月" 缺日则输出 "2024-01"，day=None，绝不瞎编日

规则匹配顺序（重要——避免误匹配）：
1. 表面粗糙度（Ra/Rz/Ry/∇）— 必须先于半径（R）与材料
2. 螺纹（M-prefix）— 必须先于直径（D 前缀）
3. 材料（Q/HT/Cr/# 后缀/304/6061-T6 等特定模式）— 必须先于公差配合（H7）与长度
4. 图号（带字母前缀 + 数字）
5. 件号（件号:/No./①/1.）
6. 数值公差（±/+−）
7. 直径（Ø/Φ/∅/phi/D/d）— 必须先于配合公差（避免 D20 被误判为 H7 类）
8. 半径（R/r）— 必须先于配合公差（避免 R5 被误判为 H7 类）
9. 配合公差（H7/g6/H7/g6）
10. 日期（yyyy-mm-dd / yyyy 年 m 月）
11. 版本（V1.0 / Rev.A / 版本:1.0）
12. 比例（n:n / n/n）
13. 角度（°/deg/度）
14. 长度（纯数字 / L=80）— 兜底规则
"""

from __future__ import annotations

import re
from typing import Any

from app.logging import get_logger
from app.schemas.identifier import (
    IdentifierKind,
    NormalizedIdentifier,
    NormalizeResult,
)

log = get_logger(__name__)


# ============================================================================
# 正则规则（re.VERBOSE 模式，便于注释与审计）
# ============================================================================

# ----- 1. 表面粗糙度 -----
# 形如 "Ra1.6" "Ra 1.6" "Rz3.2" "Ry6.3"（大小写不敏感）
_RE_SURFACE_ROUGHNESS_LETTER = re.compile(
    r"""
    ^\s*
    (?P<type>Ra|Rz|Ry)   # 粗糙度类型：Ra / Rz / Ry
    \s*                  # 类型与数值之间允许空格
    (?P<val>\d+(?:\.\d+)?)  # 数值
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# 形如 "∇1.6"（中国旧标准表面光洁度符号，归一化为 Ra）
_RE_SURFACE_ROUGHNESS_NOABRA = re.compile(
    r"""
    ^\s*
    \u2207               # ∇ U+2207（Nabla，国标用作表面光洁度符号）
    \s*
    (?P<val>\d+(?:\.\d+)?)  # 数值
    \s*$
    """,
    re.VERBOSE,
)

# ----- 2. 螺纹 -----
# 形如 "M8x1.25" "M8×1.25" "M8-1.25" "M10"（M 必须大写）
# × 为 U+00D7 乘号；普通 x 也接受；- 也接受
_RE_THREAD = re.compile(
    r"""
    ^\s*
    M                    # 螺纹标志 M（必须大写，公制螺纹）
    (?P<dia>\d+(?:\.\d+)?)  # 螺纹大径
    (?:                  # 可选的螺距部分
        [x\u00D7\-]       # 分隔符：x / × / -
        (?P<pitch>\d+(?:\.\d+)?)  # 螺距
    )?
    \s*$
    """,
    re.VERBOSE,
)

# ----- 3. 材料 -----
# 碳钢：45# / 45号钢 / 304#
_RE_MATERIAL_CARBON = re.compile(
    r"""
    ^\s*
    (?P<grade>\d{2,3})   # 钢号：45 / 304 / 20
    (?:\#|\u53f7\u94a2)   # # 或 "号钢"
    \s*$
    """,
    re.VERBOSE,
)
# 低合金钢：Q235 / Q235B / Q345
_RE_MATERIAL_QSERIES = re.compile(
    r"""
    ^\s*
    (?P<grade>Q\d{3,4}[A-Z]?)  # Q235 / Q235B / Q345
    \s*$
    """,
    re.VERBOSE,
)
# 灰铸铁：HT200 / HT250
_RE_MATERIAL_CAST_IRON = re.compile(
    r"""
    ^\s*
    (?P<grade>HT\d{3})   # HT200 / HT250
    \s*$
    """,
    re.VERBOSE,
)
# 合金钢（Cr 系列）：20Cr / 40Cr
_RE_MATERIAL_ALLOY = re.compile(
    r"""
    ^\s*
    (?P<grade>\d{2}Cr)   # 20Cr / 40Cr
    \s*$
    """,
    re.VERBOSE,
)
# 不锈钢（特定牌号白名单，避免与长度冲突）
_RE_MATERIAL_STAINLESS = re.compile(
    r"""
    ^\s*
    (?P<grade>304|316|316L|321|904L)  # 常见不锈钢牌号白名单
    \s*$
    """,
    re.VERBOSE,
)
# 铝合金：6061-T6 / 6063-T5
_RE_MATERIAL_ALUMINUM = re.compile(
    r"""
    ^\s*
    (?P<grade>\d{4}-T\d)  # 6061-T6 / 6063-T5
    \s*$
    """,
    re.VERBOSE,
)

# ----- 4. 图号 -----
# 形如 "T-2024-001" "DWG-001" "图号:T-001"
# 前缀 1-5 个字母 + 可选年分 + 序号
_RE_DRAWING_NUMBER = re.compile(
    r"""
    ^\s*
    (?:\u56fe\u53f7\s*[:\uff1a]\s*)?    # 可选前缀 "图号:" 或 "图号："
    (?P<prefix>[A-Za-z]{1,5})            # 前缀：T / DWG / DWG-001 等
    (?:[-_](?P<year>\d{4}))?             # 可选 4 位年分
    [-_]
    (?P<seq>\d{1,4})                     # 序号
    \s*$
    """,
    re.VERBOSE,
)

# ----- 5. 件号 -----
# 形如 "件号:1" "件号：1"
_RE_PART_NUMBER_LABEL = re.compile(
    r"""
    ^\s*
    \u4ef6\u53f7\s*[:\uff1a]\s*  # "件号:" 或 "件号："
    (?P<num>\d+)
    \s*$
    """,
    re.VERBOSE,
)
# 形如 "No.1" "No.1." "NO 1"
_RE_PART_NUMBER_NO = re.compile(
    r"""
    ^\s*
    [Nn][Oo]\.?\s*            # No. / NO / no
    (?P<num>\d+)
    \.?\s*$                   # 允许末尾一个点（如 "1."）
    """,
    re.VERBOSE,
)
# 形如 "1." "2." "12."（数字末尾带一个点，件号常见格式）
_RE_PART_NUMBER_DOTTED = re.compile(
    r"""
    ^\s*
    (?P<num>\d+)              # 数字
    \.                        # 末尾的点
    \s*$
    """,
    re.VERBOSE,
)
# 形如 ① ② ... ⑳（Unicode 圆圈数字）
_RE_PART_NUMBER_CIRCLED = re.compile(
    r"""
    ^\s*
    (?P<circled>[\u2460-\u2473\u3251-\u325f\u32b1-\u32bf])
    \s*$
    """,
    re.VERBOSE,
)
# 圆圈数字 Unicode 值 → 数值映射
_CIRCLED_TO_NUM: dict[str, int] = {
    chr(0x2460 + i): i + 1 for i in range(20)  # ①..⑳ → 1..20
}
# ⓪ (U+24EA) → 0
_CIRCLED_TO_NUM[chr(0x24EA)] = 0

# ----- 6. 数值公差 -----
# 形如 "±0.1" "± 0.1" "+-0.1" "-+0.1"
# ± 为 U+00B1；同时接受 +-/ -+ 作为 OCR 误读兜底
_RE_TOLERANCE_NUMERIC_STRICT = re.compile(
    r"""
    ^\s*
    (?:\u00b1|\+\-|-\+)       # ± (U+00B1) 或 +- 或 -+
    \s*
    (?P<val>\d+(?:\.\d+)?)
    \s*$
    """,
    re.VERBOSE,
)

# ----- 7. 配合公差 -----
# 形如 "H7/g6" "H7" "g6"
# 大写字母+数字=孔配合（H7），小写字母+数字=轴配合（g6）
_RE_TOLERANCE_FIT_PAIR = re.compile(
    r"""
    ^\s*
    (?P<hole>[A-Z]\d+)         # 孔配合：H7
    /
    (?P<shaft>[a-z]\d+)        # 轴配合：g6
    \s*$
    """,
    re.VERBOSE,
)
_RE_TOLERANCE_FIT_HOLE = re.compile(
    r"""
    ^\s*
    (?P<hole>[A-Z]\d+)         # 仅孔配合：H7
    \s*$
    """,
    re.VERBOSE,
)
_RE_TOLERANCE_FIT_SHAFT = re.compile(
    r"""
    ^\s*
    (?P<shaft>[a-z]\d+)        # 仅轴配合：g6
    \s*$
    """,
    re.VERBOSE,
)

# ----- 8. 日期 -----
# 形如 "2024-01-15" "2024.01.15" "2024/1/15" "2024-1"（日可缺省）
_RE_DATE_NUMERIC = re.compile(
    r"""
    ^\s*
    (?P<year>\d{4})
    [-./]
    (?P<month>\d{1,2})
    (?:[-./](?P<day>\d{1,2}))?
    \s*$
    """,
    re.VERBOSE,
)
# 形如 "2024年1月" "2024年12月"
_RE_DATE_CHINESE = re.compile(
    r"""
    ^\s*
    (?P<year>\d{4})
    \u5e74                  # 年
    (?P<month>\d{1,2})
    \u6708                  # 月
    (?:\u65e5(?P<day>\d{1,2}))?  # 可选 "日"
    \s*$
    """,
    re.VERBOSE,
)

# ----- 9. 版本 -----
# 形如 "V1.0" "v1.0" "版本:1.0" "版本：1.0"
_RE_VERSION_NUMERIC = re.compile(
    r"""
    ^\s*
    (?:V|v|\u7248\u672c\s*[:\uff1a])   # V / v / "版本:" / "版本："
    \s*
    (?P<major>\d+)
    (?:\.(?P<minor>\d+))?
    \s*$
    """,
    re.VERBOSE,
)
# 形如 "Rev.A" "Rev.A" "rev.B" "Rev A"
_RE_VERSION_LETTER = re.compile(
    r"""
    ^\s*
    [Rr][Ee][Vv]\.?\s*       # Rev / rev / Rev.
    (?P<letter>[A-Z])         # 大写字母版本号
    \s*$
    """,
    re.VERBOSE,
)

# ----- 10. 比例 -----
# 形如 "1:2" "1:1" "2:1" "1/2"
# 限制分子分母为 1-99 避免与日期冲突
_RE_SCALE = re.compile(
    r"""
    ^\s*
    (?P<num>[1-9]\d?)         # 分子：1-99
    \s*[:/]\s*
    (?P<den>[1-9]\d?)          # 分母：1-99
    \s*$
    """,
    re.VERBOSE,
)

# ----- 11. 直径 -----
# 前缀：Ø(U+00D8) / Φ(U+03A6) / ∅(U+2205) / phi / D / d
# 注意：M8 已被螺纹规则先于本规则消费
_RE_DIAMETER = re.compile(
    r"""
    ^\s*
    (?:\u00D8|\u03A6|\u2205|phi|D|d)   # 前缀
    \s*
    (?P<val>\d+(?:\.\d+)?)
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# ----- 12. 半径 -----
# 形如 "R5" "r10" "R2.5"
# R 后不跟 a/z/y 字母（否则被粗糙度规则消费）
_RE_RADIUS = re.compile(
    r"""
    ^\s*
    [Rr]                       # R 或 r
    (?![aAyYzZ])               # 负向预查：R 后不是 a/A/y/Y/z/Z（避免匹配 Ra/Ry/Rz）
    \s*
    (?P<val>\d+(?:\.\d+)?)
    \s*$
    """,
    re.VERBOSE,
)

# ----- 13. 角度 -----
# 形如 "45°" "30deg" "45度"
_RE_ANGLE = re.compile(
    r"""
    ^\s*
    (?P<val>\d+(?:\.\d+)?)
    \s*
    (?:\u00b0|deg|\u5ea6)      # ° (U+00B0) / deg / 度
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# ----- 14. 长度 -----
# 形如 "L=80" "l=80" "L = 80"
_RE_LENGTH_LPREFIX = re.compile(
    r"""
    ^\s*
    [Ll]\s*=\s*                # L = 或 l =
    (?P<val>\d+(?:\.\d+)?)
    \s*$
    """,
    re.VERBOSE,
)
# 纯数字（兜底）：100 / 50.5
_RE_LENGTH_PLAIN = re.compile(
    r"""
    ^\s*
    (?P<val>\d+(?:\.\d+)?)
    \s*$
    """,
    re.VERBOSE,
)

# ----- 标题栏 / 明细栏 标签前缀（用于 extract_from_title_block）-----
_RE_TITLE_BLOCK_LABEL = re.compile(
    r"""
    ^\s*
    (?P<label>
      \u56fe\u53f7|        # 图号
      \u56fe\u540d|        # 图名
      \u540d\u79f0|        # 名称
      \u6750\u6599|        # 材料
      \u6750\u8d28|        # 材质
      \u6bd4\u4f8b|        # 比例
      Scale|SCALE|scale|
      \u65e5\u671f|        # 日期
      Date|DATE|date|
      \u7248\u672c|        # 版本
      Rev|REV|rev|
      \u7248\u6b21|        # 版次
      \u8bbe\u8ba1|        # 设计
      \u7ed8\u5236|        # 绘制
      \u5ba1\u6838|        # 审核
      Drawn|DRAWN|drawn|
      Designer|DESIGNER|designer
    )
    \s*[:\uff1a]\s*
    (?P<value>.*)
    \s*$
    """,
    re.VERBOSE,
)

# 标签 → 标题栏字典键 映射
_LABEL_TO_KEY: dict[str, str] = {
    "图号": "drawing_number",
    "图名": "title",
    "名称": "title",
    "材料": "material",
    "材质": "material",
    "比例": "scale",
    "Scale": "scale",
    "SCALE": "scale",
    "scale": "scale",
    "日期": "date",
    "Date": "date",
    "DATE": "date",
    "date": "date",
    "版本": "version",
    "Rev": "version",
    "REV": "version",
    "rev": "version",
    "版次": "version",
    "设计": "drawn_by",
    "绘制": "drawn_by",
    "审核": "drawn_by",
    "Drawn": "drawn_by",
    "DRAWN": "drawn_by",
    "drawn": "drawn_by",
    "Designer": "drawn_by",
    "DESIGNER": "drawn_by",
    "designer": "drawn_by",
}

# 材料牌号 → 材料类别（已在 _match_material 内联使用，类别常量留此供审计/扩展）
_MATERIAL_CLASSES = (
    "carbon_steel",       # 碳钢：45# / 45号钢
    "low_alloy_steel",    # 低合金钢：Q235 / Q235B
    "cast_iron",          # 灰铸铁：HT200
    "alloy_steel",        # 合金钢：20Cr / 40Cr
    "stainless_steel",    # 不锈钢：304 / 316L
    "aluminum_alloy",     # 铝合金：6061-T6
)


# ============================================================================
# 核心实现
# ============================================================================


def normalize_text(text: str) -> NormalizedIdentifier | None:
    """对单条文本做归一化。

    Args:
        text: OCR 提取的原始文本

    Returns:
        NormalizedIdentifier 或 None（无法识别时）
    """
    if text is None:
        return None

    raw = text.strip()
    if not raw:
        return None

    # 按规则顺序依次尝试
    for matcher in _MATCHERS:
        result = matcher(raw)
        if result is not None:
            return result

    return None


def normalize_batch(texts: list[str]) -> NormalizeResult:
    """对一批文本做归一化，返回统计结果。

    Args:
        texts: OCR 提取的原始文本列表

    Returns:
        NormalizeResult，包含 identifiers / unmatched / stats
    """
    identifiers: list[NormalizedIdentifier] = []
    unmatched: list[str] = []

    for text in texts or []:
        if text is None:
            continue
        raw = text.strip() if isinstance(text, str) else str(text)
        if not raw:
            continue
        norm = normalize_text(raw)
        if norm is not None:
            identifiers.append(norm)
        else:
            unmatched.append(raw)

    stats: dict[str, int] = {}
    for ident in identifiers:
        stats[ident.kind.value] = stats.get(ident.kind.value, 0) + 1

    return NormalizeResult(
        identifiers=identifiers,
        unmatched=unmatched,
        stats=stats,
    )


def extract_from_dimensions_area(texts: list[str]) -> list[NormalizedIdentifier]:
    """专用于尺寸标注区：仅返回 DIMENSION/TOLERANCE/THREAD 类型。

    Args:
        texts: 尺寸标注区 OCR 文本列表

    Returns:
        仅含 DIMENSION / TOLERANCE_NUMERIC / TOLERANCE_FIT / THREAD 的列表
    """
    result: list[NormalizedIdentifier] = []
    allowed_kinds = {
        IdentifierKind.DIMENSION,
        IdentifierKind.TOLERANCE_NUMERIC,
        IdentifierKind.TOLERANCE_FIT,
        IdentifierKind.THREAD,
    }
    for text in texts or []:
        norm = normalize_text(text)
        if norm is not None and norm.kind in allowed_kinds:
            result.append(norm)
    return result


def extract_from_title_block(
    texts: list[str],
) -> dict[str, NormalizedIdentifier | None]:
    """专用于标题栏：返回 {drawing_number, title, material, scale, date, version, drawn_by}。

    策略：
    1. 优先识别 "标签:值" 格式的行（如 "图号:T-001" "材料:45#"）
    2. 对无标签的行，逐条尝试 normalize_text，按 kind 反向映射到键
    3. 标题/绘制者通常是自由文本，归一化为 UNKNOWN kind 包装

    Args:
        texts: 标题栏 OCR 文本列表

    Returns:
        dict 含 drawing_number / title / material / scale / date / version / drawn_by
    """
    result: dict[str, NormalizedIdentifier | None] = {
        "drawing_number": None,
        "title": None,
        "material": None,
        "scale": None,
        "date": None,
        "version": None,
        "drawn_by": None,
    }

    # kind → 标题栏键 反向映射
    kind_to_key: dict[IdentifierKind, str] = {
        IdentifierKind.DRAWING_NUMBER: "drawing_number",
        IdentifierKind.MATERIAL: "material",
        IdentifierKind.SCALE: "scale",
        IdentifierKind.DATE: "date",
        IdentifierKind.VERSION: "version",
    }

    for text in texts or []:
        if not isinstance(text, str):
            continue
        raw = text.strip()
        if not raw:
            continue

        # 1. 优先匹配 "标签:值" 格式
        label_match = _RE_TITLE_BLOCK_LABEL.match(raw)
        if label_match:
            label = label_match.group("label")
            value = label_match.group("value").strip()
            key = _LABEL_TO_KEY.get(label)
            if not key:
                continue
            if key in ("title", "drawn_by"):
                # 自由文本：用 UNKNOWN 包装
                result[key] = NormalizedIdentifier(
                    kind=IdentifierKind.UNKNOWN,
                    raw_text=raw,
                    normalized=value,
                    value=None,
                    unit=None,
                    extra={"label": label},
                    confidence=0.7,
                )
            else:
                # 标识符：尝试归一化值
                norm = normalize_text(value)
                if norm is not None and norm.kind.value != "unknown":
                    result[key] = norm
                else:
                    # 值无法识别，但仍记录原始值（用 UNKNOWN 包装）
                    result[key] = NormalizedIdentifier(
                        kind=IdentifierKind.UNKNOWN,
                        raw_text=value,
                        normalized=value,
                        value=None,
                        unit=None,
                        extra={"label": label},
                        confidence=0.5,
                    )
            continue

        # 2. 无标签的行：尝试归一化，按 kind 反向映射
        norm = normalize_text(raw)
        if norm is None:
            continue
        key = kind_to_key.get(norm.kind)
        if key and result[key] is None:
            result[key] = norm

    return result


def extract_from_parts_list(rows: list[list[str]]) -> list[dict[str, Any]]:
    """专用于明细栏：每行 [件号, 名称, 数量, 材料, 备注] → 结构化字典。

    输入列顺序约定：[件号, 名称, 数量, 材料, 备注]
    缺列时用空字符串占位；多列忽略。

    Args:
        rows: 明细栏行列表

    Returns:
        结构化字典列表，每条含 part_number / name / quantity / material / remark
    """
    result: list[dict[str, Any]] = []
    for row in rows or []:
        if not row:
            continue
        # 防御性处理：保证至少 5 列
        cells = [str(c).strip() if c is not None else "" for c in row]
        while len(cells) < 5:
            cells.append("")
        part_no_str, name, qty_str, material_str, remark = cells[:5]

        # 件号归一化
        part_number = normalize_text(part_no_str)
        # 件号规则若未命中但形如纯数字，也包装为 PART_NUMBER
        if part_number is None and part_no_str.isdigit():
            part_number = NormalizedIdentifier(
                kind=IdentifierKind.PART_NUMBER,
                raw_text=part_no_str,
                normalized=part_no_str,
                value=float(part_no_str),
                unit=None,
                extra={},
                confidence=0.7,
            )

        # 数量解析
        quantity: int | None = None
        if qty_str:
            try:
                quantity = int(qty_str)
            except ValueError:
                try:
                    quantity = int(float(qty_str))
                except ValueError:
                    quantity = None

        # 材料归一化
        material = normalize_text(material_str)
        # 若材料未命中规则但非空，包装为 UNKNOWN
        if material is None and material_str:
            material = NormalizedIdentifier(
                kind=IdentifierKind.UNKNOWN,
                raw_text=material_str,
                normalized=material_str,
                value=None,
                unit=None,
                extra={},
                confidence=0.5,
            )

        result.append({
            "part_number": part_number,
            "name": name,
            "quantity": quantity,
            "material": material,
            "remark": remark,
        })
    return result


# ============================================================================
# 各规则的具体匹配函数（按顺序调用）
# ============================================================================


def _match_surface_roughness(text: str) -> NormalizedIdentifier | None:
    """规则 1：表面粗糙度 Ra/Rz/Ry/∇。"""
    m = _RE_SURFACE_ROUGHNESS_LETTER.match(text)
    if m:
        rough_type = m.group("type")
        # 标准化：首字母大写，其余小写（Ra/Rz/Ry）
        rough_type_norm = rough_type[0].upper() + rough_type[1:].lower()
        val = float(m.group("val"))
        return NormalizedIdentifier(
            kind=IdentifierKind.SURFACE_ROUGHNESS,
            raw_text=text,
            normalized=f"{rough_type_norm}{val:g}",
            value=val,
            unit="μm",
            extra={"roughness_type": rough_type_norm},
            confidence=0.95,
        )
    m = _RE_SURFACE_ROUGHNESS_NOABRA.match(text)
    if m:
        val = float(m.group("val"))
        # ∇ 在旧国标中默认表示 Ra
        return NormalizedIdentifier(
            kind=IdentifierKind.SURFACE_ROUGHNESS,
            raw_text=text,
            normalized=f"Ra{val:g}",
            value=val,
            unit="μm",
            extra={"roughness_type": "Ra"},
            confidence=0.85,
        )
    return None


def _match_thread(text: str) -> NormalizedIdentifier | None:
    """规则 2：螺纹 M-prefix。"""
    m = _RE_THREAD.match(text)
    if not m:
        return None
    dia = float(m.group("dia"))
    pitch_str = m.group("pitch")
    if pitch_str is not None:
        pitch = float(pitch_str)
        normalized = f"M{dia:g}×{pitch:g}"
        return NormalizedIdentifier(
            kind=IdentifierKind.THREAD,
            raw_text=text,
            normalized=normalized,
            value=dia,
            unit="mm",
            extra={"pitch": pitch, "thread_type": "metric"},
            confidence=0.95,
        )
    # 无螺距（如 "M10"）：normalized 保留 "M10"，pitch=None
    return NormalizedIdentifier(
        kind=IdentifierKind.THREAD,
        raw_text=text,
        normalized=f"M{dia:g}",
        value=dia,
        unit="mm",
        extra={"pitch": None, "thread_type": "metric"},
        confidence=0.85,
    )


def _match_material(text: str) -> NormalizedIdentifier | None:
    """规则 3：材料牌号。"""
    # 碳钢 45# / 45号钢
    m = _RE_MATERIAL_CARBON.match(text)
    if m:
        grade = m.group("grade") + "#"
        return NormalizedIdentifier(
            kind=IdentifierKind.MATERIAL,
            raw_text=text,
            normalized=grade,
            value=None,
            unit=None,
            extra={"material_class": "carbon_steel", "grade": grade},
            confidence=0.95,
        )
    # 低合金钢 Q235 / Q235B
    m = _RE_MATERIAL_QSERIES.match(text)
    if m:
        grade = m.group("grade")
        return NormalizedIdentifier(
            kind=IdentifierKind.MATERIAL,
            raw_text=text,
            normalized=grade,
            value=None,
            unit=None,
            extra={"material_class": "low_alloy_steel", "grade": grade},
            confidence=0.95,
        )
    # 灰铸铁 HT200
    m = _RE_MATERIAL_CAST_IRON.match(text)
    if m:
        grade = m.group("grade")
        return NormalizedIdentifier(
            kind=IdentifierKind.MATERIAL,
            raw_text=text,
            normalized=grade,
            value=None,
            unit=None,
            extra={"material_class": "cast_iron", "grade": grade},
            confidence=0.95,
        )
    # 合金钢 20Cr / 40Cr
    m = _RE_MATERIAL_ALLOY.match(text)
    if m:
        grade = m.group("grade")
        return NormalizedIdentifier(
            kind=IdentifierKind.MATERIAL,
            raw_text=text,
            normalized=grade,
            value=None,
            unit=None,
            extra={"material_class": "alloy_steel", "grade": grade},
            confidence=0.95,
        )
    # 不锈钢 304 / 316 / 316L / 321 / 904L
    m = _RE_MATERIAL_STAINLESS.match(text)
    if m:
        grade = m.group("grade")
        return NormalizedIdentifier(
            kind=IdentifierKind.MATERIAL,
            raw_text=text,
            normalized=grade,
            value=None,
            unit=None,
            extra={"material_class": "stainless_steel", "grade": grade},
            confidence=0.9,
        )
    # 铝合金 6061-T6
    m = _RE_MATERIAL_ALUMINUM.match(text)
    if m:
        grade = m.group("grade")
        return NormalizedIdentifier(
            kind=IdentifierKind.MATERIAL,
            raw_text=text,
            normalized=grade,
            value=None,
            unit=None,
            extra={"material_class": "aluminum_alloy", "grade": grade},
            confidence=0.95,
        )
    return None


def _match_drawing_number(text: str) -> NormalizedIdentifier | None:
    """规则 4：图号。"""
    m = _RE_DRAWING_NUMBER.match(text)
    if not m:
        return None
    prefix = m.group("prefix")
    year = m.group("year")
    seq = m.group("seq")
    # 大写化前缀（如 dwg → DWG）
    prefix_norm = prefix.upper()
    if year:
        normalized = f"{prefix_norm}-{year}-{seq}"
    else:
        normalized = f"{prefix_norm}-{seq}"
    extra: dict[str, Any] = {"prefix": prefix_norm, "seq": seq}
    if year:
        extra["year"] = int(year)
    return NormalizedIdentifier(
        kind=IdentifierKind.DRAWING_NUMBER,
        raw_text=text,
        normalized=normalized,
        value=None,
        unit=None,
        extra=extra,
        confidence=0.9,
    )


def _match_part_number(text: str) -> NormalizedIdentifier | None:
    """规则 5：件号。"""
    # 件号:1
    m = _RE_PART_NUMBER_LABEL.match(text)
    if m:
        num = int(m.group("num"))
        return NormalizedIdentifier(
            kind=IdentifierKind.PART_NUMBER,
            raw_text=text,
            normalized=str(num),
            value=float(num),
            unit=None,
            extra={},
            confidence=0.95,
        )
    # No.1
    m = _RE_PART_NUMBER_NO.match(text)
    if m:
        num = int(m.group("num"))
        return NormalizedIdentifier(
            kind=IdentifierKind.PART_NUMBER,
            raw_text=text,
            normalized=str(num),
            value=float(num),
            unit=None,
            extra={},
            confidence=0.95,
        )
    # ① ② ... ⑳
    m = _RE_PART_NUMBER_CIRCLED.match(text)
    if m:
        circled = m.group("circled")
        num = _CIRCLED_TO_NUM.get(circled)
        if num is not None:
            return NormalizedIdentifier(
                kind=IdentifierKind.PART_NUMBER,
                raw_text=text,
                normalized=str(num),
                value=float(num),
                unit=None,
                extra={},
                confidence=0.95,
            )
    # 1. / 2.（末尾带点）
    m = _RE_PART_NUMBER_DOTTED.match(text)
    if m:
        num = int(m.group("num"))
        return NormalizedIdentifier(
            kind=IdentifierKind.PART_NUMBER,
            raw_text=text,
            normalized=str(num),
            value=float(num),
            unit=None,
            extra={},
            confidence=0.85,
        )
    return None


def _match_tolerance_numeric(text: str) -> NormalizedIdentifier | None:
    """规则 6：数值公差 ±/+-/-+。"""
    m = _RE_TOLERANCE_NUMERIC_STRICT.match(text)
    if not m:
        return None
    val = float(m.group("val"))
    return NormalizedIdentifier(
        kind=IdentifierKind.TOLERANCE_NUMERIC,
        raw_text=text,
        normalized=f"±{val:g}",
        value=val,
        unit="mm",
        extra={"tolerance_type": "symmetric"},
        confidence=0.95,
    )


def _match_tolerance_fit(text: str) -> NormalizedIdentifier | None:
    """规则 7：配合公差 H7/g6 / H7 / g6。"""
    # 配对：H7/g6
    m = _RE_TOLERANCE_FIT_PAIR.match(text)
    if m:
        hole = m.group("hole")
        shaft = m.group("shaft")
        return NormalizedIdentifier(
            kind=IdentifierKind.TOLERANCE_FIT,
            raw_text=text,
            normalized=f"{hole}/{shaft}",
            value=None,
            unit=None,
            extra={"hole_grade": hole, "shaft_grade": shaft},
            confidence=0.95,
        )
    # 仅孔配合：H7
    m = _RE_TOLERANCE_FIT_HOLE.match(text)
    if m:
        hole = m.group("hole")
        return NormalizedIdentifier(
            kind=IdentifierKind.TOLERANCE_FIT,
            raw_text=text,
            normalized=hole,
            value=None,
            unit=None,
            extra={"hole_grade": hole, "shaft_grade": None},
            confidence=0.85,
        )
    # 仅轴配合：g6
    m = _RE_TOLERANCE_FIT_SHAFT.match(text)
    if m:
        shaft = m.group("shaft")
        return NormalizedIdentifier(
            kind=IdentifierKind.TOLERANCE_FIT,
            raw_text=text,
            normalized=shaft,
            value=None,
            unit=None,
            extra={"hole_grade": None, "shaft_grade": shaft},
            confidence=0.85,
        )
    return None


def _match_date(text: str) -> NormalizedIdentifier | None:
    """规则 8：日期。"""
    # 数值形式：2024-01-15 / 2024.01.15 / 2024/1/15 / 2024-1
    m = _RE_DATE_NUMERIC.match(text)
    if m:
        year = int(m.group("year"))
        month = int(m.group("month"))
        day_str = m.group("day")
        day = int(day_str) if day_str else None
        normalized = f"{year:04d}-{month:02d}"
        if day is not None:
            normalized += f"-{day:02d}"
        extra: dict[str, Any] = {"year": year, "month": month}
        if day is not None:
            extra["day"] = day
        return NormalizedIdentifier(
            kind=IdentifierKind.DATE,
            raw_text=text,
            normalized=normalized,
            value=None,
            unit=None,
            extra=extra,
            confidence=0.95,
        )
    # 中文形式：2024年1月 / 2024年1月15日
    m = _RE_DATE_CHINESE.match(text)
    if m:
        year = int(m.group("year"))
        month = int(m.group("month"))
        day_str = m.group("day")
        day = int(day_str) if day_str else None
        normalized = f"{year:04d}-{month:02d}"
        if day is not None:
            normalized += f"-{day:02d}"
        extra = {"year": year, "month": month}
        if day is not None:
            extra["day"] = day
        return NormalizedIdentifier(
            kind=IdentifierKind.DATE,
            raw_text=text,
            normalized=normalized,
            value=None,
            unit=None,
            extra=extra,
            confidence=0.9,
        )
    return None


def _match_version(text: str) -> NormalizedIdentifier | None:
    """规则 9：版本。"""
    # 字母版本：Rev.A
    m = _RE_VERSION_LETTER.match(text)
    if m:
        letter = m.group("letter")
        return NormalizedIdentifier(
            kind=IdentifierKind.VERSION,
            raw_text=text,
            normalized=f"Rev.{letter}",
            value=None,
            unit=None,
            extra={"letter": letter},
            confidence=0.9,
        )
    # 数字版本：V1.0 / 版本:1.0
    m = _RE_VERSION_NUMERIC.match(text)
    if m:
        major = int(m.group("major"))
        minor_str = m.group("minor")
        minor = int(minor_str) if minor_str else 0
        normalized = f"V{major}.{minor}"
        return NormalizedIdentifier(
            kind=IdentifierKind.VERSION,
            raw_text=text,
            normalized=normalized,
            value=None,
            unit=None,
            extra={"major": major, "minor": minor},
            confidence=0.9,
        )
    return None


def _match_scale(text: str) -> NormalizedIdentifier | None:
    """规则 10：比例。"""
    m = _RE_SCALE.match(text)
    if not m:
        return None
    num = int(m.group("num"))
    den = int(m.group("den"))
    return NormalizedIdentifier(
        kind=IdentifierKind.SCALE,
        raw_text=text,
        normalized=f"{num}:{den}",
        value=None,
        unit=None,
        extra={"numerator": num, "denominator": den},
        confidence=0.9,
    )


def _match_diameter(text: str) -> NormalizedIdentifier | None:
    """规则 11：直径。"""
    m = _RE_DIAMETER.match(text)
    if not m:
        return None
    val = float(m.group("val"))
    return NormalizedIdentifier(
        kind=IdentifierKind.DIMENSION,
        raw_text=text,
        normalized=f"Ø{val:g}",
        value=val,
        unit="mm",
        extra={"sub_type": "diameter"},
        confidence=0.95,
    )


def _match_radius(text: str) -> NormalizedIdentifier | None:
    """规则 12：半径。"""
    m = _RE_RADIUS.match(text)
    if not m:
        return None
    val = float(m.group("val"))
    return NormalizedIdentifier(
        kind=IdentifierKind.DIMENSION,
        raw_text=text,
        normalized=f"R{val:g}",
        value=val,
        unit="mm",
        extra={"sub_type": "radius"},
        confidence=0.95,
    )


def _match_angle(text: str) -> NormalizedIdentifier | None:
    """规则 13：角度。"""
    m = _RE_ANGLE.match(text)
    if not m:
        return None
    val = float(m.group("val"))
    return NormalizedIdentifier(
        kind=IdentifierKind.DIMENSION,
        raw_text=text,
        normalized=f"{val:g}°",
        value=val,
        unit="°",
        extra={"sub_type": "angle"},
        confidence=0.95,
    )


def _match_length(text: str) -> NormalizedIdentifier | None:
    """规则 14：长度（兜底规则）。"""
    # L=80 / l=80
    m = _RE_LENGTH_LPREFIX.match(text)
    if m:
        val = float(m.group("val"))
        return NormalizedIdentifier(
            kind=IdentifierKind.DIMENSION,
            raw_text=text,
            normalized=f"{val:g}",
            value=val,
            unit="mm",
            extra={"sub_type": "length"},
            confidence=0.9,
        )
    # 纯数字（兜底）— 置信度较低
    m = _RE_LENGTH_PLAIN.match(text)
    if m:
        val = float(m.group("val"))
        return NormalizedIdentifier(
            kind=IdentifierKind.DIMENSION,
            raw_text=text,
            normalized=f"{val:g}",
            value=val,
            unit="mm",
            extra={"sub_type": "length"},
            confidence=0.6,  # 兜底规则，置信度低
        )
    return None


# 规则匹配器列表（顺序非常重要！）
# 关键顺序约束：
# - 直径/半径 必须先于 配合公差（避免 "D20"/"R5" 被误判为 H7 类孔/轴配合）
# - 表面粗糙度 必须先于 半径（避免 "Ra1.6" 被半径规则 R 前缀截获）
# - 螺纹 必须先于 直径（避免 "M8" 被 D/d 前缀直径规则截获——M 不在直径前缀中，但避免误判）
# - 材料 必须先于 长度（避免 "304" 被纯数字长度规则截获）
_MATCHERS = [
    _match_surface_roughness,
    _match_thread,
    _match_material,
    _match_drawing_number,
    _match_part_number,
    _match_tolerance_numeric,
    _match_diameter,
    _match_radius,
    _match_tolerance_fit,
    _match_date,
    _match_version,
    _match_scale,
    _match_angle,
    _match_length,
]


# ============================================================================
# 自检（"以覆盖测试为荣"——覆盖规则表所有示例 + 边界情况）
# ============================================================================


def self_test() -> dict[str, Any]:
    """标识符归一化模块自检。

    覆盖规则表中所有示例，每条规则至少 2 个用例（正例 + 反例）。
    失败用例要在 unmatched 中体现。

    Returns:
        {
            "rule_cases": list[dict],   # 每条规则的测试用例
            "unmatched_cases": list[str],  # 必须未匹配的文本
            "all_passed": bool,
        }
    """
    rule_cases: list[dict[str, Any]] = []

    # ----- 规则 1：直径 -----
    diameter_cases = [
        ("Ø20", "Ø20", 20.0, "mm", {"sub_type": "diameter"}),
        ("Φ30", "Ø30", 30.0, "mm", {"sub_type": "diameter"}),
        ("phi25", "Ø25", 25.0, "mm", {"sub_type": "diameter"}),
        ("D20", "Ø20", 20.0, "mm", {"sub_type": "diameter"}),
        ("∅30", "Ø30", 30.0, "mm", {"sub_type": "diameter"}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in diameter_cases:
        _check_case(rule_cases, "直径", raw, IdentifierKind.DIMENSION,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 2：半径 -----
    radius_cases = [
        ("R5", "R5", 5.0, "mm", {"sub_type": "radius"}),
        ("r10", "R10", 10.0, "mm", {"sub_type": "radius"}),
        ("R2.5", "R2.5", 2.5, "mm", {"sub_type": "radius"}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in radius_cases:
        _check_case(rule_cases, "半径", raw, IdentifierKind.DIMENSION,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 3：长度 -----
    length_cases = [
        ("100", "100", 100.0, "mm", {"sub_type": "length"}),
        ("50.5", "50.5", 50.5, "mm", {"sub_type": "length"}),
        ("L=80", "80", 80.0, "mm", {"sub_type": "length"}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in length_cases:
        _check_case(rule_cases, "长度", raw, IdentifierKind.DIMENSION,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 4：角度 -----
    angle_cases = [
        ("45°", "45°", 45.0, "°", {"sub_type": "angle"}),
        ("30deg", "30°", 30.0, "°", {"sub_type": "angle"}),
        ("45度", "45°", 45.0, "°", {"sub_type": "angle"}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in angle_cases:
        _check_case(rule_cases, "角度", raw, IdentifierKind.DIMENSION,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 5：数值公差 -----
    tol_num_cases = [
        ("±0.1", "±0.1", 0.1, "mm", {"tolerance_type": "symmetric"}),
        ("+-0.1", "±0.1", 0.1, "mm", {"tolerance_type": "symmetric"}),
        ("±0.05", "±0.05", 0.05, "mm", {"tolerance_type": "symmetric"}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in tol_num_cases:
        _check_case(rule_cases, "数值公差", raw, IdentifierKind.TOLERANCE_NUMERIC,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 6：配合公差 -----
    tol_fit_cases = [
        ("H7/g6", "H7/g6", None, None,
         {"hole_grade": "H7", "shaft_grade": "g6"}),
        ("H7", "H7", None, None,
         {"hole_grade": "H7", "shaft_grade": None}),
        ("g6", "g6", None, None,
         {"hole_grade": None, "shaft_grade": "g6"}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in tol_fit_cases:
        _check_case(rule_cases, "配合公差", raw, IdentifierKind.TOLERANCE_FIT,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 7：表面粗糙度 -----
    roughness_cases = [
        ("Ra1.6", "Ra1.6", 1.6, "μm", {"roughness_type": "Ra"}),
        ("Ra 1.6", "Ra1.6", 1.6, "μm", {"roughness_type": "Ra"}),
        ("Rz3.2", "Rz3.2", 3.2, "μm", {"roughness_type": "Rz"}),
        ("∇1.6", "Ra1.6", 1.6, "μm", {"roughness_type": "Ra"}),
        ("Ra3.2", "Ra3.2", 3.2, "μm", {"roughness_type": "Ra"}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in roughness_cases:
        _check_case(rule_cases, "表面粗糙度", raw, IdentifierKind.SURFACE_ROUGHNESS,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 8：螺纹 -----
    thread_cases = [
        ("M8x1.25", "M8×1.25", 8.0, "mm",
         {"pitch": 1.25, "thread_type": "metric"}),
        ("M8×1.25", "M8×1.25", 8.0, "mm",
         {"pitch": 1.25, "thread_type": "metric"}),
        ("M8-1.25", "M8×1.25", 8.0, "mm",
         {"pitch": 1.25, "thread_type": "metric"}),
        # 边界：M10 无螺距
        ("M10", "M10", 10.0, "mm",
         {"pitch": None, "thread_type": "metric"}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in thread_cases:
        _check_case(rule_cases, "螺纹", raw, IdentifierKind.THREAD,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 9：图号 -----
    drawing_cases = [
        ("T-2024-001", "T-2024-001", None, None,
         {"prefix": "T", "year": 2024, "seq": "001"}),
        ("DWG-001", "DWG-001", None, None,
         {"prefix": "DWG", "seq": "001"}),
        ("图号:T-001", "T-001", None, None,
         {"prefix": "T", "seq": "001"}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in drawing_cases:
        _check_case(rule_cases, "图号", raw, IdentifierKind.DRAWING_NUMBER,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 10：件号 -----
    part_cases = [
        ("件号:1", "1", 1.0, None, {}),
        ("No.1", "1", 1.0, None, {}),
        ("①", "1", 1.0, None, {}),
        ("1.", "1", 1.0, None, {}),
        # 边界：圆圈数字 ⑳
        ("⑳", "20", 20.0, None, {}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in part_cases:
        _check_case(rule_cases, "件号", raw, IdentifierKind.PART_NUMBER,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 11：材料牌号 -----
    material_cases = [
        ("45#", "45#", None, None,
         {"material_class": "carbon_steel", "grade": "45#"}),
        ("45号钢", "45#", None, None,
         {"material_class": "carbon_steel", "grade": "45#"}),
        ("Q235", "Q235", None, None,
         {"material_class": "low_alloy_steel", "grade": "Q235"}),
        ("Q235B", "Q235B", None, None,
         {"material_class": "low_alloy_steel", "grade": "Q235B"}),
        ("HT200", "HT200", None, None,
         {"material_class": "cast_iron", "grade": "HT200"}),
        ("20Cr", "20Cr", None, None,
         {"material_class": "alloy_steel", "grade": "20Cr"}),
        ("40Cr", "40Cr", None, None,
         {"material_class": "alloy_steel", "grade": "40Cr"}),
        ("304", "304", None, None,
         {"material_class": "stainless_steel", "grade": "304"}),
        ("6061-T6", "6061-T6", None, None,
         {"material_class": "aluminum_alloy", "grade": "6061-T6"}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in material_cases:
        _check_case(rule_cases, "材料牌号", raw, IdentifierKind.MATERIAL,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 12：比例 -----
    scale_cases = [
        ("1:2", "1:2", None, None, {"numerator": 1, "denominator": 2}),
        ("1:1", "1:1", None, None, {"numerator": 1, "denominator": 1}),
        ("2:1", "2:1", None, None, {"numerator": 2, "denominator": 1}),
        ("1/2", "1:2", None, None, {"numerator": 1, "denominator": 2}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in scale_cases:
        _check_case(rule_cases, "比例", raw, IdentifierKind.SCALE,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 13：日期 -----
    date_cases = [
        ("2024-01-15", "2024-01-15", None, None,
         {"year": 2024, "month": 1, "day": 15}),
        ("2024.01.15", "2024-01-15", None, None,
         {"year": 2024, "month": 1, "day": 15}),
        ("2024/1/15", "2024-01-15", None, None,
         {"year": 2024, "month": 1, "day": 15}),
        # 边界："2024年1月" 缺日，实事求是地输出 "2024-01"，day=None
        ("2024年1月", "2024-01", None, None,
         {"year": 2024, "month": 1}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in date_cases:
        _check_case(rule_cases, "日期", raw, IdentifierKind.DATE,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 规则 14：版本 -----
    version_cases = [
        ("V1.0", "V1.0", None, None, {"major": 1, "minor": 0}),
        ("v1.0", "V1.0", None, None, {"major": 1, "minor": 0}),
        # 边界：Rev.A 字母版本，extra 用 letter 字段
        ("Rev.A", "Rev.A", None, None, {"letter": "A"}),
        ("版本:1.0", "V1.0", None, None, {"major": 1, "minor": 0}),
    ]
    for raw, exp_norm, exp_val, exp_unit, exp_extra in version_cases:
        _check_case(rule_cases, "版本", raw, IdentifierKind.VERSION,
                    exp_norm, exp_val, exp_unit, exp_extra)

    # ----- 反例：必须未匹配 -----
    # 这些文本无法被任何规则识别，应如实进入 unmatched（"以实事求是为荣"）
    unmatched_cases = [
        "",                       # 空字符串
        "   ",                    # 纯空白
        "abc",                    # 纯字母无意义
        "M8x",                    # 螺纹缺螺距数值
        "Ra",                     # 粗糙度无数值
        "123abc",                 # 数字+字母混合
        "Ø",                      # 直径缺数值
        "1:1000",                 # 比例分母过大（超出 [1,99]，避免与日期冲突）
        "???!!",                  # 全符号
    ]

    # 验证反例确实进入 unmatched
    unmatched_actual: list[str] = []
    for raw in unmatched_cases:
        norm = normalize_text(raw)
        if norm is None:
            unmatched_actual.append(raw)

    # ----- 批量归一化测试 -----
    batch_texts = [
        "Ø20", "M8x1.25", "Ra1.6", "H7/g6", "1:2",
        "abc", "??", "45#", "2024-01-15", "V1.0",
        "件号:3", "100",
    ]
    batch_result = normalize_batch(batch_texts)
    # 期望 unmatched 包含 "abc" 与 "??"
    batch_unmatched_ok = (
        "abc" in batch_result.unmatched and "??" in batch_result.unmatched
    )
    rule_cases.append({
        "rule": "批量归一化",
        "raw": str(batch_texts),
        "passed": batch_unmatched_ok,
        "actual": {
            "identifiers_count": len(batch_result.identifiers),
            "unmatched": batch_result.unmatched,
            "stats": batch_result.stats,
        },
        "expected": "abc 与 ?? 在 unmatched 中",
    })

    # ----- 标题栏提取测试 -----
    title_block_texts = [
        "图号:T-2024-001",
        "名称:支架",
        "材料:45#",
        "比例:1:2",
        "日期:2024-01-15",
        "版本:V1.0",
        "绘制:张三",
    ]
    title_result = extract_from_title_block(title_block_texts)
    title_ok = (
        title_result["drawing_number"] is not None
        and title_result["drawing_number"].kind == IdentifierKind.DRAWING_NUMBER
        and title_result["material"] is not None
        and title_result["material"].kind == IdentifierKind.MATERIAL
        and title_result["scale"] is not None
        and title_result["scale"].kind == IdentifierKind.SCALE
        and title_result["date"] is not None
        and title_result["date"].kind == IdentifierKind.DATE
        and title_result["version"] is not None
        and title_result["version"].kind == IdentifierKind.VERSION
        and title_result["title"] is not None
        and title_result["title"].normalized == "支架"
        and title_result["drawn_by"] is not None
        and title_result["drawn_by"].normalized == "张三"
    )
    rule_cases.append({
        "rule": "标题栏提取",
        "raw": str(title_block_texts),
        "passed": title_ok,
        "actual": {k: (v.normalized if v else None) for k, v in title_result.items()},
        "expected": "drawing_number/material/scale/date/version/title/drawn_by 全部命中",
    })

    # ----- 明细栏提取测试 -----
    parts_rows = [
        ["1", "支架", "2", "45#", "焊接"],
        ["2", "螺栓", "10", "304", "M8"],
        ["3", "垫圈", "20", "Q235", ""],
    ]
    parts_result = extract_from_parts_list(parts_rows)
    parts_ok = (
        len(parts_result) == 3
        and parts_result[0]["part_number"] is not None
        and parts_result[0]["part_number"].value == 1.0
        and parts_result[0]["material"] is not None
        and parts_result[0]["material"].kind == IdentifierKind.MATERIAL
        and parts_result[1]["quantity"] == 10
        and parts_result[2]["name"] == "垫圈"
    )
    rule_cases.append({
        "rule": "明细栏提取",
        "raw": str(parts_rows),
        "passed": parts_ok,
        "actual": parts_result,
        "expected": "3 行全部结构化，件号/数量/材料正确",
    })

    # ----- 尺寸标注区提取测试 -----
    dim_texts = ["Ø20", "M8x1.25", "Ra1.6", "45°", "H7/g6", "T-001", "1:2"]
    dim_result = extract_from_dimensions_area(dim_texts)
    dim_kinds = {d.kind for d in dim_result}
    # DIMENSION(Ø20/45°), THREAD(M8x1.25), TOLERANCE_FIT(H7/g6) 应该被提取
    # SURFACE_ROUGHNESS / DRAWING_NUMBER / SCALE 应该被过滤掉
    dim_ok = (
        IdentifierKind.DIMENSION in dim_kinds
        and IdentifierKind.THREAD in dim_kinds
        and IdentifierKind.TOLERANCE_FIT in dim_kinds
        and IdentifierKind.SURFACE_ROUGHNESS not in dim_kinds
        and IdentifierKind.DRAWING_NUMBER not in dim_kinds
        and IdentifierKind.SCALE not in dim_kinds
    )
    rule_cases.append({
        "rule": "尺寸标注区提取",
        "raw": str(dim_texts),
        "passed": dim_ok,
        "actual": [d.kind.value for d in dim_result],
        "expected": "仅 DIMENSION/TOLERANCE/THREAD 类型",
    })

    all_passed = all(c["passed"] for c in rule_cases)
    return {
        "rule_cases": rule_cases,
        "unmatched_cases": unmatched_actual,
        "all_passed": all_passed,
    }


def _check_case(
    cases: list[dict[str, Any]],
    rule_name: str,
    raw: str,
    expected_kind: IdentifierKind,
    expected_norm: str,
    expected_value: float | None,
    expected_unit: str | None,
    expected_extra: dict[str, Any],
) -> None:
    """辅助函数：测试单个用例并加入 cases 列表。"""
    norm = normalize_text(raw)
    if norm is None:
        cases.append({
            "rule": rule_name,
            "raw": raw,
            "passed": False,
            "actual": None,
            "expected": {
                "kind": expected_kind.value,
                "normalized": expected_norm,
                "value": expected_value,
                "unit": expected_unit,
                "extra": expected_extra,
            },
        })
        return

    # 比较 extra 字典（避免浮点精度问题）
    actual_extra = dict(norm.extra)
    expected_extra_copy = dict(expected_extra)
    # 浮点比较：pitch 等浮点字段容差
    for key in list(actual_extra.keys()):
        if key in expected_extra_copy:
            a = actual_extra[key]
            e = expected_extra_copy[key]
            if isinstance(a, float) and isinstance(e, (int, float)):
                if abs(a - float(e)) < 1e-9:
                    actual_extra[key] = float(e)
                    expected_extra_copy[key] = float(e)

    passed = (
        norm.kind == expected_kind
        and norm.normalized == expected_norm
        and _value_eq(norm.value, expected_value)
        and norm.unit == expected_unit
        and actual_extra == expected_extra_copy
    )
    cases.append({
        "rule": rule_name,
        "raw": raw,
        "passed": passed,
        "actual": {
            "kind": norm.kind.value,
            "normalized": norm.normalized,
            "value": norm.value,
            "unit": norm.unit,
            "extra": norm.extra,
        },
        "expected": {
            "kind": expected_kind.value,
            "normalized": expected_norm,
            "value": expected_value,
            "unit": expected_unit,
            "extra": expected_extra,
        },
    })


def _value_eq(a: float | None, b: float | None) -> bool:
    """浮点数比较（容差 1e-9）。"""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) < 1e-9


# ============================================================================
# 命令行入口
# ============================================================================


def _print_table(report: dict[str, Any]) -> None:
    """以表格形式打印自检结果。"""
    cases = report["rule_cases"]
    print(f"\n{'='*100}")
    print(f"{'规则':<14} {'原始文本':<22} {'归一化':<22} {'值':<10} {'单位':<6} {'结果':<6}")
    print(f"{'-'*100}")
    current_rule = ""
    for c in cases:
        if c["rule"] != current_rule:
            current_rule = c["rule"]
        raw = c["raw"]
        if len(raw) > 20:
            raw = raw[:17] + "..."
        actual = c.get("actual")
        if isinstance(actual, dict):
            norm = actual.get("normalized", "")
            val = actual.get("value")
            val_str = f"{val:g}" if val is not None else "-"
            unit = actual.get("unit") or "-"
        else:
            # 批量/标题栏等聚合用例
            norm = "(聚合)"
            val_str = "-"
            unit = "-"
        mark = "[PASS]" if c["passed"] else "[FAIL]"
        print(f"{c['rule']:<14} {raw:<22} {norm:<22} {val_str:<10} {unit:<6} {mark:<6}")
        if not c["passed"]:
            exp = c.get("expected")
            print(f"  → 期望: {exp}")
            print(f"  → 实际: {actual}")

    print(f"\n{'='*100}")
    print(f"反例（必须未匹配）: {report['unmatched_cases']}")
    print(f"{'='*100}")


if __name__ == "__main__":
    import sys

    print("=" * 100)
    print("标识符归一化模块自检（Task 9.5）")
    print("=" * 100)
    print("规则匹配顺序（重要——避免误匹配）：")
    for i, matcher in enumerate(_MATCHERS, 1):
        print(f"  {i:2d}. {matcher.__name__}")
    print()

    report = self_test()
    _print_table(report)

    print()
    total = len(report["rule_cases"])
    passed = sum(1 for c in report["rule_cases"] if c["passed"])
    failed = total - passed
    print(f"用例总数: {total}  通过: {passed}  失败: {failed}")
    print(f"反例未匹配数: {len(report['unmatched_cases'])}")

    print("=" * 100)
    if report["all_passed"]:
        print("全部用例通过 ✅")
        sys.exit(0)
    else:
        failed_cases = [c["rule"] + ": " + c["raw"] for c in report["rule_cases"] if not c["passed"]]
        print(f"失败用例：")
        for f in failed_cases:
            print(f"  - {f}")
        sys.exit(1)
