"""标识符归一化 schema（Task 9.5）。

将 OCR 提取的杂乱文本（如 "Ø20"、"Φ30"、"phi25"、"M8x1.25"、
"±0.1"、"H7/g6"、"Ra1.6"、"T-2024-001" 等）归一化为结构化对象。

设计原则（八荣八耻）：
- 以复用现有为荣：仅依赖 pydantic（已在项目中使用），不引入新依赖
- 以实事求是为荣：无法识别的文本如实放入 unmatched，不强行归一化
- 所有字段显式标注 Optional 与默认值，保证向后兼容
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IdentifierKind(str, Enum):
    """标识符类型。

    取值同时是字符串，便于 JSON 序列化与前端展示。
    """

    DIMENSION = "dimension"                    # 尺寸（直径/半径/长度/角度）
    TOLERANCE_NUMERIC = "tolerance_numeric"    # 数值公差 ±0.1
    TOLERANCE_FIT = "tolerance_fit"            # 配合公差 H7/g6
    SURFACE_ROUGHNESS = "surface_roughness"    # 表面粗糙度 Ra1.6
    THREAD = "thread"                          # 螺纹 M8x1.25
    DRAWING_NUMBER = "drawing_number"          # 图号
    PART_NUMBER = "part_number"                # 件号
    MATERIAL = "material"                       # 材料牌号
    SCALE = "scale"                             # 比例
    DATE = "date"                               # 日期
    VERSION = "version"                         # 版本号
    UNKNOWN = "unknown"                         # 未知类型


class NormalizedIdentifier(BaseModel):
    """单个归一化后的标识符。

    由 normalize_text() 产出。raw_text 保留原始 OCR 文本，
    normalized 为标准表示，value/unit/extra 提供结构化字段。
    """

    kind: IdentifierKind = Field(
        ..., description="标识符类型"
    )
    raw_text: str = Field(
        ..., description="原始 OCR 文本"
    )
    normalized: str = Field(
        ..., description="归一化标准表示，如 'Ø20' / 'M8×1.25' / 'Ra1.6'"
    )
    value: float | None = Field(
        default=None, description="数值（如 20.0 / 8.0 / 1.6）"
    )
    unit: str | None = Field(
        default=None, description="单位：'mm' / '°' / 'μm' 等"
    )
    extra: dict[str, Any] = Field(
        default_factory=dict, description="额外结构化字段"
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="归一化置信度 0-1"
    )


class NormalizeResult(BaseModel):
    """批量归一化结果。

    由 normalize_batch() 产出。identifiers 为已识别的标识符列表，
    unmatched 为未匹配的原始文本，stats 按 IdentifierKind 统计数量。
    """

    identifiers: list[NormalizedIdentifier] = Field(
        default_factory=list, description="已识别的标识符列表"
    )
    unmatched: list[str] = Field(
        default_factory=list, description="未匹配的原始文本"
    )
    stats: dict[str, int] = Field(
        default_factory=dict, description="按 kind 统计的数量"
    )
