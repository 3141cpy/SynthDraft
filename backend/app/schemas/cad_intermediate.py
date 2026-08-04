"""统一 CAD 中间表示 schema（pydantic）。

覆盖工程图（DXF/DWG）与零件/装配（STEP/IGES）两态：
- 图纸态：layers / entities / dimensions / title_block / blocks / layouts
- 几何态：通过 entities 与 metadata.shape_info 描述 B-Rep 拓扑/几何属性

设计原则：
- 字段尽量保持向后兼容（除 entities/dimensions 外大多可选），
  便于不同解析后端（ezdxf / OCP / FreeCAD）按能力填充。
- 不在此层做业务校验（审图/生成规则由 Task 4/5 实现）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ===== 子模型 =====


class CADLayer(BaseModel):
    """DXF/DWG 图层。"""

    name: str
    color: int | None = None
    is_visible: bool = True
    entities_count: int = 0


class CADEntity(BaseModel):
    """单一 CAD 实体的中间表示。

    coordinates 统一以 3D 点列表表达；不同实体类型语义：
      - LINE: [start, end]
      - CIRCLE/ARC: [center]（半径放 properties.radius）
      - LWPOLYLINE/POLYLINE: 顶点序列
      - TEXT/MTEXT: [insertion_point]
      - INSERT: [insertion_point]（块名放 properties.block_name）
      - DIMENSION: 定义点序列
    """

    type: str
    layer: str | None = None
    coordinates: list[tuple[float, float, float]] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    raw_dxf_attribs: dict[str, Any] | None = None


class CADDimension(BaseModel):
    """标注（尺寸）信息。"""

    type: Literal[
        "linear",
        "aligned",
        "angular",
        "radius",
        "diameter",
        "ordinate",
        "arc_length",
        "unknown",
    ]
    layer: str | None = None
    definition_points: list[tuple[float, float, float]] = Field(default_factory=list)
    measurement: float | None = None
    text: str | None = None


class CADTitleBlock(BaseModel):
    """标题栏字段（从块属性或特定图层提取）。

    所有字段可选，因为不同图纸模板字段差异很大。
    """

    drawing_number: str | None = None
    title: str | None = None
    scale: str | None = None
    material: str | None = None
    drawn_by: str | None = None
    checked_by: str | None = None
    date: str | None = None
    version: str | None = None
    project: str | None = None
    # 兜底：未识别的属性键值对
    extras: dict[str, str] = Field(default_factory=dict)


class CADBlock(BaseModel):
    """块定义。"""

    name: str
    base_point: tuple[float, float, float] = (0.0, 0.0, 0.0)
    entities: list[CADEntity] = Field(default_factory=list)
    is_layout: bool = False


class CADViewLayout(BaseModel):
    """布局/视图区（按 space 分类）。"""

    space: Literal["model", "paper"]
    name: str
    entities: list[CADEntity] = Field(default_factory=list)


# ===== 顶层模型 =====


SourceFormat = Literal["dxf", "dwg", "step", "iges", "image", "sldprt", "sldasm", "unknown"]


class CADIntermediateModel(BaseModel):
    """CAD 解析统一中间表示。

    所有解析后端（ezdxf / OCP / FreeCAD）均输出此模型，下游审图/生成模块
    按字段消费。
    """

    source_file: str
    source_format: SourceFormat = "unknown"
    units: str | None = None

    layers: list[CADLayer] = Field(default_factory=list)
    entities: list[CADEntity] = Field(default_factory=list)
    dimensions: list[CADDimension] = Field(default_factory=list)
    title_block: CADTitleBlock | None = None
    blocks: list[CADBlock] = Field(default_factory=list)
    layouts: list[CADViewLayout] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)
