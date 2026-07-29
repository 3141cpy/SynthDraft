"""工程图区域检测与区域 OCR schema（Task 9.3 + 9.4）。

定义区域检测管线的数据结构：
- RegionType：工程图区域类型枚举（标题栏/标注区/视图区/明细栏/修订栏/技术要求/其他）
- Region：单个检测区域（bbox + 置信度 + 来源标注）
- RegionDetectionResult：单图区域检测结果
- RegionOCRResult：单个区域的 OCR 结果（含结构化字段）

设计原则（八荣八耻）：
- 复用 review_detail.py 的 pydantic v2 风格（Field + description）
- bbox 像素坐标 + 归一化坐标并存，便于不同下游消费
- source 字段如实标注检测来源（yolov11/vlm/heuristic），不假装训练过
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ===== Task 9.3：区域检测 =====


class RegionType(str, Enum):
    """工程图区域类型。

    覆盖工程图常见功能区，与 vlm_ocr.vlm_detect_regions() 的 name 字段对齐。
    """

    TITLE_BLOCK = "title_block"  # 标题栏
    DIMENSION_AREA = "dimension_area"  # 尺寸标注区
    VIEW_AREA = "view_area"  # 视图区
    PARTS_LIST = "parts_list"  # 明细栏
    REVISION_BLOCK = "revision_block"  # 修订栏
    TECHNICAL_REQUIREMENTS = "technical_requirements"  # 技术要求
    OTHER = "other"  # 其他


# 检测来源：如实标注，便于审计与降级路径追踪
RegionSource = Literal["yolov11", "vlm", "heuristic"]


class Region(BaseModel):
    """单个检测区域。

    Attributes:
        region_type: 区域类型
        bbox: 像素坐标 [x1, y1, x2, y2]（左上 + 右下）
        bbox_normalized: 归一化坐标 [x, y, w, h]（左上角 + 宽高，0-1）
        confidence: 检测置信度（0-1），heuristic 来源固定 1.0
        source: 检测来源（yolov11/vlm/heuristic）
    """

    region_type: RegionType = Field(..., description="区域类型")
    bbox: list[float] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="像素坐标 [x1, y1, x2, y2]",
    )
    bbox_normalized: list[float] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="归一化坐标 [x, y, w, h]（0-1）",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="检测置信度")
    source: RegionSource = Field(..., description="检测来源")


class RegionDetectionResult(BaseModel):
    """单图区域检测结果。

    Attributes:
        image_path: 输入图片路径
        image_size: 图片尺寸 (width, height)
        regions: 检测到的区域列表
        detector_source: 实际使用的检测器（yolov11/vlm/none）
        elapsed_ms: 检测耗时（毫秒）
        warnings: 降级与异常告警信息
    """

    image_path: str = Field(..., description="输入图片路径")
    image_size: tuple[int, int] = Field(..., description="图片尺寸 (width, height)")
    regions: list[Region] = Field(default_factory=list, description="检测到的区域列表")
    detector_source: str = Field(..., description="实际使用的检测器")
    elapsed_ms: int = Field(..., ge=0, description="检测耗时（毫秒）")
    warnings: list[str] = Field(default_factory=list, description="降级与异常告警")


# ===== Task 9.4：区域受限 OCR =====


class RegionOCRResult(BaseModel):
    """单个区域的 OCR 结果。

    Attributes:
        region_type: 区域类型（决定 structured_data 的字段）
        bbox: 区域像素坐标 [x1, y1, x2, y2]
        raw_texts: OCR 原文（按行）
        raw_items: OCR 原始条目（含 bbox/confidence），保留完整信息
        structured_data: 按区域类型结构化的字段（失败时为空 dict）
        ocr_backend: 实际使用的 OCR 后端（paddle/vlm/none）
        avg_confidence: 平均置信度（无条目时 0.0）
        elapsed_ms: 该区域 OCR 耗时（毫秒）
    """

    region_type: RegionType = Field(..., description="区域类型")
    bbox: list[float] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="区域像素坐标 [x1, y1, x2, y2]",
    )
    raw_texts: list[str] = Field(default_factory=list, description="OCR 原文（按行）")
    raw_items: list[dict[str, Any]] = Field(
        default_factory=list, description="OCR 原始条目（含 bbox/confidence）"
    )
    structured_data: dict[str, Any] = Field(
        default_factory=dict, description="按区域类型结构化的字段"
    )
    ocr_backend: str = Field(..., description="实际使用的 OCR 后端")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="平均置信度")
    elapsed_ms: int = Field(..., ge=0, description="该区域 OCR 耗时（毫秒）")
