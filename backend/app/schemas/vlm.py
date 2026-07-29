"""VLM 输出结构化 schema（VLM-04）。

定义 VLM（视觉语言模型）输出的 Pydantic 校验模型，用于：
- ``vlm_ocr.vlm_detect_regions`` 的区域列表项校验
- ``vlm_ocr.vlm_ocr_extract`` 的 OCR 结果字段校验

设计原则（八荣八耻）：
- 以实事求是为荣：VLM 输出噪声大，必须做类型校验后再交给下游
- 以复用现有为荣：复用现有 ``_normalize_bbox`` / ``_parse_json_*`` 工具，校验层仅做类型守卫
- 不阻断主流程：校验失败时由调用方 log.warning 后丢弃无效项 / 字段，返回空 list/dict
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VLMRegionItem(BaseModel):
    """VLM 区域检测单项（``vlm_detect_regions`` 输出）。

    Attributes:
        name: 区域语义名（如 title_block / dimension_area / view_area /
            parts_list / revision_block / technical_requirements）
        bbox: 归一化坐标 ``[x, y, w, h]``（左上角 + 宽高，0-1，长度恰好 4）
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(..., description="区域语义名")
    bbox: list[float] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="归一化坐标 [x, y, w, h]（左上角 + 宽高，0-1）",
    )

    @field_validator("bbox")
    @classmethod
    def _validate_bbox(cls, v: list[float]) -> list[float]:
        # 长度已由 min_length/max_length 保证；这里仅做数值性兜底
        if not all(isinstance(x, (int, float)) for x in v):
            raise ValueError("bbox 元素必须为数值")
        return [float(x) for x in v]


class VLMOCRResult(BaseModel):
    """VLM OCR 提取结果（``vlm_ocr_extract`` 输出）。

    所有字段允许 None（VLM 未识别时填 null）。下游代码应处理 None。

    Attributes:
        title: 图名
        drawing_number: 图号
        material: 材料
        scale: 比例
        dimensions: 尺寸标注列表
        technical_requirements: 技术要求文本
        surface_roughness: 表面粗糙度标注
        tolerance: 形位公差标注
    """

    model_config = ConfigDict(extra="allow")

    title: str | None = Field(default=None, description="图名")
    drawing_number: str | None = Field(default=None, description="图号")
    material: str | None = Field(default=None, description="材料")
    scale: str | None = Field(default=None, description="比例")
    dimensions: list[str] | None = Field(
        default=None, description="尺寸标注列表"
    )
    technical_requirements: str | None = Field(
        default=None, description="技术要求文本"
    )
    surface_roughness: str | None = Field(
        default=None, description="表面粗糙度标注"
    )
    tolerance: str | None = Field(default=None, description="形位公差标注")

    @field_validator("title", "drawing_number", "material", "scale",
                     "technical_requirements", "surface_roughness", "tolerance")
    @classmethod
    def _coerce_str_or_none(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            return v
        raise ValueError(f"字段必须为字符串或 null，实际类型 {type(v).__name__}")

    @field_validator("dimensions")
    @classmethod
    def _validate_dimensions(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError(
                f"dimensions 必须为字符串数组或 null，实际类型 {type(v).__name__}"
            )
        out: list[str] = []
        for item in v:
            if not isinstance(item, str):
                raise ValueError(
                    f"dimensions 元素必须为字符串，实际类型 {type(item).__name__}"
                )
            out.append(item)
        return out
