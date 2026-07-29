"""草图转 CAD schema（Task 12）。

定义草图解析、人工校准、任务结果等结构化数据模型。

依据 spec.md §"Scenario: 手绘草图转 CAD" 与风险项 R7：
- VLM 解析几何特征（圆/线/矩形/孔/倒角）
- 生成 CadQuery 代码或 SolidWorks API 调用序列
- 输出可编辑 DXF 或 SLDPRT
- 标注"草图级精度"，提示用户人工校准尺寸

设计原则（八荣八耻）：
- 以实事求是为荣：草图精度有限时明确标注 sketch_level
- 所有字段允许默认值，体现"VLM 不可用时降级"原则
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ===== API 请求 / 响应 =====


class SketchCreateRequest(BaseModel):
    """草图转 CAD 提交请求。"""

    image_key: str = Field(
        ..., description="已上传草图图片的 file_key（相对 UPLOAD_DIR）或绝对路径"
    )
    output_format: Literal["dxf", "step", "stl", "iges"] = Field(
        default="dxf",
        description="期望输出格式（默认 DXF，可编辑）",
    )


class SketchTaskAccepted(BaseModel):
    """草图任务受理响应。"""

    task_id: str = Field(..., description="Celery 任务 ID")
    status: Literal["queued"] = Field(default="queued", description="任务状态")
    websocket_url: str = Field(..., description="WebSocket 进度推送地址")
    precision_level: Literal["sketch_level"] = Field(
        default="sketch_level",
        description="精度等级（强制草图级，依据 spec.md R7）",
    )


# ===== 草图特征 =====


class SketchFeature(BaseModel):
    """单个草图几何特征。

    Attributes:
        feature_type: 几何类型（line/circle/arc/rectangle/hole/chamfer/fillet/polygon/unknown）
        parameters: 类型相关参数（如 {"radius": 50, "thickness": 20}）
        bbox: 在图像中的位置 [x1,y1,x2,y2]（归一化 0-1）
        confidence: VLM 置信度 0-1
        raw_text: VLM 原始描述
    """

    feature_type: Literal[
        "line",
        "circle",
        "arc",
        "rectangle",
        "hole",
        "chamfer",
        "fillet",
        "polygon",
        "unknown",
    ] = Field(..., description="几何类型")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="类型相关参数"
    )
    bbox: list[float] | None = Field(
        default=None, description="图像位置 [x,y,w,h]（归一化 0-1，左上角+宽高）"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="VLM 置信度")
    raw_text: str = Field(default="", description="VLM 原始描述")


class SketchParseResult(BaseModel):
    """草图解析结果。

    Attributes:
        features: 识别到的几何特征列表
        overall_shape: 整体形状描述（如"带孔圆盘"）
        dimensions_hint: 草图中标注的尺寸（如有）
        vlm_model: 实际使用的 VLM 模型名
        elapsed_ms: 解析耗时（毫秒）
        warnings: 警告信息（VLM 不可用等）
    """

    features: list[SketchFeature] = Field(default_factory=list)
    overall_shape: str = Field(default="", description="整体形状描述")
    dimensions_hint: dict[str, float] = Field(
        default_factory=dict, description="草图中标注的尺寸"
    )
    vlm_model: str = Field(default="", description="VLM 模型名")
    elapsed_ms: int = Field(default=0, description="解析耗时毫秒")
    warnings: list[str] = Field(default_factory=list, description="警告信息")


# ===== 人工校准 =====


class CalibrationItem(BaseModel):
    """校准项。

    Attributes:
        feature_index: 对应 SketchFeature 在 features 列表中的索引
        feature_type: 特征类型（与 SketchFeature.feature_type 对齐）
        parameter_name: 参数名（如 radius/length/diameter）
        original_value: VLM 推断值（可能不准确）
        calibrated_value: 用户校准值
        unit: 单位（默认 mm）
    """

    feature_index: int = Field(..., ge=0, description="对应特征索引")
    feature_type: str = Field(..., description="特征类型")
    parameter_name: str = Field(..., description="参数名")
    original_value: float | None = Field(
        default=None, description="VLM 推断值"
    )
    calibrated_value: float = Field(..., description="用户校准值")
    unit: str = Field(default="mm", description="单位")


class CalibrationRequest(BaseModel):
    """校准请求。

    Attributes:
        sketch_task_id: 原草图任务 ID
        calibrations: 校准项列表
    """

    sketch_task_id: str = Field(..., description="原草图任务 ID")
    calibrations: list[CalibrationItem] = Field(
        default_factory=list, description="校准项列表"
    )


class CalibrationResult(BaseModel):
    """校准结果。

    Attributes:
        task_id: 校准任务 ID
        success: 是否成功
        calibrated_features: 校准后的特征列表
        regenerated_code: 重新生成的 CadQuery 代码
        output_files: 输出文件路径（格式 → 路径）
        warnings: 警告信息
    """

    task_id: str = Field(..., description="校准任务 ID")
    success: bool = Field(..., description="是否成功")
    calibrated_features: list[SketchFeature] = Field(
        default_factory=list, description="校准后的特征列表"
    )
    regenerated_code: str = Field(default="", description="重新生成的 CadQuery 代码")
    output_files: dict[str, str] = Field(
        default_factory=dict, description="输出文件路径（格式 → 路径）"
    )
    warnings: list[str] = Field(default_factory=list, description="警告信息")


# ===== 任务结果 =====


class SketchTaskResult(BaseModel):
    """草图转 CAD 任务结果。

    依据 spec.md R7：始终标注 precision_level=sketch_level，提示人工校准。

    Attributes:
        task_id: Celery 任务 ID
        success: 是否成功
        precision_level: 精度等级（草图级，固定 sketch_level）
        parse_result: 草图解析结果
        generated_code: 生成的 CadQuery 代码
        output_files: 输出文件路径列表
        output_format: 输出格式（dxf/step/sldprt）
        warnings: 警告信息
        metadata: 附加元数据
    """

    task_id: str = Field(..., description="Celery 任务 ID")
    success: bool = Field(..., description="是否成功")
    precision_level: str = Field(
        default="sketch_level",
        description="精度等级（草图级，依据 spec.md R7 强制）",
    )
    parse_result: SketchParseResult = Field(
        default_factory=SketchParseResult, description="草图解析结果"
    )
    generated_code: str = Field(default="", description="生成的 CadQuery 代码")
    output_files: list[str] = Field(default_factory=list, description="输出文件路径")
    output_format: str = Field(default="dxf", description="输出格式")
    warnings: list[str] = Field(default_factory=list, description="警告信息")
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加元数据")
