"""精度分级 schema（Task 9.6）。

依据 spec.md 风险项 R5（多模态 VLM 对工程图理解精度不足），
对审图结果做精度分级，使下游消费方（前端/报告/人工复核流程）
能区分"矢量级可信结果"与"参考级需复核结果"。

三个等级：
- VECTOR_LEVEL（矢量级）：CAD 矢量数据完整可信
- REFERENCE_LEVEL（参考级）：扫描/PDF，需人工复核
- SKETCH_LEVEL（草图级）：手绘草图，强制人工校准

设计原则（八荣八耻 §"以实事求是为荣"）：
- 证据不足时如实降级到 REFERENCE_LEVEL，绝不假装高精度
- 所有判定证据显式落到 PrecisionEvidence，便于审计
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PrecisionLevel(str, Enum):
    """精度等级（依据 spec.md R5 风险项）。

    取值同时是字符串，便于 JSON 序列化与前端展示。
    """

    VECTOR_LEVEL = "vector_level"        # 矢量级：CAD 矢量数据完整可信
    REFERENCE_LEVEL = "reference_level"  # 参考级：扫描/PDF，需人工复核
    SKETCH_LEVEL = "sketch_level"        # 草图级：手绘草图，强制人工校准


class PrecisionEvidence(BaseModel):
    """精度判定的证据。

    所有字段均允许为 None / 默认值，体现"证据可能不完整"的实事求是原则。
    判定逻辑会基于已有证据做保守分级。
    """

    source_format: str = Field(
        ..., description="输入源格式：dxf/dwg/step/pdf/png/jpg/sketch"
    )
    is_vector_source: bool = Field(
        ..., description="是否为矢量源（dxf/dwg/step）"
    )
    is_raster_source: bool = Field(
        ..., description="是否为光栅源（pdf/png/jpg）"
    )
    is_sketch: bool = Field(
        default=False, description="是否为手绘草图"
    )

    # ===== OCR 证据 =====
    ocr_avg_confidence: float | None = Field(
        default=None, description="OCR 平均置信度 0-1"
    )
    ocr_text_count: int = Field(
        default=0, description="OCR 识别文字条数"
    )

    # ===== 区域检测证据 =====
    region_detection_confidence: float | None = Field(
        default=None, description="区域检测平均置信度"
    )
    region_detection_source: str | None = Field(
        default=None, description="区域检测来源：yolov11/vlm/heuristic"
    )

    # ===== 标识符归一化证据 =====
    identifier_match_rate: float | None = Field(
        default=None, description="标识符归一化命中率 0-1"
    )
    identifier_total: int = Field(
        default=0, description="标识符总数"
    )

    # ===== 图像质量证据 =====
    image_resolution: tuple[int, int] | None = Field(
        default=None, description="图像分辨率 (w,h)"
    )
    image_dpi_estimate: int | None = Field(
        default=None, description="估算 DPI"
    )
    has_skew: bool = Field(
        default=False, description="是否检测到倾斜"
    )
    skew_angle: float = Field(
        default=0.0, description="倾斜角度（度）"
    )


class PrecisionClassification(BaseModel):
    """精度分级结果。

    由 classify_precision() 产出。level 为最终结论，evidence 为
    判定所依据的全部证据，rationale 给出人类可读的判定理由。
    """

    level: PrecisionLevel = Field(
        ..., description="精度等级"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="分级置信度 0-1（对判定本身的自信程度）"
    )
    evidence: PrecisionEvidence = Field(
        ..., description="判定证据"
    )
    rationale: str = Field(
        ..., description="分级理由（人类可读）"
    )
    warnings: list[str] = Field(
        default_factory=list, description="警告信息"
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description='建议（如"建议人工复核尺寸标注"）',
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="附加元信息"
    )
